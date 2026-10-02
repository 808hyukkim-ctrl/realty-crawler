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
    QTabWidget,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

import auto_send
from app_main_common import (
    APP_STYLESHEET, DetailFilters, MultiSelectCombo, RangeInput, contains_any_keyword, parse_keywords_csv, wrap_in_scroll,
)
from onhouse_crawler import OnhouseCrawler
from schedule_manager import DAY_NAMES, ScheduleManager, ScheduledJob

DAY_LABELS = {"mon": "월", "tue": "화", "wed": "수", "thu": "목", "fri": "금", "sat": "토", "sun": "일"}
TRADE_TYPES = ["월세", "전세", "매매"]

APP_TITLE = "온하우스 매물수집기"
PHONE_VIEW_URL = "https://www.onhouse.com/index.php/dataFunction/phoneView"
PAGE_SIZE = 30
ROOM_TYPES = ["전체", "주택", "오피", "주택/오피", "사무실", "상가", "사무실/상가", "분양사무실"]   # (옛 예약 호환용)
# 온하우스 서버 필터 (2026-10-01 실측): roomType/structure 는 '주택','오피스텔' 처럼 따옴표 목록, floorArray 는 1층,2층 처럼 쉼표, 옵션은 Y
ROOM_KINDS = ["주택", "오피스텔", "아파트", "사무실", "상가"]
STRUCTURES = {"원룸": ["오픈형원룸", "분리형원룸", "분리형원룸(1룸 1거실)", "복층형원룸"], "투룸": ["투룸"], "쓰리룸": ["쓰리룸"], "포룸+": ["포룸+"]}
FLOOR_ARRAY = ["지하층", "1층", "2층", "3층 이상"]
SERVER_OPTIONS = [  # (라벨, 파라미터, 값)
    ("엘리베이터", "elevator", "Y"), ("주차 가능", "parking", "Y"), ("반려동물", "pet", "Y"), ("풀옵션", "fulloption", "Y"),
    ("즉시입주", "moveInType", "즉시입주"), ("반지하 제외", "noSemiBasement", "Y"), ("1층 제외", "noFirstFloor", "Y"),
    ("전세대출 가능", "cfLoan", "Y"), ("권리금 없음", "noPremiumPrice", "Y"), ("관리비 포함", "managementFeeYn", "Y"),
    ("인테리어", "interior", "Y"), ("내부사진 있음", "img", "room"),
]
KEYWORD_PRESETS = ["통임대", "통매매", "건물전체", "반려", "대출", "LH", "SH", "보증보험", "풀옵션", "주차", "엘리베이터", "신축", "역세권", "즉시입주"]
DATE_BY = [("확인일(업로드)", "chk"), ("등록일", "reg")]
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


_DETAIL_DATE_RE = re.compile(
    r'class="flex_title"[^>]*>\s*(확인일|등록일)\s*<.*?class="flex_desc"[^>]*>\s*([\d][\d./\- :]*?)\s*<', re.S
)


