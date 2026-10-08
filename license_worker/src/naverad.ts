// 네이버 광고정리 (2026-10-09) — 한 탭, 좌우 반반
//   왼쪽  링크 자동 정리: 네이버(당근·온하우스도) 링크를 여러 개 넣으면 광고에 필요한 값(지번·도로명·금액·사용승인일·해당층/총층·총주차대수·공급/전용면적·방/욕실·향·입주·중개사)을
//          표로 바로 뽑아 주고, [DB에 저장](매물·임대인 DB) · [엑셀] · 줄마다 [광고문구 복사]
//          - 기본 값은 bridge-parse 워커(/parse?no=, 서비스 바인딩 PARSE) · 지번 번지/사용승인일/총주차대수/도로명은 fin.land.naver.com 상세 페이지의 데이터
//   오른쪽 지번으로 네이버 매물 찾기: "역삼동 777-2" → (1) 우리 DB 에 쌓인 줄 (2) 지금 네이버에 걸린 매물 — 지번을 좌표로 바꾸고(한국 엔진 /geocode) 그 동(법정동코드)의
//          네이버 목록을 넘기며 좌표가 가까운 매물만 추린 뒤 fin.land 상세로 지번이 정확히 같은지 확인해 링크와 함께 보여준다
//   GET  /admin/naverad                 화면
//   POST /admin/naverad/parse  {urls}   링크 정리
//   POST /admin/naverad/save   {rows}   정리한 줄을 매물·임대인 DB 에 (구분 naver)
//   POST /admin/naverad/search {q}      지번 검색
import { Hono } from "hono";
import { html, raw } from "hono/html";
import { layout } from "./layout";
import { ensureListings, lookupWhere, kst, ingest } from "./listings";
import CORTAR from "./cortar.json";

type Bindings = { DB: D1Database; ADMIN_USER: string; ADMIN_PASSWORD: string; ENGINE_URL?: string; ENGINE_SECRET?: string; PARSE?: Fetcher };
export const naverad = new Hono<{ Bindings: Bindings }>();

const PARSE_API = "https://bridge-parse.808hyukkim.workers.dev/parse";
const NAVER_HEADERS: Record<string, string> = {
  'Accept': '*/*',
  'Accept-Language': 'ko-KR,ko;q=0.8,en-US;q=0.5,en;q=0.3',
  'Authorization': 'Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6IlJFQUxFU1RBVEUiLCJpYXQiOjE3NTU4NjE2MDIsImV4cCI6MTc1NTg3MjQwMn0.oUESmR0PhLfqPu50Dp0Ksd8hH6CbN69Kgy1AtKAJBkA',
  'Cookie': 'NNB=DHVGK5NIFRZGQ; BUC=dQnzU4cEAFITbLHCXucm96M1Hygq1eXI9lNBTGomvQ8=; NAC=bf7HCYhdY1viB; nstore_session=GhC7pWraNQqUi1r/3Cat+iHt; nstore_pagesession=jcNSelqqFq2n0wsMS4d-275984; ASID=d261344a00000198112a58d000000023; nhn.realestate.article.rlet_type_cd=A01; nhn.realestate.article.trade_type_cd=""; nhn.realestate.article.ipaddress_city=4100000000; _fwb=2477cFBKnotdBO5kFtJXAxb.1755860647279; landHomeFlashUseYn=Y; NACT=1; SRT30=1755860649; REALESTATE=Fri%20Aug%2022%202025%2020%3A20%3A02%20GMT%2B0900%20(Korean%20Standard%20Time); PROP_TEST_KEY=1755861602330.91922a3ba1b2bed031aac365bc7783fb4ad34c557cfec7fe9de50e9bbd33395f; PROP_TEST_ID=13ef4231cf828a73659d00b359317c1ed14816b42c7301637b8f1b90db90f7df; SRT5=1755861459',
  'Referer': 'https://new.land.naver.com/rooms?ms=37.362105,127.1040745,17&a=APT:OPST:ABYG:OBYG:GM:OR:DDDGG:JWJT:SGJT:HOJT:VL&e=RETAIL&aa=SMALLSPCRENT',
  'Sec-Fetch-Dest': 'empty', 'Sec-Fetch-Mode': 'cors', 'Sec-Fetch-Site': 'same-origin',
  'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:142.0) Gecko/20100101 Firefox/142.0',
};
const PAGE_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36";
const s = (v: any) => (v == null ? "" : String(v)).trim();
const num = (v: any) => { const n = Number(String(v ?? "").replace(/,/g, "")); return Number.isFinite(n) ? n : null; };
const ymd = (v: any) => s(v).replace(/^(\d{4})\.?(\d{2})\.?(\d{2}).*$/, "$1-$2-$3");

