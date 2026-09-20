"""
독립버전 전용 라이선스 로그인 게이트.

codecoon_server_manager 에 대한 의존이 전혀 없다 (완전 독립 실행 가능).
license_server(Flask 관리자 웹)의 /api/v1/verify API를 호출해 아이디/비밀번호/
이용권 만료 여부를 확인한다.

배포 시 VERIFY_URL 을 실제 서버 주소로 바꾼 뒤 다시 빌드하면 된다.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import uuid
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

VERIFY_URL = os.environ.get(
    "LICENSE_VERIFY_URL", "https://realty-license-server.808hyukkim.workers.dev/api/v1/verify"
)


def _cred_store_path(base_dir: str) -> str:
    # onefile exe에서는 base_dir이 임시 해제 폴더(_MEIPASS)라 실행 후 삭제됨 →
    # 저장 파일은 exe가 있는 실제 폴더에 둔다.
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(sys.executable)
    return os.path.join(base_dir, "login_saved.json")


def _load_saved_credentials(path: str) -> tuple[str, str, bool]:
    """저장된 아이디/비밀번호 로드. 없거나 손상 시 ('', '', False)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        uid = str(data.get("id") or "")
        pwd = base64.b64decode(str(data.get("pw") or "")).decode("utf-8")
        if uid and pwd:
            return uid, pwd, True
    except Exception:
        pass
    return "", "", False


def _save_credentials(path: str, uid: str, pwd: str) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {"id": uid, "pw": base64.b64encode(pwd.encode("utf-8")).decode("ascii")},
                f,
                ensure_ascii=False,
            )
    except Exception:
        pass


def _delete_credentials(path: str) -> None:
    try:
        if os.path.isfile(path):
            os.remove(path)
    except Exception:
        pass


def _get_mac_address() -> str:
    mac = uuid.getnode()
    mac_hex = f"{mac:012X}"
    return ":".join(mac_hex[i : i + 2] for i in range(0, 12, 2))


def _format_expiry_readable(iso_str: Optional[str]) -> str:
    if not iso_str:
        return "무제한"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone()
        return f"{local.year}년 {local.month}월 {local.day}일 {local.hour:02d}시 {local.minute:02d}분까지"
    except Exception:
        return iso_str


def _verify_license_api(username: str, password: str, mac_address: str) -> tuple[bool, str, Optional[str]]:
    payload = {"username": username, "password": password, "mac_address": mac_address}
    req = urllib.request.Request(
        VERIFY_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            # 기본 Python UA는 Cloudflare 봇 차단(오류 1010)에 걸리므로 브라우저처럼 위장.
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        },
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
            return False, (msg or f"인증 서버 오류(HTTP {e.code})"), None
        except Exception:
            return False, f"인증 서버 오류(HTTP {e.code})", None
    except Exception as e:
        return False, f"인증 서버 연결 실패: {e}", None

    ok = bool(data.get("success"))
    msg = str(data.get("message") or "").strip()
    expires_at = data.get("expires_at")
    return ok, (msg or ("인증 성공" if ok else "인증 실패")), expires_at


class LicenseLoginDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None, cred_path: Optional[str] = None):
        super().__init__(parent)
        self.setWindowTitle("로그인")
        self.setModal(True)
        # 다른 창 뒤에 숨지 않도록 항상 위 + 최소화(-) 버튼 제공
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.resize(420, 240)
        self._verified = False
        self._cred_path = cred_path

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title = QLabel("프로그램 사용을 위해 로그인하세요.")
        title.setStyleSheet("font-weight:700;")
        root.addWidget(title)

        row_id = QHBoxLayout()
        row_id.addWidget(QLabel("아이디"), 0)
        self.edt_id = QLineEdit()
        self.edt_id.setPlaceholderText("발급받은 아이디")
        row_id.addWidget(self.edt_id, 1)
        root.addLayout(row_id)

        row_pw = QHBoxLayout()
        row_pw.addWidget(QLabel("비밀번호"), 0)
        self.edt_pw = QLineEdit()
        self.edt_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.edt_pw.setPlaceholderText("비밀번호")
        row_pw.addWidget(self.edt_pw, 1)
        root.addLayout(row_pw)

        self.chk_remember = QCheckBox("아이디/비밀번호 기억")
        root.addWidget(self.chk_remember)

        if self._cred_path:
            uid, pwd, found = _load_saved_credentials(self._cred_path)
            if found:
                self.edt_id.setText(uid)
                self.edt_pw.setText(pwd)
                self.chk_remember.setChecked(True)

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
        self.edt_pw.returnPressed.connect(self._on_login_clicked)

    @property
    def verified(self) -> bool:
        return self._verified

    def _on_login_clicked(self):
        username = self.edt_id.text().strip()
        password = self.edt_pw.text().strip()
        if not username or not password:
            QMessageBox.warning(self, "로그인 실패", "아이디와 비밀번호를 입력하세요.")
            return
        ok, message, expires_at = _verify_license_api(username, password, _get_mac_address())
        if ok:
            self._verified = True
            if self._cred_path:
                if self.chk_remember.isChecked():
                    _save_credentials(self._cred_path, username, password)
                else:
                    _delete_credentials(self._cred_path)
            QMessageBox.information(
                self, "로그인 성공", f"{message}\n\n이용권 만료: {_format_expiry_readable(expires_at)}"
            )
            self.accept()
            return
        QMessageBox.warning(self, "로그인 실패", message)


def run_licensed_app(
    *,
    create_main_window: Callable[[], QWidget],
    base_dir: str,
    app: Optional[QApplication] = None,
    auto_login: bool = False,
    minimized: bool = False,
    on_ready: Optional[Callable[[QWidget], None]] = None,
) -> None:
    qapp = app or QApplication(sys.argv)

    dlg = LicenseLoginDialog(cred_path=_cred_store_path(base_dir))

    # 무인 실행(작업 스케줄러): 저장된 아이디/비밀번호로 창 없이 로그인 시도
    if auto_login and dlg.edt_id.text().strip() and dlg.edt_pw.text().strip():
        try:
            dlg._on_login_clicked()
        except Exception:
            pass
        if dlg.verified:
            _start_main(qapp, create_main_window, base_dir, minimized, on_ready)
            return

    def _bring_front():
        try:
            dlg.showNormal()
            dlg.raise_()
            dlg.activateWindow()
        except Exception:
            pass

    QTimer.singleShot(0, _bring_front)
    QTimer.singleShot(400, _bring_front)  # onefile exe 압축 해제 직후 포커스를 다른 창에 뺏기는 경우 대비
    if not (dlg.exec() == QDialog.DialogCode.Accepted and dlg.verified):
        sys.exit(0)

    _start_main(qapp, create_main_window, base_dir, minimized, on_ready)


def _start_main(
    qapp: QApplication,
    create_main_window: Callable[[], QWidget],
    base_dir: str,
    minimized: bool = False,
    on_ready: Optional[Callable[[QWidget], None]] = None,
) -> None:
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
    if minimized:
        win.showMinimized()
    else:
        win.show()
        win.raise_()
        win.activateWindow()
    if on_ready is not None:
        QTimer.singleShot(800, lambda: on_ready(win))
    sys.exit(qapp.exec())
