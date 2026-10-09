// 매물·임대인 DB (2026-10-08) — 지번·호수 ↔ 임대인 연락처를 쌓아 두는 곳. 엑셀(수집기 결과물·팀 매물 파일·임대인 명단 등 아무 열)을 올리거나 수기로 한 줄씩 넣는다.
//   구분+번호+거래 기준 upsert (같은 행을 다시 올리면 최근·횟수만 갱신, 수기로 고친 연락처·메모는 빈 값으로 덮어쓰지 않음)
//   GET  /admin/listings                                   화면: [수기 입력] [엑셀 올리기] 필터(구분·검색어·기간·계정·파일) 100건씩, 연락처·메모 칸 클릭해 바로 수정
//   POST /admin/listings/manual (form)                     수기 한 줄 추가
//   POST /admin/listings/upload {site, file, rows}         브라우저가 SheetJS 로 읽은 행 (헤더 줄은 브라우저가 자동으로 찾음)
//   POST /admin/listings/:id/edit {phone?, memo?}          연락처·메모 수정
//   POST /admin/listings/:id/delete                        한 줄 삭제
//   GET  /admin/listings/lookup.json?q=논현동 124-12       지번(띄어쓰기 무시, 낱말 모두 포함)으로 바로 찾기 — 화면 맨 위 '지번 조회' 칸과 외부 호출(curl -u admin:비번)이 같이 씀
//   GET  /admin/listings/rows.json?...&after=&limit=       필터 결과 → 브라우저가 엑셀 생성 (지번·연락처가 맨 앞)
//   POST /admin/listings/delete (form)                     필터 결과 삭제
//   POST /api/v1/listings {username, token, site, file, rows}  프로그램용 (log_token) — 현재 수집기는 쓰지 않음
import { Hono } from "hono";
import { html, raw } from "hono/html";
import { layout } from "./layout";

type Bindings = { DB: D1Database; ADMIN_USER: string; ADMIN_PASSWORD: string };
export const listings = new Hono<{ Bindings: Bindings }>();

export const SITE_LABEL: Record<string, string> = { naver: "네이버", daangn: "당근", onhouse: "온하우스", peterpan: "피터팬" };
const siteLabel = (s: string) => SITE_LABEL[s] || s;
const cleanSite = (h: string) => h.trim().replace(/[^a-zA-Z0-9가-힣_ ]/g, "").trim().slice(0, 20);

let ready = false;
export { ensure as ensureListings };
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
  for (const col of ["phone TEXT NOT NULL DEFAULT ''", "memo TEXT NOT NULL DEFAULT ''", "contacts TEXT NOT NULL DEFAULT ''"]) {   // 10-08 추가 열 (이미 있으면 무시)
    try { await db.prepare("ALTER TABLE listings ADD COLUMN " + col).run(); } catch (e) { /* 있음 */ }
  }
  await db.prepare("CREATE INDEX IF NOT EXISTS listings_last ON listings(last_at DESC)").run();
  await db.prepare("CREATE INDEX IF NOT EXISTS listings_site_last ON listings(site, last_at DESC)").run();
  await db.prepare("CREATE INDEX IF NOT EXISTS listings_file ON listings(file)").run();
  // 되돌리기 (2026-10-09): 지운 줄은 휴지통에 30일 보관, 작업(삭제·붙여넣기·엑셀) 기록
  await db.prepare("CREATE TABLE IF NOT EXISTS listings_trash (id INTEGER PRIMARY KEY AUTOINCREMENT, batch TEXT NOT NULL, deleted_at TEXT NOT NULL, orig_id INTEGER, row TEXT NOT NULL)").run();
  await db.prepare("CREATE INDEX IF NOT EXISTS listings_trash_batch ON listings_trash(batch)").run();
  await db.prepare("CREATE TABLE IF NOT EXISTS listings_ops (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, kind TEXT NOT NULL, label TEXT, count INTEGER NOT NULL DEFAULT 0, batch TEXT, ids TEXT, undone INTEGER NOT NULL DEFAULT 0)").run();
  try { await db.prepare("DELETE FROM listings_trash WHERE deleted_at < ?").bind(new Date(Date.now() - 30 * 86400e3).toISOString()).run(); } catch { /* */ }
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
/** 열 이름에 낱말이 들어간 첫 열의 값 (제외 낱말이 든 열은 건너뜀) */
const byWord = (row: Record<string, any>, words: string[], exclude: string[] = []) => {
  for (const w of words) {
    const k = Object.keys(row).find((c) => c.includes(w) && !exclude.some((x) => c.includes(x)) && s(row[c]));
    if (k) return s(row[k]);
  }
  return "";
};

/** 엑셀 열 이름으로 사이트를 알아낸다 (프로그램이 보낸 힌트는 열로 판별이 안 될 때만) */
export function detectSite(cols: string[], hint: string): string {
  const has = (k: string) => cols.includes(k);
  if (has("매물_URL") || (has("지번주소") && has("거래주체"))) return "daangn";
  if (has("세부주소") && has("거래방식")) return "naver";
  if (has("매물ID") && (has("확인일") || has("전체주소") || has("주소_호실"))) return "onhouse";
  const h = hint.toLowerCase();
  if (/^(네이버|naver)$/.test(h)) return "naver";
  if (/^(당근|daangn)$/.test(h)) return "daangn";
  if (/^(온하우스|onhouse)$/.test(h)) return "onhouse";
  if (/^(피터팬|peterpan)$/.test(h)) return "peterpan";
  return cleanSite(hint) || "기타";                                   // 임대인·고객 등 사용자가 적은 구분은 그대로
}

