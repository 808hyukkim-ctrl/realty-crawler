// 직원용 DB 조회 (2026-10-08) — 수집기 계정(users 표)으로 로그인해 지번 조회만 할 수 있다. 올리기·수정·삭제 없음.
//   계정에 'db' 기능(어드민 사용자 관리의 'DB 조회' 체크)이 있어야 하고, 활성·미만료여야 한다. 조회할 때마다 활동 기록에 남는다.
//   GET  /db                 로그인 폼 또는 조회 화면
//   POST /db/login           아이디·비밀번호 → 30일 쿠키(HMAC 서명)
//   POST /db/logout
//   GET  /db/lookup.json?q=  조회 (읽기 전용) — 지번(동 이름+번지)으로만, 전화번호·호수만으로는 못 찾고, 결과는 5건까지만 (DB 통째로 긁어가는 것 방지)
import { Hono } from "hono";
import { html, raw } from "hono/html";
import { STYLE } from "./layout";
import { ensureListings, lookupWhere, kst } from "./listings";

type Bindings = { DB: D1Database; ADMIN_USER: string; ADMIN_PASSWORD: string };
export const staffdb = new Hono<{ Bindings: Bindings }>();

const COOKIE = "db_s";
const DAYS = 30;
const MAX_ROWS = 5;
/** 직원 조회: "821-6" 처럼 번지만, 또는 "논현동 821-6". 전화번호 모양은 거부, 동 이름만도 거부 (2026-10-08 직원이 번지만 치는 걸로 확인) */
export function jibunCheck(q: string): string {
  const t = q.trim();
  if (/0\d{1,2}[-\s).]*\d{3,4}[-\s]*\d{4}/.test(t) || /^\d{7,}$/.test(t.replace(/\D/g, "")) && !/[가-힣]/.test(t)) return "전화번호로는 찾을 수 없습니다. 지번(번지)으로 찾아주세요. 예: 821-6";
  if (/^\s*(산\s*)?\d{1,4}(\s*-\s*\d{1,4})?\s*(번지)?\s*$/.test(t)) return "";                      // 번지만
  if (!/[가-힣]{1,10}(동|리|가|읍|면)\s*(산\s*)?\d{1,4}(-\d{1,4})?/.test(t)) return "번지를 적어주세요. 예: 821-6 또는 논현동 821-6";
  return "";
}
/** 번지만 쳤을 때: 주소에서 '공백 + 번지 + (숫자·호 아님)' 로만 맞춘다 → 호수(302호)나 다른 번지의 일부(1821-6)는 안 걸림 */
export function lotWhere(q: string): [string, any[]] {
  const lot = q.replace(/번지/g, "").replace(/\s+/g, "");
  // 앞에 '○○동/리/가 ' 가 있어야 번지로 본다 → "2층 302" 같은 호수는 안 걸림
  return [" WHERE (addr GLOB ? OR addr GLOB ?)", [`*[동리가읍면] ${lot}[^0-9호]*`, `*[동리가읍면] ${lot}`]];
}

