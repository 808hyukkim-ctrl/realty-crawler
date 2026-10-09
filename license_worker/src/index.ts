import { Hono } from "hono";
import { html } from "hono/html";
import { basicAuth } from "hono/basic-auth";
import { photos } from "./photos";
import { telegram } from "./telegram";
import { listings } from "./listings";
import { staffdb } from "./staffdb";
import { naverad } from "./naverad";
import { hosu } from "./hosu";
import { daangn } from "./daangn";   // 당근 광고자동화 (2026-10-08)
import { brief } from "./brief";     // 손님 브리핑 /b/<id> (2026-10-09)
import { layout } from "./layout";

type Bindings = {
  DB: D1Database;
  ADMIN_USER: string;
  ADMIN_PASSWORD: string;
};

const app = new Hono<{ Bindings: Bindings }>();

// ---------------------------------------------------------------- helpers

const DURATION_PRESETS: Record<string, [string, number | null]> = {
  "1day": ["1일", 1 * 24 * 60 * 60 * 1000],
  "3day": ["3일", 3 * 24 * 60 * 60 * 1000],
  "1week": ["1주일", 7 * 24 * 60 * 60 * 1000],
  "1month": ["1개월", 30 * 24 * 60 * 60 * 1000],
  "3month": ["3개월", 90 * 24 * 60 * 60 * 1000],
  "1year": ["1년", 365 * 24 * 60 * 60 * 1000],
  unlimited: ["무제한", null],
};

// 계정별 기능: 수집기(crawl) / 사진950(photo). 둘 다 체크면 둘 다, 하나만 체크면 그것만 쓸 수 있다 (2026-10-02)
const FEATURES: [string, string][] = [["crawl", "매물 수집"], ["photo", "사진950"], ["db", "DB 조회"], ["daangn", "당근 광고"]];   // db = 직원용 /db 지번 조회 (2026-10-08)
let featuresReady = false;
async function ensureFeatures(db: D1Database) {
  if (featuresReady) return;
  try { await db.prepare("ALTER TABLE users ADD COLUMN features TEXT NOT NULL DEFAULT 'crawl'").run(); } catch (e) { /* 이미 있음 */ }
  try { await db.prepare("ALTER TABLE users ADD COLUMN no_lock INTEGER NOT NULL DEFAULT 0").run(); } catch (e) { /* 이미 있음 */ }   // 1 이면 기기(MAC) 잠금 없이 어느 PC 에서나 (2026-10-09, 진식2·admin)
  featuresReady = true;
}
// 활동 기록: 누가(아이디) 어느 프로그램(app)으로 무엇을(action) 했는지 (2026-10-02)
let logReady = false;
async function ensureLog(db: D1Database) {
  if (logReady) return;
  await db.prepare("CREATE TABLE IF NOT EXISTS activity_log (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, username TEXT NOT NULL, app TEXT NOT NULL, action TEXT NOT NULL, detail TEXT, count INTEGER, mac TEXT)").run();
  await db.prepare("CREATE INDEX IF NOT EXISTS activity_log_at ON activity_log(at DESC)").run();
  logReady = true;
}
async function addLog(db: D1Database, username: string, app: string, action: string, detail: string, count: number | null, mac: string) {
  await ensureLog(db);
  await db.prepare("INSERT INTO activity_log (at, username, app, action, detail, count, mac) VALUES (?, ?, ?, ?, ?, ?, ?)")
    .bind(nowIso(), username, app, action, detail.slice(0, 500), count, mac.slice(0, 40)).run();
}
// 프로그램이 작업 기록을 보낼 때 쓰는 토큰: HMAC(아이디) — 로그인 성공 응답에 실어 준다
async function hmacHex(secret: string, msg: string): Promise<string> {
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(msg));
  return toHex(new Uint8Array(sig));
}
const logToken = (secret: string, username: string) => hmacHex(secret, "log:" + username);
const APP_LABEL: Record<string, string> = { crawl: "매물 수집기", photo: "사진950", db: "DB 조회", daangn: "당근 광고", brief: "손님 브리핑" };

