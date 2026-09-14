from __future__ import annotations

import json
import os
import sys
import uuid
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
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


def _get_mac_address() -> str:
    mac = uuid.getnode()
    mac_hex = f"{mac:012X}"
    return ":".join(mac_hex[i : i + 2] for i in range(0, 12, 2))


def _format_trial_expires_readable(iso_str: str) -> str:
    s = (iso_str or "").strip()
    if not s:
        return ""
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        kst = timezone(timedelta(hours=9))
        local = dt.astimezone(kst)
        return (
            f"{local.year}년 {local.month}월 {local.day}일 "
            f"{local.hour:02d}시 {local.minute:02d}분까지 (한국시각)"
        )
    except Exception:
        return s


def _verify_free_trial_api(
    username: str,
    password: str,
    mac_address: str,
    verify_url: str,
    fallback_url: str,
) -> tuple[bool, str, Optional[str]]:
    payload = {
        "username": username,
        "password": password,
        "mac_address": mac_address,
    }
    last_error = "인증 서버 연결 실패"
    for url in (verify_url, fallback_url):
        req = urllib.request.Request(
            url,
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
        trial_expires = data.get("trial_expires_at")
        trial_expires_s = str(trial_expires).strip() if trial_expires else None
        return ok, (msg or ("무료체험 인증 성공" if ok else "무료체험 인증 실패")), trial_expires_s

    return False, last_error, None


class FreeTrialLoginDialog(QDialog):
    def __init__(
        self,
        product_url: str,
        verify_url: str,
        fallback_url: str,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._product_url = product_url
        self._verify_url = verify_url
        self._fallback_url = fallback_url
        self.setWindowTitle("무료체험 로그인")
        self.setModal(True)
        self.resize(420, 210)
        self._verified = False

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title = QLabel("무료체험 이용을 위해 로그인하세요.")
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

        info_label = QLabel(
            f'회원이 아니신가요? <a href="{product_url}">{product_url}</a>'
        )
        info_label.setOpenExternalLinks(True)
        info_label.setTextFormat(Qt.RichText)
        root.addWidget(info_label)

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
        ok, message, trial_expires_at = _verify_free_trial_api(
            username,
            password,
            _get_mac_address(),
            self._verify_url,
            self._fallback_url,
        )
        if ok:
            self._verified = True
            if trial_expires_at:
                QMessageBox.information(
                    self,
                    "무료체험",
                    f"{message}\n\n체험 만료: {_format_trial_expires_readable(trial_expires_at)}",
                )
            self.accept()
            return
        QMessageBox.warning(
            self,
            "무료체험 실패",
            f"{message}\n\n이용권 구매: {self._product_url}",
        )


def run_free_trial_app(
    *,
    app_name: str,
    product_url: str,
    verify_url: str,
    fallback_url: str,
    create_main_window: Callable[[], QWidget],
    base_dir: str,
    app: Optional[QApplication] = None,
) -> None:
    from codecoon_server_manager.auth import check_auth

    check_auth(app_name, "김재원", 365)

    qapp = app or QApplication(sys.argv)
    dlg = FreeTrialLoginDialog(product_url, verify_url, fallback_url)
    if not (dlg.exec() == QDialog.DialogCode.Accepted and dlg.verified):
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
