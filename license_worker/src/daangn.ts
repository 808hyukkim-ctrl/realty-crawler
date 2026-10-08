// 당근 광고자동화 (2026-10-08) — 라운지와 별개로 라이선스 서버 안에서 돌아가는 "붙여넣기 → 정리 → 당근 등록 → 기록" 기능
//   화면: GET /daangn (라이선스 계정으로 로그인, 기능 'daangn' 권한 필요)
//   API : /daangn/api/<action> — 인트라넷 화면이 쓰던 이름을 그대로 써서 화면 코드를 거의 바꾸지 않는다
//         login · summary · address · building · img · daangn-connect/start · daangn-connect/poll · daangn-disconnect ·
//         daangn-direct · uploads · upload-close · upload-edit
//   당근 로그인·글 등록은 엔진(ENGINE_URL, Bearer ENGINE_SECRET)이 하고, 사용자별 당근 세션(암호문)·기록은 이 서버의 D1 에만 둔다.
import { Hono } from "hono";
import { html } from "hono/html";
import DAANGN_HTML from "./daangn.html";
import { layout } from "./layout";

type Bindings = { DB: D1Database; ADMIN_USER: string; ADMIN_PASSWORD: string; ENGINE_URL: string; ENGINE_SECRET: string };
export const daangn = new Hono<{ Bindings: Bindings }>();

// ---------------------------------------------------------------- 표
let ready = false;
async function ensure(db: D1Database) {
  if (ready) return;
  await db.prepare(`CREATE TABLE IF NOT EXISTS daangn_web_sessions (token TEXT PRIMARY KEY, username TEXT NOT NULL, created_at TEXT NOT NULL, last_at TEXT NOT NULL)`).run();
  await db.prepare(`CREATE TABLE IF NOT EXISTS daangn_sessions (username TEXT PRIMARY KEY, blob TEXT NOT NULL, phone TEXT, name TEXT, broker TEXT, connected_at TEXT NOT NULL)`).run();
  await db.prepare(`CREATE TABLE IF NOT EXISTS daangn_uploads (
    id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL, key TEXT NOT NULL, created_at TEXT NOT NULL,
    addr TEXT, ho TEXT, deal TEXT, price TEXT, phone TEXT, role TEXT, source TEXT,
    status TEXT NOT NULL, article_no TEXT, url TEXT, reason TEXT, closed INTEGER NOT NULL DEFAULT 0, closed_at TEXT, data TEXT)`).run();
  await db.prepare(`CREATE INDEX IF NOT EXISTS daangn_uploads_user ON daangn_uploads(username, created_at DESC)`).run();
  await db.prepare(`CREATE INDEX IF NOT EXISTS daangn_uploads_key ON daangn_uploads(key)`).run();
  ready = true;
}
const nowIso = () => new Date().toISOString();
const str = (v: unknown) => (v === null || v === undefined ? "" : String(v).trim());
const json = (c: any, body: unknown, status = 200) => c.json(body, status);
const normKey = (road: unknown, dong: unknown, ho: unknown) => [road, dong, ho].map((v) => str(v).replace(/\s+/g, "").replace(/호$/, "").replace(/동$/, "").toLowerCase()).join("|");

// 비밀번호 검증 — index.ts 와 같은 방식(PBKDF2/SHA 포맷은 verifyPassword 를 그대로 가져다 씀)
import { verifyPassword } from "./auth";

async function engine(c: any, path: string, init: RequestInit = {}): Promise<Response> {
  const base = String(c.env.ENGINE_URL || "").replace(/\/$/, "");
  if (!base || !c.env.ENGINE_SECRET) throw new Error("엔진 주소(ENGINE_URL)·비밀키가 설정되지 않았습니다.");
  const headers: Record<string, string> = { Authorization: `Bearer ${c.env.ENGINE_SECRET}`, ...(init.headers as Record<string, string> || {}) };
  return fetch(base + path, { ...init, headers });
}
async function engineJson(c: any, path: string, body?: unknown, method = "POST"): Promise<{ status: number; data: any }> {
  const r = await engine(c, path, { method, headers: body !== undefined ? { "content-type": "application/json" } : {}, body: body !== undefined ? JSON.stringify(body) : undefined });
  let data: any = {}; try { data = await r.json(); } catch { /* */ }
  return { status: r.status, data };
}

