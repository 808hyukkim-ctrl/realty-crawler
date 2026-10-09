// 호수 추정 (2026-10-09) — 네이버 링크만 넣으면 그 매물의 호수를 건축물대장 전유부(호별 전용면적)와 대조해 찾는다. 수집기(naver_crawler)의 호수 추론과 같은 규칙.
//   1) 네이버 상세: 동(422동)·해당층(숫자 또는 저/중/고)·총층·전용면적   2) fin.land 상세: 지번(법정동코드+번지)
//   3) 같은 주소 매물 묶음(여러 중개사가 올린 같은 집): 누군가 층을 숫자로 적었으면 저/중/고 대신 그 층을 쓴다 (근거 표시)
//   4) 건축HUB 전유공용면적 API(BUILDING_API_KEY, 동 필터, 1000행씩)로 그 건물 호별 전용면적 → 같은 층(또는 저/중/고 구간) + 면적 허용치(3㎡ 또는 8%) 안의 호
//   결과: 확정(1개) / 후보(여러 개, 12개까지 나열·그 이상은 요약) / 확인불가
//   GET  /admin/hosu            화면       POST /admin/hosu/run {urls}   링크별 결과
import { Hono } from "hono";
import { html, raw } from "hono/html";
import { layout } from "./layout";
import { NAVER_HEADERS, finLand, naverNo } from "./naverad";

type Bindings = { DB: D1Database; ADMIN_USER: string; ADMIN_PASSWORD: string; BUILDING_API_KEY?: string; PARSE?: Fetcher };
export const hosu = new Hono<{ Bindings: Bindings }>();

const s = (v: any) => (v == null ? "" : String(v)).trim();
const num = (v: any) => { const n = parseFloat(String(v ?? "").replace(/,/g, "")); return Number.isFinite(n) ? n : null; };
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

// ---------------------------------------------------------------- 층 해석 (수집기 _infer_floor_band_* 와 동일)
function floorOf(txt: string): number | null {
  const f = s(txt).split("/")[0].trim();
  if (/^-?\d+$/.test(f)) return parseInt(f, 10);
  if (/^B\d+$/i.test(f)) return -parseInt(f.replace(/[Bb]/, ""), 10);
  if (/^반지/.test(f)) return -1;
  return null;
}
function bandRange(txt: string, total: number | null): [number, number] | null {
  const f = s(txt).split("/")[0].trim(); if (!total || !f) return null;
  const hiLow = Math.max(1, Math.floor(total / 3)), hiMid = Math.max(hiLow, Math.floor((2 * total) / 3));
  if (f.includes("저")) return [1, hiLow];
  if (f.includes("중")) { const lo = Math.min(hiLow + 1, total); return [lo, Math.max(lo, hiMid)]; }
  if (f.includes("고")) { const lo = Math.min(hiMid + 1, total); return lo > total ? [total, total] : [lo, total]; }
  return null;
}
const bandWord = (txt: string) => { const f = s(txt).split("/")[0].trim(); return /저|중|고/.test(f) ? f : ""; };

