# Cython으로 app_v1_site_no_auth 등이 .pyd만 남을 때 엔트리용 (PyInstaller 진입점)
import cython_bundle_deps  # noqa: F401 — PyInstaller가 .pyd 내부 import를 못 읽어 번들용

from app_v1_site_no_auth import main

if __name__ == "__main__":
    main()