// ---------------------------------------------------------------- 공통
function naverNo(input: string): string {
  const t = s(input);
  const m = t.match(/articleNo=(\d{6,})/) || t.match(/land\.naver\.com\/(?:articles|houses|rooms|offices|complexes)\/(\d{6,})/) || t.match(/fin\.land\.naver\.com\/articles\/(\d{6,})/);
  if (m) return m[1];
  return /^\d{7,12}$/.test(t) ? t : "";
}
async function engineFetch(c: any, path: string): Promise<Response | null> {
  const base = String(c.env.ENGINE_URL || "").replace(/\/$/, "");
  if (!base || !c.env.ENGINE_SECRET) return null;
  try { return await fetch(base + path, { headers: { Authorization: `Bearer ${c.env.ENGINE_SECRET}` } }); } catch { return null; }
}
async function engineJson(c: any, path: string): Promise<any> {
  const r = await engineFetch(c, path); if (!r) return null;
  try { return await r.json(); } catch { return null; }
}
/** fin.land 상세 페이지(RSC 데이터)에서 지번·법정동코드·도로명·사용승인일·총주차대수 */
async function finLand(no: string): Promise<Record<string, string>> {
  const out: Record<string, string> = {};
  try {
    const r = await fetch(`https://fin.land.naver.com/articles/${no}`, { headers: { "User-Agent": PAGE_UA, Accept: "text/html,*/*", "Accept-Language": "ko-KR,ko;q=0.9" }, cf: { cacheTtl: 600 } } as any);
    if (!r.ok) { out._status = String(r.status); return out; }
    const h = await r.text();
    const pick = (key: string) => { const m = h.match(new RegExp('\\\\?"' + key + '\\\\?"\\s*:\\s*(?:\\\\?"([^"\\\\]*)\\\\?"|([0-9.]+)|(true|false|null))')); return m ? (m[1] ?? m[2] ?? m[3] ?? "") : ""; };
    out.jibun = pick("jibun"); out.legal = pick("legalDivisionNumber"); out.road = pick("roadName");
    out.approval = ymd(pick("useApprovalDate")); out.parking = pick("totalParkingCount"); out.parkingPer = pick("parkingCountPerHousehold");
    out.exposed = pick("isAddressExposed");
  } catch (e: any) { out._status = "err:" + (e?.message || e); }
  return out;
}
/** 법정동코드 → "시 구 동" (cortar.json 역방향) */
const CODE2NAME: Record<string, string> = {};
const NAME2CODES: Record<string, { code: string; full: string }[]> = {};
for (const [si, gus] of Object.entries(CORTAR as Record<string, Record<string, Record<string, string>>>)) {
  for (const [gu, dongs] of Object.entries(gus)) {
    for (const [dong, code] of Object.entries(dongs)) { CODE2NAME[code] = `${si} ${gu} ${dong}`; (NAME2CODES[dong] ||= []).push({ code, full: `${si} ${gu} ${dong}` }); }
  }
}