// ---------------------------------------------------------------- 건축HUB 전유부
type Unit = { dong: string; ho: string; floor: number; area: number; purpose: string };
async function hubUnits(key: string, legal: string, lot: string, dong: string): Promise<{ units: Unit[]; total: number; pages: number; error?: string }> {
  if (!key) return { units: [], total: 0, pages: 0, error: "건축물대장 API 키(BUILDING_API_KEY)가 없습니다." };
  if (!/^\d{10}$/.test(legal)) return { units: [], total: 0, pages: 0, error: "법정동코드를 읽지 못했습니다." };
  const san = /^산/.test(lot); const m = lot.replace(/^산/, "").match(/^(\d{1,4})(?:-(\d{1,4}))?$/);
  if (!m) return { units: [], total: 0, pages: 0, error: "번지를 읽지 못했습니다: " + lot };
  const base = { serviceKey: key, sigunguCd: legal.slice(0, 5), bjdongCd: legal.slice(5, 10), platGbCd: san ? "1" : "0", bun: m[1].padStart(4, "0"), ji: (m[2] || "0").padStart(4, "0"), numOfRows: "1000", _type: "json" };
  const units: Unit[] = []; let total = 0, pages = 0;
  // 건축HUB 는 한 쪽에 100행까지 → 총건수만큼 4쪽씩 같이 받는다 (전유 1건당 공용 행이 5~10개 섞여 있어 행수가 많다)
  const fetchPage = async (page: number): Promise<any[] | null> => {
    const p = new URLSearchParams({ ...base, numOfRows: "100", pageNo: String(page), ...(dong ? { dongNm: dong } : {}) });
    for (let attempt = 1; attempt <= 3; attempt++) {
      try {
        const r = await fetch("https://apis.data.go.kr/1613000/BldRgstHubService/getBrExposPubuseAreaInfo?" + p.toString(), { signal: AbortSignal.timeout(12000) } as any);
        if (!r.ok) { await sleep(400 * attempt); continue; }
        const d: any = await r.json().catch(() => null);
        const body = d?.response?.body; if (!body) { await sleep(400 * attempt); continue; }
        if (page === 1) total = Number(body.totalCount) || 0;
        const it = body.items && typeof body.items === "object" ? body.items.item : null;
        return !it ? [] : Array.isArray(it) ? it : [it];
      } catch { await sleep(400 * attempt); }
    }
    return null;
  };
  const first = await fetchPage(1);
  if (!first) return { units, total, pages, error: "건축물대장 API 응답 없음(503/시간초과) — 잠시 뒤 다시" };
  const addRows = (items: any[]) => { for (const u of items) { if (s(u.exposPubuseGbCd) !== "1") continue; const fl = num(u.flrNo); if (fl == null) continue; units.push({ dong: s(u.dongNm), ho: s(u.hoNm), floor: fl, area: Math.round((num(u.area) || 0) * 100) / 100, purpose: s(u.mainPurpsCdNm) || s(u.etcPurps) }); } };
  addRows(first); pages = 1;
  const lastPage = Math.min(60, Math.ceil(total / 100));                       // 6000행(≈600호)까지 — 동 필터가 있으면 보통 10쪽 안
  for (let p = 2; p <= lastPage; p += 4) {
    const batch = [p, p + 1, p + 2, p + 3].filter((x) => x <= lastPage);
    const rs = await Promise.all(batch.map(fetchPage));
    for (const r of rs) { if (r) { addRows(r); pages++; } }
  }
  return { units, total, pages };
}
const normDong = (d: string) => s(d).replace(/\s+/g, "").replace(/동$/, "");
const hoInt = (h: string) => { const d = (h.match(/\d+/) || [""])[0]; return d ? parseInt(d, 10) : 1e9; };
/** 후보 표시: 1개 그대로 / 12개 이하 쉼표 / 그 이상은 "3~5층 03/04호 (30개)" 요약 (수집기 _format_hosu_candidates 와 같은 취지) */
function formatCands(cs: Unit[]): string {
  const hos = Array.from(new Set(cs.map((c) => c.ho))).sort((a, b) => hoInt(a) - hoInt(b));
  if (hos.length <= 12) return hos.map((h) => (/호$/.test(h) ? h : h + "호")).join(", ");
  const floors = cs.map((c) => c.floor); const lo = Math.min(...floors), hi = Math.max(...floors);
  const lines = Array.from(new Set(hos.map((h) => h.replace(/\D/g, "").slice(-2)))).sort().join("/");
  return `${lo}~${hi}층 ${lines}호 (${hos.length}개)`;
}

