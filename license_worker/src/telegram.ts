// 텔레그램 봇을 서버(워커)가 받는다 (2026-10-06) — 프로그램이 꺼져 있어도 "목록" 에 답하고, "실행 <이름>" 은 대기열에 넣어 프로그램이 켜지면 돌린다.
//   프로그램(온하우스 수집기 / 매물수집기)은 로그인하면 예약 목록을 올리고(POST /api/v1/schedules), 10초마다 대기 명령을 가져간다(GET /api/v1/commands).
//   어드민 /admin/telegram 에서 봇 토큰·챗 ID 저장 + [웹훅 등록] (등록하면 프로그램의 직접 폴링 대신 서버가 받는다)
import { Hono } from "hono";
import { html, raw } from "hono/html";
import { layout } from "./layout";
import { getSetting, setSetting } from "./photos";

type Bindings = { DB: D1Database; ADMIN_USER: string; ADMIN_PASSWORD: string };
export const telegram = new Hono<{ Bindings: Bindings }>();

const PROGRAM_LABEL: Record<string, string> = { onhouse: "온하우스 수집기", main: "매물수집기", crawl: "매물수집기", photo: "사진950" };
const plabel = (p: string) => PROGRAM_LABEL[p] || p;
const DAY_KO: Record<string, string> = { mon: "월", tue: "화", wed: "수", thu: "목", fri: "금", sat: "토", sun: "일" };
const daysKo = (days: any) => Array.isArray(days) ? (days.includes("daily") ? "매일" : days.map((d: string) => DAY_KO[d] || d).join("")) : "";

let ready = false;
async function ensure(db: D1Database) {
  if (ready) return;
  await db.prepare("CREATE TABLE IF NOT EXISTS app_schedules (username TEXT NOT NULL, program TEXT NOT NULL, data TEXT NOT NULL, updated_at TEXT NOT NULL, last_seen TEXT, PRIMARY KEY (username, program))").run();
  await db.prepare("CREATE TABLE IF NOT EXISTS app_commands (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL, program TEXT NOT NULL, text TEXT NOT NULL, created_at TEXT NOT NULL, taken_at TEXT, done_at TEXT, result TEXT)").run();
  ready = true;
}
const nowIso = () => new Date().toISOString();
async function hmacHex(secret: string, msg: string): Promise<string> {
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(msg));
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
const logToken = (secret: string, username: string) => hmacHex(secret, "log:" + username);
const webhookSecret = (secret: string, token: string) => hmacHex(secret, "tg:" + token).then((h) => h.slice(0, 32));