// ---------------------------------------------------------------- 세션(웹 토큰)
async function userOf(c: any): Promise<{ username: string } | null> {
  await ensure(c.env.DB);
  const tok = str(c.req.header("x-intranet-token") || c.req.query("token"));
  if (!tok) return null;
  const row: any = await c.env.DB.prepare("SELECT username, last_at FROM daangn_web_sessions WHERE token = ?").bind(tok).first();
  if (!row) return null;
  if (Date.now() - new Date(row.last_at).getTime() > 14 * 86400e3) { await c.env.DB.prepare("DELETE FROM daangn_web_sessions WHERE token = ?").bind(tok).run(); return null; }
  // 계정이 아직 유효한지(비활성·만료·권한)
  const u: any = await c.env.DB.prepare("SELECT username, is_active, expires_at, features FROM users WHERE username = ?").bind(row.username).first();
  if (!u || !u.is_active) return null;
  if (u.expires_at && new Date(u.expires_at).getTime() < Date.now()) return null;
  if (!String(u.features ?? "").split(",").map((x: string) => x.trim()).includes("daangn")) return null;
  if (Date.now() - new Date(row.last_at).getTime() > 3600e3) c.env.DB.prepare("UPDATE daangn_web_sessions SET last_at = ? WHERE token = ?").bind(nowIso(), tok).run().catch(() => {});
  return { username: row.username };
}
const randomToken = () => { const a = new Uint8Array(24); crypto.getRandomValues(a); return Array.from(a, (b) => b.toString(16).padStart(2, "0")).join(""); };

// ---------------------------------------------------------------- 화면
daangn.get("/daangn", (c) => c.html(DAANGN_HTML));

// ---------------------------------------------------------------- API
daangn.options("/daangn/api/*", (c) => c.body(null, 204));

daangn.post("/daangn/api/login", async (c) => {
  await ensure(c.env.DB);
  const body = await c.req.json().catch(() => ({}));
  const username = str(body.username), password = String(body.password ?? "");
  if (!username || !password) return json(c, { error: "아이디와 비밀번호를 입력하세요." }, 400);
  const row: any = await c.env.DB.prepare("SELECT * FROM users WHERE username = ?").bind(username).first();
  if (!row || !(await verifyPassword(password, row.password_hash))) return json(c, { error: "아이디 또는 비밀번호가 올바르지 않습니다." }, 401);
  if (!row.is_active) return json(c, { error: "비활성화된 계정입니다. 관리자에게 문의하세요." }, 403);
  if (row.expires_at && new Date(row.expires_at).getTime() < Date.now()) return json(c, { error: "이용권이 만료되었습니다." }, 403);
  if (!String(row.features ?? "").split(",").map((x: string) => x.trim()).includes("daangn")) return json(c, { error: "이 계정은 '당근 광고' 이용권이 없습니다. 관리자에게 문의하세요." }, 403);
  const token = randomToken();
  await c.env.DB.prepare("INSERT INTO daangn_web_sessions (token, username, created_at, last_at) VALUES (?, ?, ?, ?)").bind(token, username, nowIso(), nowIso()).run();
  return json(c, { ok: true, token, username });
});

