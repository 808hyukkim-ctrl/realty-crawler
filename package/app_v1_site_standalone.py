"""
v1 site 실행 엔트리 - 완전 독립 버전 (codecoon_server_manager 의존 없음).
메인 UI는 app_v1_site_main.MainWindow.

인증은 자체 license_server(Flask 관리자 웹)로 검증한다 (license_gate.py).
--run-all / --run-job "예약이름" 을 붙이면 무인 실행(윈도우 작업 스케줄러용).
"""
from __future__ import annotations

import os
import sys
from typing import Optional

from PySide6.QtWidgets import QApplication

from app_v1_site_main import MainWindow
from license_gate import run_licensed_app

APP_NAME = "전국부동산매물수집기_v1"


def main(app: Optional[QApplication] = None):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    argv = sys.argv[1:]
    batch = "--run-all" in argv
    job_name: Optional[str] = None
    if "--run-job" in argv:
        i = argv.index("--run-job")
        if i + 1 < len(argv):
            job_name = argv[i + 1]
            batch = True

    on_ready = (lambda win: win.run_batch(job_name)) if batch else None
    run_licensed_app(
        create_main_window=MainWindow,
        base_dir=base_dir,
        app=app,
        auto_login=batch,
        minimized=batch,
        on_ready=on_ready,
    )


if __name__ == "__main__":
    main()
