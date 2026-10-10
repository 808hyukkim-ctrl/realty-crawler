// 손님 브리핑 (2026-10-09) — 어드민 상단 메뉴 '손님 브리핑'(/admin/brief) + 손님이 여는 공개 페이지 /b/<id>
//   어드민: 링크(네이버·당근·온하우스·그 밖)·글·엑셀 줄을 정리 워커(daangn-parse /bulk)로 정리한 뒤 사진·주소·금액·역 도보를 손님용 카드로 묶어 링크를 만든다.
//   링크는 BRIEF_MAX_LINKS 개까지(지우면 자리가 남), 링크 하나에 매물은 BRIEF_MAX_ITEMS 개까지.
//   어드민 API (/admin/brief/api/<action>, index.ts 의 /admin/* 기본 인증, 계정 이름 @admin)
//     brief-list · brief-get?id= · brief-save {id?, customer, memo, staff_name, staff_phone, items[]} · brief-delete {id}
//     brief-station {address, bd_nm, lat, lng} → 가장 가까운 지하철역 도보 (매물 좌표 → 엔진 /nearby, 없으면 주소 확정 → 좌표)
//     brief-photo (multipart file, 중개사가 직접 올리는 사진 → D1 brief_photos, /b/p/<id> 로 서빙)
//   공개: GET /b/:id (손님 페이지) · GET /b/:id/data (내용 JSON, 조회수 +1) · POST /b/:id/submit {picks[], rejects[]} (손님 O/X 제출 → 어드민에 '제출완료')
//         GET /b/img?u=&r= (외부 사진 중계, 허용 호스트만) · GET /b/p/:pid (올린 사진)
import { Hono } from "hono";
import { html, raw } from "hono/html";
import BRIEF_HTML from "./brief.html";
import BRIEF_ADMIN_HTML from "./brief_admin.html";
import { layout } from "./layout";
import { proxyImage } from "./photos";
import { addLog, engineJson } from "./daangn";

type Bindings = { DB: D1Database; ENGINE_URL: string; ENGINE_SECRET: string };
export const brief = new Hono<{ Bindings: Bindings }>();

export const BRIEF_MAX_LINKS = 5;    // 동시에 둘 수 있는 손님 링크 수
export const BRIEF_MAX_ITEMS = 10;   // 링크 하나에 담는 추천 매물 수
const MAX_PHOTOS = 30;               // 매물 하나의 사진 수
const MAX_PHOTO_BYTES = 1_000_000;   // 올리는 사진 1장 (화면에서 1280px JPEG 로 줄여 보냄)
const PUBLIC_IMG_HOST = /(\.pstatic\.net|\.gcp-karroter\.net|\.cloudfront\.net|\.daangn\.com|\.naver\.(com|net)|\.onhouse\.(com|co\.kr)|\.zigbang\.(com|io|net|co\.kr)|\.nemoapp\.kr|\.amazonaws\.com)$/i;
const OWN_PHOTO = /^\/b\/p\/[a-z0-9]{10,}$/;

let ready = false;
async function ensure(db: D1Database) {
  if (ready) return;
  await db.prepare(`CREATE TABLE IF NOT EXISTS briefs (
    id TEXT PRIMARY KEY, username TEXT NOT NULL, customer TEXT NOT NULL, memo TEXT, staff_name TEXT, staff_phone TEXT,
    data TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, views INTEGER NOT NULL DEFAULT 0, last_view_at TEXT)`).run();
  await db.prepare("CREATE INDEX IF NOT EXISTS briefs_user ON briefs(username, updated_at DESC)").run();
  try { await db.prepare("ALTER TABLE briefs ADD COLUMN response TEXT").run(); } catch { /* 이미 있음 */ }   // 손님 O/X 제출 {picks, rejects, at}
  try { await db.prepare("ALTER TABLE briefs ADD COLUMN opts TEXT").run(); } catch { /* 이미 있음 */ }       // 보기 옵션 {wm: 사진 가운데 워터마크 가리기(기본 켬)}
  await db.prepare("CREATE TABLE IF NOT EXISTS brief_station (addr TEXT PRIMARY KEY, station TEXT NOT NULL, at TEXT NOT NULL)").run();
  await db.prepare("CREATE TABLE IF NOT EXISTS brief_photos (id TEXT PRIMARY KEY, username TEXT NOT NULL, ct TEXT NOT NULL, size INTEGER NOT NULL, data BLOB NOT NULL, created_at TEXT NOT NULL)").run();
  ready = true;
}
const nowIso = () => new Date().toISOString();
const str = (v: unknown, max = 500) => (v === null || v === undefined ? "" : String(v).trim().slice(0, max));
const json = (c: any, body: unknown, status = 200) => c.json(body, status);
const ALPHA = "abcdefghjkmnpqrstuvwxyz23456789";   // 헷갈리는 글자(0 o 1 l i) 뺀 소문자+숫자
const newId = (n = 10) => { const a = new Uint8Array(n); crypto.getRandomValues(a); return Array.from(a, (b) => ALPHA[b % ALPHA.length]).join(""); };
const briefUrl = (c: any, id: string) => new URL(c.req.url).origin + "/b/" + id;
const parseJson = (s: unknown, fb: any) => { try { return JSON.parse(String(s)); } catch { return fb; } };

