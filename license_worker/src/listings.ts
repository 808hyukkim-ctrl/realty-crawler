// 매물 DB (2026-10-08) — 수집기(네이버·당근·온하우스)가 엑셀을 저장할 때마다 같은 행을 서버(D1)에 쌓는다.
//   POST /api/v1/listings {username, token, site, file, rows:[{열:값}]}   프로그램이 올림 (사이트+매물번호+거래 기준 upsert — 당근은 한 매물이 전세·월세 두 행, 다시 수집되면 최근수집·횟수만 갱신)
//   GET  /admin/listings                                                어드민 화면 (사이트·검색어·기간·계정·파일 필터, 100건씩)
//   GET  /admin/listings/rows.json?...&after=&limit=                   필터 결과를 id 순으로 내려줌 → 브라우저가 SheetJS 로 엑셀 생성
//   POST /admin/listings/delete                                         필터 결과 삭제
import { Hono } from "hono";
import { html, raw } from "hono/html";
import { layout } from "./layout";

type Bindings = { DB: D1Database; ADMIN_USER: string; ADMIN_PASSWORD: string };
export const listings = new Hono<{ Bindings: Bindings }>();

export const SITE_LABEL: Record<string, string> = { naver: "네이버", daangn: "당근", onhouse: "온하우스", peterpan: "피터팬" };
const siteLabel = (s: string) => SITE_LABEL[s] || s;