// ---------------------------------------------------------------- 링크 정리
function moneyText(deal: string, price: any, deposit: any, rent: any) {
  const f = (v: any) => (v == null || v === "" ? "" : Number(v).toLocaleString("ko-KR"));
  if (deal === "매매") return f(price);
  if (deal === "전세") return f(deposit);
  return [f(deposit), f(rent)].filter(Boolean).join(" / ");
}
async function parseOne(c: any, url: string): Promise<any> {
  const no = naverNo(url);
  const target = no ? `${PARSE_API}?no=${no}` : `${PARSE_API}?url=${encodeURIComponent(url)}`;
  const r = c.env.PARSE ? await c.env.PARSE.fetch(target) : await fetch(target);
  const txt = await r.text(); let j: any; try { j = JSON.parse(txt); } catch { throw new Error("정리 서버 응답이 JSON 이 아닙니다: " + txt.slice(0, 40)); }
  if (j.error) throw new Error(j.error);
  const fl = no ? await finLand(no) : {};
  const dongAddr = s(j.jibun || j.address_q || j.address);                       // 네이버는 "서울시 강남구 개포동" 까지만
  const jibunFull = fl.jibun ? (dongAddr ? `${dongAddr} ${fl.jibun}` : (fl.legal && CODE2NAME[fl.legal] ? `${CODE2NAME[fl.legal]} ${fl.jibun}` : fl.jibun)) : dongAddr;
  let ledger: any = null;
  if (jibunFull && /\d/.test(jibunFull)) {                                        // 건축물대장(한국 엔진) — 승인일·주차 보강
    const b = await engineJson(c, "/building?address=" + encodeURIComponent(jibunFull));
    const sm = b && b.summary ? b.summary : null;
    if (sm) { const find = (rx: RegExp) => { const k = Object.keys(sm).find((x) => rx.test(x)); return k ? sm[k] : ""; }; ledger = { approval: ymd(find(/useApr|aprv|approv|승인/i)), parking: s(find(/parking|주차/i)), purpose: s(find(/purpose|용도/i)), floors: s(find(/floor|층/i)) }; }
  }
  const deal = s(j.deal), floor = j.floor ?? "", total = j.total_floor ?? "";
  const row = {
    "매물번호": no ? `https://new.land.naver.com/houses?articleNo=${no}` : s(j.source_url || url),
    "세부주소": jibunFull, "도로명": s(fl.road), "종류": s(j.kind), "거래방식": deal, "매물명": s(j.building),
    "공급/계약/대지": j.supply_m2 ?? "", "전용/연": j.area_m2 ?? "", "해당층": floor, "전체층": total,
    "매매/전세금": deal === "매매" ? (j.price ?? "") : (j.deposit ?? ""), "월세": j.rent ?? "", "관리비": j.mgmt ?? "",
    "방수": j.rooms ?? "", "화장실수": j.baths ?? "", "방향": s(j.facing), "입주가능일": s(j.move_in),
    "사용승인일": fl.approval || (ledger && ledger.approval) || "", "총주차대수": fl.parking || (ledger && ledger.parking) || "", "세대당주차": s(fl.parkingPer),
    "중개사무소": s(j.realtor), "중개사전화": s(j.realtor_phone), "출처": s(j._source || (no ? "naver" : "")),
  } as Record<string, any>;
  return { ok: true, url, no, site: s(j._source), row, money: moneyText(deal, j.price, j.deposit, j.rent), photos: Array.isArray(j.photos) ? j.photos.length : 0, memo: s(j.memo).slice(0, 400), fin: fl._status ? `fin.land ${fl._status}` : "", ledger };
}
naverad.post("/admin/naverad/parse", async (c) => {
  const body: any = await c.req.json().catch(() => ({}));
  const urls: string[] = Array.isArray(body.urls) ? body.urls.map((u: any) => s(u)).filter(Boolean).slice(0, 30) : [];
  const out: any[] = [];
  for (const url of urls) {
    try { out.push(await parseOne(c, url)); }
    catch (e: any) { out.push({ ok: false, url, error: e?.message || String(e) }); }
  }
  return c.json({ items: out });
});
naverad.post("/admin/naverad/save", async (c) => {
  const body: any = await c.req.json().catch(() => ({}));
  const rows: any[] = Array.isArray(body.rows) ? body.rows.slice(0, 200) : [];
  if (!rows.length) return c.json({ success: false, message: "저장할 줄이 없습니다." }, 400);
  const r = await ingest(c.env.DB, c.env.ADMIN_USER || "admin", "네이버", "네이버 광고정리", rows);
  return c.json({ success: true, ...r });
});

