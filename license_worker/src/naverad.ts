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
import NA_UI from "./naverad_ui.html";   // 화면(마크업·스타일·JS) — 포털 탭과 공용 (2026-10-10)

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
export const CODE2NAME: Record<string, string> = {};
export const NAME2CODES: Record<string, { code: string; full: string }[]> = {};
for (const [si, gus] of Object.entries(CORTAR as Record<string, Record<string, Record<string, string>>>)) {
  for (const [gu, dongs] of Object.entries(gus)) {
    for (const [dong, code] of Object.entries(dongs)) { CODE2NAME[code] = `${si} ${gu} ${dong}`; (NAME2CODES[dong] ||= []).push({ code, full: `${si} ${gu} ${dong}` }); }
  }
}


/** "서울특별시 송파구 잠실동 19 잠실엘스" → {legal:"1171010100", lot:"19", dongName:"잠실동", full:"서울시 송파구 잠실동"} (구 이름으로 같은 동 이름 구분) */
export function legalOf(addr: string): { legal: string; lot: string; dongName: string; full: string; ambiguous: string[] } | null {
  const a = String(addr || "").replace(/번지/g, "");
  const m = a.match(/([가-힣]+(?:동|리|가))\s*(산)?\s*(\d{1,4}(?:-\d{1,4})?)(?![\d-])/);
  if (!m) return null;
  let cands = NAME2CODES[m[1]] || [];
  const gu = (a.match(/([가-힣]+(?:구|군|시))\s/) || [])[1];
  if (gu && cands.length > 1) { const f = cands.filter((x) => x.full.includes(gu)); if (f.length) cands = f; }
  if (!cands.length) return null;
  return { legal: cands[0].code, lot: (m[2] ? "산" : "") + m[3], dongName: m[1], full: cands[0].full, ambiguous: cands.length > 1 ? cands.map((x) => x.full) : [] };
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
  const r = await ingest(c.env.DB, c.req.header("x-account") || c.env.ADMIN_USER || "admin", "네이버", "네이버 광고정리", rows);   // 포털에서 오면 x-account = 직원 계정
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
function PAGE() { return html`${raw(NA_UI)}`; }