let ready = false;
async function ensure(db: D1Database) {
  if (ready) return;
  await db.prepare(`CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site TEXT NOT NULL, listing_no TEXT NOT NULL, url TEXT,
    username TEXT NOT NULL, file TEXT,
    addr TEXT, kind TEXT, deal TEXT, price TEXT, title TEXT,
    data TEXT NOT NULL,
    first_at TEXT NOT NULL, last_at TEXT NOT NULL, seen INTEGER NOT NULL DEFAULT 1,
    UNIQUE(site, listing_no, deal))`).run();
  await db.prepare("CREATE INDEX IF NOT EXISTS listings_last ON listings(last_at DESC)").run();
  await db.prepare("CREATE INDEX IF NOT EXISTS listings_site_last ON listings(site, last_at DESC)").run();
  await db.prepare("CREATE INDEX IF NOT EXISTS listings_file ON listings(file)").run();
  ready = true;
}
const nowIso = () => new Date().toISOString();
async function hmacHex(secret: string, msg: string): Promise<string> {
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(msg));
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
const logToken = (secret: string, username: string) => hmacHex(secret, "log:" + username);
async function sha256Hex(s: string): Promise<string> {
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// ---------------------------------------------------------------- 행 → 요약 열
const s = (v: any) => (v == null ? "" : String(v)).trim();
const first = (row: Record<string, any>, ...keys: string[]) => { for (const k of keys) { const v = s(row[k]); if (v) return v; } return ""; };

/** 엑셀 열 이름으로 사이트를 알아낸다 (프로그램이 보낸 힌트는 열로 판별이 안 될 때만) */
export function detectSite(cols: string[], hint: string): string {
  const has = (k: string) => cols.includes(k);
  if (has("매물_URL") || (has("지번주소") && has("거래주체"))) return "daangn";
  if (has("세부주소") && has("거래방식")) return "naver";
  if (has("매물ID") && (has("확인일") || has("전체주소"))) return "onhouse";
  const h = hint.toLowerCase();
  if (/네이버|naver/.test(h)) return "naver";
  if (/당근|daangn/.test(h)) return "daangn";
  if (/온하우스|onhouse/.test(h)) return "onhouse";
  if (/피터팬|peterpan/.test(h)) return "peterpan";
  return h.replace(/[^a-z0-9가-힣_]/g, "").slice(0, 20) || "etc";
}

/** 사이트별로 매물번호·링크·주소·종류·거래·금액·제목을 뽑는다 (목록 표시·검색용, 원본 행은 data 에 통째로 보관) */
export function summarize(site: string, row: Record<string, any>) {
  let no = "", url = "", addr = "", kind = "", deal = "", price = "", title = "";
  if (site === "naver") {
    const v = first(row, "매물번호");                       // 네이버 엑셀의 매물번호 셀은 전체 URL (articleNo=…)
    const m = v.match(/articleNo=(\d+)/);
    no = m ? m[1] : v; url = /^https?:/i.test(v) ? v : "";
    addr = first(row, "세부주소", "주소"); kind = first(row, "종류"); deal = first(row, "거래방식");
    price = first(row, "매매/전세금"); const w = first(row, "월세"); if (w && w !== "0") price = price ? `${price} / ${w}` : w;
    title = first(row, "매물명");
  } else if (site === "daangn") {
    no = first(row, "매물번호"); url = first(row, "매물_URL", "URL");
    addr = first(row, "지번주소", "주소"); kind = first(row, "매물유형"); deal = first(row, "거래유형");
    const w = first(row, "월세");
    price = first(row, "매매가", "전세금", "보증금"); if (w && w !== "0") price = price ? `${price} / ${w}` : w;
    title = first(row, "제목");
  } else if (site === "onhouse") {
    no = first(row, "매물ID", "물건번호").replace(/^No/i, ""); url = first(row, "URL");
    addr = first(row, "전체주소", "주소_호실", "지역");
    const pick = (["매매", "전세", "월세"] as const).find((k) => s(row[k]));
    if (pick) { deal = pick; price = s(row[pick]); kind = s(row[pick + "_태그"]).split(",")[0].trim(); }
    title = first(row, "건물명", "현업종", "지역");
  } else {
    no = first(row, "매물번호", "매물ID", "ID", "id", "번호"); url = first(row, "URL", "매물_URL", "링크", "url");
    addr = first(row, "주소", "지번주소", "세부주소", "전체주소"); kind = first(row, "종류", "매물유형"); deal = first(row, "거래방식", "거래유형");
    price = first(row, "가격", "매매가", "전세금", "보증금"); title = first(row, "제목", "매물명", "건물명");
  }
  return { no: no.slice(0, 80), url: url.slice(0, 500), addr: addr.slice(0, 200), kind: kind.slice(0, 40), deal: deal.slice(0, 20), price: price.slice(0, 60), title: title.slice(0, 200) };
}

// ---------------------------------------------------------------- 프로그램 API
listings.post("/api/v1/listings", async (c) => {
  const body: any = await c.req.json().catch(() => null);
  if (!body) return c.json({ success: false, message: "JSON 본문이 아닙니다." }, 400);
  const username = s(body.username), token = s(body.token);
  if (!username || !token || token !== (await logToken(c.env.ADMIN_PASSWORD, username))) return c.json({ success: false, message: "토큰이 맞지 않습니다." }, 401);
  const rowsIn: any[] = Array.isArray(body.rows) ? body.rows : [];
  if (!rowsIn.length) return c.json({ success: true, inserted: 0, updated: 0, message: "행이 없습니다." });
  if (rowsIn.length > 1000) return c.json({ success: false, message: "한 번에 1000행까지 보낼 수 있습니다." }, 413);
  await ensure(c.env.DB);
  const cols = Object.keys(rowsIn[0] || {});
  const site = detectSite(cols, s(body.site));
  const file = s(body.file).slice(0, 200);
  const at = nowIso();

  const stmts: D1PreparedStatement[] = [];
  const keys = new Set<string>();
  for (const raw0 of rowsIn) {
    if (!raw0 || typeof raw0 !== "object") continue;
    const row: Record<string, string> = {};
    for (const [k, v] of Object.entries(raw0)) { const kk = s(k).slice(0, 60); if (kk) row[kk] = v == null ? "" : String(v); }
    if (!Object.values(row).some((v) => v.trim())) continue;        // 빈 행
    const sum = summarize(site, row);
    const json = JSON.stringify(row);
    const no = sum.no || "h:" + (await sha256Hex(json)).slice(0, 24);
    if (keys.has(no + "|" + sum.deal)) continue;                      // 같은 파일 안의 중복 (한 statement 묶음 안에서 두 번 upsert 방지)
    keys.add(no + "|" + sum.deal);
    stmts.push(c.env.DB.prepare(
      `INSERT INTO listings (site, listing_no, url, username, file, addr, kind, deal, price, title, data, first_at, last_at, seen)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
       ON CONFLICT(site, listing_no, deal) DO UPDATE SET url = excluded.url, username = excluded.username, file = excluded.file,
         addr = excluded.addr, kind = excluded.kind, deal = excluded.deal, price = excluded.price, title = excluded.title,
         data = excluded.data, last_at = excluded.last_at, seen = listings.seen + 1`
    ).bind(site, no, sum.url, username, file, sum.addr, sum.kind, sum.deal, sum.price, sum.title, json, at, at));
  }
  const before = (await c.env.DB.prepare("SELECT COUNT(*) n FROM listings WHERE site = ?").bind(site).first<{ n: number }>())?.n ?? 0;
  for (let i = 0; i < stmts.length; i += 40) await c.env.DB.batch(stmts.slice(i, i + 40));
  const after = (await c.env.DB.prepare("SELECT COUNT(*) n FROM listings WHERE site = ?").bind(site).first<{ n: number }>())?.n ?? 0;
  const inserted = after - before;
  return c.json({ success: true, site, inserted, updated: stmts.length - inserted, total: after });
});

// ---------------------------------------------------------------- 필터
type Filter = { site: string; q: string; from: string; to: string; user: string; file: string };
function readFilter(c: any): Filter {
  const g = (k: string) => (c.req.query(k) ?? "").toString().trim();
  return { site: g("site"), q: g("q"), from: g("from"), to: g("to"), user: g("user"), file: g("file") };
}
const kstDayStart = (d: string) => new Date(d + "T00:00:00+09:00").toISOString();
const kstDayEnd = (d: string) => new Date(d + "T23:59:59.999+09:00").toISOString();
function whereOf(f: Filter): [string, any[]] {
  const w: string[] = []; const b: any[] = [];
  if (f.site) { w.push("site = ?"); b.push(f.site); }
  if (f.user) { w.push("username = ?"); b.push(f.user); }
  if (f.file) { w.push("file = ?"); b.push(f.file); }
  if (f.from && /^\d{4}-\d{2}-\d{2}$/.test(f.from)) { w.push("last_at >= ?"); b.push(kstDayStart(f.from)); }
  if (f.to && /^\d{4}-\d{2}-\d{2}$/.test(f.to)) { w.push("last_at <= ?"); b.push(kstDayEnd(f.to)); }
  if (f.q) { w.push("(addr LIKE ? OR title LIKE ? OR listing_no LIKE ? OR price LIKE ? OR kind LIKE ? OR data LIKE ?)"); const like = `%${f.q}%`; b.push(like, like, like, like, like, like); }
  return [w.length ? " WHERE " + w.join(" AND ") : "", b];
}
const qs = (f: Filter, extra: Record<string, any> = {}) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries({ ...f, ...extra })) if (v !== "" && v != null) p.set(k, String(v));
  return p.toString();
};
const kst = (iso: string) => { try { return new Date(iso).toLocaleString("ko-KR", { timeZone: "Asia/Seoul", hour12: false, year: "2-digit", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }); } catch { return iso; } };