/** 임대인 연락처: 정확한 열 이름 → '연락처/전화/휴대폰' 이 든 열 (구분·중개사 열 제외) → 안심번호 */
function landlordPhone(row: Record<string, any>): string {
  return first(row, "임대인 연락처", "임대인연락처", "임대인 전화", "임대인전화", "소유자 연락처", "연락처", "전화번호", "휴대폰", "핸드폰", "전화")
    || byWord(row, ["연락처", "전화", "휴대폰", "핸드폰"], ["구분", "중개", "안심"])
    || [first(row, "임대인", "임대인정보", "소유자", "집주인")].filter((v) => /\d{3,}/.test(v))[0]   // "관리부동산 (0502-4226-6779)" 처럼 이름+번호 섞인 칸
    || first(row, "안심번호");
}
/** 한국 전화번호: 010·011~019, 02, 031~064, 070, 080, 050x(안심) — "010-1234-5678", "02 555 1234", "(0502)4226-6776" 등 */
const PHONE_RE = /(0(?:2|[3-6][1-5]|70|80|50\d|1[016789]))[-.\s)]*(\d{3,4})[-.\s]*(\d{4})(?!\d)/g;
export const phoneDigits = (v: string) => v.replace(/\D/g, "");
/** 열 이름으로 역할: 임대인 / 임차인 / 관리 / 중개 / 안심 / 연락처(역할 없음) / 본문(설명·메모 같은 글) */
export function roleOf(col: string): string {
  if (/임대인|소유자|집주인|주인/.test(col)) return "임대인";
  if (/임차인|세입자|거주자|입주자/.test(col)) return "임차인";
  if (/관리|경비|소장/.test(col)) return "관리";
  if (/중개|부동산|공인/.test(col)) return "중개";
  if (/안심/.test(col)) return "안심";
  if (/연락처|전화|휴대폰|핸드폰|폰|TEL|tel|HP/.test(col)) return "연락처";
  return "본문";
}
const SKIP_COL = /URL|url|링크|위도|경도|좌표|일시|날짜|등록일|확인일|승인일|입주가능|번호$/;   // 번호를 찾지 않을 열 (매물번호·사업자번호·우편번호 등)
/** 번호 바로 앞에 붙은 글("세입자-010…", "동생 010…", "관리부동산 (0502…)")을 그 번호의 역할로 쓴다. 전화/연락처/층/호 같은 말은 역할이 아님 */
const LABEL_STOP = /^(전화|연락처|연락|번호|핸드폰|휴대폰|폰|전번|tel|hp|phone|층|호|동|번지|참고|문의|직통|대표)$/i;
export function inlineLabel(text: string, idx: number): string {
  const pre = text.slice(Math.max(0, idx - 24), idx);
  const m = pre.match(/([가-힣A-Za-z]{2,10})\s*[-:：(（]?\s*$/);
  if (!m) return "";
  const w = m[1].replace(/(연락처|전화번호|전화|번호|핸드폰|휴대폰)$/, "");   // "세입자연락처" → "세입자"
  return !w || LABEL_STOP.test(w) ? "" : w;
}
/** 행의 모든 칸에서 전화번호를 찾아 "역할 번호" 로 — 임대인 연락처(primary)와 같은 번호는 뺀다 */
export function extractContacts(row: Record<string, any>, primary: string): string {
  const seen = new Set<string>(phoneDigits(primary) ? [phoneDigits(primary)] : []);
  const out: string[] = [];
  for (const [col, raw] of Object.entries(row)) {
    if (SKIP_COL.test(col) && roleOf(col) === "본문") continue;
    const v = s(raw); if (!v || !/\d{4}/.test(v)) continue;
    const colRole = roleOf(col);
    for (const m of v.matchAll(PHONE_RE)) {
      const num = `${m[1]}-${m[2]}-${m[3]}`; const d = phoneDigits(num);
      if (seen.has(d)) continue; seen.add(d);
      const role = inlineLabel(v, m.index ?? 0) || (colRole === "연락처" ? "" : colRole);
      out.push((role ? role + " " : "") + num);
      if (out.length >= 8) break;
    }
    if (out.length >= 8) break;
  }
  return out.join(" · ").slice(0, 300);
}

/** 거래 칸 표시 — 금액에 '매매 … · 전세 … · 월세 …' 처럼 여러 거래가 적혀 있으면 전부 보여준다 */
export function dealsOf(deal: string | null | undefined, price: string | null | undefined): string {
  const p = String(price ?? "");
  const found = (["매매", "전세", "월세"] as const).filter((k) => new RegExp("(^|[ ·/])" + k + "\\s").test(p));
  return found.length > 1 ? found.join("·") : String(deal ?? "");
}
/** 주소에서 "동 번지" 와 호수를 뽑는다 — 중복 판정·엑셀 연락처 채우기에 쓴다. "서울 강남구 논현동 124-12, 3층 302호" → {lot:"논현동 124-12", ho:"302"} */
export function unitKey(addr: string, hoExtra = ""): { lot: string; ho: string } {
  const a = String(addr || "").replace(/번지/g, "");
  const m = a.match(/([가-힣]+(?:동|리|가))\s*(산)?\s*(\d{1,4}(?:-\d{1,4})?)(?![\d-])/);
  const lot = m ? `${m[1]} ${m[2] ? "산" : ""}${m[3]}` : "";
  const rest = m ? a.slice(m.index! + m[0].length) : a;
  let ho = String(hoExtra || "").trim().replace(/호$/, "");
  if (!ho) { const h = rest.match(/(?:^|[\s,])(?:\d+층\s*)?([A-Za-z]?\d{1,4}[A-Za-z]?)\s*호/) || rest.match(/\d+층\s*([A-Za-z]?\d{2,4}[A-Za-z]?)(?![\d-])/); ho = h ? h[1] : ""; }
  return { lot, ho: ho.toUpperCase() };
}
/** 주소 뒤에 호수 열이 따로 있으면 붙인다 ("논현동 124-12" + "302" → "논현동 124-12 302호") */
function withHo(addr: string, row: Record<string, any>): string {
  const ho = first(row, "호수", "호실", "호");
  if (!ho || !addr || addr.includes(ho)) return addr;
  return addr + " " + (/^\d+$/.test(ho) ? ho + "호" : ho);
}

/** 사이트별로 번호·링크·지번(주소+호수)·임대인 연락처·종류·거래·금액·이름을 뽑는다 (목록·검색용, 원본 행은 data 에 통째로 보관) */
export function summarize(site: string, row: Record<string, any>) {
  let no = "", url = "", addr = "", kind = "", deal = "", price = "", title = "";
  if (site === "naver") {
    const v = first(row, "매물번호");                       // 네이버 엑셀의 매물번호 셀은 전체 URL (articleNo=…)
    const m = v.match(/articleNo=(\d+)/);
    no = m ? m[1] : v; url = /^https?:/i.test(v) ? v : "";
    addr = withHo(first(row, "세부주소", "주소"), row); kind = first(row, "종류"); deal = first(row, "거래방식");
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
    // 팀에서 열을 옮겨 둔 파일은 '지역' 칸에 전체 주소가 있기도 함 → 셋 중 가장 긴 것
    addr = ["전체주소", "주소_호실", "지역"].map((k) => s(row[k]).replace(/\s+/g, " ")).sort((a, b) => b.length - a.length)[0] || "";
    const deals = (["매매", "전세", "월세"] as const).filter((k) => s(row[k]));
    if (deals.length) {   // 매매·전세·월세가 같이 있는 매물은 전부 적는다 (키의 deal 은 첫 거래로 고정 → 재업로드 때 중복 행 없음)
      deal = deals[0];
      price = deals.length > 1 ? deals.map((k) => `${k} ${s(row[k])}`).join(" · ") : s(row[deals[0]]);
      kind = (deals.map((k) => s(row[k + "_태그"])).find(Boolean) || "").split(",")[0].trim();
    }
    title = first(row, "건물명", "현업종");
  } else {
    // 팀 매물장·임대인 명단처럼 열 이름이 제각각인 엑셀
    no = first(row, "매물번호", "매물ID", "ID", "id", "번호", "No", "no") || byWord(row, ["번호"], ["전화", "연락", "안심", "등록", "사업자", "우편"]);
    url = first(row, "URL", "매물_URL", "링크", "url") || byWord(row, ["URL", "링크"], ["사진", "이미지"]);   // 사진 URL 열은 링크로 안 씀
    addr = withHo(first(row, "지번·호수", "지번주소", "지번", "주소", "세부주소", "전체주소", "소재지", "도로명주소") || byWord(row, ["지번", "주소", "소재지"]), row);
    kind = first(row, "종류", "매물유형", "용도", "건물종류") || byWord(row, ["종류", "유형", "용도"], ["대장"]);
    deal = first(row, "거래방식", "거래유형", "거래") || byWord(row, ["거래"]);
    const money = (k: string) => first(row, k, k + "(만원)") || byWord(row, [k], ["구분"]);
    const dep = money("보증금"), rent = money("월세"), sale = money("매매가") || money("매매"), jeon = money("전세금") || money("전세");
    const parts: string[] = [];
    if (sale) parts.push(`매매 ${sale}`);
    if (jeon) parts.push(`전세 ${jeon}`);
    if (rent) parts.push(`월세 ${dep || "0"} / ${rent}`); else if (dep && !jeon && !sale) parts.push(`보증금 ${dep}`);
    price = first(row, "금액", "가격") || (parts.length > 1 ? parts.join(" · ") : (rent ? `${dep || "0"} / ${rent}` : dep || jeon || sale));
    if (!deal && parts.length) deal = parts[0].split(" ")[0].replace("보증금", "월세");
    title = first(row, "임대인", "이름", "성명", "소유자", "성함", "이름/메모", "건물명", "제목", "매물명") || byWord(row, ["임대인", "이름", "성명", "소유자", "건물명", "제목"], ["연락처", "전화"]);
  }
  const phone = landlordPhone(row);
  const memo = first(row, "메모", "비고", "특이사항");
  const contacts = first(row, "기타 연락처", "임차인·관리 등") || extractContacts(row, phone);   // 수기 입력은 적은 그대로, 엑셀은 번호 패턴으로
  return { no: no.slice(0, 80), url: url.slice(0, 500), addr: addr.slice(0, 200), kind: kind.slice(0, 40), deal: deal.slice(0, 20), price: price.slice(0, 60), title: title.slice(0, 200), phone: phone.slice(0, 120), memo: memo.slice(0, 500), contacts: contacts.slice(0, 300) };
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
  const r = await ingest(c.env.DB, username, s(body.site), s(body.file), rowsIn);
  return c.json({ success: true, ...r });
});

// 어드민이 브라우저에서 올린 엑셀 행 (SheetJS 로 읽은 [{열:값}])
listings.post("/admin/listings/upload", async (c) => {
  const body: any = await c.req.json().catch(() => null);
  if (!body) return c.json({ success: false, message: "JSON 본문이 아닙니다." }, 400);
  const rowsIn: any[] = Array.isArray(body.rows) ? body.rows : [];
  if (rowsIn.length > 1000) return c.json({ success: false, message: "한 번에 1000행까지 보낼 수 있습니다." }, 413);
  const r = await ingest(c.env.DB, c.env.ADMIN_USER || "admin", s(body.site), s(body.file), rowsIn);
  return c.json({ success: true, ...r });
});

// 텍스트 붙여넣기: 한 줄 = 매물 하나. 지번·호수 / 연락처 / 거래·금액 / 종류 / 이름 을 알아서 찾는다 (2026-10-09)
const KIND_RX = /아파트|오피스텔|상가주택|빌라|다세대|다가구|단독|주택|상가|사무실|원룸|투룸|쓰리룸|토지|건물|공장|창고|지식산업센터|근생|점포/;
export function parsePastedText(text: string): { rows: Record<string, string>[]; skipped: string[] } {
  const rows: Record<string, string>[] = []; const skipped: string[] = [];
  for (const line0 of String(text || "").split(/\r?\n/)) {
    const line = line0.replace(/\t+/g, " ").replace(/\s+/g, " ").trim();
    if (!line) continue;
    let t = " " + line + " ";
    const row: Record<string, string> = {};
    const phones: string[] = [];
    t = t.replace(/(0\d{1,2})[-. ]?(\d{3,4})[-. ]?(\d{4})(?!\d)/g, (_m, a, b, cc) => { phones.push(`${a}-${b}-${cc}`); return " "; });
    const addr = t.match(/([가-힣]{1,10}(?:동|리|가|읍|면))\s*(산\s*)?(\d{1,4}(?:-\d{1,4})?)(?:번지)?(?:\s*((?:[A-Za-z가-힣0-9]{1,6}동\s*)?(?:지하\s*)?(?:B?\d{1,4}호|\d{1,3}층(?:\s*\d{1,4}호)?)))?/);
    if (!addr) { skipped.push(line); continue; }
    row["지번·호수"] = `${addr[1]} ${addr[2] ? "산" : ""}${addr[3]}${addr[4] ? " " + addr[4].replace(/\s+/g, " ") : ""}`.replace(/\s+/g, " ").trim();
    t = t.replace(addr[0], " ");
    const deal = t.match(/매매|전세|월세|반전세|단기임대|단기/); if (deal) { row["거래"] = deal[0] === "단기" ? "단기임대" : deal[0]; t = t.replace(deal[0], " "); }
    const price = t.match(/(\d[\d,]*(?:억)?\s*\d*[\d,]*(?:천|만)?\s*\/\s*\d[\d,]*(?:만)?)|(\d+억(?:\s*\d[\d,]*(?:천|만)?)?)|(\d{1,3}(?:,\d{3})+|\d{4,})(?:\s*만원?)?/);
    if (price) { row["금액"] = price[0].trim(); t = t.replace(price[0], " "); }
    const kind = t.match(KIND_RX); if (kind) { row["종류"] = kind[0]; t = t.replace(kind[0], " "); }
    // 번호: 앞에 '임차인/세입자/관리/중개' 가 붙은 번호는 기타, 그 밖에 첫 번호가 임대인
    const others: string[] = []; let owner = "";
    for (const p of phones) { const idx = line.indexOf(p.replace(/-/g, "")) >= 0 ? line.indexOf(p.replace(/-/g, "")) : line.indexOf(p); const before = line.slice(Math.max(0, idx - 8), idx); if (/임차|세입|관리|중개|부동산|기타/.test(before) || (owner && true)) { if (!owner && !/임차|세입|관리|중개|부동산|기타/.test(before)) owner = p; else others.push((before.match(/임차인|세입자|관리|중개|부동산/) || [""])[0] + (before.match(/임차인|세입자|관리|중개|부동산/) ? " " : "") + p); } else owner = p; }
    if (!owner && phones.length) owner = phones[0];
    if (owner) row["임대인 연락처"] = owner;
    if (others.length) row["기타 연락처"] = others.join(" ");
    const name = t.match(/([가-힣]{2,4})\s*(사장님|사장|대표님|대표|소유주|임대인|님|씨)/); if (name) { row["이름"] = name[1] + (name[2] ? " " + name[2] : ""); t = t.replace(name[0], " "); }
    const rest = t.replace(/임차인|세입자|관리|중개|부동산|기타|연락처|번호|:|·|\|/g, " ").replace(/\s+/g, " ").trim();
    if (rest) row["메모"] = rest;
    rows.push(row);
  }
  return { rows, skipped };
}
listings.post("/admin/listings/paste", async (c) => {
  const body: any = await c.req.json().catch(() => ({}));
  const { rows, skipped } = parsePastedText(String(body.text || ""));
  if (!rows.length) return c.json({ success: false, message: "지번(예: 논현동 124-12)이 들어 있는 줄이 없습니다.", skipped });
  const label = "텍스트 붙여넣기 " + kst(nowIso()).slice(0, 16);
  const r = await ingest(c.env.DB, c.env.ADMIN_USER || "admin", s(body.site) || "임대인", label, rows.slice(0, 500));
  return c.json({ success: true, ...r, parsed: rows.length, skipped, preview: rows.slice(0, 5) });
});

