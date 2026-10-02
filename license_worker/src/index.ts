import { Hono } from "hono";
import { html } from "hono/html";
import { basicAuth } from "hono/basic-auth";
import { photos } from "./photos";
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
const FEATURES: [string, string][] = [["crawl", "매물 수집"], ["photo", "사진950"]];
let featuresReady = false;
async function ensureFeatures(db: D1Database) {
  if (featuresReady) return;
  try { await db.prepare("ALTER TABLE users ADD COLUMN features TEXT NOT NULL DEFAULT 'crawl'").run(); } catch (e) { /* 이미 있음 */ }
  featuresReady = true;
}
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
      <td class="mono small">${u.mac_address ?? "-"}</td>
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
        <form method="post" action="/admin/users/${u.id}/password" class="inline-form">
          <input type="password" name="password" placeholder="새 비밀번호" class="pw-input">
          <button type="submit" class="btn btn-sm">변경</button>
        </form>
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
  if (macAddress) {
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
  return c.json({
    success: true, features: featureList(row.features), message: "인증 성공", expires_at: row.expires_at ?? null });
});

app.get("/healthz", (c) => c.json({ ok: true }));

export default app;