// ---------------------------------------------------------------- 어드민 화면
listings.get("/admin/listings", async (c) => {
  await ensure(c.env.DB);
  const f = readFilter(c);
  const page = Math.max(1, parseInt(c.req.query("page") ?? "1", 10) || 1);
  const PER = 100;
  const [where, binds] = whereOf(f);
  const total = (await c.env.DB.prepare("SELECT COUNT(*) n FROM listings" + where).bind(...binds).first<{ n: number }>())?.n ?? 0;
  const { results } = await c.env.DB.prepare("SELECT * FROM listings" + where + " ORDER BY last_at DESC, id DESC LIMIT ? OFFSET ?").bind(...binds, PER, (page - 1) * PER).all();
  const bySite = (await c.env.DB.prepare("SELECT site, COUNT(*) n FROM listings GROUP BY site ORDER BY n DESC").all()).results ?? [];
  const recent = (await c.env.DB.prepare("SELECT file, site, username, COUNT(*) n, MAX(last_at) t FROM listings GROUP BY file, site, username ORDER BY t DESC LIMIT 8").all()).results ?? [];
  const users = (await c.env.DB.prepare("SELECT DISTINCT username FROM listings ORDER BY username").all()).results ?? [];
  const pages = Math.max(1, Math.ceil(total / PER));

  const rows = (results ?? []).map((r: any) => {
    let data: Record<string, string> = {}; try { data = JSON.parse(r.data); } catch {}
    const detail = Object.entries(data).filter(([, v]) => s(v)).map(([k, v]) => html`<div class="kv"><b>${k}</b><span>${v}</span></div>`);
    return html`<tr>
      <td><span class="badge ${r.site === "naver" ? "status-active" : r.site === "daangn" ? "status-soon" : "status-unlimited"}">${siteLabel(r.site)}</span></td>
      <td class="mono small">${r.url ? html`<a href="${r.url}" target="_blank" rel="noopener">${r.listing_no}</a>` : r.listing_no}</td>
      <td>${r.addr ?? ""}</td>
      <td class="small">${r.kind ?? ""}</td>
      <td class="small">${r.deal ?? ""}</td>
      <td class="mono small">${r.price ?? ""}</td>
      <td class="small ttl">${r.title ?? ""}</td>
      <td class="mono small">${r.username}</td>
      <td class="mono small" title="처음 ${kst(r.first_at)} · ${r.seen}회">${kst(r.last_at)}${r.seen > 1 ? html` <span class="seen">×${r.seen}</span>` : ""}</td>
      <td><details class="det"><summary>상세</summary><div class="detbox">${detail}</div></details></td>
    </tr>`;
  });
  const siteOpts = Object.entries(SITE_LABEL).map(([k, v]) => html`<option value="${k}" ${f.site === k ? "selected" : ""}>${v}</option>`);
  const userOpts = users.map((u: any) => html`<option value="${u.username}" ${f.user === u.username ? "selected" : ""}>${u.username}</option>`);
  const pageLink = (p: number, label: string) => html`<a class="btn btn-sm" href="/admin/listings?${raw(qs(f, { page: p }))}">${label}</a>`;

  const body = html`
    <div class="page-head">
      <h1>매물 DB</h1>
      <span class="small" style="color:var(--muted)">수집기가 엑셀을 저장할 때마다 자동으로 쌓입니다 · 전체 ${bySite.reduce((a: number, r: any) => a + r.n, 0)}건 (${bySite.map((r: any) => `${siteLabel(r.site)} ${r.n}`).join(" · ") || "없음"})</span>
    </div>
    <form class="search-form lf" method="get" id="lf">
      <select name="site"><option value="">전체 사이트</option>${siteOpts}</select>
      <select name="user"><option value="">전체 계정</option>${userOpts}</select>
      <input type="text" name="q" placeholder="주소·제목·매물번호·내용 검색" value="${f.q}">
      <input type="date" name="from" value="${f.from}" title="최근수집 시작일"> ~ <input type="date" name="to" value="${f.to}" title="최근수집 종료일">
      ${f.file ? html`<input type="hidden" name="file" value="${f.file}"><span class="chip">파일: ${f.file} <a href="/admin/listings?${raw(qs({ ...f, file: "" }))}">✕</a></span>` : ""}
      <button type="submit" class="btn">검색</button>
      <a class="btn" href="/admin/listings">초기화</a>
      <button type="button" class="btn btn-primary" id="xl" ${total ? "" : "disabled"}>엑셀 다운로드 (${total}건)</button>
      <button type="button" class="btn btn-danger" id="del" ${total ? "" : "disabled"}>조건 삭제</button>
    </form>
    <div id="xlmsg" class="small" style="color:var(--muted);margin:-8px 0 12px"></div>
    ${recent.length ? html`<div class="recent"><b>최근 수집 파일</b> ${recent.map((r: any) => html`<a class="chip" href="/admin/listings?${raw(qs({ site: "", q: "", from: "", to: "", user: "", file: r.file }))}" title="${r.username} · ${kst(r.t)}">${siteLabel(r.site)} · ${r.file} <em>${r.n}</em></a>`)}</div>` : ""}
    <table class="user-table lt">
      <thead><tr><th>사이트</th><th>매물번호</th><th>주소</th><th>종류</th><th>거래</th><th>금액</th><th>제목/매물명</th><th>계정</th><th>최근수집</th><th></th></tr></thead>
      <tbody>${rows.length ? rows : html`<tr><td colspan="10" class="empty">${total ? "이 페이지에는 없습니다." : "쌓인 매물이 없습니다. 수집기로 엑셀을 저장하면 올라옵니다."}</td></tr>`}</tbody>
    </table>
    <div class="pager">${page > 1 ? pageLink(page - 1, "‹ 이전") : ""}<span class="small">${page} / ${pages} 페이지 · ${total}건</span>${page < pages ? pageLink(page + 1, "다음 ›") : ""}</div>
    <form method="post" action="/admin/listings/delete" id="delf" style="display:none">
      ${Object.entries(f).map(([k, v]) => html`<input type="hidden" name="${k}" value="${v}">`)}
    </form>
    <style>${raw(LT_STYLE)}</style>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js"></script>
    <script>var LT_QS=${raw(JSON.stringify(qs(f)))}, LT_TOTAL=${total}, LT_SITE=${raw(JSON.stringify(f.site ? siteLabel(f.site) : "전체"))};${raw(LT_JS)}</script>`;
  return c.html(layout("매물 DB", body));
});