// ---------------------------------------------------------------- 한 링크
async function naverDetail(no: string, complexNo = ""): Promise<any> {
  // 네이버가 가끔 200 인데 상세가 빈 응답을 준다(짧은 차단) → 1.5초 뒤 한 번 더 (단지 번호가 있으면 같이 보냄)
  let last = "";
  for (let attempt = 1; attempt <= 2; attempt++) {
    const r = await fetch(`https://new.land.naver.com/api/articles/${no}?complexNo=${attempt === 2 ? complexNo : ""}`, { headers: NAVER_HEADERS });
    if (r.status === 429) throw new Error("네이버가 잠시 요청을 막았습니다(429). 1~2분 뒤 다시 해주세요.");
    if (!r.ok) throw new Error(`네이버 상세 응답 ${r.status} (내려간 매물일 수 있음)`);
    const d: any = await r.json().catch(() => null);
    if (d && d.articleDetail) return d;
    last = d ? JSON.stringify(d).slice(0, 80) : "json 아님";
    if (attempt === 1) await sleep(1500);
  }
  throw new Error("네이버가 상세를 비워서 보냈습니다 — 잠시 뒤 다시 눌러주세요 (계속 비면 삭제·비공개 매물)" + (last ? ` [${last}]` : ""));
}
async function sameGroup(no: string): Promise<any[]> {
  try { const r = await fetch(`https://new.land.naver.com/api/articles?representativeArticleNo=${no}`, { headers: NAVER_HEADERS }); if (!r.ok) return []; const j: any = await r.json().catch(() => null); return Array.isArray(j) ? j : []; } catch { return []; }
}
async function hosuOne(c: any, url: string) {
  const no = naverNo(url); if (!no) throw new Error("네이버 매물 링크가 아닙니다");
  const complexNo = (s(url).match(/complexes\/(\d+)/) || (s(url).match(/complexNo=(\d+)/)) || [])[1] || "";
  const d = await naverDetail(no, complexNo);
  const ad = d.articleDetail || {}, ft = d.articleFloor || {}, sp = d.articleSpace || {}, add = d.articleAddition || {};
  const name = s(ad.aptName || ad.articleName || add.articleName);
  const dong = s(ad.buildingName || add.buildingName);                                      // "422동" / "1동" / ""
  const floorInfo = s(add.floorInfo || ad.floorInfo);                                      // "25/26" / "중/15"
  let floor = num(ft.correspondingFloorCount) ?? floorOf(floorInfo);
  const total = num(ft.totalFloorCount) ?? (() => { const t = floorInfo.split("/")[1]; return /^\d+$/.test(s(t)) ? parseInt(t, 10) : null; })();
  const area = num(sp.exclusiveSpace) ?? num(ad.exclusiveSpace);
  const band = floor == null ? bandWord(floorInfo) : "";
  // 같은 집 다른 중개사 매물에서 층 숫자 찾기
  let evidence = "";
  const group = await sameGroup(no);
  if (floor == null && group.length) {
    const hit = group.find((g: any) => s(g.articleNo) !== no && floorOf(s(g.floorInfo)) != null && (!dong || normDong(g.buildingName) === normDong(dong)));
    if (hit) { floor = floorOf(s(hit.floorInfo)); evidence = `같은 집을 ${s(hit.realtorName)}(매물 ${s(hit.articleNo)})가 ${s(hit.floorInfo)}층으로 올려 ${floor}층으로 봄`; }
  }
  const fl = await finLand(no);
  const lot = s(fl.jibun), legal = s(fl.legal);
  const addrDong = s(ad.exposureAddress || ad.cortarAddress);
  const jibunFull = lot ? `${addrDong} ${lot}`.trim() : addrDong;
  const base = { no, url: `https://new.land.naver.com/houses?articleNo=${no}`, name, dong, floorInfo, floor, total, band, area, jibun: jibunFull, road: s(fl.road), group: group.length, evidence };
  if (!lot || !legal) return { ...base, status: "확인불가", hosu: "확인불가", note: "네이버 상세에 지번이 공개되지 않은 매물입니다 (주소 비공개)", cands: [] };
  if (area == null) return { ...base, status: "확인불가", hosu: "확인불가", note: "전용면적이 없어 대조할 수 없습니다", cands: [] };
  // 건축물대장 전유부 (동 필터 → 없으면 지번 전체)
  let hub = await hubUnits(c.env.BUILDING_API_KEY || "", legal, lot, dong);
  let dongNote = "";
  if (!hub.error && !hub.units.length && dong) { hub = await hubUnits(c.env.BUILDING_API_KEY || "", legal, lot, ""); dongNote = `대장에 '${dong}' 이름이 없어 지번 전체에서 찾음`; }
  if (hub.error) return { ...base, status: "확인불가", hosu: "확인불가", note: hub.error, cands: [] };
  let pool = hub.units;
  if (dong && dongNote) { const dn = normDong(dong); const same = pool.filter((u) => normDong(u.dong) === dn || normDong(u.dong).endsWith(dn)); if (same.length) pool = same; }
  if (!pool.length) return { ...base, status: "확인불가", hosu: "확인불가", note: "건축물대장에 전유부(호별 면적)가 없는 건물입니다 (단독·다가구 등)", cands: [], hubTotal: hub.total };
  const tol = Math.max(3, 0.08 * area);
  const range = floor == null ? bandRange(floorInfo, total) : null;
  const floorOk = (f: number) => floor != null ? f === floor : range ? f >= range[0] && f <= range[1] : true;
  const gap = (u: Unit) => Math.abs(u.area - area);
  let stage = "";
  let cands = pool.filter((u) => floorOk(u.floor) && gap(u) <= tol);
  if (cands.length) stage = floor != null ? "같은 층 · 같은 면적" : `저/중/고 구간(${range ? range[0] + "~" + range[1] + "층" : "전체"}) · 같은 면적`;
  if (!cands.length && (floor != null || range)) { const inFloor = pool.filter((u) => floorOk(u.floor)); if (inFloor.length) { const best = Math.min(...inFloor.map(gap)); if (best <= tol * 2) { cands = inFloor.filter((u) => gap(u) === best); stage = "같은 층 · 면적 최근접(허용치 2배 안)"; } } }
  if (!cands.length) { const best = Math.min(...pool.map(gap)); if (best <= tol) { cands = pool.filter((u) => gap(u) === best); stage = "층 무관 · 면적 최근접"; } }
  // 면적이 똑같은 호가 여러 층에 있으면 정확 일치만 남긴다
  // 면적이 더 정확히 맞는 호가 있으면 그것만 (13.99 vs 14.29 는 다른 라인) — 0.05㎡ → 0.5㎡ 순으로 좁힌다
  for (const tier of [0.05, 0.5]) { if (cands.length > 1) { const tight = cands.filter((u) => gap(u) <= tier); if (tight.length && tight.length < cands.length) { cands = tight; break; } } }
  cands.sort((a, b) => a.floor - b.floor || hoInt(a.ho) - hoInt(b.ho));
  const out = { ...base, cands: cands.slice(0, 60).map((u) => ({ dong: u.dong, ho: u.ho, floor: u.floor, area: u.area, purpose: u.purpose })), hubTotal: hub.total, pool: pool.length, stage, note: dongNote };
  if (!cands.length) return { ...out, status: "확인불가", hosu: "확인불가", note: [dongNote, `면적 허용치(±${tol.toFixed(1)}㎡) 안에 맞는 호가 없습니다`].filter(Boolean).join(" · ") };
  const uniqHo = new Set(cands.map((u) => u.ho));
  const relaxed = /최근접/.test(stage);                                            // 완화 단계(면적이 딱 맞지 않음)는 '추정' 으로 표시
  if (uniqHo.size === 1) return { ...out, status: relaxed ? "추정" : "확정", hosu: /호$/.test(cands[0].ho) ? cands[0].ho : cands[0].ho + "호", floorFound: cands[0].floor };
  return { ...out, status: `후보 ${uniqHo.size}개`, hosu: formatCands(cands), floorRange: [cands[0].floor, cands[cands.length - 1].floor] };
}