daangn.all("/daangn/api/:action", async (c) => {
  try { return await apiHandler(c); }
  catch (e) { const msg = e instanceof Error ? e.message : String(e); console.error("[daangn api]", c.req.param("action"), msg); return json(c, { error: "서버 오류: " + msg }, 500); }
});
async function apiHandler(c: any) {
  const action = c.req.param("action");
  const me = await userOf(c);
  if (!me) return json(c, { error: "토큰이 없거나 만료됐습니다." }, 401);
  const db = c.env.DB;
  const q = (k: string) => str(c.req.query(k));

  if (action === "summary") {
    const s: any = await db.prepare("SELECT phone, name, broker, connected_at FROM daangn_sessions WHERE username = ?").bind(me.username).first();
    const cnt: any = await db.prepare("SELECT COUNT(*) n FROM daangn_uploads WHERE username = ? AND status = 'ok' AND closed = 0").bind(me.username).first();
    return json(c, { label: me.username, scopes: ["create", "building"], create: { pending: 0 }, review: { listings: 0, signups: 0 },
      daangn: s ? { connected: true, phone: s.phone ?? "", name: s.name ?? "", broker: s.broker ?? "", connected_at: s.connected_at } : { connected: false }, uploads_active: cnt?.n ?? 0 });
  }
  if (action === "address") {
    if (q("q").length < 2) return json(c, { error: "검색어는 2글자 이상." }, 400);
    const r = await engineJson(c, "/address?q=" + encodeURIComponent(q("q")), undefined, "GET"); return json(c, r.data, r.status);
  }
  if (action === "building") {
    const p = new URLSearchParams(); for (const k of ["address", "dong", "ho"]) if (q(k)) p.set(k, q(k));
    const r = await engineJson(c, "/building?" + p.toString(), undefined, "GET"); return json(c, r.data, r.status);
  }
  if (action === "img") {
    const r = await engine(c, "/img?u=" + encodeURIComponent(q("u")) + "&r=" + encodeURIComponent(q("r")), { method: "GET" });
    return new Response(r.body, { status: r.status, headers: { "content-type": r.headers.get("content-type") || "application/octet-stream", "cache-control": "private, max-age=600" } });
  }
  if (action === "daangn-connect") {   // POST {step:'start'|'poll'|'cancel', session_id?}
    const body = await c.req.json().catch(() => ({}));
    const step = str(body.step);
    if (step === "start") { const r = await engineJson(c, "/qr/start", { uid: me.username }); return json(c, r.data, r.status); }
    if (step === "cancel") { const r = await engineJson(c, "/qr/poll", { session_id: str(body.session_id), cancel: true }); return json(c, r.data, r.status); }
    const r = await engineJson(c, "/qr/poll", { session_id: str(body.session_id) });
    if (r.status === 200 && r.data?.status === "success" && r.data?.session) {
      const v = r.data.viewer || {};
      await db.prepare("INSERT INTO daangn_sessions (username, blob, phone, name, broker, connected_at) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(username) DO UPDATE SET blob = excluded.blob, phone = excluded.phone, name = excluded.name, broker = excluded.broker, connected_at = excluded.connected_at")
        .bind(me.username, String(r.data.session), str(v.phone), str(v.name), str(v.broker), nowIso()).run();
      return json(c, { status: "success", viewer: v });
    }
    return json(c, r.data, r.status);
  }
  if (action === "daangn-disconnect") { await db.prepare("DELETE FROM daangn_sessions WHERE username = ?").bind(me.username).run(); return json(c, { ok: true }); }

  if (action === "daangn-direct" || action === "daangn-publish") {
    const body = await c.req.json().catch(() => ({}));
    const sess: any = await db.prepare("SELECT blob FROM daangn_sessions WHERE username = ?").bind(me.username).first();
    if (!sess) return json(c, { ok: false, code: "no_cookies", error: "당근이 연결되어 있지 않습니다. 위의 [당근 연결]에서 QR 로그인을 먼저 해주세요." }, 400);
    const key = normKey(body.road_addr, body.dong_nm, body.ho_nm);
    const label = { addr: str(body.jibun_addr) || str(body.road_addr), ho: [str(body.dong_nm), str(body.ho_nm)].filter(Boolean).join(" "), deal: str(body.deal_type),
      price: str(body.deal_type) === "매매" ? str(body.sale_price) : [body.deposit, body.monthly_rent].filter((v) => v !== null && v !== undefined && v !== "").join(" / "),
      phone: str(body.owner_phone), role: str(body.contact_role) || "landlord", source: str(body.source_url) };
    // 우리 기록의 중복: 같은 주소·동·호수로 올린 글이 아직 살아 있으면 건너뜀
    const prev: any = await db.prepare("SELECT article_no, url FROM daangn_uploads WHERE username = ? AND key = ? AND status = 'ok' AND closed = 0 AND article_no != '' ORDER BY id DESC LIMIT 1").bind(me.username, key).first();
    if (prev && body.force_duplicate !== true) {
      const chk = await engineJson(c, "/check", { session: sess.blob, articleNo: String(prev.article_no) });
      if (chk.data?.exists !== false) {
        return json(c, { ok: false, code: "daangn_dup", error: `당근에 이미 올라간 매물입니다 (당근 매물번호 ${prev.article_no}) — 건너뜁니다`, articleNo: String(prev.article_no), articleId: String(prev.article_no), url: prev.url || "" }, 409);
      }
    }
    const listing = { ...body }; delete (listing as any).force; delete (listing as any).daangn_only;
    const options = { parking_total: body.parking_total, building_use: body.building_use, manage_type: body.manage_type, force_duplicate: body.force_duplicate === true };
    const r = await engineJson(c, "/publish", { session: sess.blob, listing, options });
    const d = r.data || {};
    const status = d.ok ? "ok" : d.code === "daangn_dup" ? "dup" : "fail";
    await db.prepare("INSERT INTO daangn_uploads (username, key, created_at, addr, ho, deal, price, phone, role, source, status, article_no, url, reason, data) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")
      .bind(me.username, key, nowIso(), label.addr, label.ho, label.deal, label.price, label.phone, label.role, label.source, status, str(d.articleNo || d.articleId), str(d.url), status === "ok" ? null : str(d.error || d.reason).slice(0, 500), JSON.stringify({ summary: d.summary ?? null, variant: d.variant ?? null, by: d.by ?? null, fields: { property_type: body.property_type, area_exclusive: body.area_exclusive, floor_no: body.floor_no, total_floors: body.total_floors, room_count: body.room_count, bathroom_count: body.bathroom_count, available_date: body.available_date, photos: Array.isArray(body.photos) ? body.photos.length : 0 } }).slice(0, 4000)).run();
    if (d.code === "no_session") await db.prepare("DELETE FROM daangn_sessions WHERE username = ?").bind(me.username).run();
    return json(c, d.ok ? { ok: true, url: d.url ?? null, articleId: d.articleNo ?? d.articleId ?? null, articleNo: d.articleNo ?? null, direct: true, variant: d.variant } : { ...d, code: d.code === "no_session" ? "no_cookies" : d.code }, r.status === 200 ? 200 : r.status);
  }

  if (action === "uploads") {
    const days = Math.min(400, Math.max(1, parseInt(q("days") || "30", 10) || 30));
    const since = new Date(Date.now() - days * 86400e3).toISOString();
    const { results } = await db.prepare("SELECT * FROM daangn_uploads WHERE username = ? AND created_at >= ? ORDER BY id DESC LIMIT 3000").bind(me.username, since).all();
    const byKey = new Map<string, any>();
    for (const r of [...(results ?? [])].reverse() as any[]) {
      const it = byKey.get(r.key) ?? { key: r.key, first_at: r.created_at, at: r.created_at, by: r.username, addr: "", ho: "", deal: "", price: "", phone: "", role: "", source: "", lounge: null, daangn: null, closed: false, closed_at: null, id: r.id };
      it.at = r.created_at; it.id = r.id; it.addr = r.addr || it.addr; it.ho = r.ho || it.ho; it.deal = r.deal || it.deal; it.price = r.price || it.price; it.phone = r.phone || it.phone; it.role = r.role || it.role; it.source = r.source || it.source;
      if (r.status === "ok") it.daangn = { no: r.article_no || "", url: r.url || "", at: r.created_at, direct: true };
      else if (!it.daangn || !it.daangn.no) it.daangn = { no: "", fail: r.reason || "", at: r.created_at, direct: true, dup: r.status === "dup" ? (String(r.reason || "").match(/(\d{5,})/) || [])[1] || "" : "" };
      it.closed = !!r.closed; it.closed_at = r.closed_at || null;
      byKey.set(r.key, it);
    }
    const rows = [...byKey.values()].map((it: any) => ({ ...it, where: it.daangn && it.daangn.no ? "당근만" : "당근 실패" })).sort((a: any, b: any) => (a.first_at < b.first_at ? 1 : -1));
    return json(c, { days, count: rows.length, rows });
  }
  if (action === "upload-close") {
    const body = await c.req.json().catch(() => ({}));
    const key = str(body.key), closed = body.closed !== false;
    if (!key) return json(c, { error: "key 가 필요합니다." }, 422);
    await db.prepare("UPDATE daangn_uploads SET closed = ?, closed_at = ? WHERE username = ? AND key = ?").bind(closed ? 1 : 0, closed ? nowIso() : null, me.username, key).run();
    return json(c, { ok: true, closed, lounge_done: false });
  }
  if (action === "upload-edit") {
    const body = await c.req.json().catch(() => ({}));
    const key = str(body.key); if (!key) return json(c, { error: "key 가 필요합니다." }, 422);
    const sets: string[] = []; const binds: unknown[] = [];
    for (const k of ["source", "phone", "role", "addr", "ho"]) if (body[k] !== undefined) { sets.push(`${k} = ?`); binds.push(str(body[k]).slice(0, 500)); }
    if (!sets.length) return json(c, { error: "고칠 값이 없습니다." }, 422);
    await db.prepare(`UPDATE daangn_uploads SET ${sets.join(", ")} WHERE username = ? AND key = ?`).bind(...binds, me.username, key).run();
    const out: Record<string, unknown> = { ok: true }; for (const k of ["source", "phone", "role", "addr", "ho"]) if (body[k] !== undefined) out[k] = str(body[k]);
    return json(c, out);
  }
  if (action === "listing-create") return json(c, { error: "이 서비스는 당근 전용입니다. [🥕 당근에 올리기]를 쓰세요." }, 400);
  if (action === "listings" || action === "signups" || action === "supply" || action === "cs") return json(c, { queue: [], rows: [], ok: 0, t: 0, recent: [] });
  return json(c, { error: "없는 창구: " + action }, 404);
}