// 수기 한 줄
listings.post("/admin/listings/manual", async (c) => {
  const form = await c.req.formData();
  const g = (k: string) => String(form.get(k) ?? "").trim();
  const addr = g("addr");
  if (!addr) return c.redirect("/admin/listings?err=" + encodeURIComponent("지번·호수를 적어주세요."));
  const row: Record<string, string> = { "지번·호수": addr, "임대인 연락처": g("phone"), "기타 연락처": g("contacts"), "종류": g("kind"), "거래": g("deal"), "금액": g("price"), "이름": g("title"), "메모": g("memo") };
  for (const k of Object.keys(row)) if (!row[k]) delete row[k];
  const r = await ingest(c.env.DB, c.env.ADMIN_USER || "admin", g("site") || "임대인", "수기 입력", [row]);
  if (r.dup) return c.redirect("/admin/listings?err=" + encodeURIComponent(`중복: 같은 지번·호수에 같은 연락처가 이미 2건 있어 추가하지 않았습니다 (${r.dupList[0] || ""})`));
  return c.redirect("/admin/listings?added=" + (r.inserted ? 1 : 0) + "&site=" + encodeURIComponent(r.site));
});

/** 행 묶음을 upsert — 돌아오는 값: 구분, 추가/갱신 건수, 그 구분의 총 건수 */
export async function ingest(db: D1Database, username: string, siteHint: string, fileName: string, rowsIn: any[]) {
  await ensure(db);
  if (!rowsIn.length) return { site: cleanSite(siteHint) || "기타", inserted: 0, updated: 0, total: 0 };
  const cols = Object.keys(rowsIn[0] || {});
  const site = detectSite(cols, siteHint);
  const file = fileName.slice(0, 200);
  const at = nowIso();

  const stmts: D1PreparedStatement[] = [];
  const keys = new Set<string>();
  // 같은 지번·호수에 같은 연락처가 이미 2건 있으면 더 쌓지 않는다 (2026-10-09, 사용자: "석촌동 1-1 이 010-2222-2222 로 4개 중복 — 2개까지만")
  const DUP_MAX = 2;
  const dupList: string[] = []; let dup = 0;
  const seenCache = new Map<string, { addr: string; site: string; listing_no: string; deal: string }[]>();
  const sameUnitRows = async (digits: string) => {
    if (seenCache.has(digits)) return seenCache.get(digits)!;
    const { results } = await db.prepare("SELECT addr, site, listing_no, deal FROM listings WHERE REPLACE(REPLACE(phone, '-', ''), ' ', '') LIKE ? LIMIT 200").bind(`%${digits}%`).all();
    const rows = (results ?? []) as any[]; seenCache.set(digits, rows); return rows;
  };
  const batchUnits = new Map<string, number>();                      // 이번 묶음 안에서 같은 단위·연락처 몇 건 넣었는지
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
    const digits = phoneDigits(sum.phone);
    if (digits.length >= 9) {
      const u = unitKey(sum.addr);
      if (u.lot) {
        const same = (await sameUnitRows(digits)).filter((r) => { const k = unitKey(r.addr); return k.lot === u.lot && k.ho === u.ho; });
        const isUpdate = same.some((r) => r.site === site && r.listing_no === no && r.deal === sum.deal);   // 같은 매물번호면 갱신이지 중복이 아님
        const bkey = `${u.lot}|${u.ho}|${digits}`; const inBatch = batchUnits.get(bkey) || 0;
        if (!isUpdate && same.length + inBatch >= DUP_MAX) { dup++; if (dupList.length < 20) dupList.push(`${u.lot}${u.ho ? " " + u.ho + "호" : ""} · ${sum.phone}`); continue; }
        if (!isUpdate) batchUnits.set(bkey, inBatch + 1);
      }
    }
    stmts.push(db.prepare(
      `INSERT INTO listings (site, listing_no, url, username, file, addr, kind, deal, price, title, phone, memo, contacts, data, first_at, last_at, seen)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
       ON CONFLICT(site, listing_no, deal) DO UPDATE SET url = excluded.url, username = excluded.username, file = excluded.file,
         addr = excluded.addr, kind = excluded.kind, deal = excluded.deal, price = excluded.price, title = excluded.title,
         phone = CASE WHEN excluded.phone <> '' THEN excluded.phone ELSE listings.phone END,
         memo = CASE WHEN excluded.memo <> '' THEN excluded.memo ELSE listings.memo END,
         contacts = CASE WHEN excluded.contacts <> '' THEN excluded.contacts ELSE listings.contacts END,
         data = excluded.data, last_at = excluded.last_at, seen = listings.seen + 1`
    ).bind(site, no, sum.url, username, file, sum.addr, sum.kind, sum.deal, sum.price, sum.title, sum.phone, sum.memo, sum.contacts, json, at, at));
  }
  const before = (await db.prepare("SELECT COUNT(*) n FROM listings WHERE site = ?").bind(site).first<{ n: number }>())?.n ?? 0;
  for (let i = 0; i < stmts.length; i += 40) await db.batch(stmts.slice(i, i + 40));
  const after = (await db.prepare("SELECT COUNT(*) n FROM listings WHERE site = ?").bind(site).first<{ n: number }>())?.n ?? 0;
  const inserted = after - before;
  try {   // 되돌리기용: 이번에 새로 생긴 줄(first_at 이 이번 시각)
    const { results } = await db.prepare("SELECT id FROM listings WHERE file = ? AND first_at = ?").bind(file, at).all();
    const ids = (results ?? []).map((r: any) => r.id);
    await db.prepare("INSERT INTO listings_ops (at, kind, label, count, batch, ids) VALUES (?, 'ingest', ?, ?, ?, ?)").bind(at, `${file} (${site})`, stmts.length, "i" + Date.now().toString(36), JSON.stringify(ids)).run();
  } catch { /* 기록 실패는 무시 */ }
  return { site, inserted, updated: stmts.length - inserted, total: after, dup, dupList };
}

// 엑셀에 연락처 채우기: [{addr, ho}] → 같은 지번(+호수)의 임대인 연락처 (호수가 맞는 줄 우선, 없으면 그 지번의 아무 줄). 서로 다른 번호는 2개까지 ' / ' 로
listings.post("/admin/listings/match", async (c) => {
  const body: any = await c.req.json().catch(() => ({}));
  return c.json({ items: await matchUnits(c.env.DB, Array.isArray(body.items) ? body.items : []) });
});
/** [{addr, ho}] → [{lot, ho, phone, n}] — 어드민 매물 DB 탭과 직원 포털 '엑셀 연락처' 탭이 같이 쓴다 */
export async function matchUnits(db: D1Database, itemsIn: any[]) {
  await ensure(db);
  const items: any[] = itemsIn.slice(0, 2000);
  const byLot = new Map<string, any[]>();
  const out: any[] = items.map((it) => { const u = unitKey(s(it.addr), s(it.ho)); return { lot: u.lot, ho: u.ho, phone: "", n: 0 }; });
  for (const o of out) if (o.lot) { if (!byLot.has(o.lot)) byLot.set(o.lot, []); }
  for (const lot of byLot.keys()) {
    const { results } = await db.prepare("SELECT addr, phone FROM listings WHERE phone <> '' AND (addr GLOB ? OR addr GLOB ?) LIMIT 100").bind(`*[동리가읍면] ${lot.split(" ").slice(1).join(" ")}[^0-9호]*`, `*[동리가읍면] ${lot.split(" ").slice(1).join(" ")}`).all();
    byLot.set(lot, ((results ?? []) as any[]).filter((r) => unitKey(r.addr).lot === lot));
  }
  for (const o of out) {
    if (!o.lot) continue;
    const rows = byLot.get(o.lot) || [];
    const pick = o.ho ? rows.filter((r) => unitKey(r.addr).ho === o.ho) : rows;
    const use = pick.length ? pick : (o.ho ? [] : rows);              // 호수를 적었는데 그 호수 줄이 없으면 비워 둔다 (다른 호수 연락처를 섞지 않음)
    const phones: string[] = []; for (const r of use) { const p = s(r.phone); if (p && !phones.some((x) => phoneDigits(x) === phoneDigits(p))) phones.push(p); }
    o.phone = phones.slice(0, 2).join(" / "); o.n = use.length;
  }
  return out;
}

