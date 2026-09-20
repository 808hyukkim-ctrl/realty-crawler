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
