# 전국부동산매물수집기 — 독립 실행 버전

## 뭐가 달라졌나
- `app_v1_site_no_auth.py`를 기반으로 `app_v1_site_standalone.py`를 새로 만들고,
  `codecoon_server_manager` 관련 import를 완전히 제거했습니다.
- UI, 크롤러(당근/네이버/피터팬/온하우스), 키워드 필터, 시간예약추출 기능은 원본과 100% 동일합니다.
- `app_v1_site_standalone.spec` — 이 새 엔트리로 빌드하는 PyInstaller 스펙 파일입니다.

## Windows에서 .exe 만들기
저는 리눅스 환경이라 여기서는 진짜 동작하는 Windows .exe를 만들 수 없습니다
(PyInstaller는 빌드를 실행하는 OS용 결과물만 만듭니다 — 크로스 컴파일 불가).
그래서 여기서는 전체 빌드 파이프라인이 문제없이 끝까지 도는 것까지 리눅스용 실행파일로
직접 확인했고, 재원님 PC(Windows)에서는 아래만 하면 됩니다.

1. 이 폴더를 통째로 재원님 Windows PC로 복사
2. Python 3.11 이상 설치되어 있는지 확인
3. `build_standalone.bat` 더블클릭 (또는 cmd에서 실행)
4. 끝나면 `dist\전국부동산매물수집기_독립버전.exe` 실행

## 참고
- `codecoon_server_manager`가 PC에 없어도 이제 정상 동작합니다.
- 회원 로그인 창은 뜨지 않습니다 (원본 `_no_auth` 버전과 동일).
- 다른 버전(v2, free_trial 등)도 같은 방식으로 만들 수 있으니 필요하면 말씀해주세요.
