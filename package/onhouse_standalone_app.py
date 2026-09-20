# -*- coding: utf-8 -*-
"""
온하우스 매물수집기 - 단독 실행 버전.

기존 onhouse_crawler.OnhouseCrawler 를 그대로 사용하고, UI/워커만 이 파일에 담는다.
- 지역: 시/도·시군구·읍면동 다중 체크 (app_main_common.MultiSelectCombo), 좌표 범위는 regions_bbox.json
- 확인일(업로드) 기간 필터: 목록이 확인일 내림차순으로 오므로, 기간보다 오래된 매물이 나오면 그 지역은 더 넘기지 않는다
- 임대인 연락처 수집은 옵션 (phoneView 호출 → 계정의 '잔여 연락처 조회수' 차감, 캐시로 재차감 방지)
- 요청 사이 랜덤 대기 / 지역당 최대 페이지로 수집량 조절
"""
from __future__ import annotations

import json
import os
import random
import re
import sys
import time
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QDate, QObject, QThread, QTime, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

import auto_send
from app_main_common import MultiSelectCombo
from onhouse_crawler import OnhouseCrawler
from schedule_manager import DAY_NAMES, ScheduleManager, ScheduledJob

DAY_LABELS = {"mon": "월", "tue": "화", "wed": "수", "thu": "목", "fri": "금", "sat": "토", "sun": "일"}
TRADE_TYPES = ["월세", "전세", "매매"]

APP_TITLE = "온하우스 매물수집기"
PHONE_VIEW_URL = "https://www.onhouse.com/index.php/dataFunction/phoneView"
PAGE_SIZE = 30
ROOM_TYPES = ["전체", "주택", "오피", "주택/오피", "사무실", "상가", "사무실/상가", "분양사무실"]
INVALID_FILENAME_CHARS = '\\/:*?"<>|'

# (라벨, 오늘 기준 며칠 전부터) — None 은 전체, -1 은 직접 지정
DATE_PERIODS: List[Tuple[str, Optional[int]]] = [
    ("전체", None),
    ("오늘", 0),
    ("어제~오늘", 1),
    ("최근 3일", 2),
    ("최근 7일", 6),
    ("최근 30일", 29),
    ("직접 지정", -1),
]


def base_dir() -> str:
    """exe 옆(또는 소스 파일 옆) 경로. 계정 파일/결과 폴더 기준."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def resource_path(name: str) -> str:
    """PyInstaller onefile 번들 데이터(sys._MEIPASS) 우선, 없으면 base_dir."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass and os.path.exists(os.path.join(meipass, name)):
        return os.path.join(meipass, name)
    return os.path.join(base_dir(), name)


def fmt_phone(raw: Any) -> str:
    digits = re.sub(r"\D", "", str(raw or ""))
    if not digits:
        return ""
    if len(digits) == 12:
        return f"{digits[:4]}-{digits[4:8]}-{digits[8:]}"
    if len(digits) == 11:
        return f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"
    if len(digits) == 10:
        if digits.startswith("02"):
            return f"{digits[:2]}-{digits[2:6]}-{digits[6:]}"
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    if len(digits) == 9 and digits.startswith("02"):
        return f"{digits[:2]}-{digits[2:5]}-{digits[5:]}"
    return digits


def safe_filename_part(s: str) -> str:
    s = (s or "").replace(" ", "_").replace("/", "_")
    for ch in INVALID_FILENAME_CHARS:
        s = s.replace(ch, "")
    return s or "전체"


def parse_quota(html: str) -> str:
    """상세 페이지의 '잔여 연락처 조회수' 영역 → '임대 486건 / 매매 99건' 문자열. 없으면 빈 문자열."""
    i = html.find("잔여 연락처 조회수")
    if i < 0:
        return ""
    seg = html[i:i + 3000]
    rows = re.findall(
        r'<div class="title">([^<]+)</div>\s*<div class="desc">\s*<span class="black">([\d,]+)</span>', seg
    )
    return " / ".join(f"{t.strip()} {n}건" for t, n in rows)