def parse_detail_dates(html: str) -> Dict[str, Optional[date]]:
    """상세 페이지의 '확인일' / '등록일' (예: 26.10.01, 2026-10-01) → date"""
    out: Dict[str, Optional[date]] = {}
    for k, v in _DETAIL_DATE_RE.findall(html or ""):
        m = re.match(r"(\d{2,4})[.\-/](\d{1,2})[.\-/](\d{1,2})", v.strip())
        if not m:
            continue
        y = int(m.group(1))
        if y < 100:
            y += 2000
        try:
            out[k] = date(y, int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    return out


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

    @staticmethod
    def _post_ok(parsed: Dict[str, Any], post: DetailFilters, keywords: List[str]) -> bool:
        """상세를 읽은 뒤 거르는 조건: 방수/층수/준공년 + 키워드(상세의 모든 값에서 찾음)"""
        if post.active:
            rooms = str(parsed.get("방수 / 욕실수") or parsed.get("방수") or "")
            floor = str(parsed.get("해당층 / 전체층") or parsed.get("해당층") or "")
            approve = " ".join(str(v) for k, v in parsed.items() if str(k).endswith("_태그") or k in ("준공년", "사용승인일"))
            if not post.passes(rooms=rooms, floor=floor, approve=approve, use=""):
                return False
        if keywords:
            text = " ".join(str(v) for v in parsed.values() if v)
            if not contains_any_keyword(text, keywords):
                return False
        return True

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
            by_reg: bool = self.p.get("date_by") == "reg"   # 기간을 확인일이 아니라 등록일로 (목록은 등록일 내림차순 요청)
            date_word = "등록일" if by_reg else "확인일"
            warned_no_reg = False
            # 거래유형별 검색 회차: 가격 조건이 거래유형마다 다르므로(보증금/월세/전세/매매가) 가격을 걸면 유형별로 따로 검색한다
            passes: List[Tuple[List[str], Dict[str, Any]]] = self.p.get("passes") or [(trade_types, {})]
            post = DetailFilters(rooms=self.p.get("post_rooms"), floors=self.p.get("post_floors"), years=self.p.get("post_years"))
            keywords: List[str] = list(self.p.get("keywords") or [])
            skipped_by_filter = 0
            # 같은 매물 중복 제거: 온하우스엔 같은 집이 매물번호만 다르게 두 번 올라오는 경우가 있다 → 주소·호실·금액·면적이 같으면 하나만
            dedupe_same: bool = bool(self.p.get("dedupe", True))
            seen_keys: set = set()
            skipped_dup = 0
            if len(passes) > 1:
                self.log.emit(f"  가격 조건이 있어 거래유형별로 {len(passes)}회 나눠 검색합니다")
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
                for pass_trades, pass_extra in passes:
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
                        trade_type=pass_trades,
                        room_type="all",
                        limit=PAGE_SIZE,
                        page=page,
                        fetch_details=False,
                        is_cancelled=lambda: self._cancel,
                        **{**({"order1": "R.INS_DATE|DESC"} if by_reg else {}), **pass_extra},
                    ) or []
                    if not ids:
                        if page == 0:
                            self.log.emit(f"  {region}: 매물 없음")
                        break

                    # 목록 항목(확인일 내림차순). HTML 파싱이 안 된 경우엔 ID만으로 진행.
                    items = crawler.last_items or [{"id": str(i), "chk": "", "lat": "", "lng": ""} for i in ids]
                    if (date_from or date_to) and not by_reg and not any(it["chk"] for it in items) and not warned_no_date:
                        warned_no_date = True
                        self.log.emit("  주의: 목록에서 확인일을 읽지 못해 기간 필터를 적용할 수 없습니다 (전체 수집).")

                    page_older_exists = False
                    todo: List[Dict[str, str]] = []
                    for it in items:
                        d = None if by_reg else parse_chk_date(it["chk"])   # 등록일 기준이면 상세를 읽은 뒤 거른다
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
                            ddates = parse_detail_dates(html)
                            reg_d = ddates.get("등록일")
                            if by_reg and (date_from or date_to):
                                if reg_d is None:
                                    if not warned_no_reg:
                                        warned_no_reg = True
                                        self.log.emit("  주의: 상세에서 등록일을 읽지 못한 매물이 있어 그 매물은 기간과 상관없이 담습니다.")
                                else:
                                    if date_from and reg_d < date_from:
                                        page_older_exists = True   # 등록일 내림차순이므로 이 뒤는 전부 더 오래됨 → 상세를 더 읽지 않고 이 지역 종료
                                        skipped_by_date += 1
                                        self.log.emit(f"  {hid} 등록일 {reg_d} — 기간 이전이라 여기서 멈춤 (이 뒤는 모두 더 오래된 매물)")
                                        break
                                    if date_to and reg_d > date_to:
                                        skipped_by_date += 1
                                        self._sleep_between()
                                        continue
                            if not self._post_ok(parsed, post, keywords):
                                skipped_by_filter += 1
                                self._sleep_between()
                                continue
                            if dedupe_same:
                                price_txt = next((str(parsed.get(k)) for k in ("월세", "전세", "매매", "단기") if parsed.get(k)), "")
                                dkey = re.sub(r"\s+", "", f"{parsed.get('전체주소') or ''}|{parsed.get('주소_호실') or ''}|{price_txt}|{parsed.get('전용면적(㎡/P)') or ''}")
                                if dkey and dkey != "|||" and dkey in seen_keys:
                                    skipped_dup += 1
                                    self.log.emit(f"  {hid} 같은 매물 중복(주소·호실·금액 동일) — 건너뜀")
                                    self._sleep_between()
                                    continue
                                seen_keys.add(dkey)
                            row: Dict[str, Any] = {
                                "매물ID": parsed.get("매물ID", hid),
                                "URL": parsed.get("URL", f"{crawler.DETAIL_URL}/{hid}"),
                                "확인일": it["chk"][:19],
                                "지역": region,
                            }
                            for k, v in parsed.items():
                                if k not in row:
                                    row[k] = v
                            if reg_d is not None:
                                row["등록일"] = reg_d.isoformat()
                            if ddates.get("확인일") is not None and not row.get("확인일"):
                                row["확인일"] = ddates["확인일"].isoformat()
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
                        when = (f"등록 {row.get('등록일')}" if by_reg and row.get("등록일") else it['chk'][:16])
                        self.log.emit(f"  [{len(all_rows)}] {hid} | {when} | {addr} | {price}{tel}")
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
                  if stopped:
                      break
                self.progress.emit(ri, total)

            if cache_path and new_lookups:
                save_contact_cache(cache_path, contact_cache)
            if date_from or date_to:
                self.log.emit(f"  {date_word} 기간 필터로 제외된 매물: {skipped_by_date}건")
            if skipped_by_filter:
                self.log.emit(f"  방수/층수/준공년/키워드 조건으로 제외된 매물: {skipped_by_filter}건")
            if skipped_dup:
                self.log.emit(f"  같은 매물 중복 제거: {skipped_dup}건")
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
        self.resize(1100, 920)
        self.setStyleSheet(APP_STYLESHEET)
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
        central = QWidget()
        central.setObjectName("appRoot")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 3)
        self.tabs.addTab(wrap_in_scroll(self._build_collect_tab()), "온하우스 수집")
        self.tabs.addTab(wrap_in_scroll(self._build_send_tab()), "자동 전송")
        self.tabs.addTab(wrap_in_scroll(self._build_schedule_tab()), "예약 자동 실행")

        ctrl = QHBoxLayout()
        self.btn_start = QPushButton("수집 시작")
        self.btn_stop = QPushButton("중지 (지금까지 저장)")
        self.btn_stop.setEnabled(False)
        self.btn_clear = QPushButton("수집 로그 지우기")
        self.btn_open = QPushButton("수집된 파일 열기")
        self.btn_sched_add = QPushButton("현재 설정으로 예약 추가")
        self.btn_start.clicked.connect(self._start)
        self.btn_stop.clicked.connect(self._stop)
        self.btn_clear.clicked.connect(lambda: self.log.clear())
        self.btn_open.clicked.connect(self._open_out_dir)
        self.btn_sched_add.clicked.connect(self._add_schedule)
        for btn in (self.btn_start, self.btn_stop, self.btn_clear, self.btn_open, self.btn_sched_add):
            ctrl.addWidget(btn)
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
        self.log.setMinimumHeight(140)
        self.log.setStyleSheet("background:#0f172a; color:#e2e8f0; border-radius:10px; padding:6px; font-family:Consolas,'Malgun Gothic';")
        root.addWidget(self.log, 1)
        self._refresh_trade_controls()

    # ---------- 탭 1: 수집 조건 ----------
    def _build_collect_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(10)

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

        reg = QGroupBox("지역 (체크박스로 여러 곳 동시 선택 가능 — 하위 단계를 체크하면 그것만, 아니면 상위 선택 전체)")
        h = QHBoxLayout(reg)
        self.cb_si = MultiSelectCombo()
        self.cb_si.set_entries([(si, si) for si in self.si_list])
        self.cb_gun = MultiSelectCombo()
        self.cb_dong = MultiSelectCombo()
        for cb, wd in ((self.cb_si, 190), (self.cb_gun, 200), (self.cb_dong, 240)):
            cb.setMinimumWidth(wd)
        h.addWidget(QLabel("시/도"))
        h.addWidget(self.cb_si)
        h.addWidget(QLabel("시·군·구"))
        h.addWidget(self.cb_gun)
        h.addWidget(QLabel("읍·면·동"))
        h.addWidget(self.cb_dong)
        h.addStretch(1)
        self.lbl_region_count = QLabel("")
        h.addWidget(self.lbl_region_count)
        self.cb_si.selection_changed.connect(self._on_si_changed)
        self.cb_gun.selection_changed.connect(self._on_gun_changed)
        self.cb_dong.selection_changed.connect(self._update_region_count)
        v.addWidget(reg)

        kind_box = QGroupBox("매물유형 (체크 없음 = 전체)")
        kg = QGridLayout(kind_box)
        self.room_checks: Dict[str, QCheckBox] = {}
        for i, k in enumerate(ROOM_KINDS):
            cb = QCheckBox(k)
            self.room_checks[k] = cb
            kg.addWidget(cb, 0, i)
        kg.addWidget(QLabel("방 구조(주택)"), 1, 0)
        self.struct_checks: Dict[str, QCheckBox] = {}
        for i, k in enumerate(STRUCTURES.keys()):
            cb = QCheckBox(k)
            self.struct_checks[k] = cb
            kg.addWidget(cb, 1, i + 1)
        kg.setColumnStretch(len(ROOM_KINDS), 1)
        v.addWidget(kind_box)

        trade_box = QGroupBox("거래유형")
        tr = QHBoxLayout(trade_box)
        self.chk_month = QCheckBox("월세")
        self.chk_jeonse = QCheckBox("전세")
        self.chk_buy = QCheckBox("매매")
        self.chk_month.setChecked(True)
        self.trade_checks: Dict[str, QCheckBox] = {"월세": self.chk_month, "전세": self.chk_jeonse, "매매": self.chk_buy}
        for c in (self.chk_month, self.chk_jeonse, self.chk_buy):
            tr.addWidget(c)
            c.toggled.connect(lambda _checked=False: self._refresh_trade_controls())
        tr.addStretch(1)
        v.addWidget(trade_box)

        price_box = QGroupBox("가격/면적/기간 (직접 입력, 빈칸=제한없음 · 가격은 온하우스 서버에서 바로 걸러짐)")
        pg = QGridLayout(price_box)
        self.sl_deposit = RangeInput("보증금", unit="만원")
        self.sl_rent = RangeInput("월세", unit="만원")
        self.sl_buy = RangeInput("매매가", unit="만원")
        self.sl_jeonse = RangeInput("전세", unit="만원")
        self.sl_area = RangeInput("면적", unit="평", unit_toggle=("㎡", 3.3058))
        pg.addWidget(self.sl_deposit, 0, 0)
        pg.addWidget(self.sl_rent, 0, 1)
        pg.addWidget(self.sl_buy, 1, 0)
        pg.addWidget(self.sl_jeonse, 1, 1)
        pg.addWidget(self.sl_area, 2, 0)
        date_wrap = QWidget()
        dr = QHBoxLayout(date_wrap)
        dr.setContentsMargins(10, 0, 0, 0)
        dr.setSpacing(8)
        self.cb_date_by = QComboBox()
        self.cb_date_by.addItems([lbl for lbl, _ in DATE_BY])
        self.cb_date_by.setToolTip(
            "확인일(업로드): 온하우스가 매물을 확인/갱신한 날 — 목록이 이 순서라 빠릅니다.\n"
            "등록일: 매물이 처음 올라온 날 — 목록을 등록일 순으로 받고 상세의 등록일로 거릅니다."
        )
        self.lbl_period = QLabel("기간")
        self.cb_period = QComboBox()
        self.cb_period.addItems([lbl for lbl, _ in DATE_PERIODS])
        self.cb_period.setMinimumWidth(110)
        self.de_from = QDateEdit(QDate.currentDate().addDays(-6))
        self.de_to = QDateEdit(QDate.currentDate())
        for de in (self.de_from, self.de_to):
            de.setCalendarPopup(True)
            de.setDisplayFormat("yyyy-MM-dd")
            de.setEnabled(False)
        dr.addWidget(QLabel("기준"))
        dr.addWidget(self.cb_date_by)
        dr.addWidget(self.lbl_period)
        dr.addWidget(self.cb_period)
        dr.addWidget(self.de_from)
        dr.addWidget(QLabel("~"))
        dr.addWidget(self.de_to)
        dr.addStretch(1)
        pg.addWidget(date_wrap, 3, 0, 1, 2)   # 기간 줄은 전체 폭 (기준·프리셋·날짜가 길어서)
        pg.setColumnStretch(0, 1)
        pg.setColumnStretch(1, 1)
        pg.setHorizontalSpacing(16)
        pg.setVerticalSpacing(4)
        self.cb_period.currentIndexChanged.connect(self._on_period_changed)
        v.addWidget(price_box)

        detail_box = QGroupBox("상세 조건 (방수/층수/준공년 — 상세를 읽은 뒤 거릅니다)")
        dg = QGridLayout(detail_box)
        self.sl_rooms = RangeInput("방수", unit="개")
        self.sl_floor = RangeInput("층수", unit="층 (반지하/지하=0)")
        self.sl_year = RangeInput("준공년", unit="년", default_min_text="1950")
        dg.addWidget(self.sl_rooms, 0, 0)
        dg.addWidget(self.sl_floor, 0, 1)
        dg.addWidget(self.sl_year, 1, 0)
        floor_wrap = QWidget()
        fl = QHBoxLayout(floor_wrap)
        fl.setContentsMargins(10, 0, 0, 0)
        fl.addWidget(QLabel("층 (서버 필터)"))
        self.floor_checks: Dict[str, QCheckBox] = {}
        for k in FLOOR_ARRAY:
            cb = QCheckBox(k)
            self.floor_checks[k] = cb
            fl.addWidget(cb)
        fl.addStretch(1)
        dg.addWidget(floor_wrap, 1, 1)
        dg.setColumnStretch(0, 1)
        dg.setColumnStretch(1, 1)
        dg.setHorizontalSpacing(16)
        dg.setVerticalSpacing(4)
        v.addWidget(detail_box)

        opt_box = QGroupBox("옵션 (온하우스 서버 필터 · 체크한 것만 수집)")
        og = QGridLayout(opt_box)
        self.option_checks: Dict[str, QCheckBox] = {}
        for i, (label, key, _val) in enumerate(SERVER_OPTIONS):
            cb = QCheckBox(label)
            self.option_checks[key] = cb
            og.addWidget(cb, i // 6, i % 6)
        v.addWidget(opt_box)

        text_box = QGroupBox("상세 텍스트 필터 (입력 키워드 + 체크 키워드 중 하나라도 매물 정보에 있으면 수집)")
        fr = QHBoxLayout(text_box)
        fr.setSpacing(12)
        left = QWidget()
        lf = QHBoxLayout(left)
        lf.setContentsMargins(0, 0, 0, 0)
        self.ed_keywords = QLineEdit()
        self.ed_keywords.setPlaceholderText("키워드,콤마로구분 (예: 통임대,역세권)")
        lf.addWidget(QLabel("키워드"))
        lf.addWidget(self.ed_keywords, 1)
        right = QWidget()
        rg = QGridLayout(right)
        rg.setContentsMargins(0, 0, 0, 0)
        rg.setHorizontalSpacing(10)
        rg.setVerticalSpacing(2)
        self.kw_checks: Dict[str, QCheckBox] = {}
        for i, kw in enumerate(KEYWORD_PRESETS):
            cb = QCheckBox(kw)
            self.kw_checks[kw] = cb
            rg.addWidget(cb, i // 7, i % 7)
        fr.addWidget(left, 1)
        fr.addWidget(right, 2)
        v.addWidget(text_box)

        opt = QGroupBox("수집 옵션")
        g = QGridLayout(opt)
        self.chk_contact = QCheckBox(
            "임대인 연락처도 수집  (새 매물 1건당 '연락처 조회수' 1 차감. 이미 조회한 매물은 캐시에서 재사용 — 차감 없음)"
        )
        g.addWidget(self.chk_contact, 0, 0, 1, 6)
        self.chk_dedupe = QCheckBox("같은 매물 중복 제거 (주소·호실·금액·면적이 같으면 하나만 — 온하우스에 두 번 올라온 매물 정리)")
        self.chk_dedupe.setChecked(True)
        g.addWidget(self.chk_dedupe, 2, 0, 1, 6)
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
        v.addStretch(1)
        return w

    # ---------- 탭 2: 자동 전송 ----------
    def _build_send_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
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
        v.addStretch(1)
        return w

    # ---------- 탭 3: 예약 ----------
    def _build_schedule_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        sch = QGroupBox("예약 자동 실행 (이 프로그램이 켜져 있는 동안, 지정 시각에 저장된 조건으로 자동 수집 · 자동실행_설정.bat 으로 무인 실행도 가능)")
        sl = QHBoxLayout(sch)
        self.lst_sched = QListWidget()
        self.lst_sched.setMinimumHeight(160)
        sl.addWidget(self.lst_sched, 1)
        bl = QVBoxLayout()
        self.btn_sched_add2 = QPushButton("현재 설정으로 예약 추가")
        self.btn_sched_toggle = QPushButton("선택 켜기/끄기")
        self.btn_sched_run = QPushButton("선택 예약 지금 실행")
        self.btn_sched_del = QPushButton("선택 삭제")
        self.btn_sched_add2.clicked.connect(self._add_schedule)
        self.btn_sched_toggle.clicked.connect(self._toggle_schedule)
        self.btn_sched_run.clicked.connect(self._run_schedule_now)
        self.btn_sched_del.clicked.connect(self._remove_schedule)
        for b in (self.btn_sched_add2, self.btn_sched_toggle, self.btn_sched_run, self.btn_sched_del):
            bl.addWidget(b)
        bl.addStretch(1)
        sl.addLayout(bl)
        v.addWidget(sch)
        v.addStretch(1)
        return w

    # ---------- 조건 읽기 ----------
    def _refresh_trade_controls(self):
        """거래유형에 맞는 가격 칸만 켠다"""
        month = self.chk_month.isChecked()
        self.sl_deposit.set_enabled(month)
        self.sl_rent.set_enabled(month)
        self.sl_jeonse.set_enabled(self.chk_jeonse.isChecked())
        self.sl_buy.set_enabled(self.chk_buy.isChecked())

    @staticmethod
    def _range_or_none(r: RangeInput):
        lo, hi = r.values()
        if lo <= 0 and hi >= RangeInput.OPEN_MAX:
            return None
        return (lo, hi)

    @staticmethod
    def _range_params(r: RangeInput, lo_key: str, hi_key: str) -> Dict[str, str]:
        v = MainWindow._range_or_none(r)
        if not v:
            return {}
        lo, hi = v
        out: Dict[str, str] = {}
        if lo > 0:
            out[lo_key] = str(lo)
        if hi < RangeInput.OPEN_MAX:
            out[hi_key] = str(hi)
        return out

    def _by_reg(self) -> bool:
        return DATE_BY[self.cb_date_by.currentIndex()][1] == "reg"

    def _server_common(self) -> Dict[str, Any]:
        """모든 회차에 공통으로 붙는 서버 필터 (매물유형·구조·층·옵션·면적)"""
        extra: Dict[str, Any] = {}
        kinds = [k for k, cb in self.room_checks.items() if cb.isChecked()]
        if kinds:
            extra["roomType"] = ",".join(f"'{k}'" for k in kinds)
        structs: List[str] = []
        for k, cb in self.struct_checks.items():
            if cb.isChecked():
                structs.extend(STRUCTURES[k])
        if structs:
            extra["structure"] = ",".join(f"'{x}'" for x in structs)
        floors = [k for k, cb in self.floor_checks.items() if cb.isChecked()]
        if floors:
            extra["floorArray"] = ",".join(floors)
        for _label, key, val in SERVER_OPTIONS:
            if self.option_checks[key].isChecked():
                extra[key] = val
        extra.update(self._range_params(self.sl_area, "minArea", "maxArea"))
        return extra

    def _build_passes(self, trade_types: List[str]) -> List[Tuple[List[str], Dict[str, Any]]]:
        """거래유형별 가격 조건 → 검색 회차. 가격 조건이 하나도 없으면 한 번에 검색"""
        common = self._server_common()
        per: Dict[str, Dict[str, str]] = {
            "월세": {**self._range_params(self.sl_deposit, "minPrice", "maxPrice"), **self._range_params(self.sl_rent, "minMonthPrice", "maxMonthPrice")},
            "전세": self._range_params(self.sl_jeonse, "minPrice", "maxPrice"),
            "매매": self._range_params(self.sl_buy, "minPrice", "maxPrice"),
        }
        if not any(per[t] for t in trade_types):
            return [(list(trade_types), dict(common))]
        return [([t], {**common, **per[t]}) for t in trade_types]

    def _keywords(self) -> List[str]:
        kws = parse_keywords_csv(self.ed_keywords.text())
        kws += [k for k, cb in self.kw_checks.items() if cb.isChecked() and k not in kws]
        return kws

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
        rng = lambda r: list(r.values())
        return {
            "si": self.cb_si.checked_labels(),
            "gun": self.cb_gun.checked_labels(),
            "dong": self.cb_dong.checked_labels(),
            "trade": [k for k, cb in self.trade_checks.items() if cb.isChecked()],
            "kinds": [k for k, cb in self.room_checks.items() if cb.isChecked()],
            "structs": [k for k, cb in self.struct_checks.items() if cb.isChecked()],
            "floors_srv": [k for k, cb in self.floor_checks.items() if cb.isChecked()],
            "options": [k for k, cb in self.option_checks.items() if cb.isChecked()],
            "deposit": rng(self.sl_deposit), "rent": rng(self.sl_rent), "buy": rng(self.sl_buy), "jeonse": rng(self.sl_jeonse), "area": rng(self.sl_area),
            "rooms": rng(self.sl_rooms), "floor": rng(self.sl_floor), "year": rng(self.sl_year),
            "keywords": self.ed_keywords.text().strip(),
            "kw_checks": [k for k, cb in self.kw_checks.items() if cb.isChecked()],
            "period_idx": self.cb_period.currentIndex(),
            "by_reg": self._by_reg(),
            "date_from": f.isoformat() if f else None,
            "date_to": t.isoformat() if t else None,
            "contact": self.chk_contact.isChecked(),
            "dedupe": self.chk_dedupe.isChecked(),
            "delay_min": self.sp_delay_min.value(),
            "delay_max": self.sp_delay_max.value(),
            "max_pages": self.sp_max_pages.value(),
        }

    @staticmethod
    def _set_range(r: RangeInput, v: Any) -> None:
        try:
            lo, hi = (v or [0, RangeInput.OPEN_MAX])
            r.edt_min.setText("" if not lo else str(int(lo)))
            r.edt_max.setText("" if hi is None or int(hi) >= RangeInput.OPEN_MAX else str(int(hi)))
        except Exception:
            pass

    def _apply_settings(self, s: Dict[str, Any]) -> None:
        # 상위 → 하위 순서로 체크해야 계단식 목록이 다시 만들어진 뒤 하위 체크가 반영된다
        self.cb_si.set_checked_labels(s.get("si") or [])
        self.cb_gun.set_checked_labels(s.get("gun") or [])
        self.cb_dong.set_checked_labels(s.get("dong") or [])
        for k, cb in self.trade_checks.items():
            cb.setChecked(k in (s.get("trade") or []))
        kinds = s.get("kinds")
        if kinds is None and s.get("room") and s.get("room") != "전체":   # 옛 예약(방유형 드롭다운) 호환
            kinds = [k for k in ROOM_KINDS if k in str(s.get("room")).replace("오피", "오피스텔")]
        for k, cb in self.room_checks.items():
            cb.setChecked(k in (kinds or []))
        for k, cb in self.struct_checks.items():
            cb.setChecked(k in (s.get("structs") or []))
        for k, cb in self.floor_checks.items():
            cb.setChecked(k in (s.get("floors_srv") or []))
        for k, cb in self.option_checks.items():
            cb.setChecked(k in (s.get("options") or []))
        for key, r in (("deposit", self.sl_deposit), ("rent", self.sl_rent), ("buy", self.sl_buy), ("jeonse", self.sl_jeonse), ("area", self.sl_area),
                       ("rooms", self.sl_rooms), ("floor", self.sl_floor), ("year", self.sl_year)):
            self._set_range(r, s.get(key))
        if s.get("year") is None:
            self.sl_year.edt_min.setText("1950")
        self.ed_keywords.setText(str(s.get("keywords") or ""))
        for k, cb in self.kw_checks.items():
            cb.setChecked(k in (s.get("kw_checks") or []))
        self.cb_period.setCurrentIndex(int(s.get("period_idx") or 0))
        if DATE_PERIODS[self.cb_period.currentIndex()][1] == -1:
            if s.get("date_from"):
                self.de_from.setDate(QDate.fromString(s["date_from"], "yyyy-MM-dd"))
            if s.get("date_to"):
                self.de_to.setDate(QDate.fromString(s["date_to"], "yyyy-MM-dd"))
        self.cb_date_by.setCurrentIndex(1 if s.get("by_reg") else 0)
        self.chk_contact.setChecked(bool(s.get("contact")))
        self.chk_dedupe.setChecked(bool(s.get("dedupe", True)))
        self.sp_delay_min.setValue(int(s.get("delay_min", 2)))
        self.sp_delay_max.setValue(int(s.get("delay_max", 5)))
        self.sp_max_pages.setValue(int(s.get("max_pages", 0)))
        self._refresh_trade_controls()

    def _settings_summary(self, s: Dict[str, Any]) -> str:
        def j(v, default="전체"):
            return ", ".join(v) if v else default

        def rng(v, unit=""):
            if not v:
                return ""
            lo, hi = v
            if (lo or 0) <= 0 and (hi is None or int(hi) >= RangeInput.OPEN_MAX):
                return ""
            return f"{lo or 0}~{'' if hi is None or int(hi) >= RangeInput.OPEN_MAX else hi}{unit}"

        period = DATE_PERIODS[int(s.get("period_idx") or 0)][0]
        if DATE_PERIODS[int(s.get("period_idx") or 0)][1] == -1:
            period = f"{s.get('date_from')} ~ {s.get('date_to')}"
        prices = [f"{k} {rng(s.get(key), '만')}" for k, key in (("보증금", "deposit"), ("월세", "rent"), ("매매", "buy"), ("전세", "jeonse")) if rng(s.get(key))]
        if rng(s.get("area")):
            prices.append(f"면적 {rng(s.get('area'), '평')}")
        details = [f"{k} {rng(s.get(key))}" for k, key in (("방수", "rooms"), ("층수", "floor"), ("준공", "year")) if rng(s.get(key))]
        opts = [lbl for lbl, key, _ in SERVER_OPTIONS if key in (s.get("options") or [])]
        kws = [x for x in parse_keywords_csv(str(s.get("keywords") or ""))] + list(s.get("kw_checks") or [])
        return (
            f"지역: {j(s.get('si'))} / {j(s.get('gun'))} / {j(s.get('dong'))}\n"
            f"유형: {j(s.get('trade'), '-')} · 매물유형 {j(s.get('kinds'))}{' · 구조 ' + j(s.get('structs')) if s.get('structs') else ''}\n"
            f"{'등록일' if s.get('by_reg') else '확인일'} {period}"
            + (f" · {' · '.join(prices)}" if prices else "")
            + (f"\n상세: {' · '.join(details)}" if details else "")
            + (f"\n층 {j(s.get('floors_srv'))}" if s.get("floors_srv") else "")
            + (f"\n옵션: {', '.join(opts)}" if opts else "")
            + (f"\n키워드: {', '.join(kws)}" if kws else "")
            + f"\n연락처 {'ON' if s.get('contact') else 'OFF'} · 대기 {s.get('delay_min')}~{s.get('delay_max')}초 · 최대 페이지 {s.get('max_pages') or '제한없음'}"
        )

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

        date_from, date_to = self._date_range()
        period_label = self.cb_period.currentText()
        if DATE_PERIODS[self.cb_period.currentIndex()][1] == -1 and date_from and date_to:
            period_label = f"{date_from:%y%m%d}-{date_to:%y%m%d}"
        by_reg = self._by_reg()
        if by_reg and (date_from or date_to):
            period_label = f"등록일{period_label}"
        passes = self._build_passes(trade_types)
        kinds = [k for k, cb in self.room_checks.items() if cb.isChecked()]
        params = {
            "uid": uid,
            "pwd": pwd,
            "regions": regions,
            "bbox": self.bbox,
            "trade_types": trade_types,
            "room_type": "all",
            "passes": passes,
            "post_rooms": self._range_or_none(self.sl_rooms),
            "post_floors": self._range_or_none(self.sl_floor),
            "post_years": self._range_or_none(self.sl_year),
            "keywords": self._keywords(),
            "contact": self.chk_contact.isChecked(),
            "dedupe": self.chk_dedupe.isChecked(),
            "delay_min": self.sp_delay_min.value(),
            "delay_max": self.sp_delay_max.value(),
            "max_pages": self.sp_max_pages.value(),
            "date_from": date_from,
            "date_to": date_to,
            "date_by": "reg" if by_reg else "chk",
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
        cond = []
        for lbl, r, unit in (("보증금", self.sl_deposit, "만"), ("월세", self.sl_rent, "만"), ("매매", self.sl_buy, "만"), ("전세", self.sl_jeonse, "만"), ("면적", self.sl_area, "평"),
                             ("방수", self.sl_rooms, "개"), ("층수", self.sl_floor, "층"), ("준공", self.sl_year, "년")):
            v = self._range_or_none(r)
            if v:
                cond.append(f"{lbl} {v[0]}~{'' if v[1] >= RangeInput.OPEN_MAX else v[1]}{unit}")
        opts = [lbl for lbl, key, _ in SERVER_OPTIONS if self.option_checks[key].isChecked()]
        self._append_log(
            f"{head}시작 {datetime.now():%Y-%m-%d %H:%M}: 지역 {len(regions)}개 / {', '.join(trade_types)} / 매물유형 {', '.join(kinds) or '전체'} / "
            f"{'등록일' if by_reg else '확인일'} {period_txt} / 연락처 {'ON' if params['contact'] else 'OFF'}"
            + (f"\n  조건: {' · '.join(cond)}" if cond else "")
            + (f"\n  옵션: {', '.join(opts)}" if opts else "")
            + (f"\n  키워드: {', '.join(params['keywords'])}" if params["keywords"] else "")
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
        try:
            from license_gate import report_activity
            m = re.search(r"(\d+)건", msg)
            report_activity("수집", f"온하우스 · {os.path.basename(msg.split(': ', 1)[-1].split(' (')[0]) if '저장' in msg else msg}", int(m.group(1)) if m else None)
        except Exception:
            pass
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
