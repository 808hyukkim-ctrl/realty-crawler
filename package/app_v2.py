"""
v2 실행 엔트리 (회원 인증). 메인 UI는 app_v2_main.MainWindow.
"""
from __future__ import annotations

import os
from typing import Optional

from PySide6.QtWidgets import QApplication

from app_v2_main import MainWindow
from member_app_shared import run_member_app


def main(app: Optional[QApplication] = None):
    run_member_app(
        app_name="전국부동산매물수집기_v2",
        create_main_window=MainWindow,
        base_dir=os.path.dirname(os.path.abspath(__file__)),
        app=app,
    )


if __name__ == "__main__":
    main()
