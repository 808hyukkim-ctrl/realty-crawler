# -*- coding: utf-8 -*-
"""매물사진 950 변환기 — 매물 링크를 주면 그 페이지의 사진만 가져와 가로 950px 로 바꿔 저장한다.

지원 링크
  · 네이버부동산 (new.land / m.land / fin.land, articleNo=…)  → 매물 API 의 사진 목록(원본 1500px)
  · 당근 부동산 (realty.daangn.com/articles/…)               → 정리 워커(/parse) 가 주는 사진 주소(원본)
  · 온하우스 (onhouse.com/index/rent_view/…)                → 유료 계정 로그인 뒤 상세의 cloudfront 사진(원본)
  · 그 밖의 사이트                                           → 페이지의 og:image / <img> (작은 아이콘 제외)
저장: 폴더\\<사이트>_<매물번호>\\01.jpg … (가로 950, 세로는 비율 · 세로를 정하면 가운데 잘라 맞춤)
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from curl_cffi import requests as cr
from PIL import Image, ImageOps
from PySide6.QtCore import QObject, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from app_main_common import APP_STYLESHEET
from onhouse_crawler import OnhouseCrawler

APP_TITLE = "매물사진 950 변환기"
PARSE_API = "https://bridge-parse.808hyukkim.workers.dev/parse"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
# 네이버 매물 API 는 쿠키 묶음 + 원래 Referer + 이 UA 가 전부 있어야 200 (정리 워커와 같은 값)
NAVER_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "ko-KR,ko;q=0.8,en-US;q=0.5,en;q=0.3",
    "Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6IlJFQUxFU1RBVEUiLCJpYXQiOjE3NTE5NDU0MzcsImV4cCI6MTc1MTk1NjIzN30.UOlh5J9b7Eq7G9mA2d2Yya0SSV5mjMOTj9oKJQXt0WY",
    "Cookie": "NNB=DHVGK5NIFRZGQ; BUC=dQnzU4cEAFITbLHCXx2pf6SBlHnD1zsFqd72oOrN3W4=; landHomeFlashUseYn=Y; REALESTATE=Tue%20Jul%2008%202025%2012%3A30%3A37%20GMT%2B0900%20(Korean%20Standard%20Time)",
    "Referer": "https://new.land.naver.com/rooms?ms=37.3595704,127.105399,16&a=APT:OPST:VL:OR&e=RETAIL",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:139.0) Gecko/20100101 Firefox/139.0",
}
MIN_SIDE = 400            # 이보다 작은 그림(아이콘·버튼·아바타)은 버린다
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")


def base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def safe_name(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "_", str(s or "")).strip("_")[:60] or "사진"


# ---------------------------------------------------------------- 링크 → 사진 주소 목록
def naver_no(url: str) -> str:
    m = re.search(r"articleNo=(\d{6,})", url) or re.search(r"land\.naver\.com/.*?/(?:article(?:s|/info)?)/(\d{6,})", url) \
        or re.search(r"land\.naver\.com/article(?:s|/info)?/(\d{6,})", url)
    return m.group(1) if m else ""


def daangn_id(url: str) -> str:
    m = re.search(r"daangn\.com/(?:kr/)?(?:realty/)?articles/(\d+)", url)
    return m.group(1) if m else ""


def onhouse_id(url: str) -> str:
    m = re.search(r"onhouse\.com/index/rent_view/(\d+)", url)
    return m.group(1) if m else ""


def photos_naver(no: str) -> Tuple[str, List[str]]:
    r = None
    for attempt in range(3):   # 네이버는 연속 요청에 429 를 내므로 조금 쉬었다 다시
        r = cr.get(f"https://new.land.naver.com/api/articles/{no}?complexNo=", headers=NAVER_HEADERS, impersonate="chrome", timeout=25)
        if r.status_code != 429:
            break
        time.sleep(20 * (attempt + 1))
    if r.status_code == 429:
        # 이 PC 가 잠시 막혔으면 정리 워커(다른 IP)를 거쳐 사진 목록만 받는다
        w = cr.get(PARSE_API, params={"no": no}, impersonate="chrome", timeout=40)
        wj = w.json() if w.status_code == 200 else {}
        if wj.get("photos"):
            title = str(wj.get("building") or wj.get("address_q") or "").strip()
            return f"네이버_{no}" + (f"_{safe_name(title)}" if title else ""), dedupe([str(u) for u in wj["photos"]])
        raise RuntimeError("네이버가 잠시 요청을 막았습니다 (429). 1~2분 뒤 다시 해주세요")
    r.raise_for_status()
    j = r.json()
    urls: List[str] = []
    for p in j.get("articlePhotos") or []:
        src = str(p.get("imageSrc") or "").strip()
        if src:
            urls.append("https://landthumb-phinf.pstatic.net" + src)   # 크기 인자 없이 = 원본
    rep = str((j.get("articleAddition") or {}).get("representativeImgUrl") or "")
    if rep and not urls:
        urls.append("https://landthumb-phinf.pstatic.net" + rep)
    ad = j.get("articleDetail") or {}
    title = str(ad.get("articleName") or ad.get("exposureAddress") or "").strip()
    return f"네이버_{no}" + (f"_{safe_name(title)}" if title else ""), dedupe(urls)


def photos_daangn(aid: str, url: str) -> Tuple[str, List[str]]:
    r = cr.get(PARSE_API, params={"url": url}, impersonate="chrome", timeout=40)
    j = r.json()
    if j.get("error"):
        raise RuntimeError(f"당근 링크 읽기 실패: {j['error']}")
    urls = [str(u).split("?")[0] for u in (j.get("photos") or []) if u]   # 크기 인자 제거 = 원본
    title = str(j.get("building") or j.get("address_q") or "").strip()
    return f"당근_{aid}" + (f"_{safe_name(title)}" if title else ""), dedupe(urls)


def photos_onhouse(hid: str, crawler: OnhouseCrawler) -> Tuple[str, List[str]]:
    html = crawler.fetch_detail(hid)
    if len(html) < 400 and ("로그인" in html or "유료" in html):
        raise RuntimeError("온하우스 상세를 열 수 없습니다 — 유료 회원사 계정으로 로그인해야 합니다")
    seen: Dict[str, str] = {}
    # 매물 사진은 room_img/, 건물 사진은 building_img/ 아래 (…_resize.jpg). ?w=… 를 떼면 원본
    for m in re.finditer(r"https://[a-z0-9.-]+\.cloudfront\.net/(?:room_img|building_img|[a-z_]*img)/([A-Za-z0-9_-]+\.(?:jpg|jpeg|png|webp))", html, re.I):
        seen.setdefault(m.group(1).lower(), m.group(0) + "?w=1900")   # CDN 리사이저에 큰 폭을 요청해 받은 뒤 950 으로 줄인다
    title = ""
    tm = re.search(r'class="addr_title"[^>]*>\s*([^<]+)<', html)
    if tm:
        title = tm.group(1).strip()
    return f"온하우스_{hid}" + (f"_{safe_name(title)}" if title else ""), list(seen.values())


def photos_generic(url: str) -> Tuple[str, List[str]]:
    r = cr.get(url, headers={"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"}, impersonate="chrome", timeout=30)
    r.raise_for_status()
    html = r.text
    cands: List[str] = []
    for m in re.finditer(r'<meta[^>]+property=["\']og:image(?::secure_url)?["\'][^>]+content=["\']([^"\']+)', html, re.I):
        cands.append(m.group(1))
    for m in re.finditer(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image', html, re.I):
        cands.append(m.group(1))
    for m in re.finditer(r"<img\b[^>]*>", html, re.I):
        tag = m.group(0)
        srcset = re.search(r'srcset=["\']([^"\']+)', tag, re.I)
        if srcset:   # 가장 큰 후보
            best, bw = "", -1
            for part in srcset.group(1).split(","):
                bits = part.strip().split()
                if not bits:
                    continue
                w = int(re.sub(r"\D", "", bits[1]) or 0) if len(bits) > 1 else 0
                if w > bw:
                    best, bw = bits[0], w
            if best:
                cands.append(best)
        for attr in ("data-original", "data-src", "data-lazy-src", "data-url", "src"):
            a = re.search(attr + r'=["\']([^"\']+)', tag, re.I)
            if a and not a.group(1).startswith("data:"):
                cands.append(a.group(1))
                break
    for m in re.finditer(r'background(?:-image)?\s*:\s*url\(["\']?([^"\')]+)', html, re.I):
        cands.append(m.group(1))
    urls = [urljoin(url, c.strip()) for c in cands if c and not c.strip().startswith("data:")]
    urls = [u for u in urls if u.startswith("http")]
    host = urlparse(url).netloc.replace("www.", "")
    tm = re.search(r"<title[^>]*>\s*([^<]{1,60})", html, re.I)
    title = tm.group(1).strip() if tm else ""
    return f"{safe_name(host)}" + (f"_{safe_name(title)}" if title else "") + f"_{datetime.now():%H%M%S}", dedupe(urls)


def dedupe(urls: List[str]) -> List[str]:
    out, seen = [], set()
    for u in urls:
        k = u.split("?")[0]
        if k in seen:
            continue
        seen.add(k)
        out.append(u)
    return out


# ---------------------------------------------------------------- 내려받기 + 크기 변환
def fetch_image(url: str, referer: str = "") -> Optional[Image.Image]:
    headers = {"User-Agent": UA, "Accept": "image/avif,image/webp,image/*,*/*;q=0.8"}
    if referer:
        headers["Referer"] = referer
    r = cr.get(url, headers=headers, impersonate="chrome", timeout=40)
    if r.status_code != 200 or not r.content:
        return None
    try:
        im = Image.open(io.BytesIO(r.content))
        im.load()
        return im
    except Exception:
        return None


def resize_to(im: Image.Image, width: int, height: int = 0) -> Image.Image:
    im = ImageOps.exif_transpose(im)
    if im.mode not in ("RGB", "L"):
        bg = Image.new("RGB", im.size, (255, 255, 255))
        try:
            bg.paste(im, mask=im.convert("RGBA").split()[-1])
        except Exception:
            bg.paste(im.convert("RGB"))
        im = bg
    elif im.mode == "L":
        im = im.convert("RGB")
    if height and height >= 100:
        return ImageOps.fit(im, (width, height), method=Image.LANCZOS, centering=(0.5, 0.5))   # 가운데 기준으로 잘라 맞춤
    w, h = im.size
    nh = max(1, round(h * width / w))
    return im.resize((width, nh), Image.LANCZOS)


def process_link(
    url: str, out_root: str, width: int, height: int, quality: int,
    oh_crawler: Optional[OnhouseCrawler], log: Callable[[str], None], cancelled: Callable[[], bool],
) -> Tuple[str, int]:
    """링크 하나 → 폴더 하나. (폴더 경로, 저장 장수)"""
    url = url.strip()
    no = naver_no(url)
    did = daangn_id(url)
    hid = onhouse_id(url)
    if no:
        label, urls = photos_naver(no)
        referer = "https://new.land.naver.com/"
    elif did:
        label, urls = photos_daangn(did, url)
        referer = "https://realty.daangn.com/"
    elif hid:
        if not oh_crawler:
            raise RuntimeError("온하우스 링크는 아이디/비밀번호(유료 회원사)가 필요합니다 — 아래 온하우스 계정에 입력하세요")
        label, urls = photos_onhouse(hid, oh_crawler)
        referer = "https://www.onhouse.com/"
    else:
        label, urls = photos_generic(url)
        referer = url
    if not urls:
        log(f"  사진 주소를 찾지 못했습니다: {url}")
        return "", 0
    log(f"  사진 후보 {len(urls)}장 → {label}")
    out_dir = os.path.join(out_root, label)
    base = out_dir
    k = 2
    while os.path.exists(out_dir):
        out_dir = f"{base}_{k}"
        k += 1
    os.makedirs(out_dir, exist_ok=True)
    n = 0
    for i, u in enumerate(urls, 1):
        if cancelled():
            break
        im = fetch_image(u, referer)
        if im is None and "?" in u:
            im = fetch_image(u.split("?")[0], referer)   # 크기 인자(?w=…)를 못 받는 파일은 원본으로
        if im is None:
            log(f"    [{i}] 내려받기 실패: {u[:90]}")
            continue
        if min(im.size) < MIN_SIDE and not (no or did or hid):
            continue   # 일반 사이트: 아이콘·버튼 제외
        try:
            out = resize_to(im, width, height)
        except Exception as e:
            log(f"    [{i}] 변환 실패: {e}")
            continue
        n += 1
        path = os.path.join(out_dir, f"{n:02d}.jpg")
        out.save(path, "JPEG", quality=quality, optimize=True)
        log(f"    [{n:02d}] {im.size[0]}x{im.size[1]} → {out.size[0]}x{out.size[1]}  {os.path.basename(path)}")
    if n == 0:
        try:
            os.rmdir(out_dir)
        except OSError:
            pass
        return "", 0
    return out_dir, n


# ---------------------------------------------------------------- 작업 스레드
class Worker(QObject):
    log = Signal(str)
    progress = Signal(int, int)
    finished = Signal(str, int, int)   # 마지막 폴더, 링크 수, 장수

    def __init__(self, links: List[str], out_root: str, width: int, height: int, quality: int, oh_id: str, oh_pw: str):
        super().__init__()
        self.links, self.out_root, self.width, self.height, self.quality = links, out_root, width, height, quality
        self.oh_id, self.oh_pw = oh_id, oh_pw
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        total_imgs, last_dir = 0, ""
        crawler: Optional[OnhouseCrawler] = None
        if any(onhouse_id(u) for u in self.links) and self.oh_id and self.oh_pw:
            try:
                crawler = OnhouseCrawler(self.oh_id, self.oh_pw, verbose=False)
                crawler.login()
                self.log.emit("온하우스 로그인 완료")
            except Exception as e:
                self.log.emit(f"온하우스 로그인 실패: {e}")
                crawler = None
        for i, url in enumerate(self.links, 1):
            if self._cancel:
                self.log.emit("중단했습니다")
                break
            self.progress.emit(i - 1, len(self.links))
            self.log.emit(f"[{i}/{len(self.links)}] {url}")
            try:
                d, n = process_link(url, self.out_root, self.width, self.height, self.quality, crawler, self.log.emit, lambda: self._cancel)
                if n:
                    total_imgs += n
                    last_dir = d
                    self.log.emit(f"  저장 {n}장 → {d}")
            except Exception as e:
                self.log.emit(f"  오류: {e}")
        self.progress.emit(len(self.links), len(self.links))
        self.finished.emit(last_dir, len(self.links), total_imgs)


# ---------------------------------------------------------------- 화면
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(900, 720)
        self.setStyleSheet(APP_STYLESHEET)
        self.base_dir = base_dir()
        self.cfg_path = os.path.join(self.base_dir, "photo950_settings.json")
        self.worker: Optional[Worker] = None
        self.thread: Optional[QThread] = None
        self._last_clip = ""
        self._queue: List[str] = []
        self._build_ui()
        self._load_cfg()
        self.clip_timer = QTimer(self)
        self.clip_timer.setInterval(800)
        self.clip_timer.timeout.connect(self._poll_clipboard)
        self.clip_timer.start()

    def _build_ui(self):
        central = QWidget()
        central.setObjectName("appRoot")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        box = QGroupBox("매물 링크 (한 줄에 하나 · 네이버부동산 / 당근 / 온하우스 / 그 밖의 사이트)")
        bl = QVBoxLayout(box)
        self.ed_links = QPlainTextEdit()
        self.ed_links.setPlaceholderText("여기에 링크를 붙여넣으세요. 여러 개면 줄마다 하나.\n예) https://new.land.naver.com/rooms?articleNo=2652272081\n    https://realty.daangn.com/articles/4401448\n    https://www.onhouse.com/index/rent_view/3546787")
        self.ed_links.setMinimumHeight(110)
        self.ed_links.setStyleSheet("background:#ffffff; color:#0f172a; border:1px solid #cbd5e1; border-radius:8px; padding:6px;")
        bl.addWidget(self.ed_links)
        row = QHBoxLayout()
        self.btn_paste = QPushButton("클립보드 붙여넣기")
        self.btn_paste.clicked.connect(self._paste)
        self.chk_watch = QCheckBox("클립보드에 링크를 복사하면 바로 가져오기 (자동 실행)")
        row.addWidget(self.btn_paste)
        row.addWidget(self.chk_watch)
        row.addStretch(1)
        bl.addLayout(row)
        root.addWidget(box)

        opt = QGroupBox("크기 / 저장 위치")
        g = QGridLayout(opt)
        self.sp_w = QSpinBox()
        self.sp_w.setRange(50, 5000)
        self.sp_w.setValue(950)
        self.chk_h = QCheckBox("세로 고정")
        self.sp_h = QSpinBox()
        self.sp_h.setRange(100, 5000)
        self.sp_h.setValue(950)
        self.sp_h.setEnabled(False)
        self.chk_h.toggled.connect(self.sp_h.setEnabled)
        self.sp_q = QSpinBox()
        self.sp_q.setRange(50, 100)
        self.sp_q.setValue(92)
        self.ed_out = QLineEdit(os.path.join(os.path.expanduser("~"), "Desktop", "매물사진950"))
        self.btn_out = QPushButton("폴더 선택")
        self.btn_out.clicked.connect(self._pick_out)
        self.chk_open = QCheckBox("끝나면 저장 폴더 열기")
        self.chk_open.setChecked(True)
        g.addWidget(QLabel("가로(px)"), 0, 0)
        g.addWidget(self.sp_w, 0, 1)
        g.addWidget(self.chk_h, 0, 2)
        g.addWidget(self.sp_h, 0, 3)
        g.addWidget(QLabel("기본은 가로 950에 세로는 비율대로. '세로 고정'을 켜면 그 크기로 가운데를 잘라 맞춤"), 0, 4, 1, 2)
        g.addWidget(QLabel("JPG 품질"), 1, 0)
        g.addWidget(self.sp_q, 1, 1)
        g.addWidget(QLabel("저장 폴더"), 1, 2)
        g.addWidget(self.ed_out, 1, 3, 1, 2)
        g.addWidget(self.btn_out, 1, 5)
        g.addWidget(self.chk_open, 2, 0, 1, 3)
        g.setColumnStretch(4, 1)
        root.addWidget(opt)

        acc = QGroupBox("온하우스 계정 (온하우스 링크일 때만 필요 · 유료 회원사)")
        al = QHBoxLayout(acc)
        self.ed_oh_id = QLineEdit()
        self.ed_oh_id.setPlaceholderText("아이디")
        self.ed_oh_pw = QLineEdit()
        self.ed_oh_pw.setPlaceholderText("비밀번호")
        self.ed_oh_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.chk_oh_save = QCheckBox("저장")
        al.addWidget(QLabel("아이디"))
        al.addWidget(self.ed_oh_id, 1)
        al.addWidget(QLabel("비밀번호"))
        al.addWidget(self.ed_oh_pw, 1)
        al.addWidget(self.chk_oh_save)
        root.addWidget(acc)

        ctrl = QHBoxLayout()
        self.btn_go = QPushButton("사진 가져와서 950으로 저장")
        self.btn_stop = QPushButton("중단")
        self.btn_stop.setEnabled(False)
        self.btn_open = QPushButton("저장 폴더 열기")
        self.btn_clear = QPushButton("링크·로그 지우기")
        self.btn_go.clicked.connect(self._start)
        self.btn_stop.clicked.connect(self._stop)
        self.btn_open.clicked.connect(lambda: self._open(self.ed_out.text().strip()))
        self.btn_clear.clicked.connect(lambda: (self.ed_links.clear(), self.log.clear()))
        for b in (self.btn_go, self.btn_stop, self.btn_open, self.btn_clear):
            ctrl.addWidget(b)
        ctrl.addStretch(1)
        root.addLayout(ctrl)

        pr = QHBoxLayout()
        self.lbl_status = QLabel("대기 중")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        pr.addWidget(self.lbl_status)
        pr.addWidget(self.progress, 1)
        root.addLayout(pr)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        self.log.setStyleSheet("background:#0f172a; color:#e2e8f0; border-radius:10px; padding:6px; font-family:Consolas,'Malgun Gothic';")
        root.addWidget(self.log, 1)

    # ---------- 설정 ----------
    def _load_cfg(self):
        try:
            if os.path.exists(self.cfg_path):
                c = json.load(open(self.cfg_path, "r", encoding="utf-8"))
                self.sp_w.setValue(int(c.get("width", 950)))
                hh = int(c.get("height", 0) or 0)
                self.chk_h.setChecked(hh >= 100)
                self.sp_h.setValue(hh if hh >= 100 else 950)
                self.sp_q.setValue(int(c.get("quality", 92)))
                if c.get("out"):
                    self.ed_out.setText(c["out"])
                self.chk_open.setChecked(bool(c.get("open", True)))
                self.chk_watch.setChecked(bool(c.get("watch", False)))
                if c.get("oh_id"):
                    self.ed_oh_id.setText(c["oh_id"])
                    self.ed_oh_pw.setText(c.get("oh_pw", ""))
                    self.chk_oh_save.setChecked(True)
                return
        except Exception:
            pass
        # 온하우스 수집기의 저장 계정이 옆에 있으면 가져온다
        for p in (os.path.join(self.base_dir, "onhouse_credentials.json"),
                  os.path.join(os.path.expanduser("~"), "Desktop", "스크랩핑 파일", "온하우스매물수집기_260921", "onhouse_credentials.json")):
            try:
                if os.path.exists(p):
                    d = json.load(open(p, "r", encoding="utf-8"))
                    if d.get("id"):
                        self.ed_oh_id.setText(d["id"])
                        self.ed_oh_pw.setText(d.get("pwd") or d.get("pw") or "")
                        self.chk_oh_save.setChecked(True)
                        break
            except Exception:
                pass

    def _save_cfg(self):
        c = {"width": self.sp_w.value(), "height": self._height(), "quality": self.sp_q.value(), "out": self.ed_out.text().strip(),
             "open": self.chk_open.isChecked(), "watch": self.chk_watch.isChecked()}
        if self.chk_oh_save.isChecked():
            c["oh_id"] = self.ed_oh_id.text().strip()
            c["oh_pw"] = self.ed_oh_pw.text().strip()
        try:
            json.dump(c, open(self.cfg_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ---------- 동작 ----------
    def _height(self) -> int:
        return self.sp_h.value() if self.chk_h.isChecked() else 0

    def _pick_out(self):
        d = QFileDialog.getExistingDirectory(self, "저장 폴더", self.ed_out.text().strip() or os.path.expanduser("~"))
        if d:
            self.ed_out.setText(d)

    def _paste(self):
        t = QGuiApplication.clipboard().text() or ""
        if t.strip():
            cur = self.ed_links.toPlainText()
            self.ed_links.setPlainText((cur + "\n" + t).strip() if cur.strip() else t.strip())

    def _poll_clipboard(self):
        if not self.chk_watch.isChecked():
            return
        t = (QGuiApplication.clipboard().text() or "").strip()
        if not t or t == self._last_clip:
            return
        self._last_clip = t
        links = [x.strip() for x in re.split(r"\s+", t) if x.strip().startswith("http")]
        if not links:
            return
        self.ed_links.setPlainText("\n".join(links))
        if self.worker:
            self._queue.extend(links)
            self._append(f"작업 중 — 대기열에 추가: {len(links)}개")
        else:
            self._start(links)

    def _links(self) -> List[str]:
        out, seen = [], set()
        for line in self.ed_links.toPlainText().splitlines():
            for tok in re.split(r"\s+", line.strip()):
                if tok.startswith("http") and tok not in seen:
                    seen.add(tok)
                    out.append(tok)
        return out

    def _start(self, links: Optional[List[str]] = None):
        if self.worker:
            return
        links = links or self._links()
        if not links:
            QMessageBox.warning(self, "확인", "링크를 한 줄에 하나씩 넣어주세요.")
            return
        out_root = self.ed_out.text().strip() or os.path.join(os.path.expanduser("~"), "Desktop", "매물사진950")
        os.makedirs(out_root, exist_ok=True)
        self._save_cfg()
        self.worker = Worker(links, out_root, self.sp_w.value(), self._height(), self.sp_q.value(), self.ed_oh_id.text().strip(), self.ed_oh_pw.text().strip())
        self.thread = QThread(self)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.log.connect(self._append)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.btn_go.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.lbl_status.setText("가져오는 중")
        self.progress.setValue(0)
        self._append(f"시작 {datetime.now():%H:%M:%S} — 링크 {len(links)}개, 가로 {self.sp_w.value()}px")
        self.thread.start()

    def _stop(self):
        if self.worker:
            self.worker.cancel()
            self.lbl_status.setText("중단 요청")

    def _on_progress(self, cur: int, total: int):
        self.progress.setValue(int(cur / total * 100) if total else 0)
        self.lbl_status.setText(f"{cur}/{total} 링크")

    def _on_finished(self, last_dir: str, n_links: int, n_imgs: int):
        self._append(f"완료: 링크 {n_links}개 → 사진 {n_imgs}장")
        self.lbl_status.setText(f"완료 — 사진 {n_imgs}장")
        self.progress.setValue(100)
        if self.thread:
            self.thread.quit()
            self.thread.wait(3000)
        self.worker = None
        self.thread = None
        self.btn_go.setEnabled(True)
        self.btn_stop.setEnabled(False)
        if n_imgs and self.chk_open.isChecked():
            self._open(last_dir or self.ed_out.text().strip())
        if self._queue:
            q, self._queue = list(dict.fromkeys(self._queue)), []
            QTimer.singleShot(300, lambda: self._start(q))

    def _append(self, s: str):
        self.log.appendPlainText(s)

    @staticmethod
    def _open(path: str):
        if path and os.path.exists(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def closeEvent(self, ev):
        self._save_cfg()
        if self.worker:
            self.worker.cancel()
            if self.thread:
                self.thread.quit()
                self.thread.wait(3000)
        super().closeEvent(ev)


def main():
    # 라이선스 로그인(수집기와 같은 서버) — 어드민에서 '사진950' 기능이 체크된 계정만 통과
    from license_gate import run_licensed_app
    run_licensed_app(create_main_window=MainWindow, base_dir=base_dir(), app_key="photo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
