"""
v1 site 실행 엔트리 (codecoon_server_manager 인증만, 회원 로그인 없음).
메인 UI는 app_v1_site_main.MainWindow.

app_v1_site.py 와 동일하나, 회원 로그인(LoginDialog) 게이트를 제거하고
codecoon_server_manager.auth.check_auth 만 수행한다.
"""
from __future__ import annotations

import os
import sys
from typing import Optional

from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication

from app_v1_site_main import MainWindow

APP_NAME = "전국부동산매물수집기_v1"


def main(app: Optional[QApplication] = None):
    from codecoon_server_manager.auth import check_auth

    # check_auth(APP_NAME, "김재원", 365)

    base_dir = os.path.dirname(os.path.abspath(__file__))
    qapp = app or QApplication(sys.argv)

    icon_path = os.path.join(base_dir, "asset", "CodeCoon_profile.ico")
    if os.path.exists(icon_path):
        app_icon = QIcon(icon_path)
        qapp.setWindowIcon(app_icon)
    else:
        app_icon = QIcon()

    qapp.setFont(QFont("Segoe UI", 10))
    win = MainWindow()
    if not app_icon.isNull():
        win.setWindowIcon(app_icon)
    win.show()
    sys.exit(qapp.exec())


if __name__ == "__main__":
    main()
