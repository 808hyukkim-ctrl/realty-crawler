# Cython으로 app_v2_free_trial 등이 .pyd만 남을 때 엔트리용 (PyInstaller 진입점)
import cython_bundle_deps_free_trial  # noqa: F401

from app_v2_free_trial import main

if __name__ == "__main__":
    main()