const featureList = (s: any) => String(s ?? "crawl").split(",").map((x) => x.trim()).filter(Boolean);
const featureLabel = (key: string) => (FEATURES.find(([k]) => k === key) || [key, key])[1];

function nowIso(): string {
  return new Date().toISOString();
}

async function hashPassword(password: string): Promise<string> {
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const hash = await pbkdf2(password, salt, 100_000);
  return `pbkdf2$100000$${toHex(salt)}$${toHex(hash)}`;
}

async function verifyPassword(password: string, stored: string): Promise<boolean> {
  const parts = stored.split("$");
  if (parts.length !== 4 || parts[0] !== "pbkdf2") return false;
  const iterations = parseInt(parts[1], 10);
  const salt = fromHex(parts[2]);
  const expected = parts[3];
  const hash = await pbkdf2(password, salt, iterations);
  return toHex(hash) === expected;
}

async function pbkdf2(password: string, salt: Uint8Array, iterations: number): Promise<Uint8Array> {
  const enc = new TextEncoder();
  const keyMaterial = await crypto.subtle.importKey("raw", enc.encode(password), "PBKDF2", false, [
    "deriveBits",
  ]);
  const bits = await crypto.subtle.deriveBits(
    { name: "PBKDF2", salt: salt as unknown as ArrayBuffer, iterations, hash: "SHA-256" },
    keyMaterial,
    256
  );
  return new Uint8Array(bits);
}