// 필터 결과를 id 오름차순으로 (after 커서) — 엑셀 만들 때 브라우저가 끝까지 긁어 간다
listings.get("/admin/listings/rows.json", async (c) => {
  await ensure(c.env.DB);
  const f = readFilter(c);
  const after = parseInt(c.req.query("after") ?? "0", 10) || 0;
  const limit = Math.min(2000, Math.max(1, parseInt(c.req.query("limit") ?? "1000", 10) || 1000));
  const [where, binds] = whereOf(f);
  const { results } = await c.env.DB.prepare("SELECT id, site, listing_no, url, username, file, first_at, last_at, seen, data FROM listings" + (where ? where + " AND" : " WHERE") + " id > ? ORDER BY id LIMIT ?").bind(...binds, after, limit).all();
  const rows = (results ?? []).map((r: any) => ({ id: r.id, site: siteLabel(r.site), no: r.listing_no, url: r.url, username: r.username, file: r.file, first_at: kst(r.first_at), last_at: kst(r.last_at), seen: r.seen, data: (() => { try { return JSON.parse(r.data); } catch { return {}; } })() }));
  return c.json({ rows, next: rows.length === limit ? rows[rows.length - 1].id : null });
});

listings.post("/admin/listings/delete", async (c) => {
  await ensure(c.env.DB);
  const form = await c.req.formData();
  const g = (k: string) => String(form.get(k) ?? "").trim();
  const f: Filter = { site: g("site"), q: g("q"), from: g("from"), to: g("to"), user: g("user"), file: g("file") };
  const [where, binds] = whereOf(f);
  const r = await c.env.DB.prepare("DELETE FROM listings" + where).bind(...binds).run();
  return c.redirect("/admin/listings?" + qs({ site: f.site, q: "", from: "", to: "", user: "", file: "" }) + "&deleted=" + (r.meta?.changes ?? 0));
});