def parse_chk_date(s: str) -> Optional[date]:
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s or "")
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def load_contact_cache(path: str) -> Dict[str, Dict[str, str]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_contact_cache(path: str, cache: Dict[str, Dict[str, str]]) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


class ListCapturingCrawler(OnhouseCrawler):
    """search() 가 받은 목록 HTML에서 매물별 확인일/좌표를 함께 뽑아 last_items 에 보관한다."""

    _ITEM_RE = re.compile(r"<article[^>]*class=\"[^\"]*listItem[^\"]*\"[^>]*>(.*?)</article>", re.S)
    _ID_RE = re.compile(r"openListItemInfo\(\s*['\"]?(\d+)")
    _DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.last_items: List[Dict[str, str]] = []

    def _parse_ids_from_html(self, html: str) -> List[str]:
        items: List[Dict[str, str]] = []
        for m in re.finditer(r"<article[^>]*class=\"[^\"]*listItem[^\"]*\"[^>]*>", html):
            head = m.group(0)
            body_end = html.find("</article>", m.end())
            body = html[m.end():body_end if body_end > 0 else m.end() + 4000]
            mid = self._ID_RE.search(head) or self._ID_RE.search(body)
            if not mid:
                continue
            md = self._DATE_RE.search(body)
            lat = re.search(r'data-lat="([\d.]+)"', head)
            lng = re.search(r'data-lng="([\d.]+)"', head)
            items.append({
                "id": mid.group(1),
                "chk": md.group(1) if md else "",
                "lat": lat.group(1) if lat else "",
                "lng": lng.group(1) if lng else "",
            })
        self.last_items = items
        return super()._parse_ids_from_html(html)


class Worker(QObject):
    progress = Signal(int, int)
    log = Signal(str)
    status = Signal(str)
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, params: Dict[str, Any]):
        super().__init__()
        self.p = params
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def _sleep_between(self):
        lo = float(self.p.get("delay_min", 0))
        hi = float(self.p.get("delay_max", 0))
        if hi <= 0 and lo <= 0:
            return
        t = random.uniform(min(lo, hi), max(lo, hi))
        end = time.time() + t
        while time.time() < end:
            if self._cancel:
                return
            time.sleep(0.2)

    def _fetch_contact(
        self, crawler: OnhouseCrawler, hid: str, html: str, fallback_type: str
    ) -> Tuple[Dict[str, str], bool]:
        """상세 HTML의 showPhoneNumber(idx, type) 파라미터로 phoneView 호출. (조회수 차감)"""
        m = re.search(r"showPhoneNumber\(\s*['\"](\d+)['\"]\s*,\s*['\"]([^'\"]+)['\"]", html)
        ptype = m.group(2) if m else fallback_type
        mb = re.search(r'data-bind="([^"]*)"', html)
        bind = mb.group(1) if mb else ""
        r = crawler.session.post(
            PHONE_VIEW_URL,
            data={"idx": hid, "type": ptype},
            impersonate="chrome",
            timeout=30,
        )
        try:
            data = r.json()
        except Exception:
            return {"연락처_관계": bind, "임대인연락처": "조회실패: 응답 파싱 오류", "추가연락처": ""}, False
        if data.get("RESULT") != "SUCCESS":
            msg = data.get("MSG") or data.get("MESSAGE") or data.get("RESULT") or "조회실패"
            return {"연락처_관계": bind, "임대인연락처": f"조회실패: {msg}", "추가연락처": ""}, False
        nums = [fmt_phone(data.get(k)) for k in ("NUMBER", "NUMBER2", "NUMBER3", "NUMBER4")]
        nums = [n for n in nums if n]
        return {
            "연락처_관계": bind,
            "임대인연락처": nums[0] if nums else "",
            "추가연락처": " / ".join(nums[1:]),
        }, True

    @Slot()
    def run(self):
        try:
            crawler = ListCapturingCrawler(id=self.p["uid"], pwd=self.p["pwd"], verbose=False)
            self.status.emit("온하우스 로그인 중...")
            crawler.login()

            regions: List[str] = self.p["regions"]
            bbox_map: Dict[str, Dict[str, float]] = self.p["bbox"]
            trade_types: List[str] = self.p["trade_types"]
            room_type: str = self.p["room_type"]
            want_contact: bool = bool(self.p.get("contact"))
            max_pages: int = int(self.p.get("max_pages", 0))
            date_from: Optional[date] = self.p.get("date_from")
            date_to: Optional[date] = self.p.get("date_to")
            contact_fail_streak = 0
            # 연락처 캐시: 같은 매물은 서버도 재차감하지 않지만, 호출 자체를 생략해 조회수/시간을 아낀다.
            cache_path: str = self.p.get("contact_cache_path", "")
            contact_cache = load_contact_cache(cache_path) if cache_path else {}
            cache_hits = 0
            new_lookups = 0
            quota_first = ""
            quota_last = ""
            skipped_by_date = 0
            warned_no_date = False

            all_rows: List[Dict[str, Any]] = []
            seen: set = set()
            total = len(regions)
            stopped = False
            checked_access = False

            for ri, region in enumerate(regions, 1):
                if self._cancel:
                    stopped = True
                    break
                bbox = bbox_map.get(region)
                if not bbox:
                    self.progress.emit(ri, total)
                    continue
                self.status.emit(f"[{ri}/{total}] {region} 검색 중")
                page = 0
                while True:
                    if self._cancel:
                        stopped = True
                        break
                    if max_pages and page >= max_pages:
                        self.log.emit(f"  {region}: 최대 페이지({max_pages}) 도달, 다음 지역으로")
                        break
                    ids = crawler.search(
                        sw_lat=bbox["lat_min"],
                        ne_lat=bbox["lat_max"],
                        sw_lng=bbox["lon_min"],
                        ne_lng=bbox["lon_max"],
                        trade_type=trade_types,
                        room_type=room_type,
                        limit=PAGE_SIZE,
                        page=page,
                        fetch_details=False,
                        is_cancelled=lambda: self._cancel,
                    ) or []
                    if not ids:
                        if page == 0:
                            self.log.emit(f"  {region}: 매물 없음")
                        break

                    # 목록 항목(확인일 내림차순). HTML 파싱이 안 된 경우엔 ID만으로 진행.
                    items = crawler.last_items or [{"id": str(i), "chk": "", "lat": "", "lng": ""} for i in ids]
                    if (date_from or date_to) and not any(it["chk"] for it in items) and not warned_no_date:
                        warned_no_date = True
                        self.log.emit("  주의: 목록에서 확인일을 읽지 못해 기간 필터를 적용할 수 없습니다 (전체 수집).")

                    page_older_exists = False
                    todo: List[Dict[str, str]] = []
                    for it in items:
                        d = parse_chk_date(it["chk"])
                        if d is not None:
                            if date_from and d < date_from:
                                page_older_exists = True
                                skipped_by_date += 1
                                continue
                            if date_to and d > date_to:
                                skipped_by_date += 1
                                continue
                        todo.append(it)

                    self.status.emit(
                        f"[{ri}/{total}] {region} p{page + 1} 매물 {len(items)}건 (기간 내 {len(todo)})"
                    )

                    for it in todo:
                        if self._cancel:
                            stopped = True
                            break
                        hid = it["id"]
                        if hid in seen:
                            continue
                        seen.add(hid)
                        try:
                            html = crawler.fetch_detail(hid)
                            # 계정 등급/로그인 상태는 첫 상세 응답으로 판별
                            if not checked_access:
                                checked_access = True
                                if len(html) < 400:
                                    if "유료" in html:
                                        self.failed.emit(
                                            "상세 조회 불가: '유료 회원사만 이용 가능' — 유료 계정으로 로그인하세요."
                                        )
                                        return
                                    if "로그인" in html:
                                        self.failed.emit("로그인 실패 — 아이디/비밀번호를 확인하세요.")
                                        return
                            q = parse_quota(html)
                            if q:
                                quota_last = q
                                if not quota_first:
                                    quota_first = q
                                    self.log.emit(f"  현재 잔여 연락처 조회수: {q}")
                            parsed = crawler._parse_detail_html(html, hid)
                            row: Dict[str, Any] = {
                                "매물ID": parsed.get("매물ID", hid),
                                "URL": parsed.get("URL", f"{crawler.DETAIL_URL}/{hid}"),
                                "확인일": it["chk"][:19],
                                "지역": region,
                            }
                            for k, v in parsed.items():
                                if k not in row:
                                    row[k] = v
                            if it["lat"] and it["lng"]:
                                row["위도"] = it["lat"]
                                row["경도"] = it["lng"]
                            if want_contact:
                                cached = contact_cache.get(hid)
                                if cached and cached.get("임대인연락처") and not str(cached["임대인연락처"]).startswith("조회실패"):
                                    row.update(cached)
                                    cache_hits += 1
                                else:
                                    contact, ok = self._fetch_contact(
                                        crawler, hid, html, trade_types[0] if trade_types else "월세"
                                    )
                                    row.update(contact)
                                    if ok:
                                        contact_fail_streak = 0
                                        new_lookups += 1
                                        contact_cache[hid] = contact
                                        if cache_path and new_lookups % 10 == 0:
                                            save_contact_cache(cache_path, contact_cache)
                                    else:
                                        contact_fail_streak += 1
                                        if contact_fail_streak >= 5:
                                            want_contact = False
                                            self.log.emit(
                                                "  주의: 연락처 조회가 5회 연속 실패 — 조회수 소진 가능. 이후 연락처 수집을 중단합니다."
                                            )
                        except InterruptedError:
                            stopped = True
                            break
                        except Exception as e:
                            row = {"매물ID": hid, "URL": f"{crawler.DETAIL_URL}/{hid}", "확인일": it["chk"][:19], "지역": region, "오류": str(e)}
                        all_rows.append(row)
                        addr = row.get("전체주소") or row.get("주소_호실") or ""
                        price = next(
                            (f"{k} {row[k]}" for k in ("월세", "전세", "매매", "매매가", "단기", "보증금") if row.get(k)), ""
                        )
                        tel = f" | {row.get('임대인연락처')}" if row.get("임대인연락처") else ""
                        self.log.emit(f"  [{len(all_rows)}] {hid} | {it['chk'][:16]} | {addr} | {price}{tel}")
                        self._sleep_between()
                    if stopped:
                        break
                    if date_from and page_older_exists:
                        # 내림차순 목록이므로 이 페이지에 기간 이전 매물이 있으면 다음 페이지는 전부 더 오래됨
                        break
                    if len(items) < PAGE_SIZE:
                        break
                    page += 1
                    self._sleep_between()
                self.progress.emit(ri, total)

            if cache_path and new_lookups:
                save_contact_cache(cache_path, contact_cache)
            if date_from or date_to:
                self.log.emit(f"  기간 필터로 제외된 매물: {skipped_by_date}건")
            if self.p.get("contact"):
                self.log.emit(
                    f"  연락처: 신규 조회 {new_lookups}건 (조회수 차감), 캐시 재사용 {cache_hits}건 (차감 없음)"
                    + (f" / 종료 시 잔여: {quota_last}" if quota_last else "")
                )

            if not all_rows:
                self.finished.emit("중단됨 (저장할 데이터 없음)" if stopped else "수집된 매물이 없습니다.")
                return

            out_dir = self.p["out_dir"]
            os.makedirs(out_dir, exist_ok=True)
            ts = datetime.now().strftime("%y%m%d_%H%M%S")
            period = self.p.get("period_label") or ""
            period_part = f"_{safe_filename_part(period)}" if period and period != "전체" else ""
            out_path = os.path.join(
                out_dir, f"온하우스_{self.p['region_label']}{period_part}_{len(all_rows)}건_{ts}.xlsx"
            )
            crawler.crawl_details_to_excel(rows=all_rows, output_path=out_path)
            prefix = "중단 저장 완료" if stopped else "저장 완료"
            send_cfg = self.p.get("send") or {}
            if send_cfg.get("mail_on") or send_cfg.get("tg_on"):
                self.log.emit("자동 전송 중...")
                caption = (
                    f"[온하우스] {self.p['region_label']} {len(all_rows)}건"
                    f" / {datetime.now():%Y-%m-%d %H:%M}"
                )
                auto_send.deliver(send_cfg, out_path, caption, self.log.emit)
            self.finished.emit(f"{prefix}: {out_path} ({len(all_rows)}건)")
        except Exception as e:
            self.failed.emit(str(e))