async function hmacHex(secret: string, msg: string): Promise<string> {
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(msg));
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
const toHex = (buf: Uint8Array) => Array.from(buf).map((b) => b.toString(16).padStart(2, "0")).join("");
function fromHex(hex: string): Uint8Array { const out = new Uint8Array(hex.length / 2); for (let i = 0; i < out.length; i++) out[i] = parseInt(hex.substr(i * 2, 2), 16); return out; }
// users.password_hash = pbkdf2$<iter>$<salt hex>$<hash hex> (index.ts 의 hashPassword 와 같은 형식)
async function verifyPassword(password: string, stored: string): Promise<boolean> {
  const parts = String(stored || "").split("$");
  if (parts.length !== 4 || parts[0] !== "pbkdf2") return false;
  const keyMaterial = await crypto.subtle.importKey("raw", new TextEncoder().encode(password), "PBKDF2", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits({ name: "PBKDF2", salt: fromHex(parts[2]) as unknown as ArrayBuffer, iterations: parseInt(parts[1], 10), hash: "SHA-256" }, keyMaterial, 256);
  return toHex(new Uint8Array(bits)) === parts[3];
}
const features = (s: any) => String(s ?? "crawl").split(",").map((x) => x.trim()).filter(Boolean);

async function session(c: any): Promise<string | null> {
  const m = (c.req.header("cookie") || "").match(new RegExp("(?:^|;\\s*)" + COOKIE + "=([^;]+)"));
  if (!m) return null;
  const [u, exp, sig] = decodeURIComponent(m[1]).split("|");
  if (!u || !exp || !sig || Number(exp) < Date.now()) return null;
  if (sig !== (await hmacHex(c.env.ADMIN_PASSWORD, `db:${u}|${exp}`))) return null;
  return u;
}
async function setSession(c: any, username: string) {
  const exp = Date.now() + DAYS * 86400e3;
  const val = encodeURIComponent(`${username}|${exp}|${await hmacHex(c.env.ADMIN_PASSWORD, `db:${username}|${exp}`)}`);
  c.header("Set-Cookie", `${COOKIE}=${val}; Path=/db; Max-Age=${DAYS * 86400}; HttpOnly; Secure; SameSite=Lax`);
}
async function log(db: D1Database, username: string, q: string, n: number) {
  try {
    await db.prepare("CREATE TABLE IF NOT EXISTS activity_log (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, username TEXT NOT NULL, app TEXT NOT NULL, action TEXT NOT NULL, detail TEXT, count INTEGER, mac TEXT)").run();
    await db.prepare("INSERT INTO activity_log (at, username, app, action, detail, count, mac) VALUES (?, ?, 'db', 'DB조회', ?, ?, '')").bind(new Date().toISOString(), username, q.slice(0, 200), n).run();
  } catch (e) { /* 기록 실패는 무시 */ }
}

function page(title: string, body: unknown) {
  return html`<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>${title}</title><style>${raw(STYLE)}${raw(DB_STYLE)}</style></head>
<body><header class="topbar"><div class="brand">🌸 매물·임대인 DB 조회</div><nav class="nav" id="nav"></nav></header><main class="container">${body}</main></body></html>`;
}

staffdb.get("/db", async (c) => {
  const u = await session(c);
  const err = c.req.query("err") || "";
  if (!u) {
    return c.html(page("DB 조회 로그인", html`
      <div class="form-box"><h1>DB 조회 로그인</h1>
        <p class="small muted" style="margin-top:-6px">매물수집기 아이디·비밀번호로 들어옵니다. 조회만 할 수 있습니다.</p>
        ${err ? html`<p class="error">${err}</p>` : ""}
        <form method="post" action="/db/login">
          <label>아이디<input type="text" name="username" required autofocus autocomplete="username"></label>
          <label>비밀번호<input type="password" name="password" required autocomplete="current-password"></label>
          <div class="form-actions"><button type="submit" class="btn btn-primary" style="width:100%">들어가기</button></div>
        </form></div>`));
  }
  const q = c.req.query("jibun") ?? c.req.query("q") ?? "";
  return c.html(page("매물·임대인 DB 조회", html`
    <div class="page-head"><h1>지번으로 찾기</h1><span class="small muted">${u} · <form method="post" action="/db/logout" class="inline-form"><button type="submit" class="x" style="font-size:12px">로그아웃</button></form></span></div>
    <div class="lookup">
      <div class="lkrow">
        <input type="text" id="lkq" placeholder="번지만 치세요 — 예: 821-6 (논현동 821-6 도 됨)" value="${q}" autofocus autocomplete="off">
        <button type="button" class="btn btn-primary" id="lkgo">찾기</button>
        <span class="small muted" id="lkmsg">번지(예: 821-6)를 치면 바로 찾습니다. 5건까지 보입니다.</span>
      </div>
      <div id="lkres"></div>
    </div>
    <p class="small muted">조회만 할 수 있습니다. 틀린 내용이나 추가할 내용은 대표에게 알려주세요.</p>
    <script>${raw(DB_JS)}</script>`));
});

staffdb.post("/db/login", async (c) => {
  const form = await c.req.formData();
  const username = String(form.get("username") ?? "").trim(), password = String(form.get("password") ?? "");
  const row: any = username ? await c.env.DB.prepare("SELECT * FROM users WHERE username = ?").bind(username).first() : null;
  const fail = (m: string) => c.redirect("/db?err=" + encodeURIComponent(m));
  if (!row || !(await verifyPassword(password, row.password_hash))) return fail("아이디 또는 비밀번호가 올바르지 않습니다.");
  if (!row.is_active) return fail("비활성화된 계정입니다.");
  if (row.expires_at && new Date(row.expires_at).getTime() < Date.now()) return fail("이용권이 만료된 계정입니다.");
  if (!features(row.features).includes("db")) return fail("이 계정은 DB 조회 권한이 없습니다. 대표에게 요청하세요.");
  await setSession(c, username);
  return c.redirect("/db");
});
staffdb.post("/db/logout", (c) => { c.header("Set-Cookie", `${COOKIE}=; Path=/db; Max-Age=0; HttpOnly; Secure; SameSite=Lax`); return c.redirect("/db"); });

/** 직원용 지번 조회 본체 — /db 화면과 직원 포털(/daangn 지번 조회 탭)이 같이 쓴다: 지번만, 5건, 조회 기록 */
export async function staffLookup(db: D1Database, username: string, qRaw: string) {
  await ensureListings(db);
  const q = String(qRaw ?? "").trim();
  if (q.length < 2) return { q, rows: [], count: 0 };
  const bad = jibunCheck(q);
  if (bad) { await log(db, username, q + " (거부)", 0); return { q, rows: [], count: 0, error: bad }; }
  const lotOnly = /^\s*(산\s*)?\d{1,4}(\s*-\s*\d{1,4})?\s*(번지)?\s*$/.test(q);
  const [where, binds] = lotOnly ? lotWhere(q) : lookupWhere(q, false);
  const { results } = await db.prepare("SELECT addr, phone, contacts, memo, kind, deal, price, title, last_at FROM listings" + where + " ORDER BY addr, id LIMIT ?").bind(...binds, MAX_ROWS + 1).all();
  const all = (results ?? []).map((r: any) => ({ addr: r.addr, phone: r.phone, contacts: r.contacts, memo: r.memo, kind: r.kind, deal: r.deal, price: r.price, title: r.title, last_at: kst(r.last_at) }));
  const rows = all.slice(0, MAX_ROWS);
  await log(db, username, q, rows.length);
  return { q, count: rows.length, more: all.length > MAX_ROWS, rows };
}
staffdb.get("/db/lookup.json", async (c) => {
  const u = await session(c);
  if (!u) return c.json({ error: "login" }, 401);
  return c.json(await staffLookup(c.env.DB, u, (c.req.query("q") ?? "").toString()));
});

const DB_STYLE = `
.muted{color:var(--muted)}
.x{border:0;background:transparent;color:var(--accent-dark);cursor:pointer;padding:0}
.lookup{background:linear-gradient(135deg,#fff0f6,#ffffff);border:2px solid var(--accent);border-radius:14px;padding:14px 16px;margin-bottom:14px;box-shadow:0 8px 28px rgba(255,92,154,.12)}
.lkrow{display:flex;flex-wrap:wrap;gap:10px;align-items:center;font-size:13px}
.lkrow input{display:inline-block;width:auto;flex:1;min-width:260px;margin:0;padding:12px 14px;font-size:16px;border:1px solid var(--border);border-radius:10px;background:#fff;color:var(--text)}
#lkres{margin-top:10px;overflow-x:auto}
#lkres table{width:100%;border-collapse:collapse;background:#fff;border:1px solid var(--border);border-radius:10px;overflow:hidden}
#lkres th,#lkres td{padding:9px 10px;border-bottom:1px solid #fbe3ec;font-size:13px;text-align:left;white-space:nowrap;max-width:260px;overflow:hidden;text-overflow:ellipsis}
#lkres th{background:var(--soft);color:var(--accent-dark);font-weight:700}
#lkres td.addr{font-weight:700;color:var(--accent-dark);max-width:340px;white-space:normal}
#lkres td.phone{font-family:Consolas,monospace;font-weight:700;font-size:14px}
#lkres td.contacts{white-space:normal;font-size:12px;line-height:1.5;min-width:140px;max-width:240px}
#lkres td.memo{white-space:normal;max-width:220px}
#lkres .lknone{color:var(--muted);font-size:13px;padding:6px 2px}
@media(max-width:700px){.container{padding:14px 10px}.page-head h1{font-size:18px}}
`;
const DB_JS = `
(function(){
  var $=function(i){return document.getElementById(i)};
  var esc=function(v){return String(v==null?'':v).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')};
  var t=null,last='';
  async function lookup(){
    var q=$('lkq').value.trim(); var res=$('lkres'), msg=$('lkmsg');
    if(q.length<2){ res.innerHTML=''; msg.textContent='번지(예: 821-6)를 치면 바로 찾습니다. 5건까지 보입니다.'; return; }
    if(q===last) return; last=q; msg.textContent='찾는 중…';
    try{
      var r=await fetch('/db/lookup.json?q='+encodeURIComponent(q)).then(function(x){ if(x.status===401){ location.href='/db'; throw new Error('로그인 필요'); } return x.json(); });
      if($('lkq').value.trim()!==q) return;
      if(r.error){ res.innerHTML='<div class="lknone">'+esc(r.error)+'</div>'; msg.textContent=''; return; }
      if(!r.rows.length){ res.innerHTML='<div class="lknone">"'+esc(q)+'" 에 해당하는 줄이 없습니다.</div>'; msg.textContent='0건'; return; }
      var h='<table><thead><tr><th>지번·호수</th><th>임대인 연락처</th><th>임차인·관리 등</th><th>종류</th><th>거래</th><th>금액</th><th>이름·제목</th><th>메모</th><th>올린 날</th></tr></thead><tbody>';
      r.rows.forEach(function(x){ h+='<tr><td class="addr">'+esc(x.addr)+'</td><td class="phone">'+esc(x.phone)+'</td><td class="contacts">'+esc(x.contacts)+'</td><td>'+esc(x.kind)+'</td><td>'+esc(x.deal)+'</td><td>'+esc(x.price)+'</td><td>'+esc(x.title)+'</td><td class="memo">'+esc(x.memo)+'</td><td class="small">'+esc(x.last_at)+'</td></tr>'; });
      h+='</tbody></table>'+(r.more?'<div class="lknone">5건까지만 보입니다. 호수까지 치면 더 정확히 나옵니다.</div>':''); res.innerHTML=h; msg.textContent=r.count+'건'+(r.more?'+':'');
    }catch(e){ msg.textContent='오류: '+e.message; }
  }
  $('lkq').addEventListener('input',function(){ clearTimeout(t); t=setTimeout(lookup,300); });
  $('lkq').addEventListener('keydown',function(e){ if(e.key==='Enter'){ e.preventDefault(); clearTimeout(t); last=''; lookup(); } });
  $('lkgo').onclick=function(){ last=''; lookup(); };
  if($('lkq').value.trim().length>=2) lookup();
})();
`;
