"""
정식(회원) 인증: app_v1 / app_v2 엔트리에서 공통 사용.
"""
from __future__ import annotations

import json
import os
import sys
import uuid
import urllib.error
import urllib.request
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

# MEMBER_VERIFY_URL = "http://54.116.98.230:8000/api/v1/admin/member/verify"
MEMBER_VERIFY_URL = "https://xn--3e0bmog4l26gfxbmyfiqhm6cw2t6le.com/api/v1/admin/member/verify"
MEMBER_VERIFY_FALLBACK_URL = "https://전국부동산매물수집기.com/api/v1/admin/member/verify"
PRODUCT_URL = "https://전국부동산매물수집기.com"


def _get_mac_address() -> str:
    mac = uuid.getnode()
    mac_hex = f"{mac:012X}"
    return ":".join(mac_hex[i : i + 2] for i in range(0, 12, 2))


def _verify_member_api(username: str, password: str, mac_address: str) -> tuple[bool, str]:
    payload = {
        "username": username,
        "password": password,
        "mac_address": mac_address,
    }
    last_error = "인증 서버 연결 실패"
    for verify_url in (MEMBER_VERIFY_URL, MEMBER_VERIFY_FALLBACK_URL):
        req = urllib.request.Request(
            verify_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=12) as res:
                body = res.read().decode("utf-8", errors="replace")
                data = json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode("utf-8", errors="replace")
                data = json.loads(body) if body else {}
                msg = str(data.get("message") or "").strip()
                last_error = msg or f"인증 서버 오류(HTTP {e.code})"
            except Exception:
                last_error = f"인증 서버 오류(HTTP {e.code})"
            continue
        except Exception as e:
            last_error = f"인증 서버 연결 실패: {e}"
            continue

        ok = bool(data.get("success"))
        msg = str(data.get("message") or "").strip()
        return ok, (msg or ("인증 성공" if ok else "인증 실패"))

    return False, last_error


class LoginDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("로그인")
        self.setModal(True)
        self.resize(420, 210)
        self._verified = False

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title = QLabel("프로그램 사용을 위해 로그인하세요.")
        title.setStyleSheet("font-weight:700;")
        root.addWidget(title)

        row_id = QHBoxLayout()
        row_id.addWidget(QLabel("아이디"), 0)
        self.edt_id = QLineEdit()
        self.edt_id.setPlaceholderText("회원 아이디")
        row_id.addWidget(self.edt_id, 1)
        root.addLayout(row_id)

        row_pw = QHBoxLayout()
        row_pw.addWidget(QLabel("비밀번호"), 0)
        self.edt_pw = QLineEdit()
        self.edt_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.edt_pw.setPlaceholderText("비밀번호")
        row_pw.addWidget(self.edt_pw, 1)
        root.addLayout(row_pw)

        self.info_label = QLabel(
            f'회원이 아니신가요? <a href="{PRODUCT_URL}">{PRODUCT_URL}</a>'
        )
        self.info_label.setOpenExternalLinks(True)
        self.info_label.setTextFormat(Qt.RichText)
        root.addWidget(self.info_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.btn_cancel = QPushButton("종료")
        self.btn_login = QPushButton("로그인")
        self.btn_login.setDefault(True)
        btn_row.addWidget(self.btn_cancel)
        btn_row.addWidget(self.btn_login)
        root.addLayout(btn_row)

        self.btn_cancel.clicked.connect(self.reject)
        self.btn_login.clicked.connect(self._on_login_clicked)
        self.edt_id.returnPressed.connect(lambda: self.edt_pw.setFocus())

    @property
    def verified(self) -> bool:
        return self._verified

    def _on_login_clicked(self):
        username = self.edt_id.text().strip()
        password = self.edt_pw.text().strip()
        if not username or not password:
            QMessageBox.warning(self, "로그인 실패", "아이디와 비밀번호를 입력하세요.")
            return
        ok, message = _verify_member_api(username, password, _get_mac_address())
        if ok:
            self._verified = True
            self.accept()
            return
        QMessageBox.warning(
            self,
            "로그인 실패",
            f"{message}\n\n이용권 구매: {PRODUCT_URL}",
        )


def _run_member_login_gate(app: QApplication) -> bool:
    dlg = LoginDialog()
    if dlg.exec() == QDialog.DialogCode.Accepted and dlg.verified:
        return True
    return False


def run_member_app(
    *,
    app_name: str,
    create_main_window: Callable[[], QWidget],
    base_dir: str,
    app: Optional[QApplication] = None,
) -> None:
    from codecoon_server_manager.auth import check_auth

    # check_auth(app_name, "김재원", 365)
    qapp = app or QApplication(sys.argv)
    if not _run_member_login_gate(qapp):
        sys.exit(0)
    icon_path = os.path.join(base_dir, "asset", "CodeCoon_profile.ico")
    if os.path.exists(icon_path):
        app_icon = QIcon(icon_path)
        qapp.setWindowIcon(app_icon)
    else:
        app_icon = QIcon()
    qapp.setFont(QFont("Segoe UI", 10))
    win = create_main_window()
    if not app_icon.isNull():
        win.setWindowIcon(app_icon)
    win.show()
    sys.exit(qapp.exec())
