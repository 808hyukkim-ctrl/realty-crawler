# -*- coding: utf-8 -*-
"""
수집 결과 엑셀 자동 전송 (메일 · 텔레그램).

- 메일: Gmail SMTP(SSL 465). 보내는 계정은 2단계 인증 + '앱 비밀번호'(16자리)가 필요하다.
        일반 비밀번호로는 구글이 로그인을 막는다. 첨부 25MB 제한.
- 텔레그램: 봇 API sendDocument. 봇 토큰 + 챗 ID 필요. 파일 50MB 제한.
둘 다 무료이고, 설정은 exe 옆 onhouse_send.json 에 저장된다.
"""
from __future__ import annotations

import json
import mimetypes
import os
import smtplib
from email.message import EmailMessage
from typing import Any, Callable, Dict, List

import requests

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"

MAIL_LIMIT = 25 * 1024 * 1024
TELEGRAM_LIMIT = 50 * 1024 * 1024

DEFAULTS: Dict[str, Any] = {
    "mail_on": False,
    "mail_from": "",
    "mail_pw": "",
    "mail_to": "",
    "tg_on": False,
    "tg_token": "",
    "tg_chat": "",
}


def load_config(path: str) -> Dict[str, Any]:
    cfg = dict(DEFAULTS)
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                cfg.update(json.load(f) or {})
    except Exception:
        pass
    return cfg


def save_config(path: str, cfg: Dict[str, Any]) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({k: cfg.get(k, v) for k, v in DEFAULTS.items()}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _recipients(raw: str) -> List[str]:
    parts = [p.strip() for p in str(raw or "").replace(";", ",").replace(" ", ",").split(",")]
    return [p for p in parts if p]


def send_mail(cfg: Dict[str, Any], file_path: str, subject: str, body: str) -> str:
    """성공하면 '메일 전송 완료: a@b.com 외 1명', 실패하면 '메일 전송 실패: 이유'."""
    sender = str(cfg.get("mail_from", "")).strip()
    pw = str(cfg.get("mail_pw", "")).replace(" ", "")
    to = _recipients(cfg.get("mail_to"))
    if not sender or not pw or not to:
        return "메일 전송 건너뜀: 보내는 주소 · 앱 비밀번호 · 받는 사람을 모두 입력하세요."
    size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
    if size > MAIL_LIMIT:
        return f"메일 전송 실패: 첨부가 25MB를 넘습니다 ({size / 1048576:.1f}MB). 텔레그램으로 받으세요."

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(to)
    msg.set_content(body)
    ctype, _ = mimetypes.guess_type(file_path)
    maintype, _, subtype = (ctype or "application/octet-stream").partition("/")
    with open(file_path, "rb") as f:
        msg.add_attachment(f.read(), maintype=maintype, subtype=subtype, filename=os.path.basename(file_path))

    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=60) as s:
            s.login(sender, pw)
            s.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        return "메일 전송 실패: 로그인 거부 — 구글 2단계 인증을 켜고 '앱 비밀번호' 16자리를 넣으세요."
    except Exception as e:
        return f"메일 전송 실패: {e}"
    head = to[0] + (f" 외 {len(to) - 1}명" if len(to) > 1 else "")
    return f"메일 전송 완료: {head}"


def send_telegram(cfg: Dict[str, Any], file_path: str, caption: str) -> str:
    token = str(cfg.get("tg_token", "")).strip()
    chat = str(cfg.get("tg_chat", "")).strip()
    if not token or not chat:
        return "텔레그램 전송 건너뜀: 봇 토큰과 챗 ID를 입력하세요."
    size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
    if size > TELEGRAM_LIMIT:
        return f"텔레그램 전송 실패: 파일이 50MB를 넘습니다 ({size / 1048576:.1f}MB)."
    try:
        with open(file_path, "rb") as f:
            r = requests.post(
                TELEGRAM_API.format(token=token, method="sendDocument"),
                data={"chat_id": chat, "caption": caption[:1000]},
                files={"document": (os.path.basename(file_path), f)},
                timeout=120,
            )
        d = r.json()
        if not d.get("ok"):
            return f"텔레그램 전송 실패: {d.get('description') or r.status_code}"
    except Exception as e:
        return f"텔레그램 전송 실패: {e}"
    return "텔레그램 전송 완료"


def find_chat_id(token: str) -> str:
    """봇에게 아무 메시지나 보낸 뒤 호출하면 그 대화방의 챗 ID를 돌려준다."""
    token = str(token or "").strip()
    if not token:
        return "봇 토큰을 먼저 입력하세요."
    try:
        r = requests.get(TELEGRAM_API.format(token=token, method="getUpdates"), timeout=30)
        d = r.json()
    except Exception as e:
        return f"조회 실패: {e}"
    if not d.get("ok"):
        return f"조회 실패: {d.get('description') or '토큰을 확인하세요.'}"
    for item in reversed(d.get("result") or []):
        msg = item.get("message") or item.get("channel_post") or {}
        chat = msg.get("chat") or {}
        if chat.get("id") is not None:
            return str(chat["id"])
    return "대화 기록이 없습니다. 텔레그램에서 봇에게 아무 메시지나 보낸 뒤 다시 누르세요."


