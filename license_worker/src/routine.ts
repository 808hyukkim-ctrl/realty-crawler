// 재원루틴 (2026-10-13) — 매일 하는 두 가지를 순서대로: <시작> 매물중복DB대조(매물·임대인 DB 탭에서 옮김) → <마무리> DB저장(텍스트 붙여넣기·엑셀 올리기·수기 입력, DB 탭에도 그대로 남아 있음)
//   GET /admin/routine
import { Hono } from "hono";
import { html, raw } from "hono/html";
import { layout } from "./layout";
import { LT_STYLE, LT_CORE_JS, LT_FILL_JS } from "./listings";

type Bindings = { DB: D1Database; ADMIN_USER: string; ADMIN_PASSWORD: string; OWNER_KEY?: string };
export const routine = new Hono<{ Bindings: Bindings }>();

routine.get("/admin/routine", async (c) => {
  const notice = c.req.query("added") != null ? (c.req.query("added") === "1" ? "한 줄 추가했습니다." : "이미 있는 줄이라 갱신했습니다.") : c.req.query("err") || "";
  const body = html`
    <div class="page-head">
      <h1>재원루틴</h1>
      <span class="small muted">매일 하는 일 두 가지를 순서대로 — ① 수집 엑셀을 DB와 대조해서 시작하고 ② 끝나면 새로 안 번호를 DB에 저장합니다. 쌓인 DB 는 <a href="/admin/listings">매물·임대인 DB</a> 탭에서 봅니다.</span>
    </div>
    ${notice ? html`<div class="notice">${notice}</div>` : ""}

    <section class="rt rt1">
      <h2><span class="step">①</span> &lt;시작&gt; 매물중복DB대조</h2>
      <div class="upbox fillbox" id="fillbox">
        <b>매물중복DB대조</b>
        <span class="small muted">매일 뽑는 수집 엑셀(네이버·당근·온하우스)을 여기에 끌어다 놓거나 고르면, 줄마다 지번(+호수)으로 DB를 대조해 <b>링크 바로 옆에 하늘색 "임대인 연락처(DB)" 칸</b>을 끼워 넣습니다. 나머지 칸은 그대로, 없는 건 빈칸. 끝나면 [내려받기] 버튼이 생깁니다.</span>
        <input type="file" id="fillfile" accept=".xlsx,.xlsm" multiple>
        <button type="button" class="btn btn-primary" id="fillgo">DB 대조하기</button>
        <textarea id="filltext" rows="2" placeholder="또는 지번을 글로 — 한 줄에 하나 (예: 석촌동 1-1 302호)"></textarea>
        <button type="button" class="btn" id="filltxt">글로 찾기</button>
        <span class="small muted" id="fillmsg"></span>
        <div id="fillout" style="width:100%"></div>
      </div>
    </section>

    <section class="rt rt2">
      <h2><span class="step">②</span> &lt;마무리&gt; DB저장</h2>
      <div class="upbox pastebox">
        <b>텍스트 붙여넣기</b>
        <input type="text" id="pssite" placeholder="구분" value="임대인" style="width:90px">
        <textarea id="pstext" rows="4" placeholder="카톡·메모·엑셀에서 복사한 글을 그대로 붙여넣으세요. 한 줄 = 매물 하나.&#10;예) 논현동 124-12 302호 010-1234-5678 월세 5000/150 빌라 김사장님&#10;    역삼동 777-2 2층 02-555-1234 임차인 010-2222-3333 매매 15억 상가"></textarea>
        <button type="button" class="btn btn-primary" id="psgo">넣기</button>
        <span class="small muted" id="psmsg">지번·호수, 임대인 연락처(첫 번호)·그 밖의 번호, 거래·금액, 종류, 이름을 줄마다 알아서 찾아 칸에 넣고, 못 알아본 글은 메모에 남깁니다. 지번이 없는 줄은 건너뜁니다.</span>
      </div>
      <div class="upbox">
        <b>엑셀 올리기</b>
        <input type="text" id="upsite" placeholder="구분 (예: 임대인)" value="임대인" title="네이버·당근·온하우스 수집기 엑셀은 열 이름으로 자동 판별됩니다">
        <input type="file" id="upfile" accept=".xlsx,.xls,.csv" multiple>
        <button type="button" class="btn btn-primary" id="upgo">올리기</button>
        <span class="small muted" id="upmsg">열 이름 줄은 자동으로 찾습니다. 지번·주소와 임대인 연락처는 맨 앞에, 임차인·세입자·관리·중개 번호는 그 옆 칸에 정리됩니다. 같은 행을 다시 올리면 중복 없이 갱신됩니다.</span>
      </div>
      <form class="upbox manual" method="post" action="/admin/listings/manual">
        <input type="hidden" name="back" value="/admin/routine">
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
    </section>
    <style>${raw(LT_STYLE)}${raw(RT_STYLE)}</style>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/exceljs/4.4.0/exceljs.min.js"></script>
    <script>window.LT_STAY=true;(function(){${raw(LT_CORE_JS)}${raw(LT_FILL_JS)}})();</script>`;
  return c.html(layout("재원루틴", body));
});

const RT_STYLE = `
.rt{background:var(--panel);border:1px solid var(--border);border-radius:16px;padding:16px 18px 10px;margin-bottom:18px}
.rt h2{margin:0 0 12px;font-size:17px;color:var(--accent-dark);display:flex;align-items:center;gap:10px}
.rt .step{display:inline-flex;width:28px;height:28px;border-radius:50%;background:var(--accent);color:#fff;align-items:center;justify-content:center;font-size:15px;font-weight:800}
.rt1{border-color:#4fc3f7;background:linear-gradient(135deg,#f1f9ff,#fff)}
.rt1 h2{color:#0277bd}.rt1 .step{background:#29b6f6}
.rt2{border-color:var(--accent)}
`;