hosu.post("/admin/hosu/run", async (c) => {
  const body: any = await c.req.json().catch(() => ({}));
  const urls: string[] = Array.isArray(body.urls) ? body.urls.map((u: any) => s(u)).filter(Boolean).slice(0, 20) : [];
  const items: any[] = [];
  for (const url of urls) {
    try { items.push({ ok: true, url, ...(await hosuOne(c, url)) }); }
    catch (e: any) { items.push({ ok: false, url, error: e?.message || String(e) }); }
  }
  return c.json({ items });
});

// ---------------------------------------------------------------- 화면
hosu.get("/admin/hosu", (c) => c.html(layout("호수 추정", PAGE())));
function PAGE() {
  return html`
<div class="page-head"><h1>호수 추정</h1><span class="small muted">네이버 링크를 넣으면 건축물대장 호별 면적과 대조해 호수를 찾습니다. 저/중/고는 같은 집을 올린 다른 중개사가 층을 숫자로 적었으면 그 층으로, 없으면 구간 후보로.</span></div>
<section class="panel">
  <textarea id="hs_links" rows="4" placeholder="네이버 매물 링크 — 여러 개면 줄바꿈·쉼표·공백으로 구분&#10;https://new.land.naver.com/houses?articleNo=2654182933"></textarea>
  <div class="na-bar"><button class="btn btn-primary" id="hs_go">호수 찾기</button><button class="btn" id="hs_clip">📋 클립보드에서</button><button class="btn" id="hs_xl" style="display:none">엑셀 다운로드</button><span class="small muted" id="hs_msg">링크 1개당 3~10초 (대장 조회). 한 번에 20개까지.</span></div>
  <div id="hs_out"></div>
</section>
<style>${raw(HS_STYLE)}</style>
<script src="https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js"></script>
<script>${raw(HS_JS)}</script>`;
}
const HS_STYLE = `
.muted{color:var(--muted)}
.panel{background:var(--panel);border:1px solid var(--border);border-radius:14px;padding:16px 18px;box-shadow:0 6px 24px rgba(255,92,154,.06)}
.panel textarea{width:100%;padding:10px 12px;border-radius:8px;border:1px solid var(--border);background:var(--input);color:var(--text);font-size:13px;box-sizing:border-box}
.na-bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:10px 0}
.hs-table{width:100%;border-collapse:collapse;background:#fff;border:1px solid var(--border);border-radius:10px;overflow:hidden;margin-top:8px}
.hs-table th,.hs-table td{padding:8px 10px;border-bottom:1px solid #fbe3ec;font-size:13px;text-align:left;vertical-align:top}
.hs-table th{background:var(--soft);color:var(--accent-dark);white-space:nowrap}
.hs-table td.hosu{font-weight:800;font-size:15px;white-space:normal}
.tag{display:inline-block;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:700;white-space:nowrap}
.tag.ok{background:rgba(47,158,110,.14);color:var(--ok)}
.tag.q{background:rgba(224,138,47,.14);color:var(--warn)}
.tag.no{background:rgba(224,74,106,.14);color:var(--danger)}
.cand{font-size:12px;color:var(--muted);white-space:normal}
.ev{font-size:12px;color:#4f5fd6}
`;
const HS_JS = `
(function(){
  var $=function(i){return document.getElementById(i)};
  var esc=function(v){return String(v==null?'':v).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')};
  var ITEMS=[];
  function links(){ var out=[],seen={}; $('hs_links').value.split(/\\s+|[,;]+(?=https?:)/).forEach(function(t){ t=t.trim(); if(/^(https?:\\/\\/|\\d{7,12}$)/.test(t)&&!seen[t]){seen[t]=1;out.push(t);} }); return out; }
  function tag(st){ return st==='확정'?'<span class="tag ok">확정</span>':st==='추정'?'<span class="tag q">추정 (면적 근사)</span>':/^후보/.test(st)?'<span class="tag q">'+esc(st)+'</span>':'<span class="tag no">'+esc(st||'확인불가')+'</span>'; }
  function paint(){
    var h='<table class="hs-table"><tr><th>#</th><th>매물</th><th>동 · 층/총층 · 전용</th><th>결과</th><th>호수</th><th>근거</th></tr>';
    ITEMS.forEach(function(it,i){
      if(!it.ok){ h+='<tr><td>'+(i+1)+'</td><td><a href="'+esc(it.url)+'" target="_blank" rel="noopener">'+esc(it.url.slice(0,60))+'</a></td><td colspan="4" style="color:var(--danger)">'+esc(it.error)+'</td></tr>'; return; }
      var fl=(it.floor!=null?it.floor+'층':(it.band?it.band+'층':'?'))+(it.total?' / '+it.total+'층':'');
      var cands=(it.cands||[]).slice(0,12).map(function(c){return (c.dong?c.dong+' ':'')+c.ho+'호 '+c.floor+'층 '+c.area+'㎡'}).join(' · ')+((it.cands||[]).length>12?' …':'');
      var ev=[]; if(it.evidence) ev.push('<span class="ev">'+esc(it.evidence)+'</span>'); if(it.stage) ev.push(esc(it.stage)); if(it.note) ev.push(esc(it.note)); if(it.group>1) ev.push('같은 집 매물 '+it.group+'건'); if(it.pool) ev.push('대장 전유부 '+it.pool+'호 대조');
      h+='<tr><td>'+(i+1)+'</td><td><b>'+esc(it.name||'')+'</b><br><span class="small">'+esc(it.jibun||'')+(it.road?' · '+esc(it.road):'')+'</span><br><a class="small" href="'+esc(it.url)+'" target="_blank" rel="noopener">'+esc(it.no)+' ↗</a></td><td>'+esc(it.dong||'-')+' · '+esc(fl)+' · '+esc(it.area!=null?it.area+'㎡':'-')+'</td><td>'+tag(it.status)+'</td><td class="hosu">'+esc(it.hosu||'')+(cands?'<div class="cand">'+esc(cands)+'</div>':'')+'</td><td class="cand">'+ev.join('<br>')+'</td></tr>';
    });
    $('hs_out').innerHTML=h+'</table>'; $('hs_xl').style.display=ITEMS.some(function(x){return x.ok})?'':'none';
  }
  async function run(){
    var urls=links(); if(!urls.length){ $('hs_msg').textContent='링크를 넣어주세요'; return; }
    $('hs_go').disabled=true; ITEMS=[]; $('hs_msg').textContent='찾는 중… 0/'+urls.length;
    try{ for(var i=0;i<urls.length;i+=3){ var r=await fetch('/admin/hosu/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({urls:urls.slice(i,i+3)})}).then(function(x){return x.json()}); ITEMS=ITEMS.concat(r.items||[]); paint(); $('hs_msg').textContent='찾는 중… '+Math.min(i+3,urls.length)+'/'+urls.length; }
      var ok=ITEMS.filter(function(x){return x.ok&&x.status==='확정'}).length, est=ITEMS.filter(function(x){return x.ok&&x.status==='추정'}).length, cand=ITEMS.filter(function(x){return x.ok&&/^후보/.test(x.status)}).length;
      $('hs_msg').textContent='완료 — 확정 '+ok+'건 · 추정 '+est+'건 · 후보 '+cand+'건 · 확인불가/실패 '+(ITEMS.length-ok-est-cand)+'건';
    }catch(e){ $('hs_msg').textContent='오류: '+e.message; }
    $('hs_go').disabled=false;
  }
  $('hs_go').onclick=run; $('hs_clip').onclick=async function(){ try{ var t=await navigator.clipboard.readText(); if(t){ $('hs_links').value=t; run(); } }catch(e){ $('hs_msg').textContent='클립보드를 읽지 못했습니다'; } };
  $('hs_xl').onclick=function(){
    var rows=ITEMS.filter(function(x){return x.ok}); var aoa=[['매물번호','매물명','지번','도로명','동','층','총층','전용㎡','결과','호수','후보','근거','링크']];
    rows.forEach(function(it){ aoa.push([it.no,it.name,it.jibun,it.road,it.dong,it.floor!=null?it.floor:it.band,it.total,it.area,it.status,it.hosu,(it.cands||[]).map(function(c){return c.ho+'호('+c.floor+'층 '+c.area+'㎡)'}).join(', '),[it.evidence,it.stage,it.note].filter(Boolean).join(' / '),it.url]); });
    var ws=XLSX.utils.aoa_to_sheet(aoa); ws['!cols']=aoa[0].map(function(h){return {wch:h==='후보'||h==='근거'?40:h==='링크'?44:12}}); var wb=XLSX.utils.book_new(); XLSX.utils.book_append_sheet(wb,ws,'호수추정'); XLSX.writeFile(wb,'호수추정_'+new Date().toISOString().slice(0,10).replace(/-/g,'')+'_'+rows.length+'건.xlsx');
  };
})();
`;