async function tgApi(token: string, method: string, body: Record<string, any>) {
  try {
    const r = await fetch(`https://api.telegram.org/bot${token}/${method}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    return (await r.json()) as any;
  } catch (e: any) { return { ok: false, description: e?.message }; }
}
async function sendText(db: D1Database, text: string) {
  const token = await getSetting(db, "tg_token"), chat = await getSetting(db, "tg_chat");
  if (!token || !chat) return;
  await tgApi(token, "sendMessage", { chat_id: chat, text: text.slice(0, 3900) });
}

export function parseCommand(text: string): [string | null, string] {
  const t = String(text || "").trim().replace(/^\//, "").trim();
  if (!t) return [null, ""];
  const sp = t.indexOf(" ");
  const head = (sp < 0 ? t : t.slice(0, sp)).toLowerCase();
  const rest = sp < 0 ? "" : t.slice(sp + 1).trim();
  if (["목록", "list", "예약"].includes(head)) return ["list", ""];
  if (["도움", "help", "명령"].includes(head)) return ["help", ""];
  if (["상태", "status"].includes(head)) return ["status", ""];
  if (["실행", "뽑아", "수집", "run", "시작"].includes(head)) return ["run", rest];
  return [null, t];
}

async function allSchedules(db: D1Database) {
  const { results } = await db.prepare("SELECT * FROM app_schedules ORDER BY program, username").all();
  return (results ?? []).map((r: any) => ({ username: r.username, program: r.program, last_seen: r.last_seen, jobs: (() => { try { return JSON.parse(r.data) as any[]; } catch { return []; } })() }));
}
const online = (last_seen: any) => last_seen ? Date.now() - new Date(last_seen).getTime() < 45_000 : false;

async function handleText(db: D1Database, text: string): Promise<string> {
  const [kind, arg] = parseCommand(text);
  const rows = await allSchedules(db);
  if (kind === "help") return "명령: 목록 — 예약 목록 / 실행 <예약이름> — 그 예약으로 수집 (뽑아·수집 <이름> 도 됨) / 상태 — 프로그램 켜짐 여부 / 도움";
  if (kind === "list") {
    if (!rows.length) return "등록된 예약이 없습니다. 프로그램에서 로그인하면 예약 목록이 올라옵니다.";
    return rows.map((r) => `[${plabel(r.program)} · ${r.username}] ${online(r.last_seen) ? "켜짐" : "꺼짐"}\n` + (r.jobs.length ? r.jobs.map((j: any) => `  ${j.enabled === false ? "(꺼짐) " : ""}${j.name} — ${j.schedule_time} ${daysKo(j.days)}`).join("\n") : "  (예약 없음)")).join("\n\n") + "\n\n실행 <예약이름> 으로 수집합니다";
  }
  if (kind === "status") {
    const { results } = await db.prepare("SELECT program, username, text, created_at, taken_at, done_at FROM app_commands ORDER BY id DESC LIMIT 5").all();
    const pend = (results ?? []).map((c: any) => `${plabel(c.program)} · ${c.text} — ${c.done_at ? "완료" : c.taken_at ? "실행 중" : "대기"}`).join("\n");
    return rows.map((r) => `${plabel(r.program)} · ${r.username}: ${online(r.last_seen) ? "켜짐" : "꺼짐"}`).join("\n") + (pend ? "\n\n최근 명령:\n" + pend : "");
  }
  if (kind === "run") {
    const name = arg.trim();
    if (!name) return "실행할 예약 이름을 적어주세요. 예) 실행 강남 월세";
    const hits: { username: string; program: string; job: any }[] = [];
    for (const r of rows) for (const j of r.jobs) if (j.name === name) hits.push({ username: r.username, program: r.program, job: j });
    if (!hits.length) for (const r of rows) for (const j of r.jobs) if (String(j.name || "").includes(name)) hits.push({ username: r.username, program: r.program, job: j });
    if (!hits.length) return `'${name}' 예약이 없습니다. '목록' 으로 이름을 확인하세요`;
    const seen = new Set<string>(); const lines: string[] = [];
    for (const h of hits) {
      const key = h.username + "|" + h.program; if (seen.has(key)) continue; seen.add(key);
      await db.prepare("INSERT INTO app_commands (username, program, text, created_at) VALUES (?, ?, ?, ?)").bind(h.username, h.program, `실행 ${h.job.name}`, nowIso()).run();
      const r = rows.find((x) => x.username === h.username && x.program === h.program);
      lines.push(`[${plabel(h.program)}] '${h.job.name}' — ${online(r?.last_seen) ? "켜져 있어 곧 시작합니다" : "프로그램이 꺼져 있습니다. 켜지면 바로 실행합니다 (12시간 내)"}`);
    }
    return lines.join("\n");
  }
  return "모르는 명령입니다. '도움' 을 보내보세요";
}

// ---------------------------------------------------------------- 텔레그램 웹훅
telegram.post("/tg/:secret", async (c) => {
  const token = await getSetting(c.env.DB, "tg_token");
  if (!token || c.req.param("secret") !== (await webhookSecret(c.env.ADMIN_PASSWORD, token))) return c.text("no", 403);
  await ensure(c.env.DB);
  const upd: any = await c.req.json().catch(() => ({}));
  const msg = upd.message || upd.edited_message || {};
  const chat = String((msg.chat || {}).id ?? ""), text = String(msg.text || "").trim();
  const chatOk = await getSetting(c.env.DB, "tg_chat");
  if (!text || !chat || (chatOk && chat !== chatOk)) return c.json({ ok: true });
  const reply = await handleText(c.env.DB, text);
  await tgApi(token, "sendMessage", { chat_id: chat, text: reply.slice(0, 3900) });
  return c.json({ ok: true });
});

// ---------------------------------------------------------------- 프로그램 API
async function authed(c: any): Promise<{ username: string; program: string } | null> {
  const q = c.req.method === "GET" ? Object.fromEntries(new URL(c.req.url).searchParams) : await c.req.json().catch(() => ({}));
  const username = String(q.username ?? "").trim(), token = String(q.token ?? "").trim(), program = String(q.program ?? "main").trim() || "main";
  if (!username || !token || token !== (await logToken(c.env.ADMIN_PASSWORD, username))) return null;
  (c as any)._body = q;
  return { username, program };
}
telegram.post("/api/v1/schedules", async (c) => {
  const a = await authed(c); if (!a) return c.json({ success: false, message: "토큰이 맞지 않습니다." }, 401);
  await ensure(c.env.DB);
  const jobs = Array.isArray((c as any)._body.jobs) ? (c as any)._body.jobs.slice(0, 200).map((j: any) => ({ name: String(j.name || "").slice(0, 80), site: String(j.site || ""), schedule_time: String(j.schedule_time || ""), days: Array.isArray(j.days) ? j.days : [], enabled: j.enabled !== false })) : [];
  await c.env.DB.prepare("INSERT INTO app_schedules (username, program, data, updated_at, last_seen) VALUES (?, ?, ?, ?, ?) ON CONFLICT(username, program) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at, last_seen = excluded.last_seen")
    .bind(a.username, a.program, JSON.stringify(jobs), nowIso(), nowIso()).run();
  return c.json({ success: true, count: jobs.length });
});
telegram.get("/api/v1/commands", async (c) => {
  const a = await authed(c); if (!a) return c.json({ success: false, message: "토큰이 맞지 않습니다." }, 401);
  await ensure(c.env.DB);
  await c.env.DB.prepare("UPDATE app_schedules SET last_seen = ? WHERE username = ? AND program = ?").bind(nowIso(), a.username, a.program).run();
  const bot = !!(await getSetting(c.env.DB, "tg_token")) && (await getSetting(c.env.DB, "tg_webhook")) === "on";
  const since = new Date(Date.now() - 12 * 3600e3).toISOString();
  const { results } = await c.env.DB.prepare("SELECT id, text FROM app_commands WHERE username = ? AND program = ? AND taken_at IS NULL AND created_at > ? ORDER BY id").bind(a.username, a.program, since).all();
  const cmds = (results ?? []) as any[];
  for (const r of cmds) await c.env.DB.prepare("UPDATE app_commands SET taken_at = ? WHERE id = ?").bind(nowIso(), r.id).run();
  return c.json({ success: true, bot, commands: cmds.map((r) => ({ id: r.id, text: r.text })) });
});
telegram.post("/api/v1/commands/:id/done", async (c) => {
  const a = await authed(c); if (!a) return c.json({ success: false, message: "토큰이 맞지 않습니다." }, 401);
  await ensure(c.env.DB);
  const text = String((c as any)._body.text || "").trim();
  await c.env.DB.prepare("UPDATE app_commands SET done_at = ?, result = ? WHERE id = ? AND username = ?").bind(nowIso(), text.slice(0, 500), c.req.param("id"), a.username).run();
  if (text) await sendText(c.env.DB, text);
  return c.json({ success: true });
});

// ---------------------------------------------------------------- 어드민 설정
telegram.get("/admin/telegram", async (c) => {
  await ensure(c.env.DB);
  const token = await getSetting(c.env.DB, "tg_token"), chat = await getSetting(c.env.DB, "tg_chat"), hook = await getSetting(c.env.DB, "tg_webhook");
  const note = c.req.query("note") || "";
  const rows = await allSchedules(c.env.DB);
  const { results } = await c.env.DB.prepare("SELECT * FROM app_commands ORDER BY id DESC LIMIT 30").all();
  const kst = (iso: any) => iso ? new Date(iso).toLocaleString("ko-KR", { timeZone: "Asia/Seoul", hour12: false }) : "";
  const body = html`
    <div class="page-head"><h1>텔레그램 봇</h1><span class="small" style="color:var(--muted)">프로그램이 꺼져 있어도 '목록'에 답하고, '실행 &lt;이름&gt;'은 대기열에 넣어 프로그램이 켜지면 돌립니다</span></div>
    ${note ? html`<div style="color:var(--ok);margin-bottom:10px">${note}</div>` : ""}
    <div class="form-box" style="margin:0 0 20px;max-width:620px">
      <form method="post" action="/admin/telegram">
        <label>봇 토큰 (@BotFather)<input name="tg_token" value="${token}" autocomplete="off" placeholder="123456:ABC-..."></label>
        <label>챗 ID (이 방에서 온 메시지만 받음)<input name="tg_chat" value="${chat}" autocomplete="off"></label>
        <div class="form-actions">
          <button class="btn btn-primary" name="act" value="save">저장</button>
          <button class="btn" name="act" value="hook_on">저장 + 웹훅 등록 (서버가 받기)</button>
          <button class="btn btn-danger" name="act" value="hook_off">웹훅 해제 (프로그램이 직접 받기)</button>
        </div>
        <p class="small" style="color:var(--muted);margin-top:10px">현재: ${hook === "on" ? "서버가 받는 중 (웹훅 등록됨)" : "프로그램이 직접 받는 중 (웹훅 없음)"} · 웹훅을 등록하면 프로그램의 직접 폴링은 자동으로 서버 대기열 방식으로 바뀝니다.</p>
      </form>
    </div>
    <h2 style="font-size:16px">올라온 예약 목록</h2>
    <table class="user-table"><thead><tr><th>프로그램</th><th>아이디</th><th>상태</th><th>예약</th><th>갱신</th></tr></thead><tbody>
      ${rows.length ? rows.map((r) => html`<tr><td>${plabel(r.program)}</td><td class="mono">${r.username}</td><td><span class="badge ${online(r.last_seen) ? "status-active" : "status-disabled"}">${online(r.last_seen) ? "켜짐" : "꺼짐"}</span></td>
        <td class="small">${r.jobs.length ? raw(r.jobs.map((j: any) => `${j.enabled === false ? "(꺼짐) " : ""}${String(j.name).replace(/</g, "&lt;")} — ${j.schedule_time} ${daysKo(j.days)}`).join("<br>")) : "(없음)"}</td><td class="mono small">${kst(r.last_seen)}</td></tr>`) : html`<tr><td colspan="5" class="empty">아직 없습니다. 프로그램에서 로그인하면 올라옵니다.</td></tr>`}
    </tbody></table>
    <h2 style="font-size:16px;margin-top:20px">최근 명령</h2>
    <table class="user-table"><thead><tr><th>시각</th><th>프로그램</th><th>아이디</th><th>명령</th><th>상태</th><th>결과</th></tr></thead><tbody>
      ${(results ?? []).length ? (results as any[]).map((x) => html`<tr><td class="mono small">${kst(x.created_at)}</td><td>${plabel(x.program)}</td><td class="mono">${x.username}</td><td>${x.text}</td><td>${x.done_at ? "완료" : x.taken_at ? "실행 중" : "대기"}</td><td class="small">${x.result ?? ""}</td></tr>`) : html`<tr><td colspan="6" class="empty">없음</td></tr>`}
    </tbody></table>`;
  return c.html(layout("텔레그램 봇", body));
});
telegram.post("/admin/telegram", async (c) => {
  await ensure(c.env.DB);
  const form = await c.req.formData();
  const token = String(form.get("tg_token") ?? "").trim(), chat = String(form.get("tg_chat") ?? "").trim(), act = String(form.get("act") ?? "save");
  await setSetting(c.env.DB, "tg_token", token); await setSetting(c.env.DB, "tg_chat", chat);
  let note = "저장했습니다";
  if (act === "hook_on" && token) {
    const url = new URL(c.req.url); const hookUrl = `${url.origin}/tg/${await webhookSecret(c.env.ADMIN_PASSWORD, token)}`;
    const r = await tgApi(token, "setWebhook", { url: hookUrl, allowed_updates: ["message"], drop_pending_updates: true });
    if (r.ok) { await setSetting(c.env.DB, "tg_webhook", "on"); note = "웹훅을 등록했습니다 — 이제 서버가 메시지를 받습니다"; }
    else note = "웹훅 등록 실패: " + (r.description || "토큰을 확인하세요");
  } else if (act === "hook_off") {
    if (token) await tgApi(token, "deleteWebhook", { drop_pending_updates: false });
    await setSetting(c.env.DB, "tg_webhook", "off"); note = "웹훅을 해제했습니다 — 프로그램이 직접 받습니다";
  }
  return c.redirect("/admin/telegram?note=" + encodeURIComponent(note));
});
