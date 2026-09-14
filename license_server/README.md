# 전국부동산매물수집기 라이선스 관리 서버

데스크톱 앱(독립버전)의 로그인/이용권 만료를 관리하는 Flask 기반 관리자 웹 + API입니다.

## 로컬 실행 (테스트용)

```
pip install -r requirements.txt
python app.py
```

기본 포트 8787, 브라우저로 `http://localhost:8787` 접속.
최초 실행 시 관리자 계정이 자동 생성됩니다 (콘솔에 출력되는 아이디/비밀번호 확인, 로그인 후 반드시 계정 설정에서 비밀번호 변경).

환경변수로 초기 관리자 계정을 지정할 수 있습니다:

```
set LICENSE_ADMIN_USER=myid
set LICENSE_ADMIN_PASSWORD=mypassword
```

## 실서버 배포

1. 서버(VPS 등)에 이 `license_server` 폴더를 업로드합니다.
2. Python 3.10+ 설치 후 `pip install -r requirements.txt`.
3. 반드시 바꿔야 하는 것:
   - `LICENSE_SECRET_KEY` 환경변수: 임의의 긴 랜덤 문자열로 설정 (세션 서명 키).
   - `LICENSE_ADMIN_USER` / `LICENSE_ADMIN_PASSWORD`: 최초 관리자 계정.
4. 운영 환경에서는 `python app.py` 대신 gunicorn 사용을 권장합니다:
   ```
   gunicorn -w 2 -b 0.0.0.0:8787 app:app
   ```
5. HTTPS가 필요하면 nginx 등 리버스 프록시 뒤에 두세요 (관리자 로그인 정보가 평문으로 오가면 안 되므로 반드시 HTTPS 권장).
6. 방화벽에서 8787(또는 원하는) 포트를 열어 데스크톱 앱들이 접근 가능하게 합니다.

## 데스크톱 앱 연동

`package/license_gate.py` 상단의 `VERIFY_URL` 을 배포한 서버 주소로 바꾸세요:

```python
VERIFY_URL = "https://your-domain-or-ip:8787/api/v1/verify"
```

바꾼 뒤 `pyinstaller --noconfirm --clean app_v1_site_standalone.spec` 로 다시 빌드하면
새 exe가 해당 서버로 로그인 인증을 요청합니다.

## 관리자 웹에서 할 수 있는 것

- 사용자(아이디/비밀번호) 등록, 이용권 기간 설정 (1일/3일/1주일/1개월/3개월/1년/무제한)
- 이용권 연장 (현재 만료일 기준으로 추가 연장)
- 계정 비활성화/활성화, 비밀번호 변경, 삭제
- 기기(MAC) 초기화 — 사용자가 PC를 바꾸거나 재설치해서 다른 기기로 인식될 때 사용
- 검색 (아이디 기준)

## 동작 방식 참고

- 사용자가 데스크톱 앱에 아이디/비밀번호를 입력하면 `/api/v1/verify` 로 아이디/비밀번호/MAC 주소를 전송합니다.
- 서버는 아이디/비밀번호가 맞고, 계정이 활성 상태이고, 이용권이 만료 전이면 인증을 통과시킵니다.
- 최초 로그인 시 MAC 주소가 자동으로 계정에 바인딩됩니다. 이후 다른 기기에서 로그인하려 하면 거부됩니다
  (동일 계정 여러 PC 공유 방지). 기기를 바꾸려면 관리자가 "기기초기화" 버튼을 눌러줘야 합니다.
