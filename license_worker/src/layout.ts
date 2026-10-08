import { html, raw } from "hono/html";

// 어드민 공통 레이아웃 (대시보드·사진950 이 같이 씀)
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
  <div class="brand">전국부동산매물수집기 · 라이선스 관리</div>
  <nav class="nav"><a href="/admin/dashboard">사용자 관리</a><a href="/admin/logs">활동 기록</a><a href="/admin/telegram">텔레그램 봇</a><a href="/admin/photos">사진 950</a><a href="/admin/listings">매물·임대인 DB</a></nav>
</header>
<main class="container">${body}</main>
</body>
</html>`;
}

export const STYLE = `
:root{color-scheme:light dark;--bg:#0f1420;--panel:#171d2b;--border:#2a3348;--text:#e7ebf3;--muted:#93a0b8;--accent:#5b7cfa;--danger:#e0556f;--ok:#3fbf7f;--warn:#e0a83f;}
*{box-sizing:border-box;}
body{margin:0;font-family:"Pretendard","Segoe UI",-apple-system,sans-serif;background:var(--bg);color:var(--text);}
a{color:var(--accent);text-decoration:none;}
.topbar{display:flex;align-items:center;justify-content:space-between;padding:14px 24px;border-bottom:1px solid var(--border);background:var(--panel);}
.brand{font-weight:700;}
.nav{display:flex;gap:6px;}
.nav a{padding:6px 12px;border-radius:8px;border:1px solid var(--border);color:var(--text);font-size:13px;}
.nav a:hover{background:#1d2436;}
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
.feat-form{display:flex;gap:10px;}
.feat{display:inline-flex!important;align-items:center;gap:4px;margin:0!important;font-size:12px;color:var(--text)!important;white-space:nowrap;}
.feat input{width:auto!important;display:inline-block!important;margin:0!important;}
.feat-pick{display:flex;gap:14px;align-items:center;margin-bottom:14px;font-size:13px;color:var(--muted);}
`;

