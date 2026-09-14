import { Hono } from "hono";
import { html, raw } from "hono/html";
import { basicAuth } from "hono/basic-auth";

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

function layout(title: string, body: unknown) {
  return html`<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${title}</title>
<style>${raw(STYLE)}</style>
</head>
<body>
<header class="topbar">
  <div class="brand">전국부동산매물수집기 · 라이선스 관리</div>
</header>
<main class="container">${body}</main>
</body>
</html>`;
}

const STYLE = `
:root{color-scheme:light dark;--bg:#0f1420;--panel:#171d2b;--border:#2a3348;--text:#e7ebf3;--muted:#93a0b8;--accent:#5b7cfa;--danger:#e0556f;--ok:#3fbf7f;--warn:#e0a83f;}
*{box-sizing:border-box;}
body{margin:0;font-family:"Pretendard","Segoe UI",-apple-system,sans-serif;background:var(--bg);color:var(--text);}
a{color:var(--accent);text-decoration:none;}
.topbar{display:flex;align-items:center;justify-content:space-between;padding:14px 24px;border-bottom:1px solid var(--border);background:var(--panel);}
.brand{font-weight:700;}
.container{max-width:1100px;margin:0 auto;padding:32px 20px;}
.form-box{max-width:420px;margin:30px auto;background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:28px;}
.form-box h1{margin-top:0;font-size:20px;}
form label{display:block;margin-bottom:14px;font-size:13px;color:var(--muted);}
form input,form select{display:block;width:100%;margin-top:6px;padding:10px 12px;border-radius:8px;border:1px solid var(--border);background:#0d121c;color:var(--text);font-size:14px;}
.btn{display:inline-block;padding:9px 16px;border-radius:8px;border:1px solid var(--border);background:#1d2436;color:var(--text);cursor:pointer;font-size:13px;}
.btn-primary{background:var(--accent);border-color:var(--accent);color:#fff;}
.btn-danger{background:transparent;color:var(--danger);border-color:var(--danger);}
.btn-sm{padding:6px 10px;font-size:12px;}
.form-actions{display:flex;gap:10px;margin-top:20px;}
.error{color:var(--danger);font-size:13px;}
.page-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:20px;}
.page-head h1{margin:0;font-size:22px;}
.search-form{margin-bottom:16px;display:flex;gap:8px;}
.search-form input{padding:8px 12px;border-radius:8px;border:1px solid var(--border);background:#0d121c;color:var(--text);min-width:220px;}
.user-table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--border);border-radius:12px;overflow:hidden;}
.user-table th,.user-table td{padding:10px 12px;border-bottom:1px solid var(--border);font-size:13px;text-align:left;vertical-align:middle;}
.user-table th{color:var(--muted);font-weight:600;background:#131a29;}
.user-table .mono{font-family:"Consolas",monospace;}
.user-table .small{font-size:11px;color:var(--muted);}
.user-table .empty{text-align:center;color:var(--muted);padding:30px;}
.badge{padding:3px 9px;border-radius:999px;font-size:11px;font-weight:600;}
.status-active{background:rgba(63,191,127,.15);color:var(--ok);}
.status-unlimited{background:rgba(91,124,250,.15);color:var(--accent);}
.status-expired{background:rgba(224,85,111,.15);color:var(--danger);}
.status-disabled{background:rgba(147,160,184,.15);color:var(--muted);}
.status-soon{background:rgba(224,168,63,.15);color:var(--warn);}
.inline-form{display:inline-flex;gap:6px;align-items:center;}
.actions{display:flex;flex-wrap:wrap;gap:6px;}
.pw-input{width:120px;padding:6px 8px;font-size:12px;}
`;

// ---------------------------------------------------------------- admin auth

app.use("/admin/*", async (c, next) => {
  const auth = basicAuth({ username: c.env.ADMIN_USER, password: c.env.ADMIN_PASSWORD });
  return auth(c, next);
});

// ---------------------------------------------------------------- dashboard

app.get("/", (c) => c.redirect("/admin/dashboard"));

app.get("/admin/dashboard", async (c) => {
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
    return html`<tr>
      <td class="mono">${u.username}</td>
      <td><span class="badge ${cls}">${label}</span></td>
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
      <thead><tr><th>아이디</th><th>상태</th><th>만료일</th><th>기기(MAC)</th><th>메모</th><th>생성일</th><th>연장</th><th>관리</th></tr></thead>
      <tbody>${rows.length ? rows : html`<tr><td colspan="8" class="empty">등록된 사용자가 없습니다.</td></tr>`}</tbody>
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
    `INSERT INTO users (username, password_hash, mac_address, is_active, expires_at, memo, created_at, updated_at)
     VALUES (?, ?, NULL, 1, ?, ?, ?, ?)`
  )
    .bind(username, passwordHash, expiresAt, memo, ts, ts)
    .run();
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
  return c.json({ success: true, message: "인증 성공", expires_at: row.expires_at ?? null });
});

app.get("/healthz", (c) => c.json({ ok: true }));

export default app;
