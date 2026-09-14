"""
v2 무료체험 실행 엔트리. 메인 UI는 app_v2_main.MainWindow.
"""
from __future__ import annotations

import os
from typing import Optional

from PySide6.QtWidgets import QApplication

from app_v2_main import MainWindow
from free_trial_app_shared import run_free_trial_app

# FREE_TRIAL_URL = "http://54.116.98.230:8000/api/v1/admin/member/free-trial"
FREE_TRIAL_URL = "https://xn--3e0bmog4l26gfxbmyfiqhm6cw2t6le.com/api/v1/admin/member/free-trial"
FREE_TRIAL_FALLBACK_URL = "https://전국부동산매물수집기.com/api/v1/admin/member/free-trial"
PRODUCT_URL = "https://전국부동산매물수집기.com"


def main(app: Optional[QApplication] = None):
    run_free_trial_app(
        app_name="전국부동산매물수집기_v2_무료체험",
        product_url=PRODUCT_URL,
        verify_url=FREE_TRIAL_URL,
        fallback_url=FREE_TRIAL_FALLBACK_URL,
        create_main_window=MainWindow,
        base_dir=os.path.dirname(os.path.abspath(__file__)),
        app=app,
    )


if __name__ == "__main__":
    main()