def deliver(cfg: Dict[str, Any], file_path: str, caption: str, log: Callable[[str], None]) -> None:
    """수집이 끝난 뒤 호출. 켜져 있는 경로로만 보내고 결과를 로그로 남긴다."""
    if not cfg:
        return
    if not os.path.exists(file_path):
        log("자동 전송 건너뜀: 저장된 파일을 찾지 못했습니다.")
        return
    if cfg.get("mail_on"):
        log("  " + send_mail(cfg, file_path, caption, caption + "\n\n온하우스 매물수집기에서 자동 발송했습니다."))
    if cfg.get("tg_on"):
        log("  " + send_telegram(cfg, file_path, caption))


# ──────────────────────────────────────────────────────────────────────────
# 텔레그램으로 수집 명령 받기 (2026-10-06)
#   봇에게 "목록" → 예약 목록 / "실행 <예약이름>" (또는 "뽑아 <이름>", "수집 <이름>") → 그 예약을 바로 실행.
#   프로그램이 켜져 있는 동안 10초마다 getUpdates 로 확인. 자동 전송 탭에 적힌 챗 ID 에서 온 메시지만 받는다.
#   네트워크는 작업 스레드에서, 실행은 호출한 쪽(UI 스레드)이 poll() 로 가져가 처리한다.
# ──────────────────────────────────────────────────────────────────────────
import threading as _threading


class TelegramCommander:
    HELP = "명령: 목록 — 예약 목록 / 실행 <예약이름> — 그 예약으로 지금 수집 (뽑아 <이름>, 수집 <이름> 도 됨) / 도움"

    def __init__(self, get_cfg: Callable[[], Dict[str, Any]], app_label: str = "매물수집기"):
        self.get_cfg = get_cfg
        self.app_label = app_label
        self.offset: int | None = None       # 다음 조회의 offset (2분 지난 메시지까지 확인한 뒤의 값)
        self._seen_ids: set = set()
        self._pending: List[Dict[str, Any]] = []
        self._lock = _threading.Lock()
        self._busy = False
        self._primed = False

    # ---- 네트워크 (작업 스레드) ----
    def _api(self, method: str, **params):
        token = str(self.get_cfg().get("tg_token", "")).strip()
        if not token:
            return None
        try:
            r = requests.post(TELEGRAM_API.format(token=token, method=method), data=params, timeout=25)
            return r.json()
        except Exception:
            return None

    def reply(self, text: str) -> None:
        chat = str(self.get_cfg().get("tg_chat", "")).strip()
        if not chat:
            return
        _threading.Thread(target=self._api, args=("sendMessage",), kwargs={"chat_id": chat, "text": text[:3900]}, daemon=True).start()

    def _fetch(self) -> None:
        """텔레그램 getUpdates. 봇 하나를 여러 프로그램(온하우스·통합 수집기)이 같이 보므로, 메시지를 바로 '확인(offset)' 하지 않고
        2분 지난 것만 확인한다 → 모든 프로그램이 같은 명령을 받을 수 있다. 같은 메시지는 update_id 로 한 번만 처리."""
        try:
            import time as _time
            d = self._api("getUpdates", timeout=0, **({"offset": self.offset} if self.offset else {}))
            if not d or not d.get("ok"):
                return
            chat_ok = str(self.get_cfg().get("tg_chat", "")).strip()
            now = _time.time()
            confirm_upto = None
            for item in d.get("result") or []:
                uid = int(item.get("update_id", 0))
                msg = item.get("message") or {}
                ts = float(msg.get("date") or 0)
                if ts and now - ts > 120:
                    confirm_upto = max(confirm_upto or 0, uid)   # 2분 지난 메시지는 다음 조회부터 안 받도록 확인
                if uid in self._seen_ids:
                    continue
                self._seen_ids.add(uid)
                if not self._primed or (ts and now - ts > 120):
                    continue   # 프로그램 켜기 전에 쌓인 옛 메시지는 무시
                chat = str((msg.get("chat") or {}).get("id", ""))
                text = str(msg.get("text") or "").strip()
                if not text or (chat_ok and chat != chat_ok):
                    continue
                with self._lock:
                    self._pending.append({"text": text, "chat": chat})
            if confirm_upto is not None:
                self.offset = confirm_upto + 1
            if len(self._seen_ids) > 2000:
                self._seen_ids = set(sorted(self._seen_ids)[-500:])
            self._primed = True
        finally:
            self._busy = False

    # ---- UI 스레드에서 주기적으로 ----
    def poll(self) -> List[Dict[str, Any]]:
        """새 명령 목록을 돌려주고, 백그라운드로 다음 조회를 시작한다."""
        cfg = self.get_cfg()
        if not str(cfg.get("tg_token", "")).strip():
            return []
        with self._lock:
            out, self._pending = self._pending, []
        if not self._busy:
            self._busy = True
            _threading.Thread(target=self._fetch, daemon=True).start()
        return out

    @staticmethod
    def parse(text: str):
        """('list'|'run'|'help'|None, 인자)"""
        t = text.strip().lstrip("/").strip()
        if not t:
            return None, ""
        head, _, rest = t.partition(" ")
        head = head.strip().lower()
        if head in ("목록", "list", "예약"):
            return "list", ""
        if head in ("도움", "help", "명령"):
            return "help", ""
        if head in ("실행", "뽑아", "수집", "run", "시작"):
            return "run", rest.strip()
        return None, t