class ScheduleAddDialog(QDialog):
    """예약 추가: 이름 / 시각(HH:mm) / 요일(매일 또는 개별). 수집 조건은 호출 시점의 화면 설정을 그대로 저장한다."""

    def __init__(self, summary: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("예약 자동 실행 추가")
        self.setMinimumWidth(460)
        self.result: Optional[Tuple[str, str, List[str]]] = None
        lay = QVBoxLayout(self)

        row = QHBoxLayout()
        row.addWidget(QLabel("예약 이름"))
        self.ed_name = QLineEdit()
        self.ed_name.setPlaceholderText("예) 강남 아침 수집")
        row.addWidget(self.ed_name, 1)
        lay.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("실행 시각"))
        self.te_time = QTimeEdit(QTime(9, 0))
        self.te_time.setDisplayFormat("HH:mm")
        row.addWidget(self.te_time)
        row.addStretch(1)
        lay.addLayout(row)

        days_box = QGroupBox("실행 요일")
        dl = QHBoxLayout(days_box)
        self.chk_daily = QCheckBox("매일")
        self.chk_daily.setChecked(True)
        dl.addWidget(self.chk_daily)
        dl.addSpacing(12)
        self.day_checks: Dict[str, QCheckBox] = {}
        for d in DAY_NAMES:
            cb = QCheckBox(DAY_LABELS[d])
            cb.setEnabled(False)
            self.day_checks[d] = cb
            dl.addWidget(cb)
        dl.addStretch(1)
        self.chk_daily.toggled.connect(self._on_daily)
        lay.addWidget(days_box)

        box = QGroupBox("이 예약에 저장되는 수집 조건 (현재 화면 설정)")
        bl = QVBoxLayout(box)
        lbl = QLabel(summary)
        lbl.setWordWrap(True)
        bl.addWidget(lbl)
        lay.addWidget(box)

        row = QHBoxLayout()
        ok = QPushButton("저장")
        cancel = QPushButton("취소")
        ok.clicked.connect(self._accept)
        cancel.clicked.connect(self.reject)
        row.addStretch(1)
        row.addWidget(ok)
        row.addWidget(cancel)
        lay.addLayout(row)

    def _on_daily(self, on: bool):
        for cb in self.day_checks.values():
            cb.setEnabled(not on)
            if on:
                cb.setChecked(False)

    def _accept(self):
        name = self.ed_name.text().strip() or f"자동 수집 {self.te_time.time().toString('HH:mm')}"
        if self.chk_daily.isChecked():
            days = ["daily"]
        else:
            days = [d for d, cb in self.day_checks.items() if cb.isChecked()]
            if not days:
                QMessageBox.warning(self, "오류", "요일을 하나 이상 선택하거나 '매일'을 체크하세요.")
                return
        self.result = (name, self.te_time.time().toString("HH:mm"), days)
        self.accept()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(980, 860)
        self.base_dir = base_dir()
        self.cred_path = os.path.join(self.base_dir, "onhouse_credentials.json")
        self.out_dir = os.path.join(self.base_dir, "data")
        self.worker: Optional[Worker] = None
        self.worker_thread: Optional[QThread] = None
        self._current_job_name: str = ""
        self._batch_queue: List[ScheduledJob] = []
        self._batch_mode: bool = False

        self.bbox: Dict[str, Dict[str, float]] = self._load_bbox()
        self._build_region_maps()
        self.schedules = ScheduleManager(os.path.join(self.base_dir, "onhouse_schedules.json"))
        self.send_path = os.path.join(self.base_dir, "onhouse_send.json")
        self._build_ui()
        self._load_credentials()
        self._load_send_config()
        self._refresh_schedule_list()
        # 예약 확인 타이머: 15초마다 실행 시각이 된 예약을 찾는다 (프로그램이 켜져 있을 때만 동작)
        self.sched_timer = QTimer(self)
        self.sched_timer.setInterval(15000)
        self.sched_timer.timeout.connect(self._check_schedules)
        self.sched_timer.start()

    # ---------- 데이터 ----------
    def _load_bbox(self) -> Dict[str, Dict[str, float]]:
        path = resource_path("regions_bbox.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "오류", f"regions_bbox.json 을 읽을 수 없습니다.\n{path}\n{e}")
            return {}

    def _build_region_maps(self):
        self.si_list: List[str] = []
        self.gun_map: Dict[str, List[str]] = {}
        self.dong_map: Dict[Tuple[str, str], List[str]] = {}
        for key in self.bbox.keys():
            tok = key.split()
            if len(tok) < 3:
                continue
            si, gun, dong = tok[0], tok[1], " ".join(tok[2:])
            if si not in self.gun_map:
                self.si_list.append(si)
                self.gun_map[si] = []
            if gun not in self.gun_map[si]:
                self.gun_map[si].append(gun)
            self.dong_map.setdefault((si, gun), []).append(dong)
        self.si_list.sort()
        for v in self.gun_map.values():
            v.sort()
        for v in self.dong_map.values():
            v.sort()

    def _load_credentials(self):
        try:
            if os.path.exists(self.cred_path):
                with open(self.cred_path, "r", encoding="utf-8") as f:
                    d = json.load(f)
                if d.get("remember"):
                    self.ed_id.setText(d.get("id", ""))
                    self.ed_pw.setText(d.get("pwd", ""))
                    self.chk_save.setChecked(True)
        except Exception:
            pass

    def _save_credentials(self, uid: str, pwd: str):
        try:
            if self.chk_save.isChecked():
                with open(self.cred_path, "w", encoding="utf-8") as f:
                    json.dump({"remember": True, "id": uid, "pwd": pwd}, f, ensure_ascii=False, indent=2)
            elif os.path.exists(self.cred_path):
                os.remove(self.cred_path)
        except Exception:
            pass

    # ---------- UI ----------
    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        v = QVBoxLayout(root)

        acc = QGroupBox("온하우스 계정 (유료 회원사 계정 필요 — 상세/연락처는 유료만 조회됨)")
        h = QHBoxLayout(acc)
        self.ed_id = QLineEdit()
        self.ed_id.setPlaceholderText("아이디")
        self.ed_pw = QLineEdit()
        self.ed_pw.setPlaceholderText("비밀번호")
        self.ed_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.chk_save = QCheckBox("아이디/비밀번호 저장")
        h.addWidget(QLabel("아이디"))
        h.addWidget(self.ed_id, 1)
        h.addWidget(QLabel("비밀번호"))
        h.addWidget(self.ed_pw, 1)
        h.addWidget(self.chk_save)
        v.addWidget(acc)

        reg = QGroupBox("지역 (체크박스로 여러 곳 동시 선택 — 하위 단계를 체크하면 그것만, 아니면 상위 선택 전체)")
        h = QHBoxLayout(reg)
        self.cb_si = MultiSelectCombo()
        self.cb_si.set_entries([(si, si) for si in self.si_list])
        self.cb_gun = MultiSelectCombo()
        self.cb_dong = MultiSelectCombo()
        for cb, w in ((self.cb_si, 190), (self.cb_gun, 200), (self.cb_dong, 240)):
            cb.setMinimumWidth(w)
        h.addWidget(QLabel("시/도"))
        h.addWidget(self.cb_si)
        h.addWidget(QLabel("시군구"))
        h.addWidget(self.cb_gun)
        h.addWidget(QLabel("읍면동"))
        h.addWidget(self.cb_dong)
        h.addStretch(1)
        self.lbl_region_count = QLabel("")
        h.addWidget(self.lbl_region_count)
        self.cb_si.selection_changed.connect(self._on_si_changed)
        self.cb_gun.selection_changed.connect(self._on_gun_changed)
        self.cb_dong.selection_changed.connect(self._update_region_count)
        v.addWidget(reg)

        typ = QGroupBox("유형 / 기간")
        h = QHBoxLayout(typ)
        self.chk_month = QCheckBox("월세")
        self.chk_jeonse = QCheckBox("전세")
        self.chk_buy = QCheckBox("매매")
        self.chk_buy.setChecked(True)
        self.trade_checks: Dict[str, QCheckBox] = {"월세": self.chk_month, "전세": self.chk_jeonse, "매매": self.chk_buy}
        self.cb_room = QComboBox()
        self.cb_room.addItems(ROOM_TYPES)
        h.addWidget(self.chk_month)
        h.addWidget(self.chk_jeonse)
        h.addWidget(self.chk_buy)
        h.addSpacing(16)
        h.addWidget(QLabel("방유형"))
        h.addWidget(self.cb_room)
        h.addSpacing(24)
        h.addWidget(QLabel("확인일(업로드) 기간"))
        self.cb_period = QComboBox()
        self.cb_period.addItems([lbl for lbl, _ in DATE_PERIODS])
        self.de_from = QDateEdit(QDate.currentDate().addDays(-6))
        self.de_to = QDateEdit(QDate.currentDate())
        for de in (self.de_from, self.de_to):
            de.setCalendarPopup(True)
            de.setDisplayFormat("yyyy-MM-dd")
            de.setEnabled(False)
        h.addWidget(self.cb_period)
        h.addWidget(self.de_from)
        h.addWidget(QLabel("~"))
        h.addWidget(self.de_to)
        h.addStretch(1)
        self.cb_period.currentIndexChanged.connect(self._on_period_changed)
        v.addWidget(typ)

        opt = QGroupBox("수집 옵션")
        g = QGridLayout(opt)
        self.chk_contact = QCheckBox(
            "임대인 연락처도 수집  (새 매물 1건당 '연락처 조회수' 1 차감. 이미 조회한 매물은 캐시에서 재사용 — 차감 없음)"
        )
        g.addWidget(self.chk_contact, 0, 0, 1, 6)
        self.sp_delay_min = QSpinBox()
        self.sp_delay_min.setRange(0, 60)
        self.sp_delay_min.setValue(2)
        self.sp_delay_max = QSpinBox()
        self.sp_delay_max.setRange(0, 120)
        self.sp_delay_max.setValue(5)
        self.sp_max_pages = QSpinBox()
        self.sp_max_pages.setRange(0, 999)
        self.sp_max_pages.setValue(0)
        self.sp_max_pages.setSpecialValueText("제한없음")
        g.addWidget(QLabel("요청 간 대기(초)"), 1, 0)
        g.addWidget(self.sp_delay_min, 1, 1)
        g.addWidget(QLabel("~"), 1, 2)
        g.addWidget(self.sp_delay_max, 1, 3)
        g.addWidget(QLabel("   지역당 최대 페이지(30건/페이지)"), 1, 4)
        g.addWidget(self.sp_max_pages, 1, 5)
        g.setColumnStretch(6, 1)
        v.addWidget(opt)

        snd = QGroupBox("수집 완료 후 자동 전송 (한 번만 입력해두면 예약 수집 결과도 자동으로 옵니다)")
        sg = QGridLayout(snd)
        self.chk_mail = QCheckBox("메일로 보내기")
        self.ed_mail_from = QLineEdit()
        self.ed_mail_from.setPlaceholderText("보내는 지메일 주소 (예: myoffice@gmail.com)")
        self.ed_mail_pw = QLineEdit()
        self.ed_mail_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.ed_mail_pw.setPlaceholderText("구글 앱 비밀번호 16자리 (일반 비밀번호 아님)")
        self.ed_mail_to = QLineEdit()
        self.ed_mail_to.setPlaceholderText("받는 사람 (여러 명이면 쉼표로 구분)")
        sg.addWidget(self.chk_mail, 0, 0)
        sg.addWidget(self.ed_mail_from, 0, 1)
        sg.addWidget(self.ed_mail_pw, 0, 2)
        sg.addWidget(self.ed_mail_to, 0, 3, 1, 2)

        self.chk_tg = QCheckBox("텔레그램으로 보내기")
        self.ed_tg_token = QLineEdit()
        self.ed_tg_token.setPlaceholderText("봇 토큰 (@BotFather 에서 발급)")
        self.ed_tg_chat = QLineEdit()
        self.ed_tg_chat.setPlaceholderText("챗 ID")
        self.btn_tg_find = QPushButton("챗 ID 찾기")
        self.btn_tg_find.clicked.connect(self._find_chat_id)
        self.btn_send_test = QPushButton("테스트 전송")
        self.btn_send_test.clicked.connect(self._test_send)
        sg.addWidget(self.chk_tg, 1, 0)
        sg.addWidget(self.ed_tg_token, 1, 1, 1, 2)
        sg.addWidget(self.ed_tg_chat, 1, 3)
        sg.addWidget(self.btn_tg_find, 1, 4)
        sg.addWidget(self.btn_send_test, 0, 5)
        sg.addWidget(
            QLabel("메일: 지메일 2단계 인증 후 '앱 비밀번호' 필요 · 첨부 25MB / 텔레그램: 엑셀 파일이 그대로 전송 · 50MB"),
            2, 0, 1, 6,
        )
        sg.setColumnStretch(1, 2)
        sg.setColumnStretch(3, 2)
        v.addWidget(snd)

        sch = QGroupBox("예약 자동 실행 (이 프로그램이 켜져 있는 동안, 지정 시각에 저장된 조건으로 자동 수집)")
        sl = QHBoxLayout(sch)
        self.lst_sched = QListWidget()
        self.lst_sched.setMaximumHeight(96)
        sl.addWidget(self.lst_sched, 1)
        bl = QVBoxLayout()
        self.btn_sched_add = QPushButton("현재 설정으로 예약 추가")
        self.btn_sched_toggle = QPushButton("선택 켜기/끄기")
        self.btn_sched_run = QPushButton("선택 예약 지금 실행")
        self.btn_sched_del = QPushButton("선택 삭제")
        self.btn_sched_add.clicked.connect(self._add_schedule)
        self.btn_sched_toggle.clicked.connect(self._toggle_schedule)
        self.btn_sched_run.clicked.connect(self._run_schedule_now)
        self.btn_sched_del.clicked.connect(self._remove_schedule)
        for b in (self.btn_sched_add, self.btn_sched_toggle, self.btn_sched_run, self.btn_sched_del):
            bl.addWidget(b)
        sl.addLayout(bl)
        v.addWidget(sch)

        h = QHBoxLayout()
        self.btn_start = QPushButton("수집 시작")
        self.btn_stop = QPushButton("중지 (지금까지 저장)")
        self.btn_stop.setEnabled(False)
        self.btn_open = QPushButton("결과 폴더 열기")
        self.btn_start.clicked.connect(self._start)
        self.btn_stop.clicked.connect(self._stop)
        self.btn_open.clicked.connect(self._open_out_dir)
        h.addWidget(self.btn_start)
        h.addWidget(self.btn_stop)
        h.addStretch(1)
        h.addWidget(self.btn_open)
        v.addLayout(h)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.lbl_status = QLabel("대기")
        v.addWidget(self.progress)
        v.addWidget(self.lbl_status)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        v.addWidget(self.log, 1)

        self._on_si_changed()

    # ---------- 지역 다중선택 ----------
    def _on_si_changed(self):
        sis = self.cb_si.checked_data()
        entries: List[tuple] = []
        for si in sis:
            for gun in self.gun_map.get(si, []):
                label = gun if len(sis) == 1 else f"{si} {gun}"
                entries.append((label, (si, gun)))
        self.cb_gun.set_entries(entries)  # 내부에서 selection_changed → _on_gun_changed

    def _on_gun_changed(self):
        guns = self.cb_gun.checked_data()
        entries: List[tuple] = []
        for si, gun in guns:
            for dong in self.dong_map.get((si, gun), []):
                label = dong if len(guns) == 1 else f"{gun} {dong}"
                entries.append((label, (si, gun, dong)))
        self.cb_dong.set_entries(entries)  # 내부에서 selection_changed → _update_region_count

    def _selected_regions(self) -> List[str]:
        """체크 상태 → regions_bbox 키 목록. 가장 하위(읍면동) 선택이 있으면 그것만 사용."""
        sis = self.cb_si.checked_data()
        guns = self.cb_gun.checked_data()
        dongs = self.cb_dong.checked_data()
        keys = list(self.bbox.keys())
        if dongs:
            want = {f"{si} {gun} {dong}" for si, gun, dong in dongs}
            return sorted(k for k in keys if k in want)
        if guns:
            want = {(si, gun) for si, gun in guns}
            return sorted(k for k in keys if len(k.split()) > 1 and (k.split()[0], k.split()[1]) in want)
        if sis:
            want = set(sis)
            return sorted(k for k in keys if k.split()[0] in want)
        return sorted(keys)

    def _region_label(self) -> str:
        def part(vals: List[Any], pick) -> str:
            if not vals:
                return "전체"
            first = pick(vals[0])
            return first if len(vals) == 1 else f"{first}외{len(vals) - 1}"

        s = "_".join([
            part(self.cb_si.checked_data(), lambda v: v),
            part(self.cb_gun.checked_data(), lambda v: v[1]),
            part(self.cb_dong.checked_data(), lambda v: v[2]),
        ])
        return safe_filename_part(s)

    def _update_region_count(self):
        self.lbl_region_count.setText(f"선택 지역 {len(self._selected_regions())}개")

    # ---------- 기간 ----------
    def _on_period_changed(self, _idx: int):
        custom = DATE_PERIODS[self.cb_period.currentIndex()][1] == -1
        self.de_from.setEnabled(custom)
        self.de_to.setEnabled(custom)

    def _date_range(self) -> Tuple[Optional[date], Optional[date]]:
        _, days = DATE_PERIODS[self.cb_period.currentIndex()]
        today = date.today()
        if days is None:
            return None, None
        if days == -1:
            f, t = self.de_from.date().toPython(), self.de_to.date().toPython()
            return (min(f, t), max(f, t))
        return today - timedelta(days=days), today

    def _append_log(self, line: str):
        self.log.appendPlainText(line)

    # ---------- 자동 전송 ----------
    def _send_config(self, save: bool = False) -> Dict[str, Any]:
        cfg = {
            "mail_on": self.chk_mail.isChecked(),
            "mail_from": self.ed_mail_from.text().strip(),
            "mail_pw": self.ed_mail_pw.text().strip(),
            "mail_to": self.ed_mail_to.text().strip(),
            "tg_on": self.chk_tg.isChecked(),
            "tg_token": self.ed_tg_token.text().strip(),
            "tg_chat": self.ed_tg_chat.text().strip(),
        }
        if save:
            auto_send.save_config(self.send_path, cfg)
        return cfg

    def _load_send_config(self) -> None:
        cfg = auto_send.load_config(self.send_path)
        self.chk_mail.setChecked(bool(cfg.get("mail_on")))
        self.ed_mail_from.setText(cfg.get("mail_from", ""))
        self.ed_mail_pw.setText(cfg.get("mail_pw", ""))
        self.ed_mail_to.setText(cfg.get("mail_to", ""))
        self.chk_tg.setChecked(bool(cfg.get("tg_on")))
        self.ed_tg_token.setText(cfg.get("tg_token", ""))
        self.ed_tg_chat.setText(cfg.get("tg_chat", ""))

    def _find_chat_id(self) -> None:
        res = auto_send.find_chat_id(self.ed_tg_token.text())
        if res.lstrip("-").isdigit():
            self.ed_tg_chat.setText(res)
            self._append_log(f"텔레그램 챗 ID를 찾았습니다: {res}")
        else:
            QMessageBox.information(self, "챗 ID 찾기", res)

    def _test_send(self) -> None:
        cfg = self._send_config(save=True)
        if not (cfg["mail_on"] or cfg["tg_on"]):
            QMessageBox.information(self, "테스트 전송", "메일 또는 텔레그램 중 보낼 곳을 체크하세요.")
            return
        path = os.path.join(self.base_dir, "온하우스_전송테스트.txt")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"온하우스 매물수집기 전송 테스트 {datetime.now():%Y-%m-%d %H:%M:%S}" + chr(10))
        except Exception as e:
            QMessageBox.warning(self, "테스트 전송", f"테스트 파일을 만들지 못했습니다: {e}")
            return
        self._append_log("테스트 전송 중...")
        auto_send.deliver(cfg, path, "온하우스 매물수집기 전송 테스트", self._append_log)
        try:
            os.remove(path)
        except Exception:
            pass
        QMessageBox.information(self, "테스트 전송", "결과를 아래 로그에서 확인하세요.")

    def _open_out_dir(self):
        os.makedirs(self.out_dir, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.out_dir))

    # ---------- 설정 스냅샷 (예약용) ----------
    def _snapshot_settings(self) -> Dict[str, Any]:
        f, t = self._date_range()
        return {
            "si": self.cb_si.checked_labels(),
            "gun": self.cb_gun.checked_labels(),
            "dong": self.cb_dong.checked_labels(),
            "trade": [k for k, cb in self.trade_checks.items() if cb.isChecked()],
            "room": self.cb_room.currentText(),
            "period_idx": self.cb_period.currentIndex(),
            "date_from": f.isoformat() if f else None,
            "date_to": t.isoformat() if t else None,
            "contact": self.chk_contact.isChecked(),
            "delay_min": self.sp_delay_min.value(),
            "delay_max": self.sp_delay_max.value(),
            "max_pages": self.sp_max_pages.value(),
        }

    def _apply_settings(self, s: Dict[str, Any]) -> None:
        # 상위 → 하위 순서로 체크해야 계단식 목록이 다시 만들어진 뒤 하위 체크가 반영된다
        self.cb_si.set_checked_labels(s.get("si") or [])
        self.cb_gun.set_checked_labels(s.get("gun") or [])
        self.cb_dong.set_checked_labels(s.get("dong") or [])
        for k, cb in self.trade_checks.items():
            cb.setChecked(k in (s.get("trade") or []))
        self.cb_room.setCurrentText(s.get("room") or "전체")
        self.cb_period.setCurrentIndex(int(s.get("period_idx") or 0))
        if DATE_PERIODS[self.cb_period.currentIndex()][1] == -1:
            if s.get("date_from"):
                self.de_from.setDate(QDate.fromString(s["date_from"], "yyyy-MM-dd"))
            if s.get("date_to"):
                self.de_to.setDate(QDate.fromString(s["date_to"], "yyyy-MM-dd"))
        self.chk_contact.setChecked(bool(s.get("contact")))
        self.sp_delay_min.setValue(int(s.get("delay_min", 2)))
        self.sp_delay_max.setValue(int(s.get("delay_max", 5)))
        self.sp_max_pages.setValue(int(s.get("max_pages", 0)))

    def _settings_summary(self, s: Dict[str, Any]) -> str:
        def j(v, default="전체"):
            return ", ".join(v) if v else default

        period = DATE_PERIODS[int(s.get("period_idx") or 0)][0]
        if DATE_PERIODS[int(s.get("period_idx") or 0)][1] == -1:
            period = f"{s.get('date_from')} ~ {s.get('date_to')}"
        return (
            f"지역: {j(s.get('si'))} / {j(s.get('gun'))} / {j(s.get('dong'))}\n"
            f"유형: {j(s.get('trade'), '-')} · 방유형 {s.get('room')} · 확인일 {period}\n"
            f"연락처 {'ON' if s.get('contact') else 'OFF'} · 대기 {s.get('delay_min')}~{s.get('delay_max')}초 · "
            f"최대 페이지 {s.get('max_pages') or '제한없음'}"
        )

    # ---------- 예약 ----------
    def _refresh_schedule_list(self):
        cur = self.lst_sched.currentItem()
        keep = cur.data(0x0100) if cur else None
        self.lst_sched.clear()
        for job in self.schedules.get_all():
            days = "매일" if "daily" in job.days else "".join(DAY_LABELS.get(d, d) for d in DAY_NAMES if d in job.days)
            last = f" | 마지막 실행 {job.last_run_date}" if job.last_run_date else ""
            it = QListWidgetItem(f"{'[켜짐]' if job.enabled else '[꺼짐]'} {job.schedule_time} {days} | {job.name}{last}")
            it.setData(0x0100, job.id)  # Qt.UserRole
            it.setToolTip(self._settings_summary(job.settings))
            self.lst_sched.addItem(it)
            if job.id == keep:
                self.lst_sched.setCurrentItem(it)

    def _selected_job(self) -> Optional[ScheduledJob]:
        it = self.lst_sched.currentItem()
        if not it:
            return None
        jid = it.data(0x0100)
        return next((j for j in self.schedules.get_all() if j.id == jid), None)

    def _add_schedule(self):
        if not self.ed_id.text().strip() or not self.ed_pw.text().strip():
            QMessageBox.warning(self, "오류", "예약 실행에는 저장된 아이디/비밀번호가 필요합니다. 먼저 입력하고 '저장'을 체크하세요.")
            return
        if not self.chk_save.isChecked():
            self.chk_save.setChecked(True)
        self._save_credentials(self.ed_id.text().strip(), self.ed_pw.text().strip())
        snap = self._snapshot_settings()
        if not snap["trade"]:
            QMessageBox.warning(self, "오류", "거래유형(월세/전세/매매)을 하나 이상 선택하세요.")
            return
        dlg = ScheduleAddDialog(self._settings_summary(snap), self)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.result:
            return
        name, hhmm, days = dlg.result
        import uuid

        self.schedules.add(ScheduledJob(id=uuid.uuid4().hex[:8], name=name, site="onhouse", settings=snap, schedule_time=hhmm, days=days))
        self._refresh_schedule_list()
        self._append_log(f"예약 추가: {hhmm} {'매일' if 'daily' in days else ','.join(DAY_LABELS[d] for d in days)} — {name}")

    def _remove_schedule(self):
        job = self._selected_job()
        if job:
            self.schedules.remove(job.id)
            self._refresh_schedule_list()

    def _toggle_schedule(self):
        job = self._selected_job()
        if job:
            job.enabled = not job.enabled
            self.schedules.update(job)
            self._refresh_schedule_list()

    def _run_schedule_now(self):
        job = self._selected_job()
        if not job:
            return
        self._run_job(job, mark=False)

    def _run_job(self, job: ScheduledJob, mark: bool = True):
        if self.worker_thread and self.worker_thread.isRunning():
            self._append_log(f"예약 [{job.name}] 건너뜀 — 다른 수집이 진행 중")
            return
        self._apply_settings(job.settings)
        self._current_job_name = job.name
        if mark:
            self.schedules.mark_ran(job.id)
            self._refresh_schedule_list()
        self._start(auto=True)

    # ---------- 무인 실행 (윈도우 작업 스케줄러용) ----------
    def run_batch(self, job_name: Optional[str] = None) -> None:
        """--run-all / --run-job 으로 실행. 저장된 예약 조건으로 수집하고 끝나면 프로그램을 닫는다."""
        self._batch_mode = True
        jobs = [j for j in self.schedules.get_all() if j.enabled]
        if job_name:
            jobs = [j for j in jobs if j.name == job_name]
        if not jobs:
            self._append_log(
                f"무인 실행: 실행할 예약이 없습니다"
                + (f" (이름 '{job_name}')" if job_name else " — 프로그램에서 예약을 먼저 만들어 두세요")
            )
            QTimer.singleShot(1500, QApplication.quit)
            return
        if not self.ed_id.text().strip() or not self.ed_pw.text().strip():
            self._append_log("무인 실행: 저장된 아이디/비밀번호가 없습니다 — 프로그램에서 '아이디/비밀번호 저장'을 체크하세요.")
            QTimer.singleShot(1500, QApplication.quit)
            return
        self._batch_queue = jobs
        self._append_log(f"무인 실행 시작: 예약 {len(jobs)}개")
        self._batch_next()

    def _batch_next(self) -> None:
        if not self._batch_queue:
            self._append_log("무인 실행 완료 — 프로그램을 종료합니다.")
            QTimer.singleShot(1500, QApplication.quit)
            return
        job = self._batch_queue.pop(0)
        self._append_log(f"무인 실행: [{job.name}]")
        self._run_job(job, mark=False)

    def _check_schedules(self):
        if self.worker_thread and self.worker_thread.isRunning():
            return
        due = self.schedules.get_due_jobs()
        if due:
            self._run_job(due[0])

    # ---------- 실행 ----------
    def _start(self, auto: bool = False):
        uid, pwd = self.ed_id.text().strip(), self.ed_pw.text().strip()
        if not uid or not pwd:
            if not auto:
                QMessageBox.warning(self, "오류", "온하우스 아이디/비밀번호를 입력하세요.")
            else:
                self._append_log("예약 실행 실패: 아이디/비밀번호 없음")
            return
        trade_types = [k for k in TRADE_TYPES if self.trade_checks[k].isChecked()]
        if not trade_types:
            if not auto:
                QMessageBox.warning(self, "오류", "거래유형(월세/전세/매매)을 하나 이상 선택하세요.")
            return
        regions = self._selected_regions()
        if not regions:
            if not auto:
                QMessageBox.warning(self, "오류", "선택된 지역이 없습니다.")
            return
        if not auto and len(regions) > 100:
            r = QMessageBox.question(
                self,
                "확인",
                f"선택 지역이 {len(regions)}개입니다. 시간이 매우 오래 걸리고 계정에 부담이 갑니다.\n계속할까요?",
            )
            if r != QMessageBox.StandardButton.Yes:
                return
        if not auto and self.chk_contact.isChecked():
            r = QMessageBox.question(
                self,
                "연락처 수집 확인",
                "연락처 수집을 켜면 새 매물 1건마다 계정의 '연락처 조회수'가 1씩 차감됩니다.\n계속할까요?",
            )
            if r != QMessageBox.StandardButton.Yes:
                return
        self._save_credentials(uid, pwd)

        room = self.cb_room.currentText()
        date_from, date_to = self._date_range()
        period_label = self.cb_period.currentText()
        if DATE_PERIODS[self.cb_period.currentIndex()][1] == -1 and date_from and date_to:
            period_label = f"{date_from:%y%m%d}-{date_to:%y%m%d}"
        params = {
            "uid": uid,
            "pwd": pwd,
            "regions": regions,
            "bbox": self.bbox,
            "trade_types": trade_types,
            "room_type": "all" if room == "전체" else room,
            "contact": self.chk_contact.isChecked(),
            "delay_min": self.sp_delay_min.value(),
            "delay_max": self.sp_delay_max.value(),
            "max_pages": self.sp_max_pages.value(),
            "date_from": date_from,
            "date_to": date_to,
            "period_label": period_label,
            "out_dir": self.out_dir,
            "region_label": self._region_label(),
            "contact_cache_path": os.path.join(self.base_dir, "onhouse_contacts_cache.json"),
            "send": self._send_config(save=True),
        }
        self.log.clear()
        period_txt = "전체" if not (date_from or date_to) else f"{date_from} ~ {date_to}"
        head = f"예약 실행 [{self._current_job_name}] " if auto and self._current_job_name else ""
        self._current_job_name = ""
        self._append_log(
            f"{head}시작 {datetime.now():%Y-%m-%d %H:%M}: 지역 {len(regions)}개 / {', '.join(trade_types)} / {room} / "
            f"확인일 {period_txt} / 연락처 {'ON' if params['contact'] else 'OFF'}"
        )
        self.progress.setValue(0)
        self.lbl_status.setText("실행 중")
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)

        self.worker_thread = QThread(self)
        self.worker = Worker(params)
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.log.connect(self._append_log)
        self.worker.status.connect(self.lbl_status.setText)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.failed.connect(self.worker_thread.quit)
        self.worker_thread.finished.connect(self._cleanup)
        self.worker_thread.start()

    def _stop(self):
        if self.worker:
            self.worker.cancel()
            self.lbl_status.setText("중지 요청 — 진행 중인 건 마무리 후 저장합니다...")
            self.btn_stop.setEnabled(False)

    def _on_progress(self, cur: int, total: int):
        self.progress.setValue(int(cur * 100 / total) if total else 0)

    def _on_finished(self, msg: str):
        self.lbl_status.setText(msg)
        self._append_log(msg)
        self.progress.setValue(100)
        if self._batch_mode:
            QTimer.singleShot(2000, self._batch_next)

    def _on_failed(self, msg: str):
        self.lbl_status.setText(f"오류: {msg}")
        self._append_log(f"오류: {msg}")
        if self._batch_mode:
            QTimer.singleShot(2000, self._batch_next)
            return
        # 예약 실행 중 모달 창이 뜨면 다음 예약이 막히므로, 사람이 시작한 경우에만 팝업
        if not self.sched_timer.isActive() or QApplication.activeWindow() is self:
            QMessageBox.critical(self, "오류", msg)

    def _cleanup(self):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        if self.worker:
            self.worker.deleteLater()
        if self.worker_thread:
            self.worker_thread.deleteLater()
        self.worker = None
        self.worker_thread = None

    def closeEvent(self, ev):
        self._send_config(save=True)
        if self.worker_thread and self.worker_thread.isRunning():
            r = QMessageBox.question(self, "종료", "수집이 진행 중입니다. 종료할까요? (저장되지 않습니다)")
            if r != QMessageBox.StandardButton.Yes:
                ev.ignore()
                return
            if self.worker:
                self.worker.cancel()
            self.worker_thread.quit()
            self.worker_thread.wait(3000)
        ev.accept()


def main():
    argv = sys.argv[1:]
    batch = "--run-all" in argv
    job_name: Optional[str] = None
    if "--run-job" in argv:
        i = argv.index("--run-job")
        if i + 1 < len(argv):
            job_name = argv[i + 1]
            batch = True

    app = QApplication.instance() or QApplication(sys.argv)
    w = MainWindow()
    if batch:
        # 작업 스케줄러가 부른 경우: 창은 최소화로 띄우고(로그 확인용) 끝나면 스스로 종료
        w.showMinimized()
        QTimer.singleShot(800, lambda: w.run_batch(job_name))
    else:
        w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