const LT_STYLE = `
.lf{flex-wrap:wrap;align-items:center}
.lf select,.lf input[type=date]{padding:8px 10px;border-radius:8px;border:1px solid var(--border);background:#0d121c;color:var(--text);font-size:13px}
.lf input[type=text]{min-width:260px}
.chip{display:inline-flex;gap:6px;align-items:center;padding:4px 10px;border-radius:999px;border:1px solid var(--border);background:#1d2436;font-size:12px;color:var(--text);margin:2px 4px 2px 0}
.chip em{font-style:normal;color:var(--accent);font-weight:600}
.recent{margin:0 0 14px;font-size:13px;color:var(--muted);line-height:2}
.lt td{max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.lt td.ttl{max-width:200px}
.seen{color:var(--warn);font-size:10px}
.det summary{cursor:pointer;color:var(--accent);font-size:12px;list-style:none}
.detbox{position:absolute;z-index:5;right:24px;max-width:640px;max-height:420px;overflow:auto;background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:12px 14px;box-shadow:0 8px 30px rgba(0,0,0,.4);white-space:normal}
.kv{display:grid;grid-template-columns:120px 1fr;gap:8px;font-size:12px;padding:3px 0;border-bottom:1px solid var(--border)}
.kv b{color:var(--muted);font-weight:600}
.kv span{white-space:pre-wrap;word-break:break-all}
.pager{display:flex;gap:12px;align-items:center;justify-content:center;margin:16px 0}
`;