// 연락처·메모 수정 (표에서 칸을 클릭해 고친다)
listings.post("/admin/listings/:id/edit", async (c) => {
  await ensure(c.env.DB);
  const id = parseInt(c.req.param("id"), 10);
  const body: any = await c.req.json().catch(() => ({}));
  const sets: string[] = []; const binds: any[] = [];
  if (typeof body.phone === "string") { sets.push("phone = ?"); binds.push(body.phone.trim().slice(0, 120)); }
  if (typeof body.memo === "string") { sets.push("memo = ?"); binds.push(body.memo.trim().slice(0, 500)); }
  if (typeof body.contacts === "string") { sets.push("contacts = ?"); binds.push(body.contacts.trim().slice(0, 300)); }
  if (typeof body.addr === "string" && body.addr.trim()) { sets.push("addr = ?"); binds.push(body.addr.trim().slice(0, 200)); }
  if (!sets.length || !Number.isFinite(id)) return c.json({ success: false, message: "고칠 내용이 없습니다." }, 400);
  await c.env.DB.prepare(`UPDATE listings SET ${sets.join(", ")} WHERE id = ?`).bind(...binds, id).run();
  return c.json({ success: true });
});
/** where 조건에 맞는 줄을 휴지통에 복사한 뒤 지우고, 작업 기록을 남긴다 → batch */
async function trashDelete(db: D1Database, where: string, binds: any[], label: string): Promise<{ batch: string; n: number }> {
  const batch = "d" + Date.now().toString(36);
  const at = nowIso();
  const { results } = await db.prepare("SELECT * FROM listings" + where).bind(...binds).all();
  const rows = (results ?? []) as any[];
  for (let i = 0; i < rows.length; i += 40) {
    await db.batch(rows.slice(i, i + 40).map((r) => db.prepare("INSERT INTO listings_trash (batch, deleted_at, orig_id, row) VALUES (?, ?, ?, ?)").bind(batch, at, r.id, JSON.stringify(r))));
  }
  if (rows.length) await db.prepare("DELETE FROM listings" + where).bind(...binds).run();
  await db.prepare("INSERT INTO listings_ops (at, kind, label, count, batch) VALUES (?, 'delete', ?, ?, ?)").bind(at, label.slice(0, 120), rows.length, batch).run();
  return { batch, n: rows.length };
}
const LCOLS = ["site", "listing_no", "url", "username", "file", "addr", "kind", "deal", "price", "title", "data", "first_at", "last_at", "seen", "phone", "memo", "contacts"];
/** 휴지통 batch 복원 — 같은 (구분, 번호, 거래) 줄이 그새 다시 생겼으면 그 줄은 건너뛴다 */
async function restoreBatch(db: D1Database, batch: string): Promise<number> {
  const { results } = await db.prepare("SELECT orig_id, row FROM listings_trash WHERE batch = ?").bind(batch).all();
  let n = 0;
  for (const t of (results ?? []) as any[]) {
    let r: any; try { r = JSON.parse(t.row); } catch { continue; }
    const cols = ["id", ...LCOLS];
    const res = await db.prepare(`INSERT OR IGNORE INTO listings (${cols.join(", ")}) VALUES (${cols.map(() => "?").join(", ")})`).bind(t.orig_id, ...LCOLS.map((k) => r[k] ?? (k === "seen" ? 1 : k === "phone" || k === "memo" || k === "contacts" ? "" : null))).run();
    if (res.meta?.changes) n++;
  }
  await db.prepare("DELETE FROM listings_trash WHERE batch = ?").bind(batch).run();
  await db.prepare("UPDATE listings_ops SET undone = 1 WHERE batch = ?").bind(batch).run();
  await db.prepare("INSERT INTO listings_ops (at, kind, label, count, batch) VALUES (?, 'restore', ?, ?, ?)").bind(nowIso(), "삭제 되돌림", n, batch).run();
  return n;
}
// 체크한 줄 삭제 {ids}
listings.post("/admin/listings/delete-ids", async (c) => {
  await ensure(c.env.DB);
  const body: any = await c.req.json().catch(() => ({}));
  const ids: number[] = Array.isArray(body.ids) ? body.ids.map((x: any) => parseInt(x, 10)).filter((x: number) => x > 0).slice(0, 500) : [];
  if (!ids.length) return c.json({ success: false, message: "선택한 줄이 없습니다." }, 400);
  const r = await trashDelete(c.env.DB, ` WHERE id IN (${ids.map(() => "?").join(",")})`, ids, `선택 삭제 ${ids.length}줄`);
  return c.json({ success: true, deleted: r.n, batch: r.batch });
});
// 되돌리기 {batch} — 삭제는 복원, 붙여넣기·엑셀은 그때 새로 들어온 줄을 지움(갱신된 줄은 그대로)
listings.post("/admin/listings/undo", async (c) => {
  await ensure(c.env.DB);
  const body: any = await c.req.json().catch(() => ({}));
  const op: any = await c.env.DB.prepare("SELECT * FROM listings_ops WHERE batch = ? AND undone = 0 AND kind IN ('delete','ingest') ORDER BY id DESC LIMIT 1").bind(s(body.batch)).first();
  if (!op) return c.json({ success: false, message: "되돌릴 작업이 없거나 이미 되돌렸습니다." }, 404);
  if (op.kind === "delete") { const n = await restoreBatch(c.env.DB, op.batch); return c.json({ success: true, kind: "delete", restored: n }); }
  if (op.kind === "ingest") {
    let ids: number[] = []; try { ids = JSON.parse(op.ids || "[]"); } catch { /* */ }
    if (!ids.length) return c.json({ success: false, message: "그 작업으로 새로 들어온 줄이 없어 지울 게 없습니다 (갱신만 된 줄은 되돌리지 않습니다)." });
    const r = await trashDelete(c.env.DB, ` WHERE id IN (${ids.map(() => "?").join(",")})`, ids, `되돌림: ${op.label}`);
    await c.env.DB.prepare("UPDATE listings_ops SET undone = 1 WHERE id = ?").bind(op.id).run();
    return c.json({ success: true, kind: "ingest", deleted: r.n, batch: r.batch });
  }
  return c.json({ success: false, message: "되돌릴 수 없는 종류입니다." });
});

listings.post("/admin/listings/:id/delete", async (c) => {
  await ensure(c.env.DB);
  await trashDelete(c.env.DB, " WHERE id = ?", [parseInt(c.req.param("id"), 10)], "한 줄 삭제");
  const back = c.req.header("referer") || "/admin/listings";
  return c.redirect(back.includes("/admin/listings") ? back : "/admin/listings");
});

