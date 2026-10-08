# 전국부동산매물수집기 라이선스 서버 (Cloudflare Workers + D1)

데스크톱 앱(독립버전)의 로그인/이용권 만료를 관리하는 Cloudflare Worker + D1(서버리스 SQLite) 기반
관리자 웹 + API입니다. 상시 켜둘 서버가 필요 없고, Cloudflare 계정으로 완전히 사용자님이 통제합니다.

## 배포 정보

- 관리자 웹 주소: https://realty-license-server.808hyukkim.workers.dev/admin/dashboard
- 로그인 방식: HTTP Basic Auth (브라우저가 자체적으로 아이디/비밀번호 입력창을 띄웁니다)
- Cloudflare 계정: 808hyukkim@gmail.com (account id: c1d09aa7727c826f26414e032cc47c9a)
- D1 데이터베이스: `license_db` (id: 562d4ba7-ab26-4958-b6b4-12ac11ef21dc)

## 관리자 로그인 정보

- 아이디: `admin`
- 비밀번호: `qwerr784`

비밀번호를 바꾸려면 로컬에 이 프로젝트를 두고 아래 명령을 실행하세요 (Cloudflare API 토큰 필요):

```
npx wrangler secret put ADMIN_PASSWORD
```

아이디를 바꾸려면 `ADMIN_USER`도 동일한 방식으로 다시 설정하면 됩니다.

## 로컬 개발/재배포

```
npm install
npm run dev            # 로컬 테스트 (로컬 D1 사용, wrangler dev)
npm run deploy         # 실제 Cloudflare에 재배포
```

코드를 수정한 뒤에는 `npm run deploy` 한 번이면 즉시 반영됩니다 (서버 재시작 필요 없음, Cloudflare가
전세계 엣지에 자동 배포).

## 데스크톱 앱 연동

`package/license_gate.py` 상단의 `VERIFY_URL` 이 이미 위 배포 주소를 가리키도록 되어 있습니다.
서버 주소를 바꾸게 되면 그 값만 수정하고 `pyinstaller --noconfirm --clean app_v1_site_standalone.spec`
로 다시 빌드하면 됩니다.

## 관리자 웹에서 할 수 있는 것

`/admin/dashboard` 접속 (브라우저가 아이디/비밀번호를 물어봄):

- 사용자(아이디/비밀번호) 등록, 이용권 기간 설정 (1일/3일/1주일/1개월/3개월/1년/무제한)
- 이용권 연장 (현재 만료일 기준 추가 연장)
- 계정 비활성화/활성화, 비밀번호 변경, 삭제
- 기기(MAC) 초기화 — 사용자가 PC를 바꾸거나 재설치해서 다른 기기로 인식될 때 사용
- 검색 (아이디 기준)

## 동작 방식

- 데스크톱 앱이 로그인 시 `/api/v1/verify` 로 아이디/비밀번호/MAC 주소를 전송합니다.
- 서버는 아이디/비밀번호가 맞고, 계정이 활성 상태이고, 이용권이 만료 전이면 인증을 통과시킵니다.
- 최초 로그인 시 MAC 주소가 자동으로 계정에 바인딩되어, 이후 다른 기기에서 로그인하면 거부됩니다
  (계정 공유 방지). 기기를 바꾸려면 관리자가 대시보드에서 "기기초기화"를 눌러줘야 합니다.

## 비용

Cloudflare Workers 무료 티어: 하루 10만 요청, D1 무료 티어: 하루 500만 행 읽기 / 10만 행 쓰기.
라이선스 검증처럼 가벼운 용도로는 사실상 계속 무료로 쓸 수 있습니다.


## 계정별 기능 (2026-10-02)

- 사용자마다 **기능** 체크박스 2개: `매물 수집`(수집기 exe) / `사진950`(매물사진 950 변환기 exe). 체크한 기능만 그 계정으로 로그인됩니다.
  둘 다 체크하면 둘 다, 하나만 체크하면 그것만. 체크를 바꾸면 바로 저장됩니다. 새 사용자 등록 때도 고를 수 있습니다.
- 기존 사용자는 자동으로 `매물 수집`만 켜진 상태가 됩니다(옛 수집기 exe 는 `app` 을 안 보내므로 수집으로 취급).
- API: `POST /api/v1/verify` 에 `app: "crawl" | "photo"` 를 보내면 그 기능이 없는 계정은 거부. 성공 응답에 `features` 배열 포함.
- 어드민 상단 **사진 950** 탭: 링크를 넣으면 사진을 모아 브라우저에서 가로 950 으로 바꿔 zip 으로 내려받는 관리자용 도구. 온하우스 링크는 그 탭에서 계정을 저장해 두면 됩니다(D1 `settings` 표).
- 배포: 이 폴더에서 `npx wrangler deploy` (D1 컬럼은 첫 요청 때 자동 추가).