// ---------------------------------------------------------------- 지번 검색
const distM = (a1: number, o1: number, a2: number, o2: number) => { const R = 6371000, d2r = Math.PI / 180; const dLat = (a2 - a1) * d2r, dLon = (o2 - o1) * d2r; const x = Math.sin(dLat / 2) ** 2 + Math.cos(a1 * d2r) * Math.cos(a2 * d2r) * Math.sin(dLon / 2) ** 2; return 2 * R * Math.asin(Math.sqrt(x)); };
function parseJibunQuery(q: string) {
  const t = q.trim().replace(/번지/g, "");
  const m = t.match(/([가-힣]+(?:동|리|가))\s*(산)?\s*(\d{1,4}(?:-\d{1,4})?)/);
  if (!m) return null;
  const dong = m[1], lot = (m[2] ? "산" : "") + m[3];
  const guM = t.match(/([가-힣]+구|[가-힣]+군|[가-힣]+시)\s/);
  return { dong, lot, gu: guM ? guM[1] : "", text: t };
}
naverad.post("/admin/naverad/search", async (c) => {
  await ensureListings(c.env.DB);
  const body: any = await c.req.json().catch(() => ({}));
  const q = s(body.q); const maxPages = Math.min(80, Math.max(5, parseInt(body.max_pages, 10) || 40));
  const startPage = Math.max(1, parseInt(body.start_page, 10) || 1);   // [더 훑기] 는 이어서
  const pj = parseJibunQuery(q);
  if (!pj) return c.json({ error: "지번을 '동이름 번지' 꼴로 적어주세요. 예: 역삼동 777-2" }, 400);
  // 1) 우리 DB
  const [where, binds] = lookupWhere(`${pj.dong} ${pj.lot}`, false);
  const { results } = await c.env.DB.prepare("SELECT id, site, addr, phone, contacts, kind, deal, price, title, url, last_at FROM listings" + where + " ORDER BY addr, id LIMIT 50").bind(...binds).all();
  const db = (results ?? []).map((r: any) => ({ ...r, last_at: kst(r.last_at) }));
  // 2) 법정동코드
  let cands = NAME2CODES[pj.dong] || [];
  if (pj.gu) cands = cands.filter((x) => x.full.includes(pj.gu));
  if (!cands.length) return c.json({ db, naver: { error: `'${pj.dong}' 의 법정동 코드를 찾지 못했습니다. 구 이름을 같이 적어보세요 (예: 강남구 ${pj.dong} ${pj.lot})` } });
  const ambiguous = cands.length > 1 ? cands.map((x) => x.full) : null;
  const cortar = cands[0];
  // 3) 좌표 (한국 엔진 → 브이월드)
  const geo = await engineJson(c, "/geocode?q=" + encodeURIComponent(`${cortar.full} ${pj.lot}`.replace(/^서울시/, "서울특별시")));
  if (!geo || !geo.ok) return c.json({ db, naver: { error: "지번의 좌표를 구하지 못했습니다 (엔진/브이월드). 지번이 맞는지 확인해주세요.", ambiguous, cortar: cortar.full } });
  const lat = Number(geo.lat), lng = Number(geo.lng);
  // 4) 네이버 목록(그 동 전체)을 넘기며 가까운 매물만
  const base = "https://new.land.naver.com/api/articles?order=rank&realEstateType=APT:OPST:VL:DDDGG:JWJT:SGJT:HOJT:ABYG:OBYG:GM:OR:SG:SMS:GJCG:APTHGJ:TJ:JGC:JGB&tradeType=&tag=::::::::&rentPriceMin=0&rentPriceMax=900000000&priceMin=0&priceMax=900000000&areaMin=0&areaMax=900000000&oldBuildYears=&recentlyBuildYears=&minHouseHoldCount=&maxHouseHoldCount=&showArticle=false&sameAddressGroup=false&minMaintenanceCost=&maxMaintenanceCost=&priceType=RETAIL&directions=&articleState=&cortarNo=" + cortar.code;
  const near: any[] = []; let scanned = 0, pages = 0, blocked = "", more = true;
  const endPage = startPage + maxPages - 1;
  for (let p = startPage; p <= endPage && more; p += 4) {
    const batch = [p, p + 1, p + 2, p + 3].filter((x) => x <= endPage);
    const rs = await Promise.all(batch.map((pg) => fetch(`${base}&page=${pg}`, { headers: NAVER_HEADERS }).then(async (r) => ({ pg, status: r.status, j: r.ok ? await r.json().catch(() => null) : null })).catch(() => ({ pg, status: 0, j: null }))));
    for (const r of rs.sort((a, b) => a.pg - b.pg)) {
      if (r.status === 429) { blocked = "네이버가 잠시 요청을 막았습니다(429). 1~2분 뒤 다시 해주세요."; more = false; break; }
      if (!r.j) { if (r.status && r.status !== 200) blocked = `네이버 목록 응답 ${r.status}`; more = false; break; }
      pages++;
      const list: any[] = Array.isArray(r.j.articleList) ? r.j.articleList : [];
      scanned += list.length;
      for (const a of list) {
        const la = Number(a.latitude), lo = Number(a.longitude); if (!la || !lo) continue;
        const d = distM(lat, lng, la, lo);
        if (d <= 70) near.push({ no: s(a.articleNo), name: s(a.articleName), type: s(a.realEstateTypeName), trade: s(a.tradeTypeName), price: s(a.dealOrWarrantPrc), rent: s(a.rentPrc), floor: s(a.floorInfo), area1: a.area1 ?? "", area2: a.area2 ?? "", dir: s(a.direction), realtor: s(a.realtorName), cp: s(a.cpName), confirm: ymd(a.articleConfirmYmd), bld: s(a.buildingName), dist: Math.round(d), lat: la, lng: lo });
      }
      if (!r.j.isMoreData || !list.length) { more = false; break; }
    }
  }
  // 5) 가까운 매물의 지번을 fin.land 로 확인 (최대 15건, 4개씩)
  near.sort((a, b) => a.dist - b.dist);
  const check = near.slice(0, 25);
  const apply = (it: any, fl: Record<string, string>) => { it.jibun = fl.jibun ? `${CODE2NAME[fl.legal] || cortar.full} ${fl.jibun}` : ""; it.exact = !!fl.jibun && fl.jibun === pj.lot && (!fl.legal || fl.legal === cortar.code); it.road = fl.road || ""; it.approval = fl.approval || ""; it.parking = fl.parking || ""; };
  for (let i = 0; i < check.length; i += 3) {
    await Promise.all(check.slice(i, i + 3).map(async (it) => { let fl = await finLand(it.no); if (!fl.jibun) { await new Promise((r) => setTimeout(r, 400)); fl = await finLand(it.no); } apply(it, fl); }));
  }
  // 같은 건물(매물명·좌표가 같은 것)은 확인된 지번을 물려받는다 — 확인 못 한 줄도 같은 건물이면 일치로
  const known = new Map<string, any>();
  for (const it of near) if (it.jibun) known.set(`${it.name}|${it.lat}|${it.lng}`, it);
  for (const it of near) { if (it.jibun) continue; const k = known.get(`${it.name}|${it.lat}|${it.lng}`); if (k) { it.jibun = k.jibun; it.exact = k.exact; it.road = k.road; it.approval = k.approval; it.parking = k.parking; it.inherited = true; } }
  for (const it of near) it.url = `https://new.land.naver.com/houses?articleNo=${it.no}`;
  const exact = near.filter((x) => x.exact), unknown = near.filter((x) => !x.exact);
  return c.json({ db, naver: { cortar: cortar.full, code: cortar.code, lat, lng, pages, scanned, blocked, ambiguous, exact, near: unknown, checked: check.length, more_pages: more, next_page: more ? endPage + 1 : null, start_page: startPage } });
});

