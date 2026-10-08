import { html, raw } from "hono/html";

// 어드민 공통 레이아웃 (대시보드·활동 기록·텔레그램·사진950·매물 DB 가 같이 씀) — 2026-10-08 밝은 핑크 테마로 교체 (사용자: "너무 어두워, 핑크색으로 화사하게")
export function layout(title: string, body: unknown) {
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
  <div class="brand">🌸 전국부동산매물수집기 · 관리</div>
  <nav class="nav"><a href="/admin/listings">매물·임대인 DB</a><a href="/admin/dashboard">사용자 관리</a><a href="/admin/logs">활동 기록</a><a href="/admin/telegram">텔레그램 봇</a><a href="/admin/photos">사진 950</a><a href="/admin/daangn">당근 광고</a></nav>
</header>
<main class="container">${body}</main>
</body>
</html>`;
}

export const STYLE = `
:root{color-scheme:light;--bg:#fff5f9;--panel:#ffffff;--soft:#ffe9f2;--border:#f5c9db;--text:#3b2230;--muted:#9d7488;--accent:#ff5c9a;--accent-dark:#d63a78;--danger:#e04a6a;--ok:#2f9e6e;--warn:#e08a2f;--input:#ffffff;}
*{box-sizing:border-box;}
body{margin:0;font-family:"Pretendard","Segoe UI","Malgun Gothic",-apple-system,sans-serif;background:var(--bg);color:var(--text);}
a{color:var(--accent-dark);text-decoration:none;}
.topbar{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;padding:14px 24px;border-bottom:1px solid var(--border);background:linear-gradient(90deg,#ffd3e4,#ffe9f2 60%,#fff5f9);}
.brand{font-weight:800;color:var(--accent-dark);}
.nav{display:flex;gap:6px;flex-wrap:wrap;}
.nav a{padding:6px 12px;border-radius:999px;border:1px solid var(--border);color:var(--accent-dark);font-size:13px;background:#fff;}
.nav a:hover{background:var(--accent);color:#fff;border-color:var(--accent);}
.container{max-width:1240px;margin:0 auto;padding:28px 20px;}
.form-box{max-width:420px;margin:30px auto;background:var(--panel);border:1px solid var(--border);border-radius:14px;padding:28px;box-shadow:0 6px 24px rgba(255,92,154,.08);}
.form-box h1{margin-top:0;font-size:20px;color:var(--accent-dark);}
form label{display:block;margin-bottom:14px;font-size:13px;color:var(--muted);}
form input,form select,form textarea{display:block;width:100%;margin-top:6px;padding:10px 12px;border-radius:8px;border:1px solid var(--border);background:var(--input);color:var(--text);font-size:14px;}
form input:focus,form select:focus,form textarea:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px rgba(255,92,154,.15);}
.btn{display:inline-block;padding:9px 16px;border-radius:999px;border:1px solid var(--border);background:#fff;color:var(--accent-dark);cursor:pointer;font-size:13px;font-weight:600;}
.btn:hover{background:var(--soft);}
.btn-primary{background:var(--accent);border-color:var(--accent);color:#fff;}
.btn-primary:hover{background:var(--accent-dark);border-color:var(--accent-dark);}
.btn-danger{background:transparent;color:var(--danger);border-color:var(--danger);}
.btn-danger:hover{background:rgba(224,74,106,.08);}
.btn[disabled]{opacity:.45;cursor:default;}
.btn-sm{padding:6px 10px;font-size:12px;}
.form-actions{display:flex;gap:10px;margin-top:20px;}
.error{color:var(--danger);font-size:13px;}
.page-head{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:18px;}
.page-head h1{margin:0;font-size:22px;color:var(--accent-dark);}
.search-form{margin-bottom:16px;display:flex;gap:8px;}
.search-form input{padding:8px 12px;border-radius:8px;border:1px solid var(--border);background:var(--input);color:var(--text);min-width:220px;}
.user-table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--border);border-radius:14px;overflow:hidden;box-shadow:0 6px 24px rgba(255,92,154,.06);}
.user-table th,.user-table td{padding:10px 12px;border-bottom:1px solid #fbe3ec;font-size:13px;text-align:left;vertical-align:middle;}
.user-table th{color:var(--accent-dark);font-weight:700;background:var(--soft);}
.user-table tr:hover td{background:#fffafc;}
.user-table .mono{font-family:"Consolas",monospace;}
.user-table .small{font-size:11px;color:var(--muted);}
.user-table .empty{text-align:center;color:var(--muted);padding:30px;}
.badge{padding:3px 9px;border-radius:999px;font-size:11px;font-weight:600;}
.status-active{background:rgba(47,158,110,.14);color:var(--ok);}
.status-unlimited{background:rgba(96,110,240,.14);color:#4f5fd6;}
.status-expired{background:rgba(224,74,106,.14);color:var(--danger);}
.status-disabled{background:rgba(157,116,136,.14);color:var(--muted);}
.status-soon{background:rgba(224,138,47,.14);color:var(--warn);}
.inline-form{display:inline-flex;gap:6px;align-items:center;}
.actions{display:flex;flex-wrap:wrap;gap:6px;}
.pw-input{width:120px;padding:6px 8px;font-size:12px;}
.feat-form{display:flex;gap:10px;}
.feat{display:inline-flex!important;align-items:center;gap:4px;margin:0!important;font-size:12px;color:var(--text)!important;white-space:nowrap;}
.feat input{width:auto!important;display:inline-block!important;margin:0!important;}
.feat-pick{display:flex;gap:14px;align-items:center;margin-bottom:14px;font-size:13px;color:var(--muted);}
select{padding:8px 12px;border-radius:8px;border:1px solid var(--border);background:var(--input);color:var(--text);}
`;