// 엑셀 만들기: 열 = 기본 정보 + 원본 행의 열(처음 나온 순서, 사이트가 섞이면 합집합). 링크 열은 하이퍼링크.
const LT_JS = `
(function(){
  var $=function(i){return document.getElementById(i)};
  var q=new URLSearchParams(location.search); if(q.get('deleted')!=null){ $('xlmsg').textContent='삭제했습니다: '+q.get('deleted')+'건'; }
  $('del').onclick=function(){ if(confirm('현재 검색 조건의 '+LT_TOTAL+'건을 삭제할까요? 되돌릴 수 없습니다.')) $('delf').submit(); };
  $('xl').onclick=async function(){
    var btn=$('xl'); btn.disabled=true; var msg=$('xlmsg'); var all=[]; var after=0;
    try{
      while(true){
        msg.textContent='내려받는 중… '+all.length+' / '+LT_TOTAL+'건';
        var r=await fetch('/admin/listings/rows.json?'+LT_QS+'&after='+after+'&limit=1000').then(function(x){return x.json()});
        all=all.concat(r.rows); if(!r.next) break; after=r.next;
      }
      if(!all.length){ msg.textContent='내려받을 행이 없습니다.'; btn.disabled=false; return; }
      var meta=['사이트','매물번호(DB)','링크(DB)','수집계정','수집파일','처음수집','최근수집','수집횟수'];
      var cols=[]; var seen={};
      all.forEach(function(r){ Object.keys(r.data).forEach(function(k){ if(!seen[k]){ seen[k]=1; cols.push(k); } }); });
      var aoa=[meta.concat(cols)];
      all.forEach(function(r){ var row=[r.site,r.no,r.url||'',r.username,r.file||'',r.first_at,r.last_at,r.seen]; cols.forEach(function(k){ var v=r.data[k]; row.push(v==null?'':String(v)); }); aoa.push(row); });
      var ws=XLSX.utils.aoa_to_sheet(aoa);
      for(var i=1;i<aoa.length;i++){ var u=aoa[i][2]; if(u){ var c=ws[XLSX.utils.encode_cell({r:i,c:2})]; if(c) c.l={Target:u}; }
        aoa[i].forEach(function(v,j){ if(typeof v==='string' && /^https?:\\/\\//.test(v) && j>2){ var cc=ws[XLSX.utils.encode_cell({r:i,c:j})]; if(cc) cc.l={Target:v}; } }); }
      ws['!cols']=aoa[0].map(function(h,j){ var w=Math.min(60,Math.max(8,String(h).length*2)); for(var i=1;i<Math.min(aoa.length,300);i++){ var v=aoa[i][j]; if(v!=null) w=Math.max(w,Math.min(60,String(v).length*1.1)); } return {wch:w}; });
      ws['!autofilter']={ref:XLSX.utils.encode_range({s:{r:0,c:0},e:{r:aoa.length-1,c:aoa[0].length-1}})};
      var wb=XLSX.utils.book_new(); XLSX.utils.book_append_sheet(wb,ws,'매물');
      var d=new Date(), ts=d.getFullYear().toString().slice(2)+('0'+(d.getMonth()+1)).slice(-2)+('0'+d.getDate()).slice(-2)+'_'+('0'+d.getHours()).slice(-2)+('0'+d.getMinutes()).slice(-2);
      XLSX.writeFile(wb,'매물DB_'+LT_SITE+'_'+all.length+'건_'+ts+'.xlsx');
      msg.textContent='엑셀 저장 완료: '+all.length+'건';
    }catch(e){ msg.textContent='오류: '+e.message; }
    btn.disabled=false;
  };
})();
`;