// ---------------------------------------------------------------- 화면
naverad.get("/admin/naverad", (c) => c.html(layout("네이버 광고정리", PAGE())));
function PAGE() {
  return html`
<div class="page-head"><h1>네이버 광고정리</h1><span class="small muted">왼쪽: 링크 넣으면 광고용 정보 자동 정리 · 오른쪽: 지번으로 우리 DB + 지금 네이버에 걸린 매물 찾기</span></div>
<div class="na-grid">
  <section class="panel">
    <h2>링크 자동 정리</h2>
    <textarea id="na_links" rows="4" placeholder="네이버 매물 링크를 여러 개 넣어도 됩니다 (줄바꿈·쉼표·공백 구분) — 당근·온하우스 링크도 됩니다&#10;https://new.land.naver.com/houses?articleNo=2653867465"></textarea>
    <div class="na-bar"><button class="btn btn-primary" id="na_go">자동 정리</button><button class="btn" id="na_clip">📋 클립보드에서</button><span class="small muted" id="na_msg"></span></div>
    <div class="na-bar" id="na_tools" style="display:none"><button class="btn btn-primary" id="na_save">체크한 줄 DB에 저장</button><button class="btn" id="na_xl">엑셀 다운로드</button><button class="btn" id="na_copyall">전체 광고문구 복사</button><label class="small"><input type="checkbox" id="na_all" checked> 전체 선택</label></div>
    <div id="na_out" class="na-out"></div>
  </section>
  <section class="panel">
    <h2>지번으로 네이버 매물 찾기</h2>
    <div class="na-bar"><input type="text" id="na_q" placeholder="예: 역삼동 777-2 (구 이름을 붙이면 더 정확: 강남구 역삼동 777-2)" style="flex:1;min-width:240px"><button class="btn btn-primary" id="na_find">찾기</button></div>
    <div class="small muted" id="na_fmsg">우리 DB 에 쌓인 줄은 바로, 네이버는 그 동의 매물 목록을 넘기며 좌표가 가까운 것만 추린 뒤 지번을 확인합니다 (10~30초).</div>
    <div id="na_fout" class="na-out"></div>
  </section>
</div>
<style>${raw(NA_STYLE)}</style>
<script src="https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js"></script>
<script>${raw(NA_JS)}</script>`;
}
const NA_STYLE = `
.muted{color:var(--muted)}
.na-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px;align-items:start}
.na-out{overflow-x:auto}
@media(max-width:1000px){.na-grid{grid-template-columns:1fr}}
.panel{background:var(--panel);border:1px solid var(--border);border-radius:14px;padding:16px 18px;box-shadow:0 6px 24px rgba(255,92,154,.06)}
.panel h2{margin:0 0 10px;font-size:16px;color:var(--accent-dark)}
.panel textarea,.panel input[type=text]{width:100%;padding:10px 12px;border-radius:8px;border:1px solid var(--border);background:var(--input);color:var(--text);font-size:13px;box-sizing:border-box}
.na-bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:10px 0}
.na-out{margin-top:8px;max-width:100%}
.na-card{border:1px solid var(--border);border-radius:10px;padding:10px 12px;margin-bottom:10px;background:#fff}
.na-card.err{border-color:var(--danger)}
.na-card .ttl{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:6px}
.na-card .ttl b{color:var(--accent-dark)}
.kv{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:4px 10px;font-size:12.5px}
.kv div{padding:4px 6px;background:var(--soft);border-radius:6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.kv div b{color:var(--muted);font-weight:600;margin-right:4px}
.kv div.big{grid-column:1 / -1;white-space:normal}
.na-table{width:100%;border-collapse:collapse;background:#fff;border:1px solid var(--border);border-radius:10px;overflow:hidden;margin-top:8px}
.na-table th,.na-table td{padding:7px 9px;border-bottom:1px solid #fbe3ec;font-size:12.5px;text-align:left;white-space:nowrap;max-width:220px;overflow:hidden;text-overflow:ellipsis}
.na-table th{background:var(--soft);color:var(--accent-dark)}
.tag{display:inline-block;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:700}
.tag.ok{background:rgba(47,158,110,.14);color:var(--ok)}
.tag.q{background:rgba(224,138,47,.14);color:var(--warn)}
.tag.db{background:rgba(96,110,240,.14);color:#4f5fd6}
.x{border:0;background:transparent;color:var(--accent-dark);cursor:pointer;font-size:12px}
`;
const NA_JS = `
(function(){
  var $=function(i){return document.getElementById(i)};
  var esc=function(v){return String(v==null?'':v).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')};
  var ITEMS=[];
  var COLS=['세부주소','도로명','거래방식','매매/전세금','월세','관리비','종류','매물명','해당층','전체층','공급/계약/대지','전용/연','사용승인일','총주차대수','세대당주차','방수','화장실수','방향','입주가능일','중개사무소','중개사전화','매물번호'];
  var LABEL={'세부주소':'지번','도로명':'도로명','거래방식':'거래','매매/전세금':'매매가/보증금','월세':'월세','관리비':'관리비','종류':'종류','매물명':'건물·매물명','해당층':'해당층','전체층':'총층','공급/계약/대지':'공급㎡','전용/연':'전용㎡','사용승인일':'사용승인일','총주차대수':'총주차대수','세대당주차':'세대당','방수':'방','화장실수':'욕실','방향':'향','입주가능일':'입주','중개사무소':'중개사','중개사전화':'중개사전화','매물번호':'링크'};
  function adText(it){ var r=it.row; var L=[]; L.push((r['종류']||'')+' '+(r['거래방식']||'')+' '+(it.money||'')); if(r['세부주소']) L.push('주소: '+r['세부주소']+(r['도로명']?' ('+r['도로명']+')':'')); if(r['매물명']) L.push('건물: '+r['매물명']);
    if(r['해당층']!==''||r['전체층']!=='') L.push('층: '+(r['해당층']||'-')+'/'+(r['전체층']||'-')); if(r['공급/계약/대지']||r['전용/연']) L.push('면적: 공급 '+(r['공급/계약/대지']||'-')+'㎡ / 전용 '+(r['전용/연']||'-')+'㎡');
    if(r['사용승인일']) L.push('사용승인일: '+r['사용승인일']); if(r['총주차대수']) L.push('총주차대수: '+r['총주차대수']+(r['세대당주차']?' (세대당 '+r['세대당주차']+')':'')); if(r['방수']!==''||r['화장실수']!=='') L.push('방 '+(r['방수']||'-')+' / 욕실 '+(r['화장실수']||'-'));
    if(r['방향']) L.push('향: '+r['방향']); if(r['입주가능일']) L.push('입주: '+r['입주가능일']); if(r['관리비']) L.push('관리비: '+r['관리비']); L.push(r['매물번호']||''); return L.join('\\n'); }
  function links(){ var out=[],seen={}; $('na_links').value.split(/[\\s,;]+/).forEach(function(t){ t=t.trim(); if(/^(https?:\\/\\/|\\d{7,12}$)/.test(t)&&!seen[t]){seen[t]=1;out.push(t);} }); return out; }
  function paint(){
    var h=''; ITEMS.forEach(function(it,i){
      if(!it.ok){ h+='<div class="na-card err"><div class="ttl"><b>'+(i+1)+'.</b> <span class="small">'+esc(it.url)+'</span></div><div style="color:var(--danger);font-size:13px">'+esc(it.error)+'</div></div>'; return; }
      var r=it.row; h+='<div class="na-card"><div class="ttl"><label><input type="checkbox" data-sel="'+i+'" '+(it.sel!==false?'checked':'')+'> <b>'+(i+1)+'. '+esc(r['세부주소']||r['매물명']||it.url)+'</b></label> <span class="tag db">'+esc(it.site||'')+'</span> <span class="small">'+esc((r['종류']||'')+' '+(r['거래방식']||'')+' '+(it.money||''))+'</span>'+(it.fin?' <span class="tag q" title="fin.land 상세를 못 읽어 지번·승인일·주차는 비어 있을 수 있음">'+esc(it.fin)+'</span>':'')+'<span style="margin-left:auto"></span><button class="x" data-copy="'+i+'">광고문구 복사</button><a class="x" href="'+esc(r['매물번호'])+'" target="_blank" rel="noopener">원문 ↗</a></div><div class="kv">';
      COLS.forEach(function(k){ if(k==='매물번호') return; var v=r[k]; if(v===''||v==null) return; h+='<div'+(k==='세부주소'||k==='도로명'||k==='중개사무소'?' class="big"':'')+'><b>'+esc(LABEL[k])+'</b>'+esc(v)+'</div>'; });
      h+='</div></div>';
    });
    $('na_out').innerHTML=h; $('na_tools').style.display=ITEMS.some(function(x){return x.ok})?'':'none';
    document.querySelectorAll('[data-sel]').forEach(function(cb){ cb.onchange=function(){ ITEMS[+cb.dataset.sel].sel=cb.checked; }; });
    document.querySelectorAll('[data-copy]').forEach(function(b){ b.onclick=function(){ navigator.clipboard.writeText(adText(ITEMS[+b.dataset.copy])).then(function(){ $('na_msg').textContent='광고문구를 복사했습니다'; }); }; });
  }
  async function run(){
    var urls=links(); if(!urls.length){ $('na_msg').textContent='링크를 넣어주세요'; return; }
    $('na_go').disabled=true; $('na_msg').textContent='정리 중… '+urls.length+'개'; ITEMS=[];
    try{
      for(var i=0;i<urls.length;i+=5){
        var r=await fetch('/admin/naverad/parse',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({urls:urls.slice(i,i+5)})}).then(function(x){return x.json()});
        ITEMS=ITEMS.concat(r.items||[]); paint(); $('na_msg').textContent='정리 중… '+Math.min(i+5,urls.length)+'/'+urls.length;
      }
      var ok=ITEMS.filter(function(x){return x.ok}).length; $('na_msg').textContent='완료: '+ok+'건 정리'+(ITEMS.length-ok?' · '+(ITEMS.length-ok)+'건 실패':'');
    }catch(e){ $('na_msg').textContent='오류: '+e.message; }
    $('na_go').disabled=false;
  }
  $('na_go').onclick=run;
  $('na_clip').onclick=async function(){ try{ var t=await navigator.clipboard.readText(); if(t){ $('na_links').value=t; run(); } }catch(e){ $('na_msg').textContent='클립보드를 읽지 못했습니다 — 붙여넣기 해주세요'; } };
  $('na_all').onchange=function(){ ITEMS.forEach(function(x){ x.sel=$('na_all').checked; }); paint(); };
  $('na_save').onclick=async function(){
    var rows=ITEMS.filter(function(x){return x.ok&&x.sel!==false}).map(function(x){return x.row}); if(!rows.length){ $('na_msg').textContent='체크한 줄이 없습니다'; return; }
    var r=await fetch('/admin/naverad/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({rows:rows})}).then(function(x){return x.json()});
    $('na_msg').textContent=r.success?('DB 저장: 추가 '+r.inserted+'건 · 갱신 '+r.updated+'건 (매물·임대인 DB 탭에서 확인)'):('저장 실패: '+(r.message||''));
  };
  $('na_xl').onclick=function(){
    var rows=ITEMS.filter(function(x){return x.ok}); if(!rows.length) return;
    var aoa=[COLS.map(function(k){return LABEL[k]})]; rows.forEach(function(it){ aoa.push(COLS.map(function(k){ var v=it.row[k]; return v==null?'':v; })); });
    var ws=XLSX.utils.aoa_to_sheet(aoa); ws['!cols']=COLS.map(function(k){return {wch:k==='세부주소'||k==='도로명'||k==='매물번호'?34:12}});
    for(var i=1;i<aoa.length;i++){ var j=COLS.indexOf('매물번호'); var cc=ws[XLSX.utils.encode_cell({r:i,c:j})]; if(cc&&/^https?:/.test(String(cc.v))) cc.l={Target:String(cc.v)}; }
    var wb=XLSX.utils.book_new(); XLSX.utils.book_append_sheet(wb,ws,'광고정리'); var d=new Date(); XLSX.writeFile(wb,'네이버광고정리_'+d.toISOString().slice(0,10).replace(/-/g,'')+'_'+rows.length+'건.xlsx');
  };
  $('na_copyall').onclick=function(){ var t=ITEMS.filter(function(x){return x.ok&&x.sel!==false}).map(adText).join('\\n\\n----------\\n\\n'); navigator.clipboard.writeText(t).then(function(){ $('na_msg').textContent='전체 광고문구를 복사했습니다'; }); };

  // ── 지번 검색
  function naRow(x, kind){ return '<tr><td>'+(kind==='exact'?'<span class="tag ok">지번 일치'+(x.inherited?' (같은 건물)':'')+'</span>':'<span class="tag q">근처 '+x.dist+'m'+(x.jibun?'':' · 지번 미확인')+'</span>')+'</td><td><a href="'+esc(x.url)+'" target="_blank" rel="noopener">'+esc(x.no)+'</a></td><td>'+esc(x.name)+(x.bld?' '+esc(x.bld):'')+'</td><td>'+esc(x.type)+' '+esc(x.trade)+'</td><td>'+esc(x.price)+(x.rent&&x.rent!=='0'?' / '+esc(x.rent):'')+'</td><td>'+esc(x.floor)+'</td><td>'+esc(x.area1)+'/'+esc(x.area2)+'</td><td>'+esc(x.jibun||'')+'</td><td>'+esc(x.realtor)+'</td><td>'+esc(x.confirm)+'</td></tr>'; }
  var ACC={q:'',exact:[],near:[],pages:0,scanned:0};
  async function find(startPage){
    var q=$('na_q').value.trim(); if(q.length<2) return; $('na_find').disabled=true; $('na_fmsg').textContent=(startPage>1?'더 훑는 중… ':'찾는 중… ')+'(우리 DB → 네이버 목록 → 지번 확인, 10~30초)';
    if(!startPage||startPage<2){ ACC={q:q,exact:[],near:[],pages:0,scanned:0}; $('na_fout').innerHTML=''; }
    try{
      var r=await fetch('/admin/naverad/search',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({q:q,start_page:startPage||1})}).then(function(x){return x.json()});
      if(r.error){ $('na_fmsg').textContent=r.error; $('na_find').disabled=false; return; }
      if(r.naver&&!r.naver.error){ var seen={}; ACC.exact.concat(ACC.near).forEach(function(x){seen[x.no]=1}); (r.naver.exact||[]).forEach(function(x){ if(!seen[x.no]){seen[x.no]=1;ACC.exact.push(x);} }); (r.naver.near||[]).forEach(function(x){ if(!seen[x.no]){seen[x.no]=1;ACC.near.push(x);} }); ACC.pages+=r.naver.pages||0; ACC.scanned+=r.naver.scanned||0; r.naver.exact=ACC.exact; r.naver.near=ACC.near; r.naver.pages=ACC.pages; r.naver.scanned=ACC.scanned; }
      var h='<h3 style="font-size:14px;margin:8px 0 4px">우리 DB <span class="tag db">'+(r.db||[]).length+'건</span></h3>';
      if((r.db||[]).length){ h+='<table class="na-table"><tr><th>지번·호수</th><th>임대인 연락처</th><th>임차인·관리 등</th><th>종류</th><th>거래</th><th>금액</th><th>이름</th><th>올린 날</th></tr>'; r.db.forEach(function(x){ h+='<tr><td>'+esc(x.addr)+'</td><td><b>'+esc(x.phone)+'</b></td><td>'+esc(x.contacts)+'</td><td>'+esc(x.kind)+'</td><td>'+esc(x.deal)+'</td><td>'+esc(x.price)+'</td><td>'+esc(x.title)+'</td><td>'+esc(x.last_at)+'</td></tr>'; }); h+='</table>'; } else h+='<div class="small muted">없음</div>';
      var n=r.naver||{};
      h+='<h3 style="font-size:14px;margin:14px 0 4px">네이버 <span class="tag ok">지번 일치 '+(n.exact||[]).length+'건</span> <span class="tag q">근처 '+(n.near||[]).length+'건</span></h3>';
      if(n.error){ h+='<div style="color:var(--danger);font-size:13px">'+esc(n.error)+'</div>'; }
      else{
        h+='<div class="small muted">'+esc(n.cortar)+' · 목록 '+n.pages+'쪽 '+n.scanned+'건 훑음'+(n.blocked?' · '+esc(n.blocked):'')+(n.ambiguous?' · 같은 이름의 동이 여럿: '+esc(n.ambiguous.join(', '))+' → 구 이름을 붙여주세요':'')+(n.more_pages?' · <button class="x" id="na_more" data-next="'+n.next_page+'">목록이 더 있습니다 — 다음 800건 더 훑기</button>':' · 목록 끝까지 훑었습니다')+'</div>';
        var all=(n.exact||[]).map(function(x){return naRow(x,'exact')}).concat((n.near||[]).map(function(x){return naRow(x,'near')}));
        if(all.length) h+='<table class="na-table"><tr><th></th><th>매물번호</th><th>매물명</th><th>종류·거래</th><th>금액</th><th>층</th><th>공급/전용</th><th>지번(확인)</th><th>중개사</th><th>확인일</th></tr>'+all.join('')+'</table>';
        else h+='<div class="small muted">지금 네이버에는 이 지번 근처 매물이 없습니다.</div>';
      }
      $('na_fout').innerHTML=h; $('na_fmsg').textContent='완료 — 지번 일치 '+(n.exact||[]).length+'건';
      var mb=$('na_more'); if(mb) mb.onclick=function(){ find(+mb.dataset.next); };
    }catch(e){ $('na_fmsg').textContent='오류: '+e.message; }
    $('na_find').disabled=false;
  }
  $('na_find').onclick=function(){ find(1); }; $('na_q').addEventListener('keydown',function(e){ if(e.key==='Enter'){ e.preventDefault(); find(1); } });
})();
`;