function toHex(buf: Uint8Array): string {
  return Array.from(buf)
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

function fromHex(hex: string): Uint8Array {
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(hex.substr(i * 2, 2), 16);
  return out;
}

function userStatus(u: any): [string, string] {
  if (!u.is_active) return ["비활성", "status-disabled"];
  if (!u.expires_at) return ["무제한", "status-unlimited"];
  const exp = new Date(u.expires_at).getTime();
  const now = Date.now();
  if (exp < now) return ["만료", "status-expired"];
  if (exp - now <= 24 * 60 * 60 * 1000) return ["곧만료", "status-soon"];
  return ["활성", "status-active"];
}

// ---------------------------------------------------------------- layout

// ---------------------------------------------------------------- admin auth

app.use("/admin/*", async (c, next) => {
  const auth = basicAuth({ username: c.env.ADMIN_USER, password: c.env.ADMIN_PASSWORD });
  return auth(c, next);
});
app.route("/", photos);   // 사진 950 (src/photos.ts)
app.route("/", telegram);   // 텔레그램 봇·예약 대기열 (src/telegram.ts)
app.route("/", listings);   // 매물 DB (src/listings.ts)
app.route("/", staffdb);    // 직원용 DB 조회 /db (src/staffdb.ts)
app.route("/", naverad);    // 네이버 광고정리 /admin/naverad (src/naverad.ts)
app.route("/", hosu);       // 호수 추정 /admin/hosu (src/hosu.ts)
app.route("/", daangn);     // 당근 광고자동화 /daangn (src/daangn.ts)
app.route("/", brief);      // 손님 브리핑 공개 페이지 /b/<id> (src/brief.ts)

// ---------------------------------------------------------------- dashboard

app.get("/", (c) => c.redirect("/admin/dashboard"));

app.get("/admin/dashboard", async (c) => {
  await ensureFeatures(c.env.DB);
  const q = c.req.query("q")?.trim() ?? "";
  const { results } = q
    ? await c.env.DB.prepare("SELECT * FROM users WHERE username LIKE ? ORDER BY created_at DESC")
        .bind(`%${q}%`)
        .all()
    : await c.env.DB.prepare("SELECT * FROM users ORDER BY created_at DESC").all();

  const rows = (results ?? []).map((u: any) => {
    const [label, cls] = userStatus(u);
    // 무제한 사용자는 연장 드롭다운도 "무제한"을 기본 선택해, 새로고침해도
    // 마치 만료일이 초기화된 것처럼 보이지 않게 한다 (실제 만료일 데이터는 항상 그대로 유지됨).
    const defaultDuration = u.expires_at ? "1month" : "unlimited";
    const durationOptions = Object.entries(DURATION_PRESETS).map(
      ([key, [optLabel]]) =>
        html`<option value="${key}" ${key === defaultDuration ? "selected" : ""}>${optLabel}</option>`
    );
    const feats = featureList(u.features);
    const featureBoxes = FEATURES.map(([key, flabel]) =>
      html`<label class="feat"><input type="checkbox" name="f" value="${key}" ${feats.includes(key) ? "checked" : ""} onchange="this.form.submit()"> ${flabel}</label>`
    );
    return html`<tr>
      <td class="mono">${u.username}</td>
      <td><span class="badge ${cls}">${label}</span></td>
      <td><form method="post" action="/admin/users/${u.id}/features" class="feat-form">${featureBoxes}</form></td>
      <td class="mono">${u.expires_at ?? "무제한"}</td>
      <td class="mono small">${u.no_lock ? html`<span class="badge status-unlimited" title="어느 기기에서나 로그인 가능">기기잠금 해제</span>` : (u.mac_address ?? "-")}</td>
      <td>${u.memo ?? ""}</td>
      <td class="mono small">${(u.created_at ?? "").slice(0, 10)}</td>
      <td>
        <form method="post" action="/admin/users/${u.id}/extend" class="inline-form">
          <select name="duration">${durationOptions}</select>
          <button type="submit" class="btn btn-sm">연장</button>
        </form>
      </td>
      <td class="actions">
        <form method="post" action="/admin/users/${u.id}/toggle" class="inline-form">
          <button type="submit" class="btn btn-sm">${u.is_active ? "비활성화" : "활성화"}</button>
        </form>
        <form method="post" action="/admin/users/${u.id}/reset_mac" class="inline-form">
          <button type="submit" class="btn btn-sm">기기초기화</button>
        </form>
        <form method="post" action="/admin/users/${u.id}/nolock" class="inline-form">
          <button type="submit" class="btn btn-sm" title="${u.no_lock ? "다시 한 기기로만 묶기" : "어느 PC 에서나 쓰게 (MAC 잠금 해제)"}">${u.no_lock ? "기기잠금 켜기" : "기기잠금 해제"}</button>
        </form>
        <form method="post" action="/admin/users/${u.id}/password" class="inline-form">
          <input type="password" name="password" placeholder="새 비밀번호" class="pw-input">
          <button type="submit" class="btn btn-sm">변경</button>
        </form>
        <a class="btn btn-sm" href="/admin/logs?q=${u.username}">기록</a>
        <form method="post" action="/admin/users/${u.id}/delete" class="inline-form"
              onsubmit="return confirm('${u.username} 계정을 삭제할까요?');">
          <button type="submit" class="btn btn-sm btn-danger">삭제</button>
        </form>
      </td>
    </tr>`;
  });

  const body = html`
    <div class="page-head">
      <h1>사용자 라이선스</h1>
      <a class="btn btn-primary" href="/admin/users/new">+ 새 사용자</a>
    </div>
    <form class="search-form" method="get">
      <input type="text" name="q" placeholder="아이디 검색" value="${q}">
      <button type="submit" class="btn">검색</button>
    </form>
    <table class="user-table">
      <thead><tr><th>아이디</th><th>상태</th><th>기능</th><th>만료일</th><th>기기(MAC)</th><th>메모</th><th>생성일</th><th>연장</th><th>관리</th></tr></thead>
      <tbody>${rows.length ? rows : html`<tr><td colspan="9" class="empty">등록된 사용자가 없습니다.</td></tr>`}</tbody>
    </table>
  `;
  return c.html(layout("대시보드", body));
});

app.get("/admin/users/new", (c) => {
  const durationOptions = Object.entries(DURATION_PRESETS).map(
    ([key, [label]]) => html`<option value="${key}" ${key === "1month" ? "selected" : ""}>${label}</option>`
  );
  const body = html`
    <div class="form-box">
      <h1>새 사용자 등록</h1>
      <form method="post">
        <label>아이디<input type="text" name="username" required autofocus></label>
        <label>비밀번호<input type="password" name="password" required></label>
        <label>이용권 기간<select name="duration">${durationOptions}</select></label>
        <div class="feat-pick"><span>기능</span>${FEATURES.map(([key, flabel]) => html`<label class="feat"><input type="checkbox" name="f" value="${key}" ${key === "crawl" ? "checked" : ""}> ${flabel}</label>`)}</div>
        <label>메모<input type="text" name="memo" placeholder="선택 입력"></label>
        <div class="form-actions">
          <a href="/admin/dashboard" class="btn">취소</a>
          <button type="submit" class="btn btn-primary">등록</button>
        </div>
      </form>
    </div>
  `;
  return c.html(layout("새 사용자", body));
});

app.post("/admin/users/new", async (c) => {
  const form = await c.req.formData();
  const username = String(form.get("username") ?? "").trim();
  const password = String(form.get("password") ?? "");
  const duration = String(form.get("duration") ?? "1month");
  const memo = String(form.get("memo") ?? "").trim();
  const feats = form.getAll("f").map((x) => String(x)).filter((x) => FEATURES.some(([k]) => k === x));
  await ensureFeatures(c.env.DB);

  if (!username || !password) {
    return c.html(layout("새 사용자", html`<div class="form-box"><p class="error">아이디와 비밀번호를 입력하세요.</p><a href="/admin/users/new" class="btn">돌아가기</a></div>`));
  }
  const exists = await c.env.DB.prepare("SELECT id FROM users WHERE username = ?").bind(username).first();
  if (exists) {
    return c.html(layout("새 사용자", html`<div class="form-box"><p class="error">이미 존재하는 아이디입니다.</p><a href="/admin/users/new" class="btn">돌아가기</a></div>`));
  }
  const [, deltaMs] = DURATION_PRESETS[duration] ?? DURATION_PRESETS["1month"];
  const expiresAt = deltaMs ? new Date(Date.now() + deltaMs).toISOString() : null;
  const ts = nowIso();
  const passwordHash = await hashPassword(password);
  await c.env.DB.prepare(
    `INSERT INTO users (username, password_hash, mac_address, is_active, expires_at, memo, created_at, updated_at, features)
     VALUES (?, ?, NULL, 1, ?, ?, ?, ?, ?)`
  )
    .bind(username, passwordHash, expiresAt, memo, ts, ts, feats.join(","))
    .run();
  return c.redirect("/admin/dashboard");
});

app.post("/admin/users/:id/features", async (c) => {
  await ensureFeatures(c.env.DB);
  const id = c.req.param("id");
  const form = await c.req.formData();
  const feats = form.getAll("f").map((x) => String(x)).filter((x) => FEATURES.some(([k]) => k === x));
  await c.env.DB.prepare("UPDATE users SET features = ?, updated_at = ? WHERE id = ?").bind(feats.join(","), nowIso(), id).run();
  return c.redirect("/admin/dashboard");
});

app.post("/admin/users/:id/extend", async (c) => {
  const id = c.req.param("id");
  const form = await c.req.formData();
  const duration = String(form.get("duration") ?? "1month");
  const row: any = await c.env.DB.prepare("SELECT * FROM users WHERE id = ?").bind(id).first();
  if (row) {
    const [, deltaMs] = DURATION_PRESETS[duration] ?? DURATION_PRESETS["1month"];
    let newExpiry: string | null;
    if (deltaMs === null) {
      newExpiry = null;
    } else {
      const current = row.expires_at ? new Date(row.expires_at).getTime() : 0;
      const base = current > Date.now() ? current : Date.now();
      newExpiry = new Date(base + deltaMs).toISOString();
    }
    await c.env.DB.prepare("UPDATE users SET expires_at = ?, updated_at = ? WHERE id = ?")
      .bind(newExpiry, nowIso(), id)
      .run();
  }
  return c.redirect("/admin/dashboard");
});

app.post("/admin/users/:id/toggle", async (c) => {
  const id = c.req.param("id");
  const row: any = await c.env.DB.prepare("SELECT * FROM users WHERE id = ?").bind(id).first();
  if (row) {
    await c.env.DB.prepare("UPDATE users SET is_active = ?, updated_at = ? WHERE id = ?")
      .bind(row.is_active ? 0 : 1, nowIso(), id)
      .run();
  }
  return c.redirect("/admin/dashboard");
});

app.post("/admin/users/:id/nolock", async (c) => {
  await ensureFeatures(c.env.DB);
  const id = c.req.param("id");
  const row: any = await c.env.DB.prepare("SELECT no_lock FROM users WHERE id = ?").bind(id).first();
  if (row) await c.env.DB.prepare("UPDATE users SET no_lock = ?, mac_address = CASE WHEN ? = 1 THEN NULL ELSE mac_address END, updated_at = ? WHERE id = ?").bind(row.no_lock ? 0 : 1, row.no_lock ? 0 : 1, nowIso(), id).run();
  return c.redirect("/admin/dashboard");
});

app.post("/admin/users/:id/reset_mac", async (c) => {
  const id = c.req.param("id");
  await c.env.DB.prepare("UPDATE users SET mac_address = NULL, updated_at = ? WHERE id = ?")
    .bind(nowIso(), id)
    .run();
  return c.redirect("/admin/dashboard");
});

app.post("/admin/users/:id/delete", async (c) => {
  const id = c.req.param("id");
  await c.env.DB.prepare("DELETE FROM users WHERE id = ?").bind(id).run();
  return c.redirect("/admin/dashboard");
});

app.post("/admin/users/:id/password", async (c) => {
  const id = c.req.param("id");
  const form = await c.req.formData();
  const password = String(form.get("password") ?? "");
  if (password) {
    const hash = await hashPassword(password);
    await c.env.DB.prepare("UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?")
      .bind(hash, nowIso(), id)
      .run();
  }
  return c.redirect("/admin/dashboard");
});

// ---------------------------------------------------------------- public api

app.post("/api/v1/verify", async (c) => {
  const body = await c.req.json().catch(() => ({}));
  const username = String(body.username ?? "").trim();
  const password = String(body.password ?? "");
  const macAddress = String(body.mac_address ?? "").trim();
  const appKey = String(body.app ?? "crawl").trim() || "crawl";   // 옛 수집기는 app 을 안 보냄 → 수집으로 취급
  await ensureFeatures(c.env.DB);

  if (!username || !password) {
    return c.json({ success: false, message: "아이디와 비밀번호를 입력하세요." }, 400);
  }

  const row: any = await c.env.DB.prepare("SELECT * FROM users WHERE username = ?").bind(username).first();
  if (!row || !(await verifyPassword(password, row.password_hash))) {
    return c.json({ success: false, message: "아이디 또는 비밀번호가 올바르지 않습니다." });
  }
  if (!row.is_active) {
    return c.json({ success: false, message: "비활성화된 계정입니다. 관리자에게 문의하세요." });
  }
  if (row.expires_at && new Date(row.expires_at).getTime() < Date.now()) {
    return c.json({ success: false, message: "이용권이 만료되었습니다." });
  }
  if (!featureList(row.features).includes(appKey)) {
    return c.json({ success: false, message: `이 계정은 '${featureLabel(appKey)}' 이용권이 없습니다. 관리자에게 문의하세요.` });
  }
  if (macAddress && !row.no_lock) {                                   // 기기잠금 해제 계정은 MAC 을 묶지도, 비교하지도 않는다
    if (!row.mac_address) {
      await c.env.DB.prepare("UPDATE users SET mac_address = ?, updated_at = ? WHERE id = ?")
        .bind(macAddress, nowIso(), row.id)
        .run();
    } else if (row.mac_address !== macAddress) {
      return c.json({
        success: false,
        message: "다른 기기에서 등록된 계정입니다. 관리자에게 기기 초기화를 요청하세요.",
      });
    }
  }
  try { await addLog(c.env.DB, row.username, appKey, "로그인", "", null, macAddress); } catch (e) {}
  return c.json({
    success: true, features: featureList(row.features), message: "인증 성공", expires_at: row.expires_at ?? null,
    log_token: await logToken(c.env.ADMIN_PASSWORD, row.username) });
});

app.post("/api/v1/log", async (c) => {
  const body: any = await c.req.json().catch(() => ({}));
  const username = String(body.username ?? "").trim();
  const token = String(body.token ?? "").trim();
  if (!username || !token || token !== (await logToken(c.env.ADMIN_PASSWORD, username))) {
    return c.json({ success: false, message: "기록 토큰이 맞지 않습니다." }, 401);
  }
  const app_ = String(body.app ?? "crawl").trim().slice(0, 20) || "crawl";
  const action = String(body.action ?? "작업").trim().slice(0, 40) || "작업";
  const detail = String(body.detail ?? "").trim();
  const count = body.count == null || body.count === "" ? null : Number(body.count);
  await addLog(c.env.DB, username, app_, action, detail, Number.isFinite(count as number) ? (count as number) : null, String(body.mac_address ?? ""));
  return c.json({ success: true });
});

app.get("/admin/logs", async (c) => {
  await ensureLog(c.env.DB);
  const q = c.req.query("q")?.trim() ?? "";
  const appF = c.req.query("app")?.trim() ?? "";
  const where: string[] = []; const binds: any[] = [];
  if (q) { where.push("username LIKE ?"); binds.push(`%${q}%`); }
  if (appF) { where.push("app = ?"); binds.push(appF); }
  const sql = "SELECT * FROM activity_log" + (where.length ? " WHERE " + where.join(" AND ") : "") + " ORDER BY at DESC LIMIT 500";
  const { results } = await c.env.DB.prepare(sql).bind(...binds).all();
  const kst = (iso: string) => { try { return new Date(iso).toLocaleString("ko-KR", { timeZone: "Asia/Seoul", hour12: false }); } catch { return iso; } };
  const rows = (results ?? []).map((r: any) => html`<tr>
    <td class="mono small">${kst(r.at)}</td>
    <td class="mono">${r.username}</td>
    <td><span class="badge ${r.app === "photo" ? "status-unlimited" : r.app === "db" ? "status-soon" : "status-active"}">${APP_LABEL[r.app] ?? r.app}</span></td>
    <td>${r.action}</td>
    <td class="small">${r.detail ?? ""}</td>
    <td class="mono">${r.count ?? ""}</td>
    <td class="mono small">${r.mac ?? ""}</td>
  </tr>`);
  const body = html`
    <div class="page-head"><h1>활동 기록</h1><span class="small" style="color:var(--muted)">최근 500건 · 로그인과 수집/사진 작업이 남습니다 (프로그램이 끝날 때 보냄)</span></div>
    <form class="search-form" method="get">
      <input type="text" name="q" placeholder="아이디 검색" value="${q}">
      <select name="app" style="padding:8px 12px;border-radius:8px;border:1px solid var(--border);background:var(--input);color:var(--text)">
        <option value="" ${appF === "" ? "selected" : ""}>전체 프로그램</option>
        <option value="crawl" ${appF === "crawl" ? "selected" : ""}>매물 수집기</option>
        <option value="photo" ${appF === "photo" ? "selected" : ""}>사진950</option>
        <option value="db" ${appF === "db" ? "selected" : ""}>DB 조회</option>
      </select>
      <button type="submit" class="btn">검색</button>
    </form>
    <table class="user-table">
      <thead><tr><th>시각</th><th>아이디</th><th>프로그램</th><th>작업</th><th>내용</th><th>건수</th><th>기기</th></tr></thead>
      <tbody>${rows.length ? rows : html`<tr><td colspan="7" class="empty">기록이 없습니다.</td></tr>`}</tbody>
    </table>`;
  return c.html(layout("활동 기록", body));
});

app.get("/healthz", (c) => c.json({ ok: true }));

export default app;