## 활동 기록 (2026-10-02)

- 상단 **활동 기록** 탭(`/admin/logs`): 누가(아이디) 어느 프로그램(매물 수집기/사진950)으로 무엇을(로그인 / 수집 / 사진950) 몇 건 했는지, 기기(MAC)까지 최근 500건. 아이디 검색·프로그램 필터. 대시보드 각 사용자 줄의 [기록] 버튼으로 그 사람 것만 봅니다.
- 로그인은 서버가 바로 기록하고, 수집/사진 작업은 프로그램이 끝날 때 `POST /api/v1/log` 로 보냅니다(로그인 응답의 `log_token` 으로 본인 확인). 2026-10-02 이후 빌드된 exe 만 작업 기록을 보냅니다(옛 exe 는 로그인만 남음).
- 표: D1 `activity_log` (첫 요청 때 자동 생성).

## 텔레그램 봇을 서버가 받기 (2026-10-06)

- 어드민 **텔레그램 봇** 탭(`/admin/telegram`): 봇 토큰·챗 ID 저장 → [저장 + 웹훅 등록]. 등록하면 텔레그램 메시지가 서버로 오고, 프로그램이 꺼져 있어도 답합니다.
  - `목록` → 올라온 예약 목록(프로그램별, 켜짐/꺼짐 표시) · `실행 <이름>` → 대기열에 넣고, 프로그램이 켜져 있으면 10초 안에 시작, 꺼져 있으면 켜질 때(12시간 내) 실행 · `상태` · `도움`
- 프로그램(온하우스 수집기·매물수집기)은 로그인하면 예약 목록을 `POST /api/v1/schedules` 로 올리고(예약이 바뀔 때마다 갱신), 10초마다 `GET /api/v1/commands` 로 대기 명령을 가져가며 결과를 `POST /api/v1/commands/:id/done` 으로 알리면 서버가 텔레그램 답장을 보냅니다.
- [웹훅 해제]를 누르면 예전처럼 프로그램이 봇을 직접 봅니다(getUpdates). 웹훅이 켜져 있는 동안은 2026-10-06 이후 빌드 exe 만 명령을 받습니다.
- 표: D1 `app_schedules`, `app_commands` (자동 생성).


### 2026-10-08 매물·임대인 DB — 거래 전부 표시
- 한 매물에 매매·전세·월세가 같이 있으면 금액 칸에 `매매 5억 · 전세 3억 · 월세 5000 / 150` 처럼 전부 적고 거래 칸은 `매매·전세·월세`. 검색 필터에 **거래**(매매/전세/월세) 추가. 엑셀 다운로드·지번 조회 결과도 같음.

## 당근 광고자동화 (2026-10-08)

- 사용자 화면 `/daangn` — 라이선스 계정(아이디/비밀번호)으로 로그인. 어드민 사용자 관리에서 기능 **당근 광고** 를 체크한 계정만 들어옵니다.
  매물 링크·글 붙여넣기 → 자동 정리(daangn-parse 워커) → 건축물대장 확인 → [당근 연결(QR)] 로 본인 당근 계정 연결 → [🥕 당근에 올리기] / 여러 건 일괄 → 업로드 기록 탭.
  라운지에는 아무것도 저장하지 않습니다(당근 전용). 화면은 `라운지 인트라넷/site/index.html` 을 `Desktop/당근광고자동화/build_daangn_html.py` 가 복제해 `src/daangn.html` 로 만듭니다 — 직접 고치지 말고 인트라넷을 고친 뒤 `bash Desktop/당근광고자동화/deploy_worker.sh`.
- 서버 코드 `src/daangn.ts`: `/daangn/api/*` (login·summary·address·building·img·daangn-connect·daangn-disconnect·daangn-direct·uploads·upload-close·upload-edit), 표 `daangn_web_sessions`·`daangn_sessions`(사용자별 당근 세션 암호문)·`daangn_uploads` (자동 생성). 어드민 **당근 광고** 탭 `/admin/daangn`.
- 당근 로그인·등록은 라운지 서버 기계의 별도 컨테이너 `daangn-engine`(:8092, `Desktop/당근광고자동화/engine`) 이 하고, 이 워커는 시크릿 `ENGINE_URL`(`https://www.loungeplus.kr/daangn-engine`)·`ENGINE_SECRET` 으로 부릅니다. 엔진 배포 `bash engine/deploy_engine.sh`, 외부 경로(443 nginx) `bash engine/nginx_route.sh`.
- 로컬 테스트: `python -X utf8 -I Desktop/당근광고자동화/test_worker_local.py` (가짜 엔진 + `wrangler dev --local`, 기존 verify/admin 포함 39개 검사).