// ---------------------------------------------------------------- 필터
type Filter = { site: string; q: string; from: string; to: string; user: string; file: string; deal: string };
function readFilter(c: any): Filter {
  const g = (k: string) => (c.req.query(k) ?? "").toString().trim();
  return { site: g("site"), q: g("q"), from: g("from"), to: g("to"), user: g("user"), file: g("file"), deal: g("deal") };
}
const kstDayStart = (d: string) => new Date(d + "T00:00:00+09:00").toISOString();
const kstDayEnd = (d: string) => new Date(d + "T23:59:59.999+09:00").toISOString();
function whereOf(f: Filter): [string, any[]] {
  const w: string[] = []; const b: any[] = [];
  if (f.site) { w.push("site = ?"); b.push(f.site); }
  if (f.user) { w.push("username = ?"); b.push(f.user); }
  if (f.file) { w.push("file = ?"); b.push(f.file); }
  if (f.deal && ["매매", "전세", "월세"].includes(f.deal)) { w.push("(deal LIKE ? OR price LIKE ?)"); b.push(`%${f.deal}%`, `%${f.deal} %`); }   // 금액에 같이 적힌 거래도
  if (f.from && /^\d{4}-\d{2}-\d{2}$/.test(f.from)) { w.push("last_at >= ?"); b.push(kstDayStart(f.from)); }
  if (f.to && /^\d{4}-\d{2}-\d{2}$/.test(f.to)) { w.push("last_at <= ?"); b.push(kstDayEnd(f.to)); }
  if (f.q) {
    const like = `%${f.q}%`; const digits = f.q.replace(/\D/g, "");
    w.push("(addr LIKE ? OR phone LIKE ? OR contacts LIKE ? OR memo LIKE ? OR title LIKE ? OR listing_no LIKE ? OR price LIKE ? OR kind LIKE ? OR data LIKE ?" + (digits.length >= 4 ? " OR REPLACE(REPLACE(phone, '-', ''), ' ', '') LIKE ? OR REPLACE(REPLACE(contacts, '-', ''), ' ', '') LIKE ?" : "") + ")");
    b.push(like, like, like, like, like, like, like, like, like); if (digits.length >= 4) b.push(`%${digits}%`, `%${digits}%`);
  }
  return [w.length ? " WHERE " + w.join(" AND ") : "", b];
}
const qs = (f: Filter, extra: Record<string, any> = {}) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries({ ...f, ...extra })) if (v !== "" && v != null) p.set(k, String(v));
  return p.toString();
};
const showNo = (no: string) => (String(no || "").startsWith("h:") ? "" : no);   // 번호가 없던 행은 내용 해시가 키 — 화면·엑셀엔 빈칸
export const kst = (iso: string) => { try { return new Date(iso).toLocaleString("ko-KR", { timeZone: "Asia/Seoul", hour12: false, year: "2-digit", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }); } catch { return iso; } };

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
  const ops = (await c.env.DB.prepare("SELECT at, kind, label, count, batch, undone FROM listings_ops WHERE kind IN ('delete','ingest','restore') ORDER BY id DESC LIMIT 6").all()).results ?? [];
  const siteKeys = Array.from(new Set([...bySite.map((r: any) => String(r.site)), ...(f.site ? [f.site] : [])]));
  const pages = Math.max(1, Math.ceil(total / PER));
  const notice = c.req.query("restored") != null ? `되돌렸습니다: 복원 ${c.req.query("restored")}건${Number(c.req.query("undeleted")) ? ` · 지움 ${c.req.query("undeleted")}건` : ""}` : c.req.query("deleted") != null ? `삭제했습니다: ${c.req.query("deleted")}건 (위 "최근 작업"에서 되돌릴 수 있습니다)` : c.req.query("added") != null ? (c.req.query("added") === "1" ? "한 줄 추가했습니다." : "이미 있는 줄이라 갱신했습니다.") : c.req.query("err") || "";

  const rows = (results ?? []).map((r: any) => {
    let data: Record<string, string> = {}; try { data = JSON.parse(r.data); } catch {}
    const detail = Object.entries(data).filter(([, v]) => s(v)).map(([k, v]) => html`<div class="kv"><b>${k}</b><span>${v}</span></div>`);
    return html`<tr data-id="${r.id}">
      <td class="ck"><input type="checkbox" class="rowck" value="${r.id}"></td>
      <td class="addr ed" data-f="addr" title="클릭해서 고치기">${r.addr ?? ""}</td>
      <td class="phone ed" data-f="phone" title="클릭해서 고치기">${r.phone ?? ""}</td>
      <td class="small contacts ed" data-f="contacts" title="임차인·세입자·관리·중개 등 (클릭해서 고치기)">${r.contacts ?? ""}</td>
      <td class="small">${r.kind ?? ""}</td>
      <td class="small">${dealsOf(r.deal, r.price)}</td>
      <td class="mono small">${r.price ?? ""}</td>
      <td class="small ttl">${r.title ?? ""}</td>
      <td class="small memo ed" data-f="memo" title="클릭해서 고치기">${r.memo ?? ""}</td>
      <td class="mono small" title="처음 ${kst(r.first_at)} · ${r.seen}회 · ${siteLabel(r.site)} · ${r.username} · ${r.file ?? ""}">${kst(r.last_at)}${r.seen > 1 ? html` <span class="seen">×${r.seen}</span>` : ""}</td>
      <td class="small muted src"><a href="/admin/listings?${raw(qs({ site: "", q: "", from: "", to: "", user: "", file: r.file ?? "" }))}" title="${r.file ?? ""} · ${siteLabel(r.site)} · ${r.username} — 이 파일에서 온 줄만 보기">${(r.file ?? "").length > 18 ? (r.file ?? "").slice(0, 17) + "…" : (r.file ?? "")}</a></td>
      <td class="nowrap"><details class="det"><summary>상세</summary><div class="detbox">${r.url ? html`<div class="kv"><b>링크</b><span><a href="${r.url}" target="_blank" rel="noopener">${r.url}</a></span></div>` : ""}${detail}</div></details>
        <form method="post" action="/admin/listings/${r.id}/delete" class="inline-form" onsubmit="return confirm('이 줄을 삭제할까요?')"><button type="submit" class="x" title="삭제">✕</button></form></td>
    </tr>`;
  });
  const siteOpts = siteKeys.map((k) => html`<option value="${k}" ${f.site === k ? "selected" : ""}>${siteLabel(k)}</option>`);
  const userOpts = users.map((u: any) => html`<option value="${u.username}" ${f.user === u.username ? "selected" : ""}>${u.username}</option>`);
  const pageLink = (p: number, label: string) => html`<a class="btn btn-sm" href="/admin/listings?${raw(qs(f, { page: p }))}">${label}</a>`;

  const body = html`
    <div class="page-head">
      <h1>매물·임대인 DB</h1>
      <span class="small muted">전체 ${bySite.reduce((a: number, r: any) => a + r.n, 0)}건 (${bySite.map((r: any) => `${siteLabel(r.site)} ${r.n}`).join(" · ") || "없음"})</span>
    </div>
    ${notice ? html`<div class="notice">${notice}</div>` : ""}
    ${ops.length ? html`<div class="opsbar"><b>최근 작업</b> ${ops.map((o: any) => html`<span class="chip ${o.undone ? "done" : ""}">${o.kind === "delete" ? "삭제" : o.kind === "ingest" ? "넣기" : "복원"} ${o.count}건 · ${o.label ?? ""} <em>${kst(o.at)}</em>${o.undone ? html` <i>되돌림</i>` : (o.kind === "delete" || o.kind === "ingest") ? html` <button type="button" class="undo" data-batch="${o.batch}" title="${o.kind === "delete" ? "지운 줄을 다시 살립니다" : "그때 새로 들어온 줄을 지웁니다 (갱신된 줄은 그대로)"}">${o.kind === "delete" ? "되돌리기" : "넣은 줄 지우기"}</button>` : ""}</span>`)}</div>` : ""}
    <div class="lookup">
      <div class="lkrow"><b>지번 조회</b>
        <input type="text" id="lkq" placeholder="지번만 치세요 — 예: 논현동 124-12 (호수·전화번호도 됨)" value="${c.req.query("jibun") ?? ""}" autofocus autocomplete="off">
        <button type="button" class="btn btn-primary" id="lkgo">찾기</button>
        <span class="small muted" id="lkmsg">치는 대로 바로 찾습니다. 결과의 연락처·메모 칸도 클릭해서 고칠 수 있습니다.</span>
      </div>
      <div id="lkres"></div>
    </div>
    <form class="upbox manual" method="post" action="/admin/listings/manual">
      <b>수기 입력</b>
      <input type="text" name="addr" placeholder="지번·호수 (예: 논현동 124-12 302호)" required style="min-width:260px">
      <input type="text" name="phone" placeholder="임대인 연락처" style="min-width:150px">
      <input type="text" name="contacts" placeholder="임차인·관리 등 (예: 임차인 010-… 관리 02-…)" style="min-width:230px">
      <input type="text" name="kind" placeholder="종류" style="width:90px">
      <input type="text" name="deal" placeholder="거래" style="width:70px">
      <input type="text" name="price" placeholder="금액" style="width:110px">
      <input type="text" name="title" placeholder="이름" style="width:90px">
      <input type="text" name="memo" placeholder="메모" style="min-width:160px">
      <input type="text" name="site" placeholder="구분" value="임대인" style="width:90px">
      <button type="submit" class="btn btn-primary">추가</button>
    </form>
    <div class="upbox">
      <b>엑셀 올리기</b>
      <input type="text" id="upsite" placeholder="구분 (예: 임대인)" value="임대인" title="네이버·당근·온하우스 수집기 엑셀은 열 이름으로 자동 판별됩니다">
      <input type="file" id="upfile" accept=".xlsx,.xls,.csv" multiple>
      <button type="button" class="btn btn-primary" id="upgo">올리기</button>
      <span class="small muted" id="upmsg">열 이름 줄은 자동으로 찾습니다(위에 제목 줄이 있어도 됨). 지번·주소와 임대인 연락처는 맨 앞에, 임차인·세입자·관리·중개 번호(010·02·0502…)는 그 옆 칸에 정리됩니다. 같은 행을 다시 올리면 중복 없이 갱신됩니다.</span>
    </div>
    <div class="upbox pastebox">
      <b>텍스트 붙여넣기</b>
      <input type="text" id="pssite" placeholder="구분" value="임대인" style="width:90px">
      <textarea id="pstext" rows="4" placeholder="카톡·메모·엑셀에서 복사한 글을 그대로 붙여넣으세요. 한 줄 = 매물 하나.&#10;예) 논현동 124-12 302호 010-1234-5678 월세 5000/150 빌라 김사장님&#10;    역삼동 777-2 2층 02-555-1234 임차인 010-2222-3333 매매 15억 상가"></textarea>
      <button type="button" class="btn btn-primary" id="psgo">넣기</button>
      <span class="small muted" id="psmsg">지번·호수, 임대인 연락처(첫 번호)·그 밖의 번호, 거래·금액, 종류, 이름을 줄마다 알아서 찾아 칸에 넣고, 못 알아본 글은 메모에 남깁니다. 지번이 없는 줄은 건너뜁니다.</span>
    </div>
    <div class="upbox fillbox" id="fillbox">
      <b>엑셀에 임대인 연락처 채우기</b>
      <span class="small muted">매일 뽑는 수집 엑셀을 여기에 끌어다 놓거나 고르면, 줄마다 지번(+호수)으로 DB를 찾아 <b>링크 바로 옆에 "임대인 연락처(DB)" 칸</b>을 끼워 넣고 다시 내려받습니다. 나머지 칸은 그대로, 없는 건 빈칸.</span>
      <input type="file" id="fillfile" accept=".xlsx,.xlsm" multiple>
      <button type="button" class="btn btn-primary" id="fillgo">연락처 채워서 내려받기</button>
      <textarea id="filltext" rows="2" placeholder="또는 지번을 글로 — 한 줄에 하나 (예: 석촌동 1-1 302호)"></textarea>
      <button type="button" class="btn" id="filltxt">글로 찾기</button>
      <span class="small muted" id="fillmsg"></span>
      <div id="fillout" style="width:100%"></div>
    </div>
    <form class="search-form lf" method="get" id="lf">
      <select name="site"><option value="">전체 구분</option>${siteOpts}</select>
      <select name="user"><option value="">전체 계정</option>${userOpts}</select>
      <select name="deal"><option value="">전체 거래</option>${raw(["매매", "전세", "월세"].map((d) => `<option value="${d}"${f.deal === d ? " selected" : ""}>${d}</option>`).join(""))}</select>
      <input type="text" name="q" placeholder="지번·연락처·이름·메모·내용 검색" value="${f.q}">
      <input type="date" name="from" value="${f.from}" title="올린 날 시작"> ~ <input type="date" name="to" value="${f.to}" title="올린 날 끝">
      ${f.file ? html`<input type="hidden" name="file" value="${f.file}"><span class="chip">파일: ${f.file} <a href="/admin/listings?${raw(qs({ ...f, file: "" }))}">✕</a></span>` : ""}
      <button type="submit" class="btn">검색</button>
      <a class="btn" href="/admin/listings">초기화</a>
      <button type="button" class="btn btn-primary" id="xl" ${total ? "" : "disabled"}>엑셀 다운로드 (${total}건)</button>
      <button type="button" class="btn btn-danger" id="delsel" disabled>선택 삭제 (0)</button>
      <button type="button" class="btn btn-danger" id="del" ${total ? "" : "disabled"}>조건 삭제</button>
    </form>
    <div id="xlmsg" class="small muted" style="margin:-8px 0 12px"></div>
    ${recent.length ? html`<div class="recent"><b>최근 올린 파일</b> ${recent.map((r: any) => html`<a class="chip" href="/admin/listings?${raw(qs({ site: "", q: "", from: "", to: "", user: "", file: r.file }))}" title="${r.username} · ${kst(r.t)}">${siteLabel(r.site)} · ${r.file} <em>${r.n}</em></a>`)}</div>` : ""}
    <table class="user-table lt">
      <thead><tr><th class="ck"><input type="checkbox" id="ckall" title="이 페이지 전부 선택"></th><th>지번·호수</th><th>임대인 연락처</th><th>임차인·관리 등</th><th>종류</th><th>거래</th><th>금액</th><th>이름·제목</th><th>메모</th><th>올린 날</th><th>출처 파일</th><th></th></tr></thead>
      <tbody>${rows.length ? rows : html`<tr><td colspan="12" class="empty">${total ? "이 페이지에는 없습니다." : "아직 비어 있습니다. 위에서 수기로 넣거나 엑셀을 올리면 쌓입니다."}</td></tr>`}</tbody>
    </table>
    <div class="pager">${page > 1 ? pageLink(page - 1, "‹ 이전") : ""}<span class="small">${page} / ${pages} 페이지 · ${total}건</span>${page < pages ? pageLink(page + 1, "다음 ›") : ""}</div>
    <form method="post" action="/admin/listings/delete" id="delf" style="display:none">
      ${Object.entries(f).map(([k, v]) => html`<input type="hidden" name="${k}" value="${v}">`)}
    </form>
    <style>${raw(LT_STYLE)}</style>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/exceljs/4.4.0/exceljs.min.js"></script>
    <script>var LT_QS=${raw(JSON.stringify(qs(f)))}, LT_TOTAL=${total}, LT_SITE=${raw(JSON.stringify(f.site ? siteLabel(f.site) : "전체"))};${raw(LT_JS)}</script>`;
  return c.html(layout("매물·임대인 DB", body));
});

