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
export const NAVER_HEADERS: Record<string, string> = {
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
export function naverNo(input: string): string {
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
export async function finLand(no: string): Promise<Record<string, string>> {
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
  return { ok: true, url, no, site: s(j._source), row, money: moneyText(deal, j.price, j.deposit, j.rent), photos: Array.isArray(j.photos) ? j.photos.length : 0, memo: s(j.memo).slice(0, 2500), fin: fl._status ? `fin.land ${fl._status}` : "", ledger };
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
// 건축물대장(+주변 정보): 한국 엔진 /building 을 그대로 중계 — 라운지 서버와 무관 (2026-10-09)
naverad.get("/admin/naverad/building", async (c) => {
  const address = s(c.req.query("address")); if (!address) return c.json({ error: "address 필요" }, 400);
  const p = new URLSearchParams({ address, nearby: "1" }); for (const k of ["dong", "ho"]) if (s(c.req.query(k))) p.set(k, s(c.req.query(k)));
  const r = await engineFetch(c, "/building?" + p.toString());
  if (!r) return c.json({ error: "엔진(ENGINE_URL) 연결이 안 됩니다." }, 503);
  const j: any = await r.json().catch(() => ({ error: "엔진 응답이 JSON 이 아닙니다" }));
  return c.json(j, r.status as any);
});
naverad.post("/admin/naverad/search", async (c) => {
  await ensureListings(c.env.DB);
  const body: any = await c.req.json().catch(() => ({}));
  const q = s(body.q);
  const pj = parseJibunQuery(q);
  if (!pj) return c.json({ error: "지번을 '동이름 번지' 꼴로 적어주세요. 예: 역삼동 777-2" }, 400);
  // 1) 우리 DB
  const [where, binds] = lookupWhere(`${pj.dong} ${pj.lot}`, false);
  const { results } = await c.env.DB.prepare("SELECT id, site, addr, phone, contacts, kind, deal, price, title, url, last_at, file FROM listings" + where + " ORDER BY addr, id LIMIT 50").bind(...binds).all();
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
  // 4) 네이버 목록을 지도 범위로 (zoom=18 + 범위 → 그 자리 주변 60m 상자만, 보통 2~5쪽)
  const d = 0.0006;
  const base = `https://new.land.naver.com/api/articles?order=rank&realEstateType=APT:OPST:VL:DDDGG:JWJT:SGJT:HOJT:ABYG:OBYG:GM:OR:SG:SMS:GJCG:APTHGJ:TJ:JGC:JGB&tradeType=&tag=::::::::&rentPriceMin=0&rentPriceMax=900000000&priceMin=0&priceMax=900000000&areaMin=0&areaMax=900000000&oldBuildYears=&recentlyBuildYears=&minHouseHoldCount=&maxHouseHoldCount=&showArticle=false&sameAddressGroup=false&minMaintenanceCost=&maxMaintenanceCost=&priceType=RETAIL&directions=&articleState=&zoom=18&cortarNo=${cortar.code}&leftLon=${lng - d}&rightLon=${lng + d}&topLat=${lat + d}&bottomLat=${lat - d}`;
  const near: any[] = []; let scanned = 0, pages = 0, blocked = "";
  for (let p = 1; p <= 12; p++) {
    let r: Response; try { r = await fetch(`${base}&page=${p}`, { headers: NAVER_HEADERS }); } catch { blocked = "네이버 목록을 불러오지 못했습니다"; break; }
    if (r.status === 429) { blocked = "네이버가 잠시 요청을 막았습니다(429). 1~2분 뒤 다시 해주세요."; break; }
    const j: any = r.ok ? await r.json().catch(() => null) : null;
    if (!j) { blocked = `네이버 목록 응답 ${r.status}`; break; }
    pages++;
    const list: any[] = Array.isArray(j.articleList) ? j.articleList : [];
    scanned += list.length;
    for (const a of list) {
      const la = Number(a.latitude) || 0, lo = Number(a.longitude) || 0;
      near.push({ no: s(a.articleNo), name: s(a.articleName), type: s(a.realEstateTypeName), trade: s(a.tradeTypeName), price: s(a.dealOrWarrantPrc), rent: s(a.rentPrc), floor: s(a.floorInfo), area1: a.area1 ?? "", area2: a.area2 ?? "", dir: s(a.direction), realtor: s(a.realtorName), cp: s(a.cpName), confirm: ymd(a.articleConfirmYmd), feature: s(a.articleFeatureDesc), same: a.sameAddrCnt ?? 1, lat: la, lng: lo, dist: la ? Math.round(distM(lat, lng, la, lo)) : null, locShow: !!a.isLocationShow, jibun: "", exact: false, url: `https://new.land.naver.com/houses?articleNo=${s(a.articleNo)}` });
    }
    if (!j.isMoreData || !list.length) break;
  }
  // 5) 지번 확인 — 같은 좌표(=같은 건물)끼리 한 건만: 상세 API exposureAddress(주소 공개면 번지까지) → 없으면 fin.land
  const lotOf = (addr: string) => { const m = s(addr).match(/(산\s*)?(\d{1,4}(?:-\d{1,4})?)\s*$/); return m ? (m[1] ? "산" : "") + m[2] : ""; };
  const dongOk = (addr: string) => !addr || addr.includes(pj.dong);
  const groups = new Map<string, any[]>();
  for (const it of near) { const k = `${it.lat}|${it.lng}`; (groups.get(k) || groups.set(k, []).get(k)!).push(it); }
  const reps = [...groups.values()].sort((a, b) => (a[0].dist ?? 9e9) - (b[0].dist ?? 9e9)).slice(0, 30);
  let checked = 0;
  const detailAddr = async (no: string): Promise<string> => {
    try { const r = await fetch(`https://new.land.naver.com/api/articles/${no}?complexNo=`, { headers: NAVER_HEADERS }); if (!r.ok) return ""; const j: any = await r.json().catch(() => null); return s(j?.articleDetail?.exposureAddress); } catch { return ""; }
  };
  for (let i = 0; i < reps.length; i += 4) {
    await Promise.all(reps.slice(i, i + 4).map(async (g) => {
      checked++;
      let addr = ""; let road = "", approval = "", parking = "";
      for (const it of g.slice(0, 2)) { addr = await detailAddr(it.no); if (lotOf(addr)) break; }
      if (!lotOf(addr)) { const fl = await finLand(g[0].no); if (fl.jibun) { addr = `${CODE2NAME[fl.legal] || cortar.full} ${fl.jibun}`; road = fl.road || ""; approval = fl.approval || ""; parking = fl.parking || ""; } }
      const lot = lotOf(addr);
      const exact = !!lot && lot === pj.lot && dongOk(addr);
      const likely = !lot && g[0].dist != null && g[0].dist <= 15;   // 주소 비공개지만 바로 그 자리(15m 안) → 그 건물로 본다
      for (const it of g) { it.jibun = lot ? addr : ""; it.exact = exact || likely; it.likely = likely; it.road = road; it.approval = approval; it.parking = parking; }
    }));
  }
  near.sort((a, b) => (a.dist ?? 9e9) - (b.dist ?? 9e9));
  const exact = near.filter((x) => x.exact), rest = near.filter((x) => !x.exact);
  const brokers = Array.from(new Set(exact.map((x) => x.realtor).filter(Boolean)));
  return c.json({ db, naver: { cortar: cortar.full, code: cortar.code, lat, lng, pages, scanned, blocked, ambiguous, exact, near: rest, brokers, count: exact.length, broker_count: brokers.length, checked } });
});

// ---------------------------------------------------------------- 화면
naverad.get("/admin/naverad", (c) => c.html(layout("네이버 광고정리", PAGE())));
function PAGE() {
  return html`
<div class="page-head"><h1>네이버 광고정리</h1><span class="small muted">위: 링크 넣으면 광고용 정보 자동 정리 · 아래: 지번으로 우리 DB + 지금 네이버에 걸린 매물 찾기 (줄을 누르면 그 매물이 바로 정리됩니다)</span></div>
<div class="na-stack">
  <section class="panel green">
    <h2>⚡ 링크 자동 정리</h2>
    <textarea id="na_links" rows="4" placeholder="아무 링크나 넣어주세요. 정리해드릴게요!  여러 개면 줄바꿈·쉼표·공백으로 구분&#10;https://new.land.naver.com/houses?articleNo=2653867465"></textarea>
    <div class="na-bar"><button class="btn btn-primary" id="na_go">자동 정리</button><button class="btn" id="na_clip">📋 클립보드에서</button><span class="small muted" id="na_msg"></span></div>
    <div class="na-bar" id="na_tools" style="display:none"><button class="btn btn-primary" id="na_save">체크한 줄 DB에 저장</button><button class="btn" id="na_clear" title="정리한 목록을 비웁니다 (DB 에 저장한 것은 그대로)">목록 지우기</button><button class="btn" id="na_xl">엑셀 다운로드</button><button class="btn" id="na_copyall">전체 광고문구 복사</button><label class="small"><input type="checkbox" id="na_all" checked> 전체 선택</label></div>
    <div id="na_out" class="na-out"></div>
  </section>
  <section class="panel pink">
    <h2><span class="nlogo">N</span>🔍 지번으로 매물 찾기</h2>
    <div class="na-bar"><input type="text" id="na_q" placeholder="예: 양재동 17-27 (구 이름을 붙이면 더 정확: 서초구 양재동 17-27)" style="flex:1;min-width:240px"><button class="btn btn-primary" id="na_find">찾기</button><label class="small" style="display:flex;align-items:center;gap:5px;margin:0;white-space:nowrap" title="같은 매물(종류·거래·금액·층·면적이 같은 것)을 여러 부동산이 올렸으면 한 줄로 묶어 'N곳' 으로 보여줍니다"><input type="checkbox" id="na_group" checked style="width:16px;height:16px;margin:0"> 중복매물 묶기</label></div>
    <div class="small muted" id="na_fmsg">우리 DB 에 쌓인 줄은 바로, 네이버는 그 지번 자리(60m 안)의 매물을 모아 지번을 확인합니다 (5~15초). 줄을 누르면 오른쪽에 바로 정리됩니다.</div>
    <div class="na-split">
      <div id="na_fout" class="na-out"></div>
      <div class="na-pick"><div id="na_pick"><div class="small muted" style="padding:14px">← 결과 줄을 누르면 그 매물의 광고 정보가 여기에 정리됩니다 (위 링크 자동 정리와는 별개)</div></div><div id="na_bldg" class="na-bldg"></div></div>
    </div>
  </section>
</div>
<style>${raw(NA_STYLE)}</style>
<script src="https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js"></script>
<script>${raw(NA_JS)}</script>`;
}
const NA_STYLE = `
.muted{color:var(--muted)}
.na-stack{display:flex;flex-direction:column;gap:16px}
.panel.green{border-color:#8fd3a8;background:#f3fbf5;box-shadow:0 6px 24px rgba(47,158,110,.08)}
.panel.green h2{color:#1f7a4d}
.panel.pink{border-color:#f6b4cf;background:#fff4f8}
.panel.pink h2{color:#c2366f}
.nlogo{display:inline-block;background:#03c75a;color:#fff;font-weight:900;border-radius:5px;padding:0 6px;margin-right:4px;font-size:14px;line-height:22px;vertical-align:middle}
.na-split{display:grid;grid-template-columns:minmax(0,3fr) minmax(300px,2fr);gap:14px;align-items:start}
.na-pick{position:sticky;top:12px;max-height:calc(100vh - 24px);overflow:auto}
.na-bldg{margin-top:12px}
.bsec{background:#fff;border:1px solid var(--border);border-radius:10px;padding:10px 12px;margin-bottom:10px}
.bsec h4{margin:0 0 6px;font-size:13.5px;color:var(--accent-dark)}
.brow{display:flex;gap:10px;font-size:12.5px;padding:3px 0;border-bottom:1px dashed #f3dbe5}
.brow span{color:var(--muted);min-width:84px}
.brow b{font-weight:600}
.bsec table{width:100%;border-collapse:collapse;font-size:12px}
.bsec th,.bsec td{padding:4px 6px;border-bottom:1px solid #f6e6ec;text-align:left}
.bsec th{color:var(--muted);font-weight:600}
.bsec td.r,.bsec th.r{text-align:right}
.bsec tr.hit td{background:#fff0f6;font-weight:700}
.bnote{font-size:11.5px;color:var(--muted)}
.golink{color:#03c75a!important;font-weight:800}
.na-card .desc{margin-top:8px;font-size:12.5px;line-height:1.55;background:var(--soft);border-radius:8px;padding:8px 10px}
.na-card .desc b{display:block;color:var(--accent-dark);margin-bottom:4px}
.na-table tr.pick{cursor:pointer}
.na-table tr.pick:hover td{background:#fff0f6}
.na-table tr.pick.on td{background:#ffe3ee}
.cnt{display:flex;gap:14px;align-items:baseline;flex-wrap:wrap;margin:8px 0 4px}
.cnt b{font-size:22px;color:#03c75a}
.cnt .b2 b{color:#c2366f}
.na-out{overflow-x:auto}
@media(max-width:1000px){.na-split{grid-template-columns:1fr}.na-pick{position:static}}
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
  $('na_clear').onclick=function(){ if(ITEMS.length&&!confirm('정리한 목록 '+ITEMS.length+'건을 지울까요? (DB 에 저장한 것은 그대로)')) return; ITEMS=[]; $('na_links').value=''; paint(); $('na_msg').textContent='목록을 비웠습니다'; };
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

  // ── 지번 검색 (줄을 누르면 그 매물을 자동 정리해 오른쪽에 + 위 목록에 추가)
  // 정리 서버 memo 에서 글 내용만: 앞의 요약 줄([네이버]·거래:·층:·전용·등록일·향·방·입주), 중개사 이름/전화 줄, '<중개대상물의 표시…>' 이후를 뺀다
  function descOnly(memo){
    var lines=String(memo||'').replace(/\\r/g,'').split('\\n'), out=[], started=false;
    for(var i=0;i<lines.length;i++){ var t=lines[i].trim();
      if(/^<\\s*중개대상물/.test(t)) break;
      if(!started){ if(!t||/^\\[/.test(t)||/^(거래|층|전용|공급|네이버 등록일|등록일|확인일|향|방|욕실|입주|관리비|면적|주차|해당층|총층)\\s*[:：]?\\s*/.test(t)&&t.length<60||/^전용\\s*\\d/.test(t)) continue; started=true; }
      if(/공인중개사|부동산중개|중개법인|중개사무소|☎|\\d{2,3}-\\d{3,4}-\\d{4}|개설등록번호/.test(t)) continue;
      out.push(t);
    }
    return out.join('\\n').replace(/\\n{3,}/g,'\\n\\n').trim();
  }
  var HIDE_PICK={'중개사무소':1,'중개사전화':1,'출처':1,'매물번호':1};
  function cardHtml(it, title, pickMode){
    if(!it.ok) return '<div class="na-card err"><div class="ttl"><b>'+esc(title||'')+'</b> <span class="small">'+esc(it.url)+'</span></div><div style="color:var(--danger);font-size:13px">'+esc(it.error)+'</div></div>';
    var r=it.row, h='<div class="na-card"><div class="ttl"><b>'+esc(title||r['세부주소']||r['매물명']||it.url)+'</b> <span class="tag db">'+esc(it.site||'')+'</span> <span class="small muted">'+esc(it.money||'')+'</span> <button class="x" data-pcopy="1">광고문구 복사</button> <a class="x golink" href="'+esc(it.url)+'" target="_blank" rel="noopener">'+(pickMode?'매물 링크로 바로가기 ↗':'네이버에서 열기')+'</a></div><div class="kv">';
    COLS.forEach(function(k){ if(k==='매물번호') return; if(pickMode&&HIDE_PICK[k]) return; var v=r[k]; if(v===''||v==null) return; h+='<div'+(k==='세부주소'||k==='도로명'||k==='중개사무소'?' class="big"':'')+'><b>'+esc(LABEL[k])+'</b>'+esc(v)+'</div>'; });
    var memo=pickMode?descOnly(it.memo):it.memo;
    return h+'</div>'+(memo?'<div class="desc"><b>설명</b><div style="white-space:pre-wrap">'+esc(memo)+'</div></div>':'')+'</div>';
  }
  async function pick(url, tr){
    document.querySelectorAll('.na-table tr.pick.on').forEach(function(x){x.classList.remove('on')}); if(tr) tr.classList.add('on');
    $('na_pick').innerHTML='<div class="small muted" style="padding:14px">정리 중… (네이버 상세 + 건축물대장, 5초 안팎)</div>';
    try{
      var r=await fetch('/admin/naverad/parse',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({urls:[url]})}).then(function(x){return x.json()});
      var it=(r.items||[])[0]; if(!it){ $('na_pick').innerHTML='<div class="na-card err">응답이 비었습니다</div>'; return; }
      $('na_pick').innerHTML=cardHtml(it,'선택한 매물',true)+(it.ok?'<div class="na-bar" style="margin:6px 0 0"><button class="btn btn-primary" data-psave="1">이 매물 DB에 저장</button><button class="btn" data-pup="1">위 정리 목록에도 넣기</button><span class="small muted" id="na_pmsg"></span></div>':'');
      var b=$('na_pick').querySelector('[data-pcopy]'); if(b) b.onclick=function(){ navigator.clipboard.writeText(adText(it)).then(function(){ $('na_pmsg').textContent='광고문구를 복사했습니다'; }); };
      var sv=$('na_pick').querySelector('[data-psave]'); if(sv) sv.onclick=async function(){ sv.disabled=true; try{ var rr=await fetch('/admin/naverad/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({rows:[it.row]})}).then(function(x){return x.json()}); $('na_pmsg').textContent=rr.success?('DB 저장: 추가 '+rr.inserted+'건 · 갱신 '+rr.updated+'건'):('저장 실패: '+(rr.message||'')); }catch(e){ $('na_pmsg').textContent='저장 실패: '+e.message; } sv.disabled=false; };
      var up=$('na_pick').querySelector('[data-pup]'); if(up) up.onclick=function(){ if(!ITEMS.some(function(x){return x.ok&&x.no===it.no})){ ITEMS.push(it); paint(); } $('na_pmsg').textContent='위 링크 자동 정리 목록에 넣었습니다'; };
      var sa=String(it.ok&&it.row['세부주소']||''); var hoM=sa.match(/(\\d{1,4}[A-Za-z]?)호\\s*$/);
      var jb=(sa.match(/^(.*?[가-힣]+(?:동|리|가)\\s*(?:산\\s*)?\\d{1,4}(?:-\\d{1,4})?)/)||[])[1]||'';
      if(jb||BL.addr) loadBldg((jb||BL.addr).replace(/^서울시/,'서울특별시'), hoM?hoM[1]:'');
    }catch(e){ $('na_pick').innerHTML='<div class="na-card err">'+esc(e.message)+'</div>'; }
  }
  // ── 건축물대장 패널 (엔진 /building: 요약 · 호실 · 층별 현황 · 주변 정보)
  var BL={addr:'',key:''};
  var bNum=function(v){ var x=Number(v); return isFinite(x)&&x>0?x:0 };
  var fmtA=function(a){ return bNum(a)?bNum(a).toFixed(2)+'㎡ <span class="bnote">'+(bNum(a)/3.3058).toFixed(1)+'평</span>':'-' };
  async function loadBldg(addr, ho){
    var box=$('na_bldg'); if(!box||!addr) return; var key=addr+'|'+(ho||''); if(key===BL.key) return; BL.key=key; BL.addr=addr;
    box.innerHTML='<div class="bsec"><h4>🏢 건축물대장</h4><div class="bnote">⏳ '+esc(addr)+(ho?' '+esc(ho)+'호':'')+' 대장·주변 정보를 읽는 중…</div></div>';
    var j; try{ j=await fetch('/admin/naverad/building?address='+encodeURIComponent(addr)+(ho?'&ho='+encodeURIComponent(ho):'')).then(function(x){return x.json()}); }catch(e){ box.innerHTML='<div class="bsec"><h4>🏢 건축물대장</h4><div class="bnote" style="color:var(--danger)">못 읽었습니다: '+esc(e.message)+'</div></div>'; return; }
    if(key!==BL.key) return;
    if(j.error){ box.innerHTML='<div class="bsec"><h4>🏢 건축물대장</h4><div class="bnote" style="color:var(--danger)">'+esc(j.error)+'</div></div>'; return; }
    var S0=j.summary||{}, floors=j.floors||[], near=j.nearby||[], units=j.unit==null?[]:(Array.isArray(j.unit)?j.unit:[j.unit]), list=j.units||[];
    var height=0; (S0.dongs||[]).forEach(function(d){ height=Math.max(height,bNum(d.height)); });
    var row=function(k,v){ return v?'<div class="brow"><span>'+k+'</span><b>'+v+'</b></div>':'' };
    var h='<div class="bsec"><h4>🏢 건축물대장 요약 <span class="bnote" style="font-weight:400">'+esc((j.address&&j.address.bdNm)||S0.bldNm||'')+(S0.kind?' · '+esc(S0.kind):'')+'</span></h4>'
      +row('건축물용도',esc(S0.mainPurpose||''))+row('구조',esc(S0.structure||''))+row('사용승인일',esc(String(S0.useAprDay||'').replace(/^(\d{4})(\d{2})(\d{2})$/,'$1-$2-$3')))
      +row('총 층수',(S0.grndFloors?'지상 '+S0.grndFloors+'층':'')+(S0.ugrndFloors?' / 지하 '+S0.ugrndFloors+'층':''))
      +row('총 세대수',(S0.households?S0.households+'세대':'')+(S0.families?' · '+S0.families+'가구':''))
      +row('주차',S0.parking?'총 '+S0.parking+'대'+(S0.households?' <span class="bnote">세대당 '+(S0.parking/S0.households).toFixed(2)+'대</span>':''):'')
      +row('승강기',S0.elevators&&(S0.elevators.ride||S0.elevators.emergency)?'승용 '+(S0.elevators.ride||0)+'대'+(S0.elevators.emergency?' · 비상 '+S0.elevators.emergency+'대':''):'')
      +row('높이',height?height+'m':'')+row('연면적',bNum(S0.totArea)?fmtA(S0.totArea):'')+'</div>';
    h+='<div class="bsec"><h4>'+(ho?esc(ho)+'호 면적':'호실 면적')+'</h4>';
    if(ho&&units.length){ h+='<table><tr><th>동</th><th>호</th><th>층</th><th>용도</th><th class="r">전용</th><th class="r">공급</th></tr>'+units.slice(0,8).map(function(u){ return '<tr class="hit"><td>'+esc(u.dongNm||'-')+'</td><td>'+esc(u.hoNm||'')+'</td><td>'+(u.floor||'')+'</td><td>'+esc(u.purpose||'')+'</td><td class="r">'+fmtA(u.exclusive)+'</td><td class="r">'+fmtA(u.supply)+'</td></tr>'; }).join('')+'</table>'; }
    else if(ho) h+='<div class="bnote" style="color:var(--warn)">대장에 '+esc(ho)+'호 전유부가 없습니다 — '+esc(S0.kind||'일반건축물')+'(다가구·단독 등)은 호별 면적이 없고 층 면적만 있습니다.</div>';
    else if(list.length) h+='<div class="bnote">전유 호실 '+list.length+'개'+(list.length>=60?' (60개까지만)':'')+'</div><table><tr><th>동</th><th>호</th><th>층</th><th>용도</th><th class="r">전용</th></tr>'+list.slice(0,30).map(function(u){ return '<tr><td>'+esc(u.dongNm||'-')+'</td><td>'+esc(u.hoNm||'')+'</td><td>'+(u.floor||'')+'</td><td>'+esc(u.purpose||'')+'</td><td class="r">'+fmtA(u.exclusive)+'</td></tr>'; }).join('')+'</table>';
    else h+='<div class="bnote">전유부(호별 면적)가 없는 건물입니다. 매물을 누르면 호수가 있을 때 그 호실을 찾습니다.</div>';
    h+='</div>';
    h+='<div class="bsec"><h4>층별 현황</h4>';
    var fl=floors.filter(function(f){ return !/부속/.test(f.mainAtch||'') });
    if(!fl.length) h+='<div class="bnote">층별 현황이 없습니다.</div>';
    else h+='<table><tr><th>구분</th><th>층</th><th>주용도</th><th class="r">면적</th></tr>'+fl.slice(0,40).map(function(f){ return '<tr><td>'+esc(f.kind||'')+'</td><td>'+esc(f.floorName||(f.floor+'층'))+'</td><td>'+esc(f.purpose||'')+'</td><td class="r">'+fmtA(f.area)+'</td></tr>'; }).join('')+'</table>'+(fl.length>40?'<div class="bnote">'+fl.length+'층 중 40개까지만</div>':'');
    h+='</div>';
    var nz=near.filter(function(x){ return x&&x.name });
    h+='<div class="bsec"><h4>주변 정보</h4>'+(nz.length?nz.map(function(x){ return '<div class="brow"><span>'+esc(x.label||x.category||'')+'</span><b>'+esc(x.name)+' <span class="bnote" style="font-weight:400">'+esc(x.distanceText||'')+(x.walkMin?' · 도보 '+x.walkMin+'분':'')+'</span></b></div>'; }).join(''):'<div class="bnote">주변 정보가 없습니다 (엔진에 카카오·버스 키가 없으면 비어 있습니다).</div>')+'</div>';
    box.innerHTML=h;
  }
  var LAST=null;
  function groupRows(arr){
    if(!$('na_group').checked) return arr;
    var m={}, out=[];
    arr.forEach(function(x){ var k=[x.type,x.trade,x.price,x.rent,x.floor,x.area1,x.area2,x.jibun||''].join('|'); if(m[k]){ m[k].dups.push(x); if(x.realtor&&m[k].brokers.indexOf(x.realtor)<0) m[k].brokers.push(x.realtor); } else { var g=Object.assign({},x,{dups:[],brokers:x.realtor?[x.realtor]:[]}); m[k]=g; out.push(g); } });
    return out;
  }
  function naRow(x, kind){
    var tag = kind==='exact' ? (x.likely?'<span class="tag ok" title="주소 비공개지만 바로 그 자리(15m 안)에 찍힌 매물">위치 일치</span>':'<span class="tag ok">지번 일치</span>') : '<span class="tag q">근처 '+(x.dist==null?'?':x.dist)+'m'+(x.jibun?'':' · 지번 비공개')+'</span>';
    var dupN=(x.dups||[]).length, brokers=x.brokers||[];
    var realtorCell = dupN ? '<b>'+(brokers.length||1)+'곳</b> <span class="small muted" title="'+esc(brokers.join(', '))+'">'+esc(brokers.slice(0,2).join(', '))+(brokers.length>2?' 외 '+(brokers.length-2):'')+'</span>' : esc(x.realtor);
    return '<tr class="pick" data-url="'+esc(x.url)+'" title="누르면 이 매물을 바로 정리합니다'+(dupN?' (같은 매물 '+(dupN+1)+'건 묶음)':'')+'"><td>'+tag+(dupN?'<div class="small muted">×'+(dupN+1)+'</div>':'')+'</td><td>'+esc(x.no)+'</td><td>'+esc(x.name)+(x.feature?'<div class="small muted" style="white-space:normal;max-width:220px">'+esc(x.feature)+'</div>':'')+'</td><td>'+esc(x.type)+' '+esc(x.trade)+'</td><td>'+esc(x.price)+(x.rent?' / '+esc(x.rent):'')+'</td><td>'+esc(x.floor)+'</td><td>'+esc(x.area1)+'/'+esc(x.area2)+'</td><td>'+esc(x.jibun||'')+'</td><td>'+realtorCell+'</td><td>'+esc(x.confirm)+'</td></tr>';
  }
  async function find(){
    var q=$('na_q').value.trim(); if(q.length<2) return; $('na_find').disabled=true; $('na_fmsg').textContent='찾는 중… (우리 DB → 네이버 그 자리 매물 → 지번 확인, 5~15초)'; $('na_fout').innerHTML='';
    try{
      var r=await fetch('/admin/naverad/search',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({q:q})}).then(function(x){return x.json()});
      if(r.error){ $('na_fmsg').textContent=r.error; $('na_find').disabled=false; return; }
      LAST={r:r,q:q}; renderFind(); 
    }catch(e){ $('na_fmsg').textContent='오류: '+e.message; }
    $('na_find').disabled=false;
  }
  function renderFind(){
    var r=LAST.r, q=LAST.q;
      var n=r.naver||{}, ex0=n.exact||[], nr0=n.near||[], ex=groupRows(ex0), nr=groupRows(nr0);
      var h='';
      if(!n.error){ h+='<div class="cnt"><span>네이버에 <b>'+ex0.length+'</b>건 올라와 있음'+(ex.length!==ex0.length?' <span class="small muted">(묶으면 '+ex.length+'건)</span>':'')+'</span><span class="b2">부동산 <b>'+(n.broker_count||0)+'</b>곳</span><span class="small muted">근처 다른 지번 '+nr.length+'건 · '+esc(n.cortar||'')+' · 목록 '+(n.pages||0)+'쪽 '+(n.scanned||0)+'건 중 확인 '+(n.checked||0)+'건물'+(n.blocked?' · '+esc(n.blocked):'')+(n.ambiguous?' · 같은 이름의 동이 여럿: '+esc(n.ambiguous.join(', '))+' → 구 이름을 붙여주세요':'')+'</span></div>'; }
      h+='<h3 style="font-size:14px;margin:8px 0 4px">우리 DB <span class="tag db">'+(r.db||[]).length+'건</span></h3>';
      if((r.db||[]).length){ h+='<table class="na-table"><tr><th>지번·호수</th><th>임대인 연락처</th><th>임차인·관리 등</th><th>종류</th><th>거래</th><th>금액</th><th>이름</th><th>출처</th><th>올린 날</th></tr>'; r.db.forEach(function(x){ h+='<tr><td>'+esc(x.addr)+'</td><td>'+esc(x.phone)+'</td><td>'+esc(x.contacts)+'</td><td>'+esc(x.kind)+'</td><td>'+esc(x.deal)+'</td><td>'+esc(x.price)+'</td><td>'+esc(x.title)+'</td><td class="small muted">'+esc(x.site)+' · '+esc(x.file||'')+'</td><td>'+esc(x.last_at)+'</td></tr>'; }); h+='</table>'; }
      h+='<h3 style="font-size:14px;margin:14px 0 4px">네이버 <span class="tag ok">지번 일치 '+ex.length+'건</span> <span class="tag q">근처 '+nr.length+'건</span></h3>';
      if(n.error){ h+='<div style="color:var(--danger);font-size:13px">'+esc(n.error)+'</div>'; }
      else{
        var all=ex.map(function(x){return naRow(x,'exact')}).concat(nr.map(function(x){return naRow(x,'near')}));
        if(all.length) h+='<table class="na-table"><tr><th></th><th>매물번호</th><th>매물명</th><th>종류·거래</th><th>금액</th><th>층</th><th>공급/전용</th><th>지번(확인)</th><th>중개사</th><th>확인일</th></tr>'+all.join('')+'</table>';
        else h+='<div class="small muted">지금 네이버에는 이 지번 자리의 매물이 없습니다.</div>';
      }
      $('na_fout').innerHTML=h; $('na_fmsg').textContent='완료 — 네이버 '+ex0.length+'건 (부동산 '+(n.broker_count||0)+'곳)'+(nr0.length?' · 근처 '+nr0.length+'건':'');
      if(n.cortar){ var lot=(q.match(/(산\s*)?(\d{1,4}(?:-\d{1,4})?)\s*$/)||[])[0]||''; loadBldg((n.cortar+' '+lot).replace(/^서울시/,'서울특별시').trim(), ''); }
      document.querySelectorAll('#na_fout tr.pick').forEach(function(tr){ tr.onclick=function(){ pick(tr.dataset.url, tr); }; });
  }
  $('na_group').onchange=function(){ if(LAST) renderFind(); };
  $('na_find').onclick=find; $('na_q').addEventListener('keydown',function(e){ if(e.key==='Enter'){ e.preventDefault(); find(); } });
})();
`;