// ---------------------------------------------------------------- 어드민
daangn.get("/admin/daangn", async (c) => {
  await ensure(c.env.DB);
  const { results: users } = await c.env.DB.prepare("SELECT u.username, u.features, u.is_active, u.expires_at, s.phone, s.name, s.broker, s.connected_at, (SELECT COUNT(*) FROM daangn_uploads d WHERE d.username = u.username AND d.status = 'ok') ok_n, (SELECT COUNT(*) FROM daangn_uploads d WHERE d.username = u.username AND d.status != 'ok') fail_n, (SELECT MAX(created_at) FROM daangn_uploads d WHERE d.username = u.username) last_at FROM users u LEFT JOIN daangn_sessions s ON s.username = u.username ORDER BY u.username").all();
  const { results: recent } = await c.env.DB.prepare("SELECT username, created_at, addr, ho, deal, price, status, article_no, url, reason, closed FROM daangn_uploads ORDER BY id DESC LIMIT 100").all();
  const dt = (s: unknown) => (s ? new Date(String(s)).toLocaleString("ko-KR", { timeZone: "Asia/Seoul", hour12: false }) : "");
  let engineOk = "확인 안 됨";
  try { const r = await engine(c, "/health", { method: "GET" }); const j: any = await r.json(); engineOk = r.ok ? `정상 (QR 세션 ${j.sessions ?? 0}개, 키 vworld:${j.keys?.vworld ? "O" : "X"} juso:${j.keys?.juso ? "O" : "X"} hub:${j.keys?.hub ? "O" : "X"})` : `응답 ${r.status}`; } catch (e) { engineOk = "연결 실패: " + (e instanceof Error ? e.message : String(e)); }
  return c.html(layout("당근 광고자동화", html`
    <h1>🥕 당근 광고자동화</h1>
    <p class="muted">사용자 화면: <a href="/daangn" target="_blank">/daangn</a> (라이선스 계정으로 로그인, 기능 '당근 광고' 권한 필요) · 엔진: ${engineOk}</p>
    <h2>사용자별 연결·등록</h2>
    <table><thead><tr><th>아이디</th><th>당근 광고 권한</th><th>당근 연결</th><th>연결 계정</th><th>성공</th><th>실패·중복</th><th>마지막</th></tr></thead><tbody>
    ${(users ?? []).map((u: any) => html`<tr>
      <td>${u.username}</td>
      <td>${String(u.features ?? "").split(",").includes("daangn") ? "O" : html`<span class="muted">X</span>`}</td>
      <td>${u.connected_at ? html`<b>연결됨</b> <span class="small muted">${dt(u.connected_at)}</span>` : html`<span class="muted">-</span>`}</td>
      <td class="small">${[u.name, u.phone, u.broker].filter(Boolean).join(" · ")}</td>
      <td>${u.ok_n}</td><td>${u.fail_n}</td><td class="small muted">${dt(u.last_at)}</td></tr>`)}
    </tbody></table>
    <h2>최근 등록 100건</h2>
    <table><thead><tr><th>일시</th><th>아이디</th><th>주소 · 호수</th><th>거래</th><th>금액</th><th>결과</th><th>당근 매물번호</th></tr></thead><tbody>
    ${(recent ?? []).map((r: any) => html`<tr style="${r.closed ? "opacity:.5" : ""}">
      <td class="small">${dt(r.created_at)}</td><td>${r.username}</td><td>${r.addr} ${r.ho ?? ""}</td><td>${r.deal ?? ""}</td><td>${r.price ?? ""}</td>
      <td>${r.status === "ok" ? "성공" : r.status === "dup" ? html`<span class="muted" title="${r.reason ?? ""}">중복</span>` : html`<span style="color:#b42318" title="${r.reason ?? ""}">실패</span>`}</td>
      <td>${r.article_no ? html`<a href="${r.url}" target="_blank" rel="noopener">${r.article_no}</a>` : ""}</td></tr>`)}
    </tbody></table>`));
});