// 지번 조회: "논현동 124-12", "논현동124-12 302", "역삼동 777" 처럼 치면 띄어쓰기를 무시하고 낱말이 모두 들어간 주소를 찾는다 (전화번호 숫자로도 찾힘)
export function lookupWhere(q: string, allowPhone = true): [string, any[]] {
  const toks = q.trim().split(/\s+/).map((t) => t.replace(/번지$/, "")).filter(Boolean).slice(0, 6);
  if (!toks.length) return ["", []];
  const digits = allowPhone ? q.replace(/\D/g, "") : "";
  const w: string[] = []; const b: any[] = [];
  for (const t of toks) { w.push("REPLACE(REPLACE(addr, ' ', ''), ',', '') LIKE ?"); b.push(`%${t.replace(/,/g, "")}%`); }
  let sql = "(" + w.join(" AND ") + ")";
  if (digits.length >= 7 && toks.length === 1) { sql += " OR REPLACE(REPLACE(phone, '-', ''), ' ', '') LIKE ? OR REPLACE(REPLACE(contacts, '-', ''), ' ', '') LIKE ?"; b.push(`%${digits}%`, `%${digits}%`); }
  return [" WHERE " + sql, b];
}
listings.get("/admin/listings/lookup.json", async (c) => {
  await ensure(c.env.DB);
  const q = (c.req.query("q") ?? c.req.query("jibun") ?? "").toString().trim();
  if (q.length < 2) return c.json({ q, rows: [], count: 0 });
  const [where, binds] = lookupWhere(q);
  const { results } = await c.env.DB.prepare("SELECT id, site, addr, phone, contacts, memo, kind, deal, price, title, url, last_at FROM listings" + where + " ORDER BY addr, id LIMIT 300").bind(...binds).all();
  const rows = (results ?? []).map((r: any) => ({ id: r.id, site: siteLabel(r.site), addr: r.addr, phone: r.phone, contacts: r.contacts, memo: r.memo, kind: r.kind, deal: dealsOf(r.deal, r.price), price: r.price, title: r.title, url: r.url, last_at: kst(r.last_at) }));
  return c.json({ q, count: rows.length, rows });
});

// 필터 결과를 id 오름차순으로 (after 커서) — 엑셀 만들 때 브라우저가 끝까지 긁어 간다
listings.get("/admin/listings/rows.json", async (c) => {
  await ensure(c.env.DB);
  const f = readFilter(c);
  const after = parseInt(c.req.query("after") ?? "0", 10) || 0;
  const limit = Math.min(2000, Math.max(1, parseInt(c.req.query("limit") ?? "1000", 10) || 1000));
  const [where, binds] = whereOf(f);
  const { results } = await c.env.DB.prepare("SELECT id, site, listing_no, url, username, file, addr, phone, contacts, memo, kind, deal, price, title, first_at, last_at, seen, data FROM listings" + (where ? where + " AND" : " WHERE") + " id > ? ORDER BY id LIMIT ?").bind(...binds, after, limit).all();
  const rows = (results ?? []).map((r: any) => ({ id: r.id, site: siteLabel(r.site), no: showNo(r.listing_no), url: r.url, username: r.username, file: r.file, addr: r.addr, phone: r.phone, contacts: r.contacts, memo: r.memo, kind: r.kind, deal: dealsOf(r.deal, r.price), price: r.price, title: r.title, first_at: kst(r.first_at), last_at: kst(r.last_at), seen: r.seen, data: (() => { try { return JSON.parse(r.data); } catch { return {}; } })() }));
  return c.json({ rows, next: rows.length === limit ? rows[rows.length - 1].id : null });
});

listings.post("/admin/listings/delete", async (c) => {
  await ensure(c.env.DB);
  const form = await c.req.formData();
  const g = (k: string) => String(form.get(k) ?? "").trim();
  const f: Filter = { site: g("site"), q: g("q"), from: g("from"), to: g("to"), user: g("user"), file: g("file") };
  const [where, binds] = whereOf(f);
  const r = await trashDelete(c.env.DB, where, binds, "조건 삭제" + (f.file ? " (파일 " + f.file + ")" : f.q ? " (검색 " + f.q + ")" : f.site ? " (구분 " + f.site + ")" : ""));
  return c.redirect("/admin/listings?" + qs({ site: f.site, q: "", from: "", to: "", user: "", file: "" }) + "&deleted=" + r.n);
});

const LT_STYLE = `
.lf{flex-wrap:wrap;align-items:center}
.lf select,.lf input{display:inline-block;width:auto;margin:0;padding:8px 10px;border-radius:8px;border:1px solid var(--border);background:var(--input);color:var(--text);font-size:13px}
.lf input[type=text]{min-width:260px}
.muted{color:var(--muted)}
.chip{display:inline-flex;gap:6px;align-items:center;padding:4px 10px;border-radius:999px;border:1px solid var(--border);background:var(--soft);font-size:12px;color:var(--text);margin:2px 4px 2px 0}
.chip em{font-style:normal;color:var(--accent);font-weight:600}
.recent{margin:0 0 14px;font-size:13px;color:var(--muted);line-height:2}
.notice{background:var(--soft);border:1px solid var(--border);border-radius:10px;padding:10px 14px;margin-bottom:14px;font-size:13px;color:var(--accent-dark)}
.lt td{max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.lt td.addr{font-weight:700;color:var(--accent-dark);max-width:320px}
.lt td.phone{font-family:Consolas,monospace;font-weight:600;min-width:130px}
.lt td.memo{max-width:180px}
.lt td.contacts,#lkres td.contacts{max-width:230px;white-space:normal;font-size:12px;line-height:1.5;min-width:120px}
.lt td.ttl{max-width:160px}
.lt td.nowrap{white-space:nowrap}
.lt td.ed{cursor:text}
.lt td.ed:hover{background:var(--soft)}
.lt td.ed input{width:100%;box-sizing:border-box;padding:4px 6px;border:1px solid var(--accent);border-radius:6px;font-size:13px;background:#fff;color:var(--text)}
.seen{color:var(--warn);font-size:10px}
.det{display:inline-block;margin-right:6px}
.det summary{cursor:pointer;color:var(--accent);font-size:12px;list-style:none}
.detbox{position:absolute;z-index:5;right:24px;max-width:640px;max-height:420px;overflow:auto;background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:12px 14px;box-shadow:0 8px 30px rgba(230,100,150,.25);white-space:normal}
.kv{display:grid;grid-template-columns:120px 1fr;gap:8px;font-size:12px;padding:3px 0;border-bottom:1px solid var(--border)}
.kv b{color:var(--muted);font-weight:600}
.kv span{white-space:pre-wrap;word-break:break-all}
.x{border:0;background:transparent;color:var(--muted);cursor:pointer;font-size:13px;padding:2px 4px}
.x:hover{color:var(--danger)}
.pager{display:flex;gap:12px;align-items:center;justify-content:center;margin:16px 0}
.upbox{display:flex;flex-wrap:wrap;gap:10px;align-items:center;background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:12px 16px;margin-bottom:12px;font-size:13px}
.upbox b{color:var(--accent-dark)}
.pastebox textarea{flex:1;min-width:280px;padding:8px 10px;border-radius:8px;border:1px solid var(--border);background:var(--input);color:var(--text);font-size:12.5px;font-family:inherit;margin:0}
.lt td.src{max-width:130px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:11.5px}
.lt td.ck,.lt th.ck{width:30px;text-align:center;padding:4px}
.lt .rowck,#ckall{width:20px;height:20px;cursor:pointer;accent-color:var(--accent);margin:0}
.opsbar{margin:0 0 12px;font-size:12.5px;color:var(--muted);line-height:2}
.opsbar .chip.done{opacity:.55}
.opsbar .undo{border:1px solid var(--accent);background:#fff;color:var(--accent-dark);border-radius:999px;padding:1px 9px;font-size:11.5px;cursor:pointer;margin-left:4px}
.opsbar i{font-style:normal;color:var(--ok);font-size:11.5px}
.lt td.src a{color:var(--accent-dark)}
.upbox input[type=text]{width:140px;padding:8px 10px;border-radius:8px;border:1px solid var(--border);background:var(--input);color:var(--text);margin:0;display:inline-block}
.upbox input[type=file]{color:var(--muted);font-size:12px;display:inline-block;width:auto;margin:0}
.fillbox{border:2px dashed var(--accent);background:linear-gradient(135deg,#fff0f6,#fff)}
.fillbox.drag{background:#ffe3ee}
.fillbox textarea{flex:1;min-width:220px;padding:8px 10px;border-radius:8px;border:1px solid var(--border);background:var(--input);color:var(--text);font-size:13px;margin:0}
#fillout table{width:100%;border-collapse:collapse;background:#fff;border:1px solid var(--border);border-radius:8px;overflow:hidden;margin-top:6px}
#fillout th,#fillout td{padding:6px 9px;border-bottom:1px solid #fbe3ec;font-size:12.5px;text-align:left}
#fillout th{background:var(--soft);color:var(--accent-dark)}
.status-pink{background:rgba(255,92,154,.15);color:var(--accent-dark)}
.lookup{background:linear-gradient(135deg,#fff0f6,#ffffff);border:2px solid var(--accent);border-radius:14px;padding:14px 16px;margin-bottom:14px;box-shadow:0 8px 28px rgba(255,92,154,.12)}
.lkrow{display:flex;flex-wrap:wrap;gap:10px;align-items:center;font-size:13px}
.lkrow b{color:var(--accent-dark);font-size:15px}
.lkrow input{display:inline-block;width:auto;min-width:340px;margin:0;padding:11px 14px;font-size:15px;border:1px solid var(--border);border-radius:10px;background:#fff;color:var(--text)}
#lkres{margin-top:10px}
#lkres table{width:100%;border-collapse:collapse;background:#fff;border:1px solid var(--border);border-radius:10px;overflow:hidden}
#lkres th,#lkres td{padding:8px 10px;border-bottom:1px solid #fbe3ec;font-size:13px;text-align:left;white-space:nowrap;max-width:260px;overflow:hidden;text-overflow:ellipsis}
#lkres th{background:var(--soft);color:var(--accent-dark);font-weight:700}
#lkres td.addr{font-weight:700;color:var(--accent-dark);max-width:340px}
#lkres td.phone{font-family:Consolas,monospace;font-weight:700;font-size:14px;min-width:140px}
#lkres td.ed{cursor:text}
#lkres td.ed:hover{background:var(--soft)}
#lkres td.ed input{width:100%;box-sizing:border-box;padding:4px 6px;border:1px solid var(--accent);border-radius:6px;font-size:13px;background:#fff;color:var(--text)}
#lkres .lknone{color:var(--muted);font-size:13px;padding:6px 2px}
#lkres .lkmore{color:var(--muted);font-size:12px;padding:6px 2px}
`;

