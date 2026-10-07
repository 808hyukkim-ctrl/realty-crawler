// 사진 950 — 매물 링크를 넣으면 페이지의 사진 주소를 모아 주고(서버), 브라우저가 가로 950 으로 바꿔 zip 으로 내려받는다 (2026-10-02)
//   GET  /admin/photos                 화면
//   POST /admin/photos/settings        온하우스 계정 저장 (D1 settings)
//   POST /admin/photos/collect {urls}  링크별 사진 주소 목록
//   GET  /admin/photos/img?u=          사진 바이트 중계 (캔버스에서 쓰려면 같은 출처여야 함)
import { Hono } from "hono";
import { html, raw } from "hono/html";
import { layout } from "./layout";

type Bindings = { DB: D1Database; ADMIN_USER: string; ADMIN_PASSWORD: string };
export const photos = new Hono<{ Bindings: Bindings }>();

const PARSE_API = "https://bridge-parse.808hyukkim.workers.dev/parse";
const BROWSER_HEADERS: Record<string, string> = {
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
  Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
  "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.5",
};
// 네이버 매물 API 는 쿠키 묶음 + 원래 Referer + 이 UA 가 전부 있어야 200 (bridge-parse 워커와 같은 값)
const NAVER_HEADERS: Record<string, string> = {
  Accept: "*/*",
  "Accept-Language": "ko-KR,ko;q=0.8,en-US;q=0.5,en;q=0.3",
  Authorization: "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6IlJFQUxFU1RBVEUiLCJpYXQiOjE3NTE5NDU0MzcsImV4cCI6MTc1MTk1NjIzN30.UOlh5J9b7Eq7G9mA2d2Yya0SSV5mjMOTj9oKJQXt0WY",
  Cookie: "NNB=DHVGK5NIFRZGQ; BUC=dQnzU4cEAFITbLHCXx2pf6SBlHnD1zsFqd72oOrN3W4=; landHomeFlashUseYn=Y; REALESTATE=Tue%20Jul%2008%202025%2012%3A30%3A37%20GMT%2B0900%20(Korean%20Standard%20Time)",
  Referer: "https://new.land.naver.com/rooms?ms=37.3595704,127.105399,16&a=APT:OPST:VL:OR&e=RETAIL",
  "Sec-Fetch-Dest": "empty",
  "Sec-Fetch-Mode": "cors",
  "Sec-Fetch-Site": "same-origin",
  "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:139.0) Gecko/20100101 Firefox/139.0",
};
const ONHOUSE_HOST = "https://www.onhouse.com";
const OH = { cookie: "", at: 0, id: "" };

// ---------------------------------------------------------------- settings (D1)
async function ensureSettings(db: D1Database) {
  await db.prepare("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)").run();
}
export async function getSetting(db: D1Database, key: string): Promise<string> {
  await ensureSettings(db);
  const row = await db.prepare("SELECT value FROM settings WHERE key = ?").bind(key).first<{ value: string }>();
  return row?.value ?? "";
}
export async function setSetting(db: D1Database, key: string, value: string) {
  await ensureSettings(db);
  await db.prepare("INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at")
    .bind(key, value, new Date().toISOString()).run();
}

