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