// 브라우저 쪽: 헤더 줄 찾기 → 올리기 / 칸 클릭 수정 / 엑셀 만들기(지번·연락처가 맨 앞) / 조건 삭제
const LT_JS = `
(function(){
  var $=function(i){return document.getElementById(i)};
  // 열 이름 줄: 비어있지 않은 칸이 3개 이상이고 그 90% 가 '숫자 없는 20자 이하 글자' 이며 열 이름 낱말이 2개 이상 → 헤더.
  //   팀에서 여러 번 내려받아 이어붙인 파일은 중간에 헤더 줄이 또 나오므로(열 구성이 달라짐) 그때마다 열 이름을 바꿔 읽는다.
  var HW=['매물','주소','연락처','임대인','번호','거래','월세','전세','매매','종류','이름','URL','등록','확인','지번','호수','면적','금액','메모','비고','성명','전화','건물','층','옵션','제목'];
  function isHeader(row){
    var cells=(row||[]).map(function(v){return String(v==null?'':v).trim()}).filter(Boolean); if(cells.length<3) return false;
    var txt=cells.filter(function(v){return v.length<=20&&!/\\d/.test(v)}).length; if(txt<cells.length*0.9) return false;
    var hits=0; HW.forEach(function(w){ if(cells.some(function(v){return v.indexOf(w)>=0})) hits++; }); return hits>=2;
  }
  function findHeader(aoa){
    for(var i=0;i<Math.min(aoa.length,15);i++) if(isHeader(aoa[i])) return i;
    var sc=[]; for(var i=0;i<Math.min(aoa.length,15);i++){ var seen={},n=0; (aoa[i]||[]).forEach(function(v){ v=String(v==null?'':v).trim(); if(!v||v.length>20||/^https?:/i.test(v)||/^[\\d,.\\s/-]+$/.test(v)||seen[v]) return; seen[v]=1; n++; }); sc.push(n); }
    var mx=Math.max.apply(null,sc.concat([0])); if(mx<2) return 0;
    for(var j=0;j<sc.length;j++){ if(sc[j]>=3 && sc[j]>=mx*0.6) return j; }
    return 0;
  }
  $('psgo').onclick=async function(){
    var text=$('pstext').value; if(!text.trim()){ $('psmsg').textContent='붙여넣을 글이 없습니다'; return; }
    $('psgo').disabled=true; $('psmsg').textContent='정리해서 넣는 중…';
    try{
      var r=await fetch('/admin/listings/paste',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({site:$('pssite').value,text:text})}).then(function(x){return x.json()});
      if(!r.success){ $('psmsg').textContent=r.message||'실패'; $('psgo').disabled=false; return; }
      $('psmsg').textContent='넣었습니다: 추가 '+r.inserted+'건 · 갱신 '+r.updated+'건'+(r.skipped&&r.skipped.length?' · 지번 없어 건너뜀 '+r.skipped.length+'줄':'')+' — 잠시 뒤 표가 새로 뜹니다';
      setTimeout(function(){ location.href='/admin/listings?file='+encodeURIComponent('텍스트 붙여넣기'); },900);
    }catch(e){ $('psmsg').textContent='오류: '+e.message; $('psgo').disabled=false; }
  };
  $('upgo').onclick=async function(){
    var files=$('upfile').files; var site=$('upsite').value.trim(); var msg=$('upmsg');
    if(!files.length){ msg.textContent='엑셀 파일을 고르세요.'; return; }
    $('upgo').disabled=true; var totalIns=0,totalUpd=0,totalDup=0,dupList=[],fail=[];
    for(var fi=0;fi<files.length;fi++){
      var f=files[fi];
      try{
        var wb=XLSX.read(await f.arrayBuffer(),{type:'array',cellDates:true});
        var ws=wb.Sheets[wb.SheetNames[0]];
        var aoa=XLSX.utils.sheet_to_json(ws,{header:1,raw:false,defval:''});
        var hi=findHeader(aoa);
        var hdr=(aoa[hi]||[]).map(function(h){return String(h==null?'':h).trim()});
        var rows=[];
        for(var i=hi+1;i<aoa.length;i++){
          if(isHeader(aoa[i])){ hdr=aoa[i].map(function(h){return String(h==null?'':h).trim()}); continue; }   // 블록이 바뀜
          var o={},any=false; hdr.forEach(function(h,j){ if(!h) return; var v=aoa[i][j]; if(v==null) return; v=String(v).trim(); if(v){ o[h]=v; any=true; } }); if(any) rows.push(o); }
        if(!rows.length){ fail.push(f.name+' (행 없음)'); continue; }
        for(var k=0;k<rows.length;k+=500){
          msg.textContent='올리는 중… '+f.name+' '+Math.min(k+500,rows.length)+'/'+rows.length+'행';
          var r=await fetch('/admin/listings/upload',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({site:site,file:f.name,rows:rows.slice(k,k+500)})}).then(function(x){return x.json()});
          if(!r.success){ fail.push(f.name+' ('+(r.message||'오류')+')'); break; }
          totalIns+=r.inserted; totalUpd+=r.updated; totalDup+=(r.dup||0); (r.dupList||[]).forEach(function(d){ if(dupList.length<20) dupList.push(d); });
        }
      }catch(e){ fail.push(f.name+' ('+e.message+')'); }
    }
    msg.textContent='완료: 추가 '+totalIns+'건 · 갱신 '+totalUpd+'건'+(totalDup?' · 중복으로 건너뜀 '+totalDup+'건':'')+(fail.length?' · 실패: '+fail.join(', '):'')+' — 잠시 후 목록을 새로 불러옵니다.';
    $('upgo').disabled=false;
    if(totalDup){ alert('중복 '+totalDup+'건은 넣지 않았습니다 — 같은 지번·호수에 같은 연락처가 이미 2건 있는 줄입니다.'+String.fromCharCode(10)+dupList.join(String.fromCharCode(10))); }
    if(totalIns||totalUpd) setTimeout(function(){ location.href='/admin/listings'; },1500);
  };
  // ── 엑셀에 임대인 연락처 채우기: ExcelJS 로 서식·링크 그대로 두고 링크 열 옆에 열 하나만 끼운다
  var ADDR_COLS=['세부주소','지번주소','전체주소','주소_호실','지번·호수','지번','주소','소재지'], HO_COLS=['호수','호실','호'], LINK_COLS=['매물번호','매물_URL','URL','링크','url'];
  function hdrIdx(hdr, names){ for(var i=0;i<names.length;i++){ var j=hdr.findIndex(function(h){return String(h||'').trim()===names[i]}); if(j>=0) return j; } return -1; }
  async function matchItems(items){ var out=[]; for(var i=0;i<items.length;i+=500){ var r=await fetch('/admin/listings/match',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({items:items.slice(i,i+500)})}).then(function(x){return x.json()}); out=out.concat(r.items||[]); } return out; }
  async function fillWorkbook(file){
    var wb=new ExcelJS.Workbook(); await wb.xlsx.load(await file.arrayBuffer());
    var total=0, hit=0;
    for(var si=0; si<wb.worksheets.length; si++){
      var ws=wb.worksheets[si]; var rowsV=[]; ws.eachRow({includeEmpty:true},function(row,n){ rowsV[n]=row.values.slice(1).map(function(v){ return v&&typeof v==='object'?(v.text||v.result||v.hyperlink||(v.richText?v.richText.map(function(x){return x.text}).join(''):'')):v; }); });
      var hdrN=-1; for(var n=1;n<rowsV.length&&n<=15;n++){ if(isHeader(rowsV[n]||[])){ hdrN=n; break; } }
      if(hdrN<0) continue;
      var hdr=(rowsV[hdrN]||[]).map(function(h){return String(h==null?'':h).trim()});
      var li=hdrIdx(hdr,LINK_COLS); if(li<0){ li=hdr.findIndex(function(h,j){ return rowsV.slice(hdrN+1,hdrN+6).some(function(r){ return /^https?:\\/\\//.test(String((r||[])[j]||'')); }); }); }
      var ai=hdrIdx(hdr,ADDR_COLS), hi=hdrIdx(hdr,HO_COLS);
      if(ai<0){ continue; }
      var insertAt=(li>=0?li:ai)+2;   // ExcelJS 는 1부터, '옆 칸' 이므로 +2
      var items=[], rowNos=[];
      for(var n=hdrN+1;n<rowsV.length;n++){ var r=rowsV[n]||[]; if(isHeader(r)){ continue; } var addr=String(r[ai]==null?'':r[ai]).trim(); if(!addr) { items.push({addr:'',ho:''}); rowNos.push(n); continue; } items.push({addr:addr, ho:hi>=0?String(r[hi]==null?'':r[hi]).trim():''}); rowNos.push(n); }
      var res=await matchItems(items);
      var colVals=[]; for(var n=0;n<rowsV.length;n++) colVals[n]='';
      colVals[hdrN]='임대인 연락처(DB)';
      rowNos.forEach(function(n,k){ var p=(res[k]||{}).phone||''; colVals[n]=p; total++; if(p) hit++; });
      ws.spliceColumns(insertAt, 0, colVals.slice(1));
      var col=ws.getColumn(insertAt); col.width=18; ws.getRow(hdrN).getCell(insertAt).font={bold:true};
    }
    var buf=await wb.xlsx.writeBuffer(); var name=file.name.replace(/\\.xlsx?$/i,'')+'_연락처.xlsx';
    var a=document.createElement('a'); a.href=URL.createObjectURL(new Blob([buf],{type:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'})); a.download=name; document.body.appendChild(a); a.click(); setTimeout(function(){URL.revokeObjectURL(a.href);a.remove();},3000);
    return {total:total, hit:hit, name:name};
  }
  async function fillFiles(files){
    if(!files||!files.length) return; var msg=$('fillmsg'); $('fillgo').disabled=true; var lines=[];
    for(var i=0;i<files.length;i++){ var f=files[i]; msg.textContent='채우는 중… '+f.name; try{ var r=await fillWorkbook(f); lines.push(r.name+': '+r.total+'줄 중 연락처 '+r.hit+'건 채움'); }catch(e){ lines.push(f.name+': 실패 ('+e.message+')'); } }
    msg.textContent='완료 — '+lines.join(' · ')+' (내려받기 폴더 확인)'; $('fillgo').disabled=false;
  }
  $('fillgo').onclick=function(){ fillFiles($('fillfile').files); };
  $('fillfile').onchange=function(){ if($('fillfile').files.length) fillFiles($('fillfile').files); };
  var fb=$('fillbox'); ['dragenter','dragover'].forEach(function(ev){ fb.addEventListener(ev,function(e){ e.preventDefault(); fb.classList.add('drag'); }); }); ['dragleave','drop'].forEach(function(ev){ fb.addEventListener(ev,function(e){ e.preventDefault(); fb.classList.remove('drag'); }); });
  fb.addEventListener('drop',function(e){ var fs=[].filter.call(e.dataTransfer.files,function(f){return /\\.xlsx?$|\\.xlsm$/i.test(f.name)}); if(fs.length) fillFiles(fs); else $('fillmsg').textContent='xlsx 파일만 됩니다'; });
  $('filltxt').onclick=async function(){
    var lines=$('filltext').value.split(/\\n/).map(function(x){return x.trim()}).filter(Boolean); if(!lines.length){ $('fillmsg').textContent='지번을 적어주세요'; return; }
    var res=await matchItems(lines.map(function(l){return {addr:l,ho:''}}));
    var h='<table><tr><th>적은 지번</th><th>찾은 단위</th><th>임대인 연락처(DB)</th></tr>'; var hit=0;
    lines.forEach(function(l,i){ var r=res[i]||{}; if(r.phone) hit++; h+='<tr><td>'+esc(l)+'</td><td>'+esc(r.lot||'')+(r.ho?' '+esc(r.ho)+'호':'')+'</td><td><b>'+esc(r.phone||'')+'</b></td></tr>'; });
    $('fillout').innerHTML=h+'</table>'; $('fillmsg').textContent=lines.length+'줄 중 '+hit+'건 찾음';
  };
  // 지번 조회: 치는 대로(0.3초 뒤) 찾기, Enter·[찾기]도 됨. 결과 표의 연락처·메모·지번 칸도 클릭 수정.
  var esc=function(v){return String(v==null?'':v).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')};
  var lkTimer=null, lkLast='';
  async function lookup(){
    var q=$('lkq').value.trim(); var res=$('lkres'), msg=$('lkmsg');
    if(q.length<2){ res.innerHTML=''; msg.textContent='치는 대로 바로 찾습니다. 결과의 연락처·메모 칸도 클릭해서 고칠 수 있습니다.'; return; }
    if(q===lkLast) return; lkLast=q;
    msg.textContent='찾는 중…';
    try{
      var r=await fetch('/admin/listings/lookup.json?q='+encodeURIComponent(q)).then(function(x){return x.json()});
      if($('lkq').value.trim()!==q) return;
      if(!r.rows.length){ res.innerHTML='<div class="lknone">"'+esc(q)+'" 에 해당하는 줄이 없습니다. 위 수기 입력으로 넣어두세요.</div>'; msg.textContent='0건'; return; }
      var h='<table><thead><tr><th>지번·호수</th><th>임대인 연락처</th><th>임차인·관리 등</th><th>종류</th><th>거래</th><th>금액</th><th>이름·제목</th><th>메모</th><th>올린 날</th></tr></thead><tbody>';
      r.rows.forEach(function(x){ h+='<tr data-id="'+x.id+'"><td class="addr ed" data-f="addr">'+esc(x.addr)+'</td><td class="phone ed" data-f="phone">'+esc(x.phone)+'</td><td class="contacts ed" data-f="contacts">'+esc(x.contacts)+'</td><td>'+esc(x.kind)+'</td><td>'+esc(x.deal)+'</td><td>'+esc(x.price)+'</td><td>'+esc(x.title)+'</td><td class="memo ed" data-f="memo">'+esc(x.memo)+'</td><td class="small">'+esc(x.last_at)+'</td></tr>'; });
      h+='</tbody></table>'+(r.count>=300?'<div class="lkmore">300건까지만 보입니다. 지번을 더 자세히 치세요.</div>':'');
      res.innerHTML=h; msg.textContent=r.count+'건';
    }catch(e){ msg.textContent='오류: '+e.message; }
  }
  $('lkq').addEventListener('input',function(){ clearTimeout(lkTimer); lkTimer=setTimeout(lookup,300); });
  $('lkq').addEventListener('keydown',function(e){ if(e.key==='Enter'){ e.preventDefault(); clearTimeout(lkTimer); lkLast=''; lookup(); } });
  $('lkgo').onclick=function(){ lkLast=''; lookup(); };
  if($('lkq').value.trim().length>=2) lookup();
  // 칸 클릭 → 입력칸 → Enter/포커스 벗어나면 저장, Esc 취소 (목록 표·조회 결과 둘 다)
  document.addEventListener('click',function(ev){
      var td=ev.target.closest&&ev.target.closest('td.ed'); if(!td) return;
      if(td.querySelector('input')) return;
      var old=td.textContent, id=td.parentNode.getAttribute('data-id'), f=td.getAttribute('data-f');
      var inp=document.createElement('input'); inp.value=old; td.textContent=''; td.appendChild(inp); inp.focus(); inp.select();
      var done=false;
      function save(){ if(done) return; done=true; var v=inp.value.trim(); if(v===old.trim()||(f==='addr'&&!v)){ td.textContent=old; return; }
        var body={}; body[f]=v;
        fetch('/admin/listings/'+id+'/edit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}).then(function(r){return r.json()}).then(function(r){ td.textContent=r.success?v:old; if(!r.success) alert(r.message||'저장 실패'); }).catch(function(){ td.textContent=old; alert('저장 실패'); }); }
      inp.addEventListener('keydown',function(e){ if(e.key==='Enter'){ e.preventDefault(); save(); } if(e.key==='Escape'){ done=true; td.textContent=old; } });
      inp.addEventListener('blur',save);
  });
  $('del').onclick=function(){ if(confirm('현재 검색 조건의 '+LT_TOTAL+'건을 삭제할까요? (위 "최근 작업"에서 되돌릴 수 있습니다)')) $('delf').submit(); };
  // 체크박스 선택 삭제
  function selIds(){ return Array.prototype.slice.call(document.querySelectorAll('.rowck:checked')).map(function(c){return c.value}); }
  function paintSel(){ var n=selIds().length; var b=$('delsel'); b.textContent='선택 삭제 ('+n+')'; b.disabled=!n; }
  document.addEventListener('change',function(e){ if(e.target&&e.target.classList&&e.target.classList.contains('rowck')) paintSel(); });
  var ca=$('ckall'); if(ca) ca.onchange=function(){ document.querySelectorAll('.rowck').forEach(function(c){ c.checked=ca.checked; }); paintSel(); };
  $('delsel').onclick=async function(){
    var ids=selIds(); if(!ids.length) return; if(!confirm('체크한 '+ids.length+'줄을 삭제할까요? (최근 작업에서 되돌릴 수 있습니다)')) return;
    var r=await fetch('/admin/listings/delete-ids',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ids:ids})}).then(function(x){return x.json()});
    if(r.success) location.href='/admin/listings?'+LT_QS+'&deleted='+r.deleted; else alert(r.message||'삭제 실패');
  };
  document.querySelectorAll('.undo').forEach(function(b){ b.onclick=async function(){ b.disabled=true; var r=await fetch('/admin/listings/undo',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({batch:b.dataset.batch})}).then(function(x){return x.json()}); if(r.success) location.href='/admin/listings?restored='+(r.restored!=null?r.restored:0)+'&undeleted='+(r.deleted!=null?r.deleted:0); else { alert(r.message||'되돌리기 실패'); b.disabled=false; } }; });
  $('xl').onclick=async function(){
    var btn=$('xl'); btn.disabled=true; var msg=$('xlmsg'); var all=[]; var after=0;
    try{
      while(true){
        msg.textContent='내려받는 중… '+all.length+' / '+LT_TOTAL+'건';
        var r=await fetch('/admin/listings/rows.json?'+LT_QS+'&after='+after+'&limit=1000').then(function(x){return x.json()});
        all=all.concat(r.rows); if(!r.next) break; after=r.next;
      }
      if(!all.length){ msg.textContent='내려받을 행이 없습니다.'; btn.disabled=false; return; }
      var meta=['지번·호수','임대인 연락처','임차인·관리 등','종류','거래','금액','이름·제목','메모','번호(DB)','링크(DB)','구분','올린 계정','파일','처음 올림','최근 올림','올린 횟수'];
      var cols=[]; var seen={};
      all.forEach(function(r){ Object.keys(r.data).forEach(function(k){ if(!seen[k]){ seen[k]=1; cols.push(k); } }); });
      var aoa=[meta.concat(cols)];
      all.forEach(function(r){ var row=[r.addr||'',r.phone||'',r.contacts||'',r.kind||'',r.deal||'',r.price||'',r.title||'',r.memo||'',r.no,r.url||'',r.site,r.username,r.file||'',r.first_at,r.last_at,r.seen]; cols.forEach(function(k){ var v=r.data[k]; row.push(v==null?'':String(v)); }); aoa.push(row); });
      var ws=XLSX.utils.aoa_to_sheet(aoa);
      for(var i=1;i<aoa.length;i++){ aoa[i].forEach(function(v,j){ if(typeof v==='string' && /^https?:\\/\\//.test(v)){ var cc=ws[XLSX.utils.encode_cell({r:i,c:j})]; if(cc) cc.l={Target:v}; } }); }
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