// ---------------------------------------------------------------- 링크 판별
const naverNo = (u: string) => (u.match(/articleNo=(\d{6,})/) || u.match(/land\.naver\.com\/.*?article(?:s|\/info)?\/(\d{6,})/) || [])[1] || "";
const daangnId = (u: string) => (u.match(/daangn\.com\/(?:kr\/)?(?:realty\/)?articles\/(\d+)/) || [])[1] || "";
const onhouseId = (u: string) => (/onhouse\.com/.test(u) ? (u.match(/rent_view\/(\d+)/) || [])[1] : "") || "";   // 로그인 리다이렉트(?login=true&callback=/index/rent_view/N) 꼴도
const safeName = (s: string) => String(s || "").replace(/[\\/:*?"<>|\s]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 60) || "사진";
const dedupe = (urls: string[]) => { const out: string[] = []; const seen = new Set<string>(); for (const u of urls) { const k = u.split("?")[0]; if (seen.has(k)) continue; seen.add(k); out.push(u); } return out; };
const stripTags = (s: string) => String(s || "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();

type Found = { label: string; photos: string[]; referer: string };

async function photosNaver(no: string): Promise<Found> {
  const r = await fetch(`https://new.land.naver.com/api/articles/${no}?complexNo=`, { headers: NAVER_HEADERS });
  if (r.status === 429) throw new Error("네이버가 잠시 요청을 막았습니다 (429). 1~2분 뒤 다시 해주세요");
  if (!r.ok) throw new Error(`네이버 응답 ${r.status}`);
  const j: any = await r.json();
  const urls = (Array.isArray(j.articlePhotos) ? j.articlePhotos : []).map((p: any) => String(p?.imageSrc || "").trim()).filter(Boolean)
    .map((src: string) => "https://landthumb-phinf.pstatic.net" + src);   // 크기 인자 없이 = 원본
  const rep = String(j.articleAddition?.representativeImgUrl || "");
  if (rep && !urls.length) urls.push("https://landthumb-phinf.pstatic.net" + rep);
  const title = String(j.articleDetail?.articleName || j.articleDetail?.exposureAddress || "").trim();
  return { label: `네이버_${no}` + (title ? `_${safeName(title)}` : ""), photos: dedupe(urls), referer: "https://new.land.naver.com/" };
}

async function photosDaangn(id: string, url: string): Promise<Found> {
  const r = await fetch(`${PARSE_API}?url=${encodeURIComponent(url)}`);
  const j: any = await r.json();
  if (j.error) throw new Error(`당근 링크 읽기 실패: ${j.error}`);
  const urls = (j.photos || []).map((u: any) => String(u).split("?")[0]);   // 크기 인자 제거 = 원본
  const title = String(j.building || j.address_q || "").trim();
  return { label: `당근_${id}` + (title ? `_${safeName(title)}` : ""), photos: dedupe(urls), referer: "https://realty.daangn.com/" };
}

async function onhouseLogin(id: string, pw: string): Promise<string> {
  const form = new URLSearchParams({ from_page: "", dg_login_ver: "", id, pwd: pw });
  const res = await fetch(`${ONHOUSE_HOST}/index.php/dataFunction/login`, { method: "POST", body: form, headers: { ...BROWSER_HEADERS, "Content-Type": "application/x-www-form-urlencoded" }, redirect: "manual" });
  const setCookie = (typeof (res.headers as any).getSetCookie === "function" ? (res.headers as any).getSetCookie() : [res.headers.get("set-cookie") || ""]).join("; ");
  const m = setCookie.match(/ci_session=([^;]+)/);
  if (!m) throw new Error(`온하우스 로그인 실패 (HTTP ${res.status}) — 아이디/비밀번호를 확인하세요`);
  const cookie = `ci_session=${m[1]}`;
  await fetch(`${ONHOUSE_HOST}/login_opt/toLoginNormal`, { headers: { ...BROWSER_HEADERS, Cookie: cookie }, redirect: "manual" }).catch(() => {});
  OH.cookie = cookie; OH.at = Date.now(); OH.id = id;
  return cookie;
}
async function photosOnhouse(hid: string, db: D1Database): Promise<Found> {
  const id = await getSetting(db, "onhouse_id"), pw = await getSetting(db, "onhouse_pw");
  if (!id || !pw) throw new Error("온하우스 링크는 유료 회원사 아이디/비밀번호가 필요합니다 — 아래 '온하우스 계정'에 저장하세요");
  const get = (cookie: string) => fetch(`${ONHOUSE_HOST}/index/rent_view/${hid}`, { headers: { ...BROWSER_HEADERS, Cookie: cookie }, redirect: "manual" }).then((r) => r.text());
  let page = OH.cookie && OH.id === id && Date.now() - OH.at < 6 * 3600e3 ? await get(OH.cookie) : "";
  if (!page.includes("topMainTitleArea")) page = await get(await onhouseLogin(id, pw));
  if (!page.includes("topMainTitleArea")) throw new Error("온하우스 상세를 열 수 없습니다 (유료 회원사만 조회 가능)");
  const seen = new Map<string, string>();
  // 직방 연동 매물 사진(ic.zigbang.com, ?w= 필수) + 온하우스 자체 사진/건물 사진(cloudfront). 큰 폭을 요청해 받아 950 으로 줄인다
  for (const m of page.matchAll(/https:\/\/ic\.zigbang\.com\/vp\/rooms\/[A-Za-z0-9]+\/([A-Za-z0-9]+\.(?:jpg|jpeg|png|webp))/gi)) {
    const k = "zb:" + m[1].toLowerCase(); if (!seen.has(k)) seen.set(k, m[0] + "?w=1900");
  }
  for (const m of page.matchAll(/https:\/\/[a-z0-9.-]+\.cloudfront\.net\/(?:room_img|building_img|[a-z_]*img)\/([A-Za-z0-9_-]+\.(?:jpg|jpeg|png|webp))/gi)) {
    const k = m[1].toLowerCase(); if (!seen.has(k)) seen.set(k, m[0] + "?w=1900");
  }
  const title = stripTags((page.match(/class="addr_title"[^>]*>([\s\S]*?)<\/h6>/) || [])[1] || "");
  return { label: `온하우스_${hid}` + (title ? `_${safeName(title)}` : ""), photos: [...seen.values()], referer: ONHOUSE_HOST + "/" };
}

async function photosGeneric(url: string): Promise<Found> {
  const r = await fetch(url, { headers: BROWSER_HEADERS, redirect: "follow" });
  if (!r.ok) throw new Error(`페이지 응답 ${r.status}`);
  const page = await r.text();
  const cands: string[] = [];
  for (const m of page.matchAll(/<meta[^>]+property=["']og:image(?::secure_url)?["'][^>]+content=["']([^"']+)/gi)) cands.push(m[1]);
  for (const m of page.matchAll(/<meta[^>]+content=["']([^"']+)["'][^>]+property=["']og:image/gi)) cands.push(m[1]);
  for (const m of page.matchAll(/<img\b[^>]*>/gi)) {
    const tag = m[0];
    const ss = tag.match(/srcset=["']([^"']+)/i);
    if (ss) { let best = "", bw = -1; for (const part of ss[1].split(",")) { const bits = part.trim().split(/\s+/); if (!bits[0]) continue; const w = bits[1] ? parseInt(bits[1].replace(/\D/g, "") || "0", 10) : 0; if (w > bw) { best = bits[0]; bw = w; } } if (best) cands.push(best); }
    for (const attr of ["data-original", "data-src", "data-lazy-src", "data-url", "src"]) { const a = tag.match(new RegExp(attr + '=["\']([^"\']+)', "i")); if (a && !a[1].startsWith("data:")) { cands.push(a[1]); break; } }
  }
  for (const m of page.matchAll(/background(?:-image)?\s*:\s*url\(["']?([^"')]+)/gi)) cands.push(m[1]);
  const urls: string[] = [];
  for (const c of cands) { try { const u = new URL(c.trim(), url).toString(); if (u.startsWith("http")) urls.push(u); } catch {} }
  const host = new URL(url).hostname.replace(/^www\./, "");
  const title = stripTags((page.match(/<title[^>]*>([\s\S]{1,80}?)<\/title>/i) || [])[1] || "");
  return { label: safeName(host) + (title ? `_${safeName(title)}` : ""), photos: dedupe(urls), referer: url };
}

// ---------------------------------------------------------------- 라우트
photos.get("/admin/photos", async (c) => {
  const ohId = await getSetting(c.env.DB, "onhouse_id");
  const ohPw = await getSetting(c.env.DB, "onhouse_pw");
  const saved = c.req.query("saved") === "1";
  return c.html(layout("사진 950", PAGE(ohId, !!ohPw, saved)));
});

photos.post("/admin/photos/settings", async (c) => {
  const form = await c.req.formData();
  const id = String(form.get("onhouse_id") ?? "").trim();
  const pw = String(form.get("onhouse_pw") ?? "").trim();
  await setSetting(c.env.DB, "onhouse_id", id);
  if (pw) await setSetting(c.env.DB, "onhouse_pw", pw);
  if (!id) await setSetting(c.env.DB, "onhouse_pw", "");
  OH.cookie = ""; OH.at = 0;
  return c.redirect("/admin/photos?saved=1");
});

photos.post("/admin/photos/collect", async (c) => {
  const body: any = await c.req.json().catch(() => ({}));
  const urls: string[] = Array.isArray(body.urls) ? body.urls.map((u: any) => String(u).trim()).filter((u: string) => /^https?:\/\//.test(u)).slice(0, 50) : [];
  const out: any[] = [];
  for (const url of urls) {
    try {
      const no = naverNo(url), did = daangnId(url), hid = onhouseId(url);
      const f = no ? await photosNaver(no) : did ? await photosDaangn(did, url) : hid ? await photosOnhouse(hid, c.env.DB) : await photosGeneric(url);
      out.push({ url, ok: true, site: no ? "naver" : did ? "daangn" : hid ? "onhouse" : "generic", ...f });
    } catch (e: any) {
      out.push({ url, ok: false, error: e?.message || String(e) });
    }
  }
  return c.json({ items: out });
});

const PROXY_HOST_OK = /(\.pstatic\.net|\.gcp-karroter\.net|\.cloudfront\.net|\.daangn\.com|\.naver\.(com|net)|\.onhouse\.com|\.zigbang\.com)$/i;
photos.get("/admin/photos/img", async (c) => {
  const u = c.req.query("u") || "";
  const ref = c.req.query("r") || "";
  let target: URL;
  try { target = new URL(u); } catch { return c.text("bad url", 400); }
  if (!/^https?:$/.test(target.protocol)) return c.text("bad url", 400);
  const headers: Record<string, string> = { "User-Agent": BROWSER_HEADERS["User-Agent"], Accept: "image/avif,image/webp,image/*,*/*;q=0.8" };
  if (ref) headers.Referer = ref;
  let r = await fetch(target.toString(), { headers, cf: { cacheTtl: 3600, cacheEverything: true } } as any);
  if (!r.ok && /[?&]w=\d+/.test(target.search)) r = await fetch(target.toString().replace(/([?&])w=\d+/, "$1w=873"), { headers } as any);   // 큰 폭을 못 받으면 873
  if (!r.ok && target.search) r = await fetch(target.origin + target.pathname, { headers } as any);   // 그래도 안 되면 인자 없는 원본으로
  if (!r.ok) return c.text(`image ${r.status}`, 502);
  const ct = r.headers.get("content-type") || "application/octet-stream";
  if (!/^image\//.test(ct) && !PROXY_HOST_OK.test(target.hostname)) return c.text("not image", 415);
  return new Response(r.body, { status: 200, headers: { "Content-Type": ct, "Cache-Control": "private, max-age=3600" } });
});

// ---------------------------------------------------------------- 화면
function PAGE(ohId: string, hasPw: boolean, saved: boolean) {
  return html`
<div class="page-head"><h1>사진 950</h1><a class="btn btn-sm" href="/admin/dashboard">사용자 관리로</a></div>
<p class="muted" style="margin:-8px 0 16px;color:var(--muted);font-size:13px">매물 링크를 넣으면 사진만 모아 가로 950px 로 바꿔 zip 으로 내려받습니다. 네이버부동산 · 당근 · 온하우스(계정 필요) · 그 밖의 사이트.</p>
<div class="ph-grid">
  <section class="panel">
    <label>매물 링크 (한 줄에 하나)<textarea id="links" rows="6" placeholder="https://new.land.naver.com/rooms?articleNo=2652272081&#10;https://realty.daangn.com/articles/4401448&#10;https://www.onhouse.com/index/rent_view/3554712"></textarea></label>
    <div class="ph-opts">
      <label>가로(px)<input type="number" id="w" value="950" min="50" max="5000"></label>
      <label class="ph-chk"><input type="checkbox" id="fixh"> 세로 고정 <input type="number" id="h" value="950" min="100" max="5000" disabled></label>
      <label>JPG 품질<input type="number" id="q" value="92" min="50" max="100"></label>
      <label class="ph-chk"><input type="checkbox" id="onezip" checked> 링크마다 zip 하나씩 (끄면 전부 한 zip)</label>
    </div>
    <div class="form-actions"><button class="btn btn-primary" id="go">사진 가져와서 950으로 저장</button><button class="btn" id="stop" disabled>중단</button><span id="status" class="ph-status"></span></div>
    <div class="ph-bar"><div id="bar"></div></div>
    <div id="log" class="ph-log"></div>
  </section>
  <section class="panel">
    <h2 style="margin:0 0 10px;font-size:15px">온하우스 계정 <span class="small" style="color:var(--muted);font-weight:400">(온하우스 링크일 때만 · 유료 회원사)</span></h2>
    ${saved ? html`<div class="ph-ok">저장했습니다</div>` : ""}
    <form method="post" action="/admin/photos/settings">
      <label>아이디<input name="onhouse_id" value="${ohId}" autocomplete="off"></label>
      <label>비밀번호<input name="onhouse_pw" type="password" placeholder="${hasPw ? "저장됨 (바꿀 때만 입력)" : "비밀번호"}" autocomplete="new-password"></label>
      <div class="form-actions"><button class="btn btn-sm" type="submit">저장</button></div>
    </form>
    <h2 style="margin:18px 0 8px;font-size:15px">미리보기</h2>
    <div id="thumbs" class="ph-thumbs"></div>
  </section>
</div>
<style>${raw(PH_STYLE)}</style>
<script src="https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js"></script>
<script>${raw(PH_JS)}</script>`;
}

const PH_STYLE = `
.ph-grid{display:grid;grid-template-columns:minmax(0,3fr) minmax(280px,2fr);gap:16px;align-items:start}
@media(max-width:860px){.ph-grid{grid-template-columns:1fr}}
.panel{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:18px}
.panel textarea{display:block;width:100%;margin-top:6px;padding:10px 12px;border-radius:8px;border:1px solid var(--border);background:#0d121c;color:var(--text);font-size:13px;font-family:Consolas,monospace;resize:vertical}
.ph-opts{display:flex;flex-wrap:wrap;gap:12px 18px;align-items:end;margin:4px 0 8px}
.ph-opts label{margin:0}
.ph-opts input[type=number]{width:96px;display:inline-block}
.ph-chk{display:flex!important;align-items:center;gap:6px;color:var(--text)!important}
.ph-chk input[type=checkbox]{width:auto;display:inline-block;margin:0}
.ph-status{font-size:13px;color:var(--muted);align-self:center}
.ph-bar{height:8px;background:#0d121c;border:1px solid var(--border);border-radius:999px;overflow:hidden;margin:12px 0}
.ph-bar div{height:100%;width:0;background:var(--accent);transition:width .2s}
.ph-log{font-family:Consolas,monospace;font-size:12px;white-space:pre-wrap;background:#0d121c;border:1px solid var(--border);border-radius:8px;padding:10px;max-height:320px;overflow:auto;color:#cbd5e1}
.ph-ok{color:var(--ok);font-size:13px;margin-bottom:8px}
.ph-thumbs{display:grid;grid-template-columns:repeat(auto-fill,minmax(84px,1fr));gap:6px}
.ph-thumbs img{width:100%;aspect-ratio:1;object-fit:cover;border-radius:6px;border:1px solid var(--border)}
`;

const PH_JS = `
(function(){
  var $=function(id){return document.getElementById(id)};
  var running=false, stopReq=false;
  $('fixh').onchange=function(){ $('h').disabled=!this.checked; };
  function log(s){ var el=$('log'); el.textContent+=s+'\\n'; el.scrollTop=el.scrollHeight; }
  function setBar(p){ $('bar').style.width=Math.max(0,Math.min(100,p))+'%'; }
  function links(){ var out=[],seen={}; $('links').value.split(/\\s+/).forEach(function(t){ t=t.trim(); if(/^https?:\\/\\//.test(t)&&!seen[t]){seen[t]=1;out.push(t);} }); return out; }
  function loadImg(url, ref){ return new Promise(function(ok,bad){ var im=new Image(); im.onload=function(){ok(im)}; im.onerror=function(){bad(new Error('load'))}; im.src='/admin/photos/img?u='+encodeURIComponent(url)+(ref?'&r='+encodeURIComponent(ref):''); }); }
  function resize(im, w, h, q){ var cw=w, ch=h>0?h:Math.max(1,Math.round(im.naturalHeight*w/im.naturalWidth)); var c=document.createElement('canvas'); c.width=cw; c.height=ch; var x=c.getContext('2d'); x.imageSmoothingQuality='high';
    if(h>0){ var s=Math.max(cw/im.naturalWidth, ch/im.naturalHeight); var dw=im.naturalWidth*s, dh=im.naturalHeight*s; x.drawImage(im,(cw-dw)/2,(ch-dh)/2,dw,dh); } else { x.drawImage(im,0,0,cw,ch); }
    return new Promise(function(ok){ c.toBlob(function(b){ok({blob:b,w:cw,h:ch})},'image/jpeg',q/100); }); }
  function save(blob, name){ var a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download=name; document.body.appendChild(a); a.click(); setTimeout(function(){URL.revokeObjectURL(a.href); a.remove();},2000); }
  $('stop').onclick=function(){ stopReq=true; };
  $('go').onclick=async function(){
    if(running) return; var urls=links(); if(!urls.length){ alert('링크를 한 줄에 하나씩 넣어주세요'); return; }
    running=true; stopReq=false; $('go').disabled=true; $('stop').disabled=false; $('log').textContent=''; $('thumbs').innerHTML=''; setBar(0);
    var w=parseInt($('w').value)||950, h=$('fixh').checked?(parseInt($('h').value)||0):0, q=parseInt($('q').value)||92, perLink=$('onezip').checked;
    $('status').textContent='사진 주소 모으는 중…';
    var res; try{ res=await fetch('/admin/photos/collect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({urls:urls})}).then(function(r){return r.json()}); }catch(e){ log('서버 오류: '+e.message); running=false; $('go').disabled=false; $('stop').disabled=true; return; }
    var items=res.items||[]; var total=0; items.forEach(function(it){ if(it.ok) total+=it.photos.length; }); var done=0, savedN=0;
    var allZip = perLink?null:new JSZip();
    for(var i=0;i<items.length;i++){
      var it=items[i]; if(stopReq){ log('중단'); break; }
      log('['+(i+1)+'/'+items.length+'] '+it.url);
      if(!it.ok){ log('  오류: '+it.error); continue; }
      if(!it.photos.length){ log('  사진 주소를 찾지 못했습니다'); continue; }
      log('  사진 후보 '+it.photos.length+'장 → '+it.label);
      var zip = perLink?new JSZip():allZip.folder(it.label); var n=0;
      for(var k=0;k<it.photos.length;k++){
        if(stopReq) break; var u=it.photos[k];
        try{ var im=await loadImg(u, it.referer); if(it.site==='generic' && Math.min(im.naturalWidth,im.naturalHeight)<400){ done++; setBar(done/total*100); continue; }
          var r=await resize(im,w,h,q); n++; var name=(n<10?'0':'')+n+'.jpg'; zip.file(name, r.blob);
          log('    ['+name+'] '+im.naturalWidth+'x'+im.naturalHeight+' → '+r.w+'x'+r.h);
          if($('thumbs').children.length<60){ var t=document.createElement('img'); t.src=URL.createObjectURL(r.blob); $('thumbs').appendChild(t); }
        }catch(e){ log('    내려받기 실패: '+u.slice(0,90)); }
        done++; setBar(done/total*100); $('status').textContent=done+'/'+total+'장';
      }
      if(perLink && n){ var b=await zip.generateAsync({type:'blob'}); save(b, it.label+'.zip'); savedN+=n; log('  저장 '+n+'장 → '+it.label+'.zip'); }
      else if(!perLink) savedN+=n;
    }
    if(!perLink && savedN){ var b2=await allZip.generateAsync({type:'blob'}); save(b2,'매물사진950_'+new Date().toISOString().slice(0,16).replace(/[-:T]/g,'')+'.zip'); log('저장 '+savedN+'장 → 한 zip'); }
    $('status').textContent='완료 — 사진 '+savedN+'장'; setBar(100); running=false; $('go').disabled=false; $('stop').disabled=true;
  };
})();
`;