type Item = { n: number; title: string; addr: string; price: string; station: string; memo: string; photos: string[]; spec: Record<string, unknown>; src: string; lat: number | null; lng: number | null };
const SPEC_KEYS = ["deal_type", "deposit", "monthly_rent", "sale_price", "manage_prc", "area_exclusive", "area_supply", "floor_no", "total_floors", "room_count", "bathroom_count", "direction", "available_date", "is_parking", "is_pet", "property_type", "bd_nm", "ho_nm", "dong_nm", "road_addr"];
const coord = (v: unknown) => { const n = Number(v); return Number.isFinite(n) && n ? n : null; };
/** 어드민이 보낸 매물 목록을 저장 모양으로 정리(글자 수·사진 수 제한, 알 수 없는 키 제거). 사진은 외부 주소(https) 또는 직접 올린 /b/p/<id> */
function cleanItems(raw: unknown): Item[] {
  const arr = Array.isArray(raw) ? raw.slice(0, BRIEF_MAX_ITEMS) : [];
  return arr.map((it: any, i: number) => {
    const spec: Record<string, unknown> = {};
    const s = it && typeof it.spec === "object" && it.spec ? it.spec : {};
    for (const k of SPEC_KEYS) if (s[k] !== undefined && s[k] !== null && s[k] !== "") spec[k] = typeof s[k] === "number" ? s[k] : str(s[k], 120);
    const photos = (Array.isArray(it?.photos) ? it.photos : []).map((p: unknown) => str(p, 1000)).filter((p: string) => /^https?:\/\//.test(p) || OWN_PHOTO.test(p)).slice(0, MAX_PHOTOS);
    return { n: i + 1, title: str(it?.title, 80), addr: str(it?.addr, 160), price: str(it?.price, 80), station: str(it?.station, 80), memo: str(it?.memo, 600), photos, spec, src: str(it?.src, 1000), lat: coord(it?.lat), lng: coord(it?.lng) };
  });
}
/** 손님에게 보여 주는 모양 — 원문 링크(src)·좌표는 뺀다 */
function publicItems(items: Item[]) { return items.map(({ src, lat, lng, ...rest }) => rest); }
const lotKey = (s: string) => { const m = String(s || "").match(/([가-힣]+(?:동|리|가))\s*(산\s*)?(\d{1,4}(?:-\d{1,4})?)(?![\d-])/); return m ? m[1] + " " + (m[2] ? "산" : "") + m[3] : ""; };
const dongOf = (s: string) => (String(s || "").match(/([가-힣]{1,10}(?:동|읍|면|리|가))(?=\s|$|\d)/) || [])[1] || "";

/** 엔진 주변정보에서 지하철 → "역삼역 도보 5분" */
function stationText(near: any[]): string {
  const sw = (Array.isArray(near) ? near : []).find((x) => x && (x.category === "subway" || /지하철/.test(String(x.label || ""))) && x.name);
  if (!sw) return "";
  let name = String(sw.name).replace(/\s*\d+호선.*$/, "").replace(/\s*(수인분당선|신분당선|경의중앙선|경춘선|공항철도|우이신설선|김포골드라인|서해선|신림선|에버라인|의정부경전철|동해선|대구선).*$/, "").trim();
  if (!/역$/.test(name)) name += "역";
  return `${name} 도보 ${sw.walkMin ? sw.walkMin + "분" : (sw.distanceText || "")}`.trim();
}
/** 매물 → 가장 가까운 지하철역. ① 매물 좌표(네이버 등) → 엔진 /nearby  ② 주소를 확정(정확 지번 → 건물명 → 후보가 하나뿐일 때만) → 엔진 /nearby?q=  ③ 못 정하면 빈 값(엉뚱한 역보다 낫다). 30일 캐시 */
async function stationOf(c: any, address: string, bdNm: string, lat: number | null, lng: number | null): Promise<{ station: string; by: string }> {
  const db: D1Database = c.env.DB;
  const key = (lat && lng ? `@${lat.toFixed(5)},${lng.toFixed(5)}` : [address.replace(/\s+/g, " ").trim(), bdNm].filter(Boolean).join(" | ")).slice(0, 200);
  if (key.length < 2) return { station: "", by: "none" };
  const hit: any = await db.prepare("SELECT station, at FROM brief_station WHERE addr = ?").bind(key).first();
  if (hit && Date.now() - new Date(hit.at).getTime() < 30 * 86400e3) return { station: hit.station, by: "cache" };
  let station = "", by = "";
  try {
    if (lat && lng) {
      const r = await engineJson(c, `/nearby?lat=${lat}&lng=${lng}`, undefined, "GET");
      station = stationText(r.data?.nearby); by = "coord";
    } else {
      // 주소 확정: 글의 지번("가락동 123")과 똑같은 후보 → 건물명(헬리오시티) 후보(같은 동 우선) → 후보가 하나뿐일 때만 그 주소
      const find = async (q: string): Promise<any[]> => { if (q.length < 2) return []; const a = await engineJson(c, "/address?q=" + encodeURIComponent(q), undefined, "GET"); return Array.isArray(a.data?.items) ? a.data.items : []; };
      const want = lotKey(address), dong = dongOf(address);
      let pick: any = null;
      if (want) {
        const items = await find(address);
        pick = items.find((it) => lotKey(it.jibunAddr || "") === want) || null;
        if (!pick) { const items2 = await find(address.replace(/^(서울|서울시|서울특별시|경기|경기도|인천|인천시|인천광역시)\s+/, "")); pick = items2.find((it) => lotKey(it.jibunAddr || "") === want) || null; }
        by = "lot";
      }
      if (!pick && bdNm) {
        const items = await find(bdNm);
        const same = dong ? items.filter((it) => String(it.jibunAddr || "").includes(dong)) : items;
        const named = (same.length ? same : items).filter((it) => String(it.bdNm || "").replace(/\s/g, "").includes(bdNm.replace(/\s/g, "")));
        pick = named[0] || same[0] || null; by = "building";
      }
      if (!pick && !want && address) { const items = await find(address); if (items.length === 1) { pick = items[0]; by = "single"; } }
      if (pick) {
        const q = pick.roadAddr || pick.jibunAddr;
        const r = await engineJson(c, "/nearby?q=" + encodeURIComponent(q), undefined, "GET");
        station = stationText(r.data?.nearby);
      } else by = "unresolved";
    }
  } catch { by = "error"; }
  if (station) await db.prepare("INSERT INTO brief_station (addr, station, at) VALUES (?, ?, ?) ON CONFLICT(addr) DO UPDATE SET station = excluded.station, at = excluded.at").bind(key, station, nowIso()).run().catch(() => {});
  return { station, by };
}
/** 보기 옵션 — wm: 외부 사이트 사진 가운데(워터마크 자리)를 손님 페이지에서 흐리게 가린다(기본 켬). 올린 사진(/b/p/)은 가리지 않는다 */
const optsOut = (r: any) => { const v = parseJson(r?.opts, null) || {}; return { wm: v.wm !== false }; };
const optsIn = (body: any) => JSON.stringify({ wm: body?.opts?.wm !== false });
const respOut = (r: any) => { const v = parseJson(r.response, null); return v && typeof v === "object" ? { picks: Array.isArray(v.picks) ? v.picks : [], rejects: Array.isArray(v.rejects) ? v.rejects : [], at: v.at || null, note: v.note || "" } : null; };

// ---------------------------------------------------------------- 어드민 API
export async function briefApi(c: any, me: { username: string; features: string[] }, action: string) {
  const db: D1Database = c.env.DB;
  await ensure(db);
  const q = (k: string) => str(c.req.query(k));
  const rowOut = (r: any) => ({ id: r.id, customer: r.customer, memo: r.memo || "", staff_name: r.staff_name || "", staff_phone: r.staff_phone || "", count: (parseJson(r.data, []) as any[]).length,
    created_at: r.created_at, updated_at: r.updated_at, views: r.views || 0, last_view_at: r.last_view_at || null, response: respOut(r), opts: optsOut(r), url: briefUrl(c, r.id) });

  if (action === "brief-list") {
    const { results } = await db.prepare("SELECT id, customer, memo, staff_name, staff_phone, data, created_at, updated_at, views, last_view_at, response, opts FROM briefs WHERE username = ? ORDER BY updated_at DESC").bind(me.username).all();
    return json(c, { rows: (results ?? []).map(rowOut), max: BRIEF_MAX_LINKS, max_items: BRIEF_MAX_ITEMS });
  }
  if (action === "brief-get") {
    const r: any = await db.prepare("SELECT * FROM briefs WHERE id = ? AND username = ?").bind(q("id"), me.username).first();
    if (!r) return json(c, { error: "그 링크가 없습니다(지워졌거나 다른 계정의 링크)." }, 404);
    return json(c, { ...rowOut(r), items: parseJson(r.data, []) });
  }
  if (action === "brief-station") {
    const body = await c.req.json().catch(() => ({}));
    return json(c, await stationOf(c, str(body.address, 200), str(body.bd_nm, 60), coord(body.lat), coord(body.lng)));
  }
  if (action === "brief-photo") {   // 중개사가 직접 올리는 사진: multipart file (화면에서 1280px JPEG 로 줄여 보냄)
    if (c.req.method !== "POST") return json(c, { error: "POST 로 올려주세요." }, 405);
    let file: File | null = null;
    try { const fd = await c.req.formData(); const f = fd.get("file"); if (f && typeof f !== "string") file = f as File; } catch { /* */ }
    if (!file) return json(c, { error: "사진 파일이 없습니다." }, 422);
    const ct = /^image\/(jpeg|png|webp|gif)$/i.test(file.type) ? file.type.toLowerCase() : "";
    if (!ct) return json(c, { error: "JPG·PNG·WEBP 사진만 올릴 수 있습니다." }, 415);
    const buf = await file.arrayBuffer();
    if (buf.byteLength > MAX_PHOTO_BYTES) return json(c, { error: `사진이 너무 큽니다(${Math.round(buf.byteLength / 1024)}KB). 1MB 이하로 줄여주세요.` }, 413);
    const id = newId(14);
    await db.prepare("INSERT INTO brief_photos (id, username, ct, size, data, created_at) VALUES (?, ?, ?, ?, ?, ?)").bind(id, me.username, ct, buf.byteLength, buf, nowIso()).run();
    return json(c, { ok: true, id, url: "/b/p/" + id, size: buf.byteLength });
  }
  if (action === "brief-save") {
    const body = await c.req.json().catch(() => ({}));
    const id = str(body.id, 40), customer = str(body.customer, 60), memo = str(body.memo, 1000), staffName = str(body.staff_name, 40), staffPhone = str(body.staff_phone, 40);
    if (!customer) return json(c, { error: "손님 이름(또는 호칭)을 넣어주세요." }, 422);
    if (!Array.isArray(body.items) || !body.items.length) return json(c, { error: "담긴 매물이 없습니다. 링크나 글을 정리해서 먼저 담아주세요." }, 422);
    if (body.items.length > BRIEF_MAX_ITEMS) return json(c, { error: `매물은 링크 하나에 ${BRIEF_MAX_ITEMS}개까지입니다.` }, 422);
    const items = cleanItems(body.items);
    const data = JSON.stringify(items);
    if (data.length > 400_000) return json(c, { error: "내용이 너무 큽니다(사진 주소가 너무 많음). 사진을 줄여주세요." }, 413);
    const now = nowIso();
    if (id) {
      const r: any = await db.prepare("SELECT id FROM briefs WHERE id = ? AND username = ?").bind(id, me.username).first();
      if (!r) return json(c, { error: "갱신할 링크가 없습니다(지워졌거나 다른 계정의 링크). [새로 시작] 뒤 다시 만들어주세요." }, 404);
      await db.prepare("UPDATE briefs SET customer = ?, memo = ?, staff_name = ?, staff_phone = ?, data = ?, updated_at = ?, opts = ? WHERE id = ? AND username = ?").bind(customer, memo, staffName, staffPhone, data, now, optsIn(body), id, me.username).run();
      await addLog(db, me.username, "brief", "브리핑 갱신", `${customer} · 매물 ${items.length}건 · ${id}`, items.length);
      return json(c, { ok: true, id, url: briefUrl(c, id), updated: true });
    }
    const cnt: any = await db.prepare("SELECT COUNT(*) n FROM briefs WHERE username = ?").bind(me.username).first();
    if ((cnt?.n ?? 0) >= BRIEF_MAX_LINKS) return json(c, { error: `손님 링크는 ${BRIEF_MAX_LINKS}개까지입니다. 아래 목록에서 안 쓰는 링크를 지우면 새로 만들 수 있습니다.`, code: "limit", max: BRIEF_MAX_LINKS }, 409);
    let nid = newId();
    for (let i = 0; i < 3; i++) { const dup = await db.prepare("SELECT 1 FROM briefs WHERE id = ?").bind(nid).first(); if (!dup) break; nid = newId(); }
    await db.prepare("INSERT INTO briefs (id, username, customer, memo, staff_name, staff_phone, data, created_at, updated_at, views, opts) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)").bind(nid, me.username, customer, memo, staffName, staffPhone, data, now, now, optsIn(body)).run();
    await addLog(db, me.username, "brief", "브리핑 생성", `${customer} · 매물 ${items.length}건 · ${nid}`, items.length);
    return json(c, { ok: true, id: nid, url: briefUrl(c, nid), updated: false });
  }
  if (action === "brief-delete") {
    const body = await c.req.json().catch(() => ({}));
    const id = str(body.id, 40); if (!id) return json(c, { error: "id 가 필요합니다." }, 422);
    const row: any = await db.prepare("SELECT data FROM briefs WHERE id = ? AND username = ?").bind(id, me.username).first();
    if (!row) return json(c, { error: "지울 링크가 없습니다." }, 404);
    await db.prepare("DELETE FROM briefs WHERE id = ? AND username = ?").bind(id, me.username).run();
    // 이 링크에만 쓰인 올린 사진은 같이 지운다
    const mine = new Set<string>(); for (const it of parseJson(row.data, []) as any[]) for (const p of it.photos || []) if (OWN_PHOTO.test(p)) mine.add(p.slice(5));
    if (mine.size) {
      const { results } = await db.prepare("SELECT data FROM briefs WHERE username = ?").bind(me.username).all();
      for (const r of (results ?? []) as any[]) for (const it of parseJson(r.data, []) as any[]) for (const p of it.photos || []) if (OWN_PHOTO.test(p)) mine.delete(p.slice(5));
      for (const pid of mine) await db.prepare("DELETE FROM brief_photos WHERE id = ? AND username = ?").bind(pid, me.username).run().catch(() => {});
    }
    await addLog(db, me.username, "brief", "브리핑 삭제", id, null);
    return json(c, { ok: true });
  }
  return json(c, { error: "없는 창구: " + action }, 404);
}

// ---------------------------------------------------------------- 어드민 화면 (index.ts 의 /admin/* 기본 인증이 먼저 걸린다)
const ADMIN_ME = { username: "@admin", features: ["brief"] };
brief.get("/admin/brief", (c) => c.html(layout("손님 브리핑", html`${raw(BRIEF_ADMIN_HTML)}`)));
brief.all("/admin/brief/api/:action", async (c) => {
  try { return await briefApi(c, ADMIN_ME, c.req.param("action")); }
  catch (e) { const msg = e instanceof Error ? e.message : String(e); console.error("[brief admin]", msg); return json(c, { error: "서버 오류: " + msg }, 500); }
});

// ---------------------------------------------------------------- 손님 공개 페이지
brief.get("/b/img", (c) => {
  const u = c.req.query("u") || "";
  let t: URL; try { t = new URL(u); } catch { return c.text("bad url", 400); }
  if (!/^https?:$/.test(t.protocol) || !PUBLIC_IMG_HOST.test(t.hostname)) return c.text("host not allowed", 403);
  return proxyImage(c, u, c.req.query("r") || "");
});
brief.get("/b/p/:pid", async (c) => {   // 중개사가 올린 사진
  await ensure(c.env.DB);
  const pid = str(c.req.param("pid"), 40);
  const r: any = await c.env.DB.prepare("SELECT ct, data FROM brief_photos WHERE id = ?").bind(pid).first();
  if (!r) return c.text("not found", 404);
  // D1 의 BLOB 은 환경에 따라 ArrayBuffer 또는 숫자 배열로 온다
  const body: ArrayBuffer | Uint8Array = r.data instanceof ArrayBuffer ? r.data : Array.isArray(r.data) ? new Uint8Array(r.data) : ArrayBuffer.isView(r.data) ? new Uint8Array((r.data as Uint8Array).buffer) : new TextEncoder().encode(String(r.data));
  return new Response(body as any, { status: 200, headers: { "Content-Type": r.ct, "Cache-Control": "public, max-age=31536000, immutable" } });
});
brief.get("/b/:id/data", async (c) => {
  await ensure(c.env.DB);
  const id = str(c.req.param("id"), 40);
  const r: any = await c.env.DB.prepare("SELECT customer, memo, staff_name, staff_phone, data, updated_at, response, opts FROM briefs WHERE id = ?").bind(id).first();
  if (!r) return c.json({ error: "없거나 지워진 브리핑입니다." }, 404, { "cache-control": "no-store" });
  const bump = c.env.DB.prepare("UPDATE briefs SET views = views + 1, last_view_at = ? WHERE id = ?").bind(nowIso(), id).run().catch(() => {});
  try { c.executionCtx.waitUntil(bump); } catch { await bump; }
  return c.json({ customer: r.customer, memo: r.memo || "", staff: { name: r.staff_name || "", phone: r.staff_phone || "" }, items: publicItems(parseJson(r.data, [])), updated_at: r.updated_at, response: respOut(r), opts: optsOut(r) }, 200, { "cache-control": "no-store" });
});
brief.post("/b/:id/submit", async (c) => {   // 손님 O/X 제출 → 어드민 목록에 '제출완료', 활동 기록
  await ensure(c.env.DB);
  const id = str(c.req.param("id"), 40);
  const r: any = await c.env.DB.prepare("SELECT username, customer, data FROM briefs WHERE id = ?").bind(id).first();
  if (!r) return c.json({ error: "없거나 지워진 브리핑입니다." }, 404);
  const body = await c.req.json().catch(() => ({}));
  const ns = new Set((parseJson(r.data, []) as any[]).map((it) => Number(it.n)));
  const nums = (v: unknown) => [...new Set((Array.isArray(v) ? v : []).map((x) => Number(x)).filter((n) => Number.isInteger(n) && ns.has(n)))].sort((a, b) => a - b);
  const picks = nums(body.picks), rejects = nums(body.rejects).filter((n) => !picks.includes(n));
  const resp = { picks, rejects, at: nowIso(), note: str(body.note, 500) };
  await c.env.DB.prepare("UPDATE briefs SET response = ? WHERE id = ?").bind(JSON.stringify(resp), id).run();
  await addLog(c.env.DB, r.username, "brief", "손님 제출완료", `${r.customer} · O ${picks.length ? picks.map((n) => n + "번").join("·") : "없음"} / X ${rejects.length ? rejects.map((n) => n + "번").join("·") : "없음"} · ${id}`, picks.length);
  return c.json({ ok: true, response: resp });
});
brief.get("/b/:id", (c) => c.html(BRIEF_HTML, 200, { "cache-control": "no-store", "x-robots-tag": "noindex" }));
