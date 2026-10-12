# -*- coding: utf-8 -*-
"""
긱톡 게시글 수집기 (gigtalk.co.kr) - 단독 실행 GUI.

핵심: 긱톡의 긱잡(일감·알바)·노하우·서비스 글을 커뮤니티/카테고리/기간/검색어로 골라
      엑셀로 만들고 메일/텔레그램으로 보낸다. 이미 받은 글은 다시 넣지 않는다.

무인 실행:  프로그램.exe --run-all   (저장된 설정으로 한 번 돌리고 스스로 종료)
"""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QDate, QObject, Qt, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
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
    QVBoxLayout,
    QWidget,
)

import auto_send
import gigtalk_crawler as gk
import daangn_jobs_crawler as dj

APP_TITLE = "긱톡 · 당근알바 수집기"
SETTINGS_FILE = "gigtalk_settings.json"
SEEN_FILE = "gigtalk_seen.json"
SEND_FILE = "send_config.json"
DJ_SETTINGS_FILE = "daangn_jobs_settings.json"
DJ_SEEN_FILE = "daangn_jobs_seen.json"
DJ_REGIONS_FILE = "daangn_jobs_regions.json"
DJ_DEFAULT_KEYWORDS = "재택, 투잡, 부업"
MEETS_FILE = "gigtalk_meets.json"
CATS_FILE = "gigtalk_categories.json"

PERIODS = [
    ("오늘", 0),
    ("어제 오늘", 1),
    ("최근 3일", 3),
    ("최근 7일", 7),
    ("최근 14일", 14),
    ("최근 30일", 30),
    ("최근 90일", 90),
    ("직접 지정", -1),
]


def base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def read_json(path: str) -> Any:
    import json

    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return None


def write_json(path: str, data: Any) -> None:
    import json

    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def split_words(s: str) -> List[str]:
    out: List[str] = []
    for w in (s or "").replace("\n", ",").split(","):
        w = w.strip()
        if w and w not in out:
            out.append(w)
    return out


class CheckList(QListWidget):
    """체크박스 목록."""

    def __init__(self, height: int = 150):
        super().__init__()
        self.setMaximumHeight(height)

    def set_items(self, labels: List[str], checked: Optional[List[str]] = None) -> None:
        keep = set(checked or self.checked())
        self.clear()
        for t in labels:
            it = QListWidgetItem(t)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if t in keep else Qt.CheckState.Unchecked)
            self.addItem(it)

    def labels(self) -> List[str]:
        return [self.item(i).text() for i in range(self.count())]

    def checked(self) -> List[str]:
        return [self.item(i).text() for i in range(self.count())
                if self.item(i).checkState() == Qt.CheckState.Checked]

    def set_checked(self, labels: List[str]) -> None:
        s = set(labels or [])
        for i in range(self.count()):
            self.item(i).setCheckState(
                Qt.CheckState.Checked if self.item(i).text() in s else Qt.CheckState.Unchecked)

    def check_all(self, on: bool) -> None:
        for i in range(self.count()):
            self.item(i).setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)

    def filter(self, text: str) -> None:
        t = (text or "").strip().lower()
        for i in range(self.count()):
            it = self.item(i)
            it.setHidden(bool(t) and t not in it.text().lower())


class FuncWorker(QObject):
    """짧은 작업(목록 받기)을 스레드에서 돌린다."""

    log = Signal(str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable[[Callable[[str], None]], Any]):
        super().__init__()
        self.fn = fn

    @Slot()
    def run(self) -> None:
        try:
            self.done.emit(self.fn(self.log.emit))
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class Worker(QObject):
    log = Signal(str)
    progress = Signal(int, int)
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, p: Dict[str, Any]):
        super().__init__()
        self.p = p
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    @Slot()
    def run(self) -> None:
        try:
            p = self.p
            cli = gk.GigtalkClient(self.log.emit, delay=(0.3, 0.9) if p.get("polite", True) else (0.05, 0.2))
            seen_path = os.path.join(p["base_dir"], SEEN_FILE)
            seen = gk.load_seen(seen_path) if p["skip_seen"] else {}
            rows = gk.collect(
                cli,
                post_types=p["types"],
                meet_ids=p["meet_ids"],
                category_ids=p["category_ids"],
                search_terms=p["search_terms"],
                start=p["start"],
                end=p["end"],
                max_count=p["max_count"],
                include_words=p["include_words"],
                exclude_words=p["exclude_words"],
                region_words=p["region_words"],
                only_open=p["only_open"],
                seen_ids={int(k) for k in seen.keys() if str(k).isdigit()},
                stop=lambda: self._stop,
                log=self.log.emit,
                progress=self.progress.emit,
                category_meet=p["category_meet"],
            )
            if self._stop:
                self.log.emit("중지했습니다." + (f" (지금까지 {len(rows)}건은 저장합니다)" if rows else ""))
            self.log.emit(
                f"조건에 맞는 글 {len(rows)}건 (등록일 {p['start']} ~ {p['end']}"
                + (f", 이미 받은 {len(seen)}건 제외" if p["skip_seen"] else "")
                + ")"
            )
            if not rows:
                self.finished.emit("새로 받을 글이 없습니다.")
                return

            kinds = "·".join(gk.TYPE_KO.get(t, t) for t in p["types"])
            scope = p.get("scope_label") or "전체"
            out_dir = os.path.join(p["base_dir"], "data")
            fname = f"긱톡_{kinds}_{scope}_{len(rows)}건_{datetime.now():%y%m%d_%H%M%S}.xlsx"
            fname = "".join(ch for ch in fname if ch not in '\\/:*?"<>|')
            out_path = gk.save_excel(rows, os.path.join(out_dir, fname))
            self.log.emit(f"저장: {out_path}")

            if p["skip_seen"]:
                for r in rows:
                    seen[str(r["번호"])] = (r.get("등록일시") or "")[:10] or date.today().isoformat()
                gk.save_seen(seen_path, seen)
                self.log.emit(f"  받은 글 기록: 총 {len(seen)}건")

            cfg = p.get("send") or {}
            if cfg.get("mail_on") or cfg.get("tg_on"):
                self.log.emit("자동 전송 중...")
                caption = f"[긱톡 {kinds}] {scope} {len(rows)}건 / 등록일 {p['start']} ~ {p['end']}"
                auto_send.deliver(cfg, out_path, caption, self.log.emit)

            self.finished.emit(f"완료: {len(rows)}건 — {out_path}")
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class DaangnWorker(QObject):
    log = Signal(str)
    progress = Signal(int, int)
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, p: Dict[str, Any]):
        super().__init__()
        self.p = p
        self._stop = False
        self._stop_detail = False

    def stop(self) -> None:
        """1단계: 검색만 멈추고 모은 글의 상세는 받아서 저장"""
        self._stop = True

    def stop_detail(self) -> None:
        """2단계: 상세도 건너뛰고 바로 저장"""
        self._stop = True
        self._stop_detail = True

    @Slot()
    def run(self) -> None:
        try:
            p = self.p
            cli = dj.DaangnJobsClient(self.log.emit, delay=(0.3, 0.8) if p.get("polite", True) else (0.05, 0.2))
            # 고른 시군구의 동 목록 (캐시 없으면 받아서 저장)
            cache = read_json(os.path.join(p["base_dir"], DJ_REGIONS_FILE)) or {}
            dongs_cache: Dict[str, List[Dict[str, Any]]] = cache.get("dongs") or {}
            region_ids: List[int] = []
            names: Dict[int, str] = {}
            dong_filter = [w for w in p.get("dong_words") or [] if w]
            for gu in p["gus"]:
                key = str(gu["_id"])
                if key not in dongs_cache:
                    self.log.emit(f"{gu['name']} 동 목록 받는 중...")
                    dongs_cache[key] = cli.region_children(int(gu["_id"]))
                    cache["dongs"] = dongs_cache
                    write_json(os.path.join(p["base_dir"], DJ_REGIONS_FILE), cache)
                for d in dongs_cache[key]:
                    if dong_filter and not any(w in (d.get("name") or "") for w in dong_filter):
                        continue
                    if d["_id"] not in names:
                        region_ids.append(int(d["_id"]))
                        names[int(d["_id"])] = f"{gu['name']} {d.get('name', '')}"
            if self._stop:
                self.finished.emit("중지했습니다.")
                return
            if not region_ids:
                self.failed.emit("검색할 동이 없습니다. 시도와 시군구를 고르세요." + (" (동 이름 조건에 맞는 동이 없음)" if dong_filter else ""))
                return
            self.log.emit(f"동 {len(region_ids)}개 × 검색어 {len(p['keywords']) or 1}개 검색 (각 동은 이웃 동까지 포함해 검색되고 중복은 뺍니다)")

            seen_path = os.path.join(p["base_dir"], DJ_SEEN_FILE)
            seen = gk.load_seen(seen_path) if p["skip_seen"] else {}
            rows = dj.collect(
                cli, region_ids, p["keywords"], p["start"], p["end"], max_count=p["max_count"],
                short_term=p["short_term"], with_detail=p["with_detail"],
                include_words=p["include_words"], exclude_words=p["exclude_words"],
                skip_closed=p["skip_closed"], seen_ids=set(seen.keys()),
                stop=lambda: self._stop, log=self.log.emit, progress=self.progress.emit, region_names=names,
                stop_detail=lambda: self._stop_detail, workers=2 if p.get("polite", True) else 4,
            )
            if self._stop:
                self.log.emit("중지했습니다." + (f" (지금까지 {len(rows)}건은 저장합니다)" if rows else ""))
            self.log.emit(f"조건에 맞는 공고 {len(rows)}건 (등록일 {p['start']} ~ {p['end']}" + (f", 이미 받은 {len(seen)}건 제외" if p["skip_seen"] else "") + ")")
            if not rows:
                self.finished.emit("새로 받을 공고가 없습니다.")
                return
            scope = p.get("scope_label") or "전체"
            out_dir = os.path.join(p["base_dir"], "data")
            fname = f"당근알바_{scope}_{len(rows)}건_{datetime.now():%y%m%d_%H%M%S}.xlsx"
            fname = "".join(ch for ch in fname if ch not in '\\/:*?"<>|')
            out_path = dj.save_excel(rows, os.path.join(out_dir, fname))
            self.log.emit(f"저장: {out_path}")
            if p["skip_seen"]:
                for r in rows:
                    if r.get("_id"):
                        seen[str(r["_id"])] = (r.get("등록일시") or "")[:10] or date.today().isoformat()
                gk.save_seen(seen_path, seen)
                self.log.emit(f"  받은 공고 기록: 총 {len(seen)}건")
            cfg = p.get("send") or {}
            if cfg.get("mail_on") or cfg.get("tg_on"):
                self.log.emit("자동 전송 중...")
                auto_send.deliver(cfg, out_path, f"[당근알바] {scope} {len(rows)}건 / 등록일 {p['start']} ~ {p['end']}", self.log.emit)
            self.finished.emit(f"완료: {len(rows)}건 — {out_path}")
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1040, 900)
        self.base_dir = base_dir()
        self.worker: Optional[Worker] = None
        self.thread: Optional[QThread] = None
        self.fthread: Optional[QThread] = None
        self.fworker: Optional[FuncWorker] = None
        self._batch = False
        self.meets: List[Dict[str, Any]] = []
        self.cat_map: Dict[str, Tuple[int, int, str]] = {}  # 라벨 → (카테고리 id, 커뮤니티 id, type)
        self.dj_worker: Optional[DaangnWorker] = None
        self.dj_thread: Optional[QThread] = None
        self.dj_regions: Dict[str, Any] = {}
        self._batch_queue: List[str] = []
        self._build_ui()
        self._apply_style()
        self._load_lists()
        self._load_settings()

    # ---------- UI ----------
    def _build_ui(self) -> None:
        w = QWidget()
        w.setObjectName("appRoot")
        self.setCentralWidget(w)
        outer = QVBoxLayout(w)
        title = QLabel(APP_TITLE)
        title.setObjectName("appTitle")
        subtitle = QLabel("긱톡(gigtalk.co.kr) 글과 당근알바(jobs.daangn.com) 공고를 조건으로 골라 엑셀로 만듭니다 — 탭에서 고르세요")
        subtitle.setObjectName("appSubtitle")
        outer.addWidget(title)
        outer.addWidget(subtitle)
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)

        page = QWidget()
        v = QVBoxLayout(page)

        # 1. 종류
        kind = QGroupBox("1. 어떤 글을 받을까요")
        kg = QHBoxLayout(kind)
        self.chk_types: Dict[str, QCheckBox] = {}
        for lbl, t in gk.POST_TYPES:
            cb = QCheckBox(lbl)
            cb.setChecked(t == "job")
            cb.toggled.connect(lambda *_: self._refresh_cat_view())
            self.chk_types[t] = cb
            kg.addWidget(cb)
        kg.addStretch(1)
        v.addWidget(kind)

        # 2. 커뮤니티/카테고리
        reg = QGroupBox("2. 커뮤니티 · 카테고리 고르기 (아무것도 안 고르면 전체)")
        rg = QGridLayout(reg)
        self.lst_meet = CheckList(200)
        self.lst_cat = CheckList(200)
        self.lst_meet.setMinimumHeight(180)
        self.lst_cat.setMinimumHeight(180)
        self.lst_meet.itemChanged.connect(lambda *_: self._refresh_cat_view())
        self.btn_meet_refresh = QPushButton("커뮤니티 목록 새로 받기")
        self.btn_meet_refresh.clicked.connect(self._refresh_meets)
        self.btn_meet_clear = QPushButton("커뮤니티 전체 해제")
        self.btn_meet_clear.clicked.connect(lambda: self.lst_meet.check_all(False))
        self.btn_cat_load = QPushButton("카테고리 목록 새로 받기")
        self.btn_cat_load.clicked.connect(self._load_categories)
        self.btn_cat_clear = QPushButton("카테고리 전체 해제")
        self.btn_cat_clear.clicked.connect(lambda: self.lst_cat.check_all(False))
        self.ed_cat_find = QLineEdit()
        self.ed_cat_find.setPlaceholderText("카테고리 찾기 (예: 번역)")
        self.ed_cat_find.textChanged.connect(lambda *_: self._refresh_cat_view())
        rg.addWidget(QLabel("커뮤니티"), 0, 0)
        rg.addWidget(QLabel("카테고리  (고른 커뮤니티·종류의 것만 보입니다. 비면 [카테고리 받기])"), 0, 1)
        rg.addWidget(self.lst_meet, 1, 0)
        rg.addWidget(self.lst_cat, 1, 1)
        mrow = QHBoxLayout()
        mrow.addWidget(self.btn_meet_refresh)
        mrow.addWidget(self.btn_meet_clear)
        rg.addLayout(mrow, 2, 0)
        rg.addWidget(self.ed_cat_find, 2, 1)
        crow = QHBoxLayout()
        crow.addWidget(self.btn_cat_load)
        crow.addWidget(self.btn_cat_clear)
        rg.addLayout(crow, 3, 1)
        rg.setColumnStretch(0, 1)
        rg.setColumnStretch(1, 2)
        v.addWidget(reg)

        # 3. 조건
        cond = QGroupBox("3. 조건")
        cg = QGridLayout(cond)
        self.cb_period = QComboBox()
        self.cb_period.addItems([p[0] for p in PERIODS])
        self.cb_period.setCurrentIndex(1)
        self.cb_period.currentIndexChanged.connect(self._on_period_changed)
        self.de_from = QDateEdit(QDate.currentDate().addDays(-1))
        self.de_from.setCalendarPopup(True)
        self.de_from.setDisplayFormat("yyyy-MM-dd")
        self.de_to = QDateEdit(QDate.currentDate())
        self.de_to.setCalendarPopup(True)
        self.de_to.setDisplayFormat("yyyy-MM-dd")
        for _de in (self.de_from, self.de_to):
            _de.setMinimumWidth(170)
            _de.setMinimumHeight(34)
        self.de_from.setEnabled(False)
        self.de_to.setEnabled(False)
        self.ed_search = QLineEdit()
        self.ed_search.setPlaceholderText("긱톡 검색어 (쉼표로 여러 개, 각각 따로 검색) 예: 번역, 타이핑")
        self.ed_include = QLineEdit()
        self.ed_include.setPlaceholderText("제목·내용에 이 단어가 있는 글만 (쉼표) 예: 재택, 부업")
        self.ed_exclude = QLineEdit()
        self.ed_exclude.setPlaceholderText("이 단어가 있으면 빼기 (쉼표) 예: 보험, 대출")
        self.ed_region = QLineEdit()
        self.ed_region.setPlaceholderText("지역에 이 단어가 있는 글만 (쉼표) 예: 서울, 성남  (지역 없는 글은 빠짐)")
        self.sp_max = QSpinBox()
        self.sp_max.setRange(10, 20000)
        self.sp_max.setSingleStep(50)
        self.sp_max.setValue(500)
        self.chk_open = QCheckBox("모집중만 (마감일 지난 긱잡 빼기)")
        self.chk_open.setChecked(True)
        self.chk_seen = QCheckBox("이미 받은 글은 빼기 (매일 받을 때 켜세요)")
        self.chk_seen.setChecked(True)
        self.chk_polite = QCheckBox("천천히 받기 (요청 사이 잠깐 쉼, 권장)")
        self.chk_polite.setChecked(True)
        self.chk_auto = QCheckBox("자동 실행(--run-all)에 긱톡 포함")
        self.chk_auto.setChecked(True)
        cg.addWidget(QLabel("등록일 기간"), 0, 0)
        cg.addWidget(self.cb_period, 0, 1)
        cg.addWidget(self.de_from, 0, 2)
        cg.addWidget(QLabel("~"), 0, 3)
        cg.addWidget(self.de_to, 0, 4)
        cg.addWidget(QLabel("최대 건수"), 0, 5)
        cg.addWidget(self.sp_max, 0, 6)
        cg.addWidget(QLabel("긱톡 검색어"), 1, 0)
        cg.addWidget(self.ed_search, 1, 1, 1, 6)
        cg.addWidget(QLabel("포함 단어"), 2, 0)
        cg.addWidget(self.ed_include, 2, 1, 1, 6)
        cg.addWidget(QLabel("제외 단어"), 3, 0)
        cg.addWidget(self.ed_exclude, 3, 1, 1, 6)
        cg.addWidget(QLabel("지역 단어"), 4, 0)
        cg.addWidget(self.ed_region, 4, 1, 1, 6)
        cg.addWidget(self.chk_open, 5, 0, 1, 3)
        cg.addWidget(self.chk_seen, 5, 3, 1, 2)
        cg.addWidget(self.chk_polite, 5, 5, 1, 2)
        cg.addWidget(self.chk_auto, 6, 0, 1, 3)
        cg.setColumnStretch(1, 1)
        v.addWidget(cond)

        row = QHBoxLayout()
        self.btn_start = QPushButton("지금 수집")
        self.btn_start.clicked.connect(self._start)
        self.btn_stop = QPushButton("중지")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop)
        self.btn_open = QPushButton("결과 폴더 열기")
        self.btn_open.clicked.connect(self._open_out)
        self.btn_reset_seen = QPushButton("받은 기록 지우기")
        self.btn_reset_seen.clicked.connect(self._reset_seen)
        row.addWidget(self.btn_start)
        row.addWidget(self.btn_stop)
        row.addWidget(self.btn_open)
        row.addWidget(self.btn_reset_seen)
        row.addStretch(1)
        v.addLayout(row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        v.addWidget(self.progress)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(110)
        v.addWidget(self.log, 1)
        self.tabs.addTab(page, "긱톡")
        self._build_daangn_tab()

        # 보내기 · 자동화 탭
        page2 = QWidget()
        v2 = QVBoxLayout(page2)
        snd = QGroupBox("다 되면 보내기 (한 번만 입력해두면 자동 실행에도 그대로 씁니다)")
        ng = QGridLayout(snd)
        self.chk_mail = QCheckBox("메일")
        self.ed_mail_from = QLineEdit()
        self.ed_mail_from.setPlaceholderText("보내는 지메일 주소")
        self.ed_mail_pw = QLineEdit()
        self.ed_mail_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.ed_mail_pw.setPlaceholderText("구글 앱 비밀번호 16자리")
        self.ed_mail_to = QLineEdit()
        self.ed_mail_to.setPlaceholderText("받는 사람 (쉼표로 여러 명)")
        self.chk_tg = QCheckBox("텔레그램")
        self.ed_tg_token = QLineEdit()
        self.ed_tg_token.setPlaceholderText("봇 토큰")
        self.ed_tg_chat = QLineEdit()
        self.ed_tg_chat.setPlaceholderText("챗 ID")
        self.btn_tg_find = QPushButton("챗 ID 찾기")
        self.btn_tg_find.clicked.connect(self._find_chat_id)
        self.btn_test = QPushButton("테스트 전송")
        self.btn_test.clicked.connect(self._test_send)
        ng.addWidget(self.chk_mail, 0, 0)
        ng.addWidget(self.ed_mail_from, 0, 1)
        ng.addWidget(self.ed_mail_pw, 0, 2)
        ng.addWidget(self.ed_mail_to, 0, 3)
        ng.addWidget(self.btn_test, 0, 4)
        ng.addWidget(self.chk_tg, 1, 0)
        ng.addWidget(self.ed_tg_token, 1, 1, 1, 2)
        ng.addWidget(self.ed_tg_chat, 1, 3)
        ng.addWidget(self.btn_tg_find, 1, 4)
        ng.setColumnStretch(1, 2)
        ng.setColumnStretch(3, 1)
        v2.addWidget(snd)
        auto = QGroupBox("자동 실행")
        ag = QVBoxLayout(auto)
        ag.addWidget(QLabel(
            "1) 긱톡 탭 / 당근알바 탭에서 조건을 정하고 [지금 수집]으로 한 번 돌려보세요. 그 설정이 저장됩니다.\n"
            "2) 위에 메일 또는 텔레그램을 넣고 [테스트 전송]으로 확인하세요.\n"
            "3) 프로그램 폴더의  자동실행_설정.bat  을 실행하면 매일 정한 시각에 PC가 깨어나 긱톡 → 당근알바 순서로 수집하고 보냅니다.\n""   (각 탭의 '자동 실행에 포함' 체크로 어느 쪽을 돌릴지 정합니다)\n"
            "   (명령줄:  프로그램.exe --run-all  = 저장된 설정으로 한 번 돌리고 스스로 닫힘)\n"
            "4) 끄려면  자동실행_해제.bat  을 실행하세요."
        ))
        v2.addWidget(auto)
        v2.addStretch(1)
        self.tabs.addTab(page2, "보내기 · 자동화")

    # ---------- 목록(커뮤니티/카테고리) ----------
    def _meet_labels(self) -> List[str]:
        return [m["name"] for m in self.meets]

    def _load_lists(self) -> None:
        self.meets = read_json(os.path.join(self.base_dir, MEETS_FILE)) or list(gk.BUILTIN_MEETS)
        self.lst_meet.set_items(self._meet_labels())
        cats = read_json(os.path.join(self.base_dir, CATS_FILE)) or list(gk.BUILTIN_CATEGORIES)
        self._set_categories(cats)
        self._refresh_cat_view()

    def _set_categories(self, cats: List[Dict[str, Any]], checked: Optional[List[str]] = None) -> None:
        name_of = {m["id"]: m["name"] for m in self.meets}
        self.cat_map = {}
        labels: List[str] = []
        for c in cats:
            lbl = f"{name_of.get(c.get('meetId'), c.get('meetId'))} > {c.get('name')} [{gk.TYPE_KO.get(c.get('postType'), c.get('postType'))}]"
            if lbl in self.cat_map:
                continue
            self.cat_map[lbl] = (int(c["id"]), int(c.get("meetId") or 0), str(c.get("postType") or ""))
            labels.append(lbl)
        self.lst_cat.set_items(labels, checked)


    def _refresh_cat_view(self) -> None:
        """고른 커뮤니티·글 종류에 속한 카테고리만 보이게 (체크된 것은 항상 보임)."""
        if not hasattr(self, "lst_cat"):
            return
        meet_ids = set(self._selected_meet_ids())
        types = set(self._selected_types())
        find = (self.ed_cat_find.text() or "").strip().lower() if hasattr(self, "ed_cat_find") else ""
        for i in range(self.lst_cat.count()):
            it = self.lst_cat.item(i)
            cid, mid, ptype = self.cat_map.get(it.text(), (0, 0, ""))
            show = True
            if meet_ids and mid not in meet_ids:
                show = False
            if types and ptype and ptype not in types:
                show = False
            if find and find not in it.text().lower():
                show = False
            if it.checkState() == Qt.CheckState.Checked:
                show = True
            it.setHidden(not show)

    def _run_func(self, fn: Callable[[Callable[[str], None]], Any], on_done: Callable[[Any], None], busy_btns: List[QPushButton],
                  on_fail: Optional[Callable[[str], None]] = None, quiet: bool = False) -> None:
        if self.fthread and self.fthread.isRunning():
            if not quiet:
                self._append("목록을 받는 중입니다. 잠시 후 다시 눌러 주세요.")
            return
        for b in busy_btns:
            b.setEnabled(False)
        self.fthread = QThread(self)
        self.fworker = FuncWorker(fn)
        self.fworker.moveToThread(self.fthread)
        self.fthread.started.connect(self.fworker.run)
        self.fworker.log.connect(self._append)

        def _finish() -> None:
            for b in busy_btns:
                b.setEnabled(True)

        def _done(res: Any) -> None:
            try:
                on_done(res)
            except Exception as e:  # noqa: BLE001
                self._append("처리 오류: " + str(e))
            finally:
                _finish()

        def _fail(msg: str) -> None:
            _finish()
            self._append("오류: " + msg)
            if on_fail:
                try:
                    on_fail(msg)
                except Exception:
                    pass
            if not self._batch and not quiet:
                QMessageBox.warning(self, "오류", msg)

        self.fworker.done.connect(_done)
        self.fworker.failed.connect(_fail)
        self.fworker.done.connect(self.fthread.quit)
        self.fworker.failed.connect(self.fthread.quit)
        self.fthread.finished.connect(self.fworker.deleteLater)
        self.fthread.start()

    def _refresh_meets(self) -> None:
        def fn(log: Callable[[str], None]) -> List[Dict[str, Any]]:
            log("긱톡에서 커뮤니티 목록을 받는 중...")
            return gk.GigtalkClient(log, delay=(0.0, 0.0)).meets()

        def done(meets: List[Dict[str, Any]]) -> None:
            checked = self.lst_meet.checked()
            self.meets = meets
            write_json(os.path.join(self.base_dir, MEETS_FILE), meets)
            self.lst_meet.set_items(self._meet_labels(), checked)
            self._append(f"커뮤니티 {len(meets)}개를 받았습니다.")

        self._run_func(fn, done, [self.btn_meet_refresh, self.btn_cat_load])

    def _selected_meet_ids(self) -> List[int]:
        names = set(self.lst_meet.checked())
        return [int(m["id"]) for m in self.meets if m["name"] in names]

    def _selected_types(self) -> List[str]:
        return [t for t, cb in self.chk_types.items() if cb.isChecked()]

    def _load_categories(self) -> None:
        meet_ids = self._selected_meet_ids() or [int(m["id"]) for m in self.meets]
        types = self._selected_types() or ["job"]
        if not self._selected_meet_ids() and len(meet_ids) * len(types) > 20:
            if QMessageBox.question(self, "카테고리 받기",
                                    f"커뮤니티를 고르지 않아 전체 {len(meet_ids)}개 × 종류 {len(types)}개 = {len(meet_ids) * len(types)}번 요청합니다. 계속할까요?") != QMessageBox.StandardButton.Yes:
                return

        def fn(log: Callable[[str], None]) -> List[Dict[str, Any]]:
            cli = gk.GigtalkClient(log, delay=(0.1, 0.3))
            out: List[Dict[str, Any]] = []
            for m in meet_ids:
                for t in types:
                    out += cli.categories(m, t)
            log(f"카테고리 {len(out)}개를 받았습니다.")
            return out

        def done(cats: List[Dict[str, Any]]) -> None:
            # 다른 커뮤니티의 기존 카테고리는 남겨두고, 이번에 받은 커뮤니티×종류만 갈아끼움
            old = read_json(os.path.join(self.base_dir, CATS_FILE)) or []
            touched = {(m, t) for m in meet_ids for t in types}
            keep = [c for c in old if (int(c.get("meetId") or 0), str(c.get("postType") or "")) not in touched]
            merged = keep + cats
            write_json(os.path.join(self.base_dir, CATS_FILE), merged)
            self._set_categories(merged, self.lst_cat.checked())
            self._refresh_cat_view()

        self._run_func(fn, done, [self.btn_meet_refresh, self.btn_cat_load])

    # ---------- 기간 ----------
    def _on_period_changed(self, idx: int) -> None:
        custom = PERIODS[idx][1] < 0
        self.de_from.setEnabled(custom)
        self.de_to.setEnabled(custom)

    def _date_range(self) -> Tuple[date, date]:
        days = PERIODS[self.cb_period.currentIndex()][1]
        if days < 0:
            f = self.de_from.date().toPython()
            t = self.de_to.date().toPython()
            if f > t:
                f, t = t, f
            return f, t
        t = date.today()
        return t - timedelta(days=days), t

    # ---------- 로그/기타 ----------
    def _append(self, s: str) -> None:
        self.log.appendPlainText(f"[{datetime.now():%H:%M:%S}] {s}")
        try:
            with open(os.path.join(self.base_dir, "실행기록.log"), "a", encoding="utf-8") as f:
                f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {s}\n")
        except Exception:
            pass

    def _open_out(self) -> None:
        d = os.path.join(self.base_dir, "data")
        os.makedirs(d, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(d))

    def _reset_seen(self) -> None:
        p = os.path.join(self.base_dir, SEEN_FILE)
        if QMessageBox.question(self, "받은 기록 지우기", "이미 받은 글 기록을 지울까요?\n다음 실행에서 기간 안의 모든 글이 다시 나옵니다.") != QMessageBox.StandardButton.Yes:
            return
        try:
            if os.path.exists(p):
                os.remove(p)
            self._append("받은 기록을 지웠습니다.")
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "오류", str(e))

    # ---------- 전송 ----------
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
            auto_send.save_config(os.path.join(self.base_dir, SEND_FILE), cfg)
        return cfg

    def _find_chat_id(self) -> None:
        res = auto_send.find_chat_id(self.ed_tg_token.text())
        if res.lstrip("-").isdigit():
            self.ed_tg_chat.setText(res)
            self._append("텔레그램 챗 ID: " + res)
        else:
            QMessageBox.information(self, "챗 ID 찾기", res)

    def _test_send(self) -> None:
        cfg = self._send_config(save=True)
        if not (cfg["mail_on"] or cfg["tg_on"]):
            QMessageBox.information(self, "테스트 전송", "메일 또는 텔레그램을 체크하세요.")
            return
        p = os.path.join(self.base_dir, "전송테스트.txt")
        try:
            with open(p, "w", encoding="utf-8") as f:
                f.write("긱톡 게시글 수집기 전송 테스트 {0:%Y-%m-%d %H:%M:%S}".format(datetime.now()) + chr(10))
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "테스트 전송", str(e))
            return
        auto_send.deliver(cfg, p, "긱톡 게시글 수집기 전송 테스트", self._append)
        try:
            os.remove(p)
        except Exception:
            pass
        QMessageBox.information(self, "테스트 전송", "결과를 수집 탭 아래 기록에서 확인하세요.")

    # ---------- 설정 ----------
    def _settings(self) -> Dict[str, Any]:
        f, t = self._date_range()
        return {
            "types": self._selected_types(),
            "meets": self.lst_meet.checked(),
            "categories": self.lst_cat.checked(),
            "period_idx": self.cb_period.currentIndex(),
            "date_from": f.isoformat(),
            "date_to": t.isoformat(),
            "search": self.ed_search.text().strip(),
            "include": self.ed_include.text().strip(),
            "exclude": self.ed_exclude.text().strip(),
            "region": self.ed_region.text().strip(),
            "max_count": self.sp_max.value(),
            "only_open": self.chk_open.isChecked(),
            "skip_seen": self.chk_seen.isChecked(),
            "polite": self.chk_polite.isChecked(),
            "auto_include": self.chk_auto.isChecked(),
        }

    def _save_settings(self) -> None:
        write_json(os.path.join(self.base_dir, SETTINGS_FILE), self._settings())
        self._send_config(save=True)
        if hasattr(self, "dj_lst_sido"):
            self._dj_save_settings()

    def _load_settings(self) -> None:
        s = read_json(os.path.join(self.base_dir, SETTINGS_FILE)) or {}
        if s:
            types = s.get("types") or ["job"]
            for t, cb in self.chk_types.items():
                cb.setChecked(t in types)
            self.lst_meet.set_checked(s.get("meets") or [])
            self.lst_cat.set_checked(s.get("categories") or [])
            self.cb_period.setCurrentIndex(int(s.get("period_idx", 1)))
            if s.get("date_from"):
                self.de_from.setDate(QDate.fromString(s["date_from"], "yyyy-MM-dd"))
            if s.get("date_to"):
                self.de_to.setDate(QDate.fromString(s["date_to"], "yyyy-MM-dd"))
            self.ed_search.setText(s.get("search", ""))
            self.ed_include.setText(s.get("include", ""))
            self.ed_exclude.setText(s.get("exclude", ""))
            self.ed_region.setText(s.get("region", ""))
            self.sp_max.setValue(int(s.get("max_count", 500)))
            self.chk_open.setChecked(bool(s.get("only_open", True)))
            self.chk_seen.setChecked(bool(s.get("skip_seen", True)))
            self.chk_polite.setChecked(bool(s.get("polite", True)))
            self.chk_auto.setChecked(bool(s.get("auto_include", True)))
        else:
            self.lst_meet.set_checked(["재택모음"])
        self._refresh_cat_view()
        self._dj_load_settings()
        cfg = auto_send.load_config(os.path.join(self.base_dir, SEND_FILE))
        self.chk_mail.setChecked(bool(cfg.get("mail_on")))
        self.ed_mail_from.setText(cfg.get("mail_from", ""))
        self.ed_mail_pw.setText(cfg.get("mail_pw", ""))
        self.ed_mail_to.setText(cfg.get("mail_to", ""))
        self.chk_tg.setChecked(bool(cfg.get("tg_on")))
        self.ed_tg_token.setText(cfg.get("tg_token", ""))
        self.ed_tg_chat.setText(cfg.get("tg_chat", ""))

    # ====================== 당근알바 ======================
    def _build_daangn_tab(self) -> None:
        page = QWidget()
        v = QVBoxLayout(page)
        reg = QGroupBox("1. 지역 고르기 (시도 → 시군구, 시군구 안의 모든 동을 이웃 동까지 검색)")
        rg = QGridLayout(reg)
        self.dj_lst_sido = CheckList(200)
        self.dj_lst_sido.setMinimumHeight(160)
        self.dj_lst_gu = CheckList(200)
        self.dj_lst_gu.setMinimumHeight(160)
        self.dj_lst_sido.itemChanged.connect(self._dj_on_sido_changed)
        self.dj_ed_gu_find = QLineEdit()
        self.dj_ed_gu_find.setPlaceholderText("시군구 찾기 (예: 강남)")
        self.dj_ed_gu_find.textChanged.connect(self.dj_lst_gu.filter)
        self.dj_ed_dong = QLineEdit()
        self.dj_ed_dong.setPlaceholderText("동 이름으로 좁히기 (쉼표, 비우면 시군구 전체) 예: 역삼, 삼성")
        self.dj_btn_sido_all = QPushButton("시도 전체 선택")
        self.dj_btn_sido_all.clicked.connect(lambda: self._dj_check_all_sido(True))
        self.dj_btn_sido_clear = QPushButton("시도 전체 해제")
        self.dj_btn_sido_clear.clicked.connect(lambda: self._dj_check_all_sido(False))
        self.dj_btn_gu_all = QPushButton("보이는 시군구 전체 선택")
        self.dj_btn_gu_all.clicked.connect(lambda: self.dj_lst_gu.check_all(True))
        self.dj_btn_gu_clear = QPushButton("시군구 전체 해제")
        self.dj_btn_gu_clear.clicked.connect(lambda: self.dj_lst_gu.check_all(False))
        rg.addWidget(QLabel("시 · 도"), 0, 0)
        rg.addWidget(QLabel("시 · 군 · 구  (시도를 고르면 채워집니다)"), 0, 1)
        rg.addWidget(self.dj_lst_sido, 1, 0)
        rg.addWidget(self.dj_lst_gu, 1, 1)
        sidorow = QHBoxLayout()
        sidorow.addWidget(self.dj_btn_sido_all)
        sidorow.addWidget(self.dj_btn_sido_clear)
        rg.addLayout(sidorow, 2, 0)
        rg.addWidget(self.dj_ed_gu_find, 2, 1)
        gurow = QHBoxLayout()
        gurow.addWidget(self.dj_btn_gu_all)
        gurow.addWidget(self.dj_btn_gu_clear)
        rg.addLayout(gurow, 3, 1)
        rg.addWidget(QLabel("동 좁히기"), 4, 0)
        rg.addWidget(self.dj_ed_dong, 4, 1)
        rg.setColumnStretch(0, 1)
        rg.setColumnStretch(1, 2)
        v.addWidget(reg)

        cond = QGroupBox("2. 조건")
        cg = QGridLayout(cond)
        self.dj_ed_kw = QLineEdit(DJ_DEFAULT_KEYWORDS)
        self.dj_ed_kw.setPlaceholderText("당근알바 검색어 (쉼표로 여러 개, 각각 따로 검색) 예: 재택, 투잡, 부업")
        self.dj_chk_short = QCheckBox("단기만 (1개월 미만)")
        self.dj_cb_period = QComboBox()
        self.dj_cb_period.addItems([p[0] for p in PERIODS])
        self.dj_cb_period.setCurrentIndex(2)
        self.dj_cb_period.currentIndexChanged.connect(self._dj_on_period_changed)
        self.dj_de_from = QDateEdit(QDate.currentDate().addDays(-3))
        self.dj_de_from.setCalendarPopup(True)
        self.dj_de_from.setDisplayFormat("yyyy-MM-dd")
        self.dj_de_to = QDateEdit(QDate.currentDate())
        self.dj_de_to.setCalendarPopup(True)
        self.dj_de_to.setDisplayFormat("yyyy-MM-dd")
        for _de in (self.dj_de_from, self.dj_de_to):
            _de.setMinimumWidth(170)
            _de.setMinimumHeight(34)
        self.dj_de_from.setEnabled(False)
        self.dj_de_to.setEnabled(False)
        self.dj_sp_max = QSpinBox()
        self.dj_sp_max.setRange(10, 5000)
        self.dj_sp_max.setSingleStep(50)
        self.dj_sp_max.setValue(300)
        self.dj_ed_include = QLineEdit()
        self.dj_ed_include.setPlaceholderText("제목·내용에 이 단어가 있는 공고만 (쉼표)")
        self.dj_ed_exclude = QLineEdit()
        self.dj_ed_exclude.setPlaceholderText("이 단어가 있으면 빼기 (쉼표) 예: 보험, 대출, 다단계")
        self.dj_chk_detail = QCheckBox("상세도 가져오기 (내용·주소·050 안심번호·조회수·지원자 — 공고당 요청 1~2번 더)")
        self.dj_chk_detail.setChecked(True)
        self.dj_chk_closed = QCheckBox("마감된 공고 빼기")
        self.dj_chk_closed.setChecked(True)
        self.dj_chk_seen = QCheckBox("이미 받은 공고는 빼기")
        self.dj_chk_seen.setChecked(True)
        self.dj_chk_polite = QCheckBox("천천히 받기 (동시 2개, 끄면 4개)")
        self.dj_chk_polite.setChecked(True)
        self.dj_chk_auto = QCheckBox("자동 실행(--run-all)에 당근알바 포함")
        self.dj_chk_auto.setChecked(True)
        cg.addWidget(QLabel("검색어"), 0, 0)
        cg.addWidget(self.dj_ed_kw, 0, 1, 1, 5)
        cg.addWidget(self.dj_chk_short, 0, 6)
        cg.addWidget(QLabel("등록일 기간"), 1, 0)
        cg.addWidget(self.dj_cb_period, 1, 1)
        cg.addWidget(self.dj_de_from, 1, 2)
        cg.addWidget(QLabel("~"), 1, 3)
        cg.addWidget(self.dj_de_to, 1, 4)
        cg.addWidget(QLabel("최대 건수"), 1, 5)
        cg.addWidget(self.dj_sp_max, 1, 6)
        cg.addWidget(QLabel("포함 단어"), 2, 0)
        cg.addWidget(self.dj_ed_include, 2, 1, 1, 6)
        cg.addWidget(QLabel("제외 단어"), 3, 0)
        cg.addWidget(self.dj_ed_exclude, 3, 1, 1, 6)
        cg.addWidget(self.dj_chk_detail, 4, 0, 1, 3)
        cg.addWidget(self.dj_chk_closed, 4, 3, 1, 2)
        cg.addWidget(self.dj_chk_seen, 4, 5, 1, 2)
        cg.addWidget(self.dj_chk_polite, 5, 0, 1, 3)
        cg.addWidget(self.dj_chk_auto, 5, 3, 1, 4)
        cg.setColumnStretch(1, 1)
        v.addWidget(cond)

        row = QHBoxLayout()
        self.dj_btn_start = QPushButton("지금 수집")
        self.dj_btn_start.clicked.connect(self._dj_start)
        self.dj_btn_stop = QPushButton("중지")
        self.dj_btn_stop.setEnabled(False)
        self.dj_btn_stop.clicked.connect(self._dj_stop)
        self.dj_btn_open = QPushButton("결과 폴더 열기")
        self.dj_btn_open.clicked.connect(self._open_out)
        self.dj_btn_reset_seen = QPushButton("받은 기록 지우기")
        self.dj_btn_reset_seen.clicked.connect(self._dj_reset_seen)
        row.addWidget(self.dj_btn_start)
        row.addWidget(self.dj_btn_stop)
        row.addWidget(self.dj_btn_open)
        row.addWidget(self.dj_btn_reset_seen)
        row.addStretch(1)
        v.addLayout(row)
        self.dj_progress = QProgressBar()
        self.dj_progress.setRange(0, 0)
        self.dj_progress.setVisible(False)
        v.addWidget(self.dj_progress)
        self.dj_log = QPlainTextEdit()
        self.dj_log.setReadOnly(True)
        self.dj_log.setMinimumHeight(110)
        v.addWidget(self.dj_log, 1)
        self.tabs.addTab(page, "당근알바")
        self._dj_load_regions()

    def _dj_append(self, s: str) -> None:
        self.dj_log.appendPlainText(f"[{datetime.now():%H:%M:%S}] {s}")
        try:
            with open(os.path.join(self.base_dir, "실행기록.log"), "a", encoding="utf-8") as f:
                f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} [당근알바] {s}\n")
        except Exception:
            pass

    def _dj_load_regions(self) -> None:
        self.dj_regions = read_json(os.path.join(self.base_dir, DJ_REGIONS_FILE)) or {}
        sidos = self.dj_regions.get("sidos") or list(dj.BUILTIN_SIDOS)
        self.dj_regions.setdefault("sidos", sidos)
        gus = dict(dj.BUILTIN_GUS)
        gus.update(self.dj_regions.get("gus") or {})
        self.dj_regions["gus"] = gus
        self.dj_regions.setdefault("dongs", {})
        self._dj_gu_fetching = False
        self._dj_gu_recheck = False
        self.dj_lst_sido.set_items([s["name"] for s in sidos])

    def _dj_sido_ids(self, names: List[str]) -> List[Dict[str, Any]]:
        return [s for s in self.dj_regions.get("sidos", []) if s["name"] in set(names)]

    def _dj_check_all_sido(self, on: bool) -> None:
        self.dj_lst_sido.blockSignals(True)
        try:
            self.dj_lst_sido.check_all(on)
        finally:
            self.dj_lst_sido.blockSignals(False)
        self._dj_on_sido_changed()

    def _dj_on_sido_changed(self, *_: Any) -> None:
        try:
            self._dj_fill_gu()
            sel = self._dj_sido_ids(self.dj_lst_sido.checked())
            missing = [s for s in sel if not self.dj_regions.get("gus", {}).get(str(s["_id"]))]
            if not missing:
                return
            if self._dj_gu_fetching or (self.fthread and self.fthread.isRunning()):
                self._dj_gu_recheck = True   # 받는 중이면 끝난 뒤 다시 확인
                return
            self._dj_gu_fetching = True

            def fn(log: Callable[[str], None]) -> Dict[str, List[Dict[str, Any]]]:
                cli = dj.DaangnJobsClient(log, delay=(0.1, 0.3))
                out: Dict[str, List[Dict[str, Any]]] = {}
                for s in missing:
                    log(f"{s['name']} 시군구 목록 받는 중...")
                    try:
                        out[str(s["_id"])] = cli.region_children(int(s["_id"]))
                    except Exception as e:  # noqa: BLE001
                        log(f"  {s['name']} 실패: {e}")
                return out

            def done(res: Dict[str, List[Dict[str, Any]]]) -> None:
                self._dj_gu_fetching = False
                self.dj_regions.setdefault("gus", {}).update({k: v for k, v in res.items() if v})
                write_json(os.path.join(self.base_dir, DJ_REGIONS_FILE), self.dj_regions)
                self._dj_fill_gu()
                if self._dj_gu_recheck:
                    self._dj_gu_recheck = False
                    QTimer.singleShot(0, self._dj_on_sido_changed)

            def fail(_msg: str) -> None:
                self._dj_gu_fetching = False

            self._run_func(fn, done, [], on_fail=fail, quiet=True)
        except Exception as e:  # noqa: BLE001
            self._dj_append("시군구 목록 처리 오류: " + str(e))

    def _dj_gu_label(self, sido: Dict[str, Any], gu: Dict[str, Any]) -> str:
        return f"{sido['name']} {gu['name']}"

    def _dj_fill_gu(self, checked: Optional[List[str]] = None) -> None:
        keep = checked if checked is not None else self.dj_lst_gu.checked()
        labels: List[str] = []
        for s in self._dj_sido_ids(self.dj_lst_sido.checked()):
            for g in self.dj_regions.get("gus", {}).get(str(s["_id"]), []):
                labels.append(self._dj_gu_label(s, g))
        self.dj_lst_gu.set_items(labels, keep)
        self.dj_lst_gu.filter(self.dj_ed_gu_find.text())

    def _dj_selected_gus(self) -> List[Dict[str, Any]]:
        want = set(self.dj_lst_gu.checked())
        out = []
        for s in self._dj_sido_ids(self.dj_lst_sido.checked()):
            for g in self.dj_regions.get("gus", {}).get(str(s["_id"]), []):
                if self._dj_gu_label(s, g) in want:
                    out.append({"_id": g["_id"], "name": self._dj_gu_label(s, g)})
        return out

    def _dj_on_period_changed(self, idx: int) -> None:
        custom = PERIODS[idx][1] < 0
        self.dj_de_from.setEnabled(custom)
        self.dj_de_to.setEnabled(custom)

    def _dj_date_range(self) -> Tuple[date, date]:
        days = PERIODS[self.dj_cb_period.currentIndex()][1]
        if days < 0:
            f = self.dj_de_from.date().toPython()
            t = self.dj_de_to.date().toPython()
            if f > t:
                f, t = t, f
            return f, t
        t = date.today()
        return t - timedelta(days=days), t

    def _dj_reset_seen(self) -> None:
        p = os.path.join(self.base_dir, DJ_SEEN_FILE)
        if QMessageBox.question(self, "받은 기록 지우기", "당근알바 받은 공고 기록을 지울까요?") != QMessageBox.StandardButton.Yes:
            return
        try:
            if os.path.exists(p):
                os.remove(p)
            self._dj_append("받은 기록을 지웠습니다.")
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "오류", str(e))

    def _dj_settings(self) -> Dict[str, Any]:
        f, t = self._dj_date_range()
        return {
            "sidos": self.dj_lst_sido.checked(),
            "gus": self.dj_lst_gu.checked(),
            "dong": self.dj_ed_dong.text().strip(),
            "keywords": self.dj_ed_kw.text().strip(),
            "short_term": self.dj_chk_short.isChecked(),
            "period_idx": self.dj_cb_period.currentIndex(),
            "date_from": f.isoformat(),
            "date_to": t.isoformat(),
            "max_count": self.dj_sp_max.value(),
            "include": self.dj_ed_include.text().strip(),
            "exclude": self.dj_ed_exclude.text().strip(),
            "with_detail": self.dj_chk_detail.isChecked(),
            "skip_closed": self.dj_chk_closed.isChecked(),
            "skip_seen": self.dj_chk_seen.isChecked(),
            "polite": self.dj_chk_polite.isChecked(),
            "auto_include": self.dj_chk_auto.isChecked(),
        }

    def _dj_save_settings(self) -> None:
        write_json(os.path.join(self.base_dir, DJ_SETTINGS_FILE), self._dj_settings())

    def _dj_load_settings(self) -> None:
        s = read_json(os.path.join(self.base_dir, DJ_SETTINGS_FILE)) or {}
        if not s:
            return
        self._dj_pending_gus = s.get("gus") or []
        self.dj_lst_sido.set_checked(s.get("sidos") or [])
        self._dj_fill_gu(self._dj_pending_gus)
        self.dj_ed_dong.setText(s.get("dong", ""))
        self.dj_ed_kw.setText(s.get("keywords", DJ_DEFAULT_KEYWORDS))
        self.dj_chk_short.setChecked(bool(s.get("short_term", False)))
        self.dj_cb_period.setCurrentIndex(int(s.get("period_idx", 2)))
        if s.get("date_from"):
            self.dj_de_from.setDate(QDate.fromString(s["date_from"], "yyyy-MM-dd"))
        if s.get("date_to"):
            self.dj_de_to.setDate(QDate.fromString(s["date_to"], "yyyy-MM-dd"))
        self.dj_sp_max.setValue(int(s.get("max_count", 300)))
        self.dj_ed_include.setText(s.get("include", ""))
        self.dj_ed_exclude.setText(s.get("exclude", ""))
        self.dj_chk_detail.setChecked(bool(s.get("with_detail", True)))
        self.dj_chk_closed.setChecked(bool(s.get("skip_closed", True)))
        self.dj_chk_seen.setChecked(bool(s.get("skip_seen", True)))
        self.dj_chk_polite.setChecked(bool(s.get("polite", True)))
        self.dj_chk_auto.setChecked(bool(s.get("auto_include", True)))

    def _dj_start(self, auto: bool = False) -> None:
        if self.dj_thread and self.dj_thread.isRunning():
            return
        self._dj_save_settings()
        self._send_config(save=True)
        s = self._dj_settings()
        f, t = self._dj_date_range()
        gus = self._dj_selected_gus()
        if not gus:
            msg = "당근알바: 시도와 시군구를 하나 이상 고르세요."
            if auto or self._batch:
                self._dj_append("실행 불가: " + msg)
                self._batch_step_done()
            else:
                QMessageBox.information(self, "확인", msg)
            return
        scope = gus[0]["name"].split(" ", 1)[-1] + (f" 외 {len(gus) - 1}" if len(gus) > 1 else "")
        kws = split_words(s["keywords"])
        if kws:
            scope += "_" + "·".join(kws)[:30]
        p = dict(
            gus=gus, dong_words=split_words(s["dong"]), keywords=kws, start=f, end=t,
            max_count=int(s["max_count"]), short_term=bool(s["short_term"]), with_detail=bool(s["with_detail"]),
            include_words=split_words(s["include"]), exclude_words=split_words(s["exclude"]),
            skip_closed=bool(s["skip_closed"]), skip_seen=bool(s["skip_seen"]), polite=bool(s["polite"]),
            base_dir=self.base_dir, send=self._send_config(), scope_label=scope,
        )
        self.dj_log.clear()
        self._dj_append(f"시작 {datetime.now():%Y-%m-%d %H:%M} — {', '.join(g['name'] for g in gus)} / 검색어 {s['keywords'] or '(없음)'} / 등록일 {f} ~ {t}" + (" / 단기만" if s["short_term"] else ""))
        self.dj_btn_start.setEnabled(False)
        self.dj_btn_stop.setEnabled(True)
        self.dj_progress.setRange(0, max(1, int(s["max_count"])))
        self.dj_progress.setValue(0)
        self.dj_progress.setVisible(True)
        self.dj_thread = QThread(self)
        self.dj_worker = DaangnWorker(p)
        self.dj_worker.moveToThread(self.dj_thread)
        self.dj_thread.started.connect(self.dj_worker.run)
        self.dj_worker.log.connect(self._dj_append)
        self.dj_worker.progress.connect(self._dj_on_progress)
        self.dj_worker.finished.connect(self._dj_done)
        self.dj_worker.failed.connect(self._dj_fail)
        self.dj_worker.finished.connect(self.dj_thread.quit)
        self.dj_worker.failed.connect(self.dj_thread.quit)
        self.dj_thread.finished.connect(self._dj_cleanup)
        self.dj_thread.start()

    def _dj_on_progress(self, n: int, mx: int) -> None:
        if mx:
            self.dj_progress.setRange(0, mx)
            self.dj_progress.setValue(min(n, mx))
        self.dj_progress.setFormat(f"{n}건")

    def _dj_stop(self) -> None:
        if not self.dj_worker:
            return
        if not self.dj_worker._stop:
            self.dj_worker.stop()
            self._dj_append("검색을 멈춥니다. 지금까지 모은 글의 상세(내용·주소·안심번호)는 받아서 저장합니다. 상세도 건너뛰려면 [상세도 건너뛰기]를 누르세요.")
            self.dj_btn_stop.setText("상세도 건너뛰기")
        else:
            self.dj_worker.stop_detail()
            self._dj_append("상세 받기도 건너뛰고 바로 저장합니다.")
            self.dj_btn_stop.setEnabled(False)

    def _dj_done(self, msg: str) -> None:
        self._dj_append(msg)
        self._dj_load_regions_quiet()
        if self._batch:
            self._batch_step_done()

    def _dj_fail(self, msg: str) -> None:
        self._dj_append("오류: " + msg)
        if self._batch:
            self._batch_step_done()
        else:
            QMessageBox.warning(self, "오류", msg)

    def _dj_load_regions_quiet(self) -> None:
        d = read_json(os.path.join(self.base_dir, DJ_REGIONS_FILE)) or {}
        if d:
            self.dj_regions.setdefault("dongs", {}).update(d.get("dongs") or {})

    def _dj_cleanup(self) -> None:
        self.dj_btn_start.setEnabled(True)
        self.dj_btn_stop.setEnabled(False)
        self.dj_btn_stop.setText("중지")
        self.dj_progress.setVisible(False)
        if self.dj_worker:
            self.dj_worker.deleteLater()
        if self.dj_thread:
            self.dj_thread.deleteLater()
        self.dj_worker = None
        self.dj_thread = None

    # ====================== 자동 실행 순서 ======================
    def _batch_step_done(self) -> None:
        """자동 실행에서 한 단계가 끝나면 다음 단계를, 없으면 프로그램을 닫는다."""
        if self._batch_queue:
            nxt = self._batch_queue.pop(0)
            if nxt == "gk":
                QTimer.singleShot(500, lambda: self._start(auto=True))
            else:
                QTimer.singleShot(500, lambda: self._dj_start(auto=True))
            return
        self._append("자동 실행 완료 — 프로그램을 닫습니다.")
        QTimer.singleShot(2000, QApplication.quit)

    # ---------- 실행 ----------
    def _start(self, auto: bool = False) -> None:
        if self.thread and self.thread.isRunning():
            return
        self._save_settings()
        s = self._settings()
        f, t = self._date_range()
        types = s["types"]
        if not types:
            msg = "받을 글 종류를 하나 이상 체크하세요."
            if auto or self._batch:
                self._append("실행 불가: " + msg)
                self._batch_step_done()
            else:
                QMessageBox.information(self, "확인", msg)
            return
        meet_ids = self._selected_meet_ids()
        cat_ids: List[int] = []
        cat_meet: Dict[int, int] = {}
        for lbl in s["categories"]:
            if lbl in self.cat_map:
                cid, mid, ptype = self.cat_map[lbl]
                if ptype and ptype not in types:
                    continue
                cat_ids.append(cid)
                cat_meet[cid] = mid
        if s["categories"] and not cat_ids:
            self._append("고른 카테고리가 선택한 글 종류와 맞지 않아 카테고리 조건 없이 받습니다.")

        if s["categories"] and cat_ids:
            scope = s["categories"][0].split(" > ")[-1].split(" [")[0] + (f" 외 {len(cat_ids) - 1}" if len(cat_ids) > 1 else "")
        elif s["meets"]:
            scope = s["meets"][0] + (f" 외 {len(s['meets']) - 1}" if len(s["meets"]) > 1 else "")
        else:
            scope = "전체"
        if s["search"]:
            scope += "_" + "·".join(split_words(s["search"]))[:30]

        p = dict(
            types=types,
            meet_ids=meet_ids,
            category_ids=cat_ids,
            category_meet=cat_meet,
            search_terms=split_words(s["search"]),
            include_words=split_words(s["include"]),
            exclude_words=split_words(s["exclude"]),
            region_words=split_words(s["region"]),
            start=f,
            end=t,
            max_count=int(s["max_count"]),
            only_open=bool(s["only_open"]),
            skip_seen=bool(s["skip_seen"]),
            polite=bool(s["polite"]),
            base_dir=self.base_dir,
            send=self._send_config(),
            scope_label=scope,
        )

        self.log.clear()
        self._append(
            f"시작 {datetime.now():%Y-%m-%d %H:%M} — 종류 {'·'.join(gk.TYPE_KO.get(x, x) for x in types)} / 등록일 {f} ~ {t} / "
            + (f"카테고리 {len(cat_ids)}개" if cat_ids else (f"커뮤니티 {', '.join(s['meets'])}" if s["meets"] else "커뮤니티 전체"))
            + (f" / 검색어 {s['search']}" if s["search"] else "")
        )
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.progress.setRange(0, max(1, int(s["max_count"])))
        self.progress.setValue(0)
        self.progress.setVisible(True)

        self.thread = QThread(self)
        self.worker = Worker(p)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.log.connect(self._append)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._done)
        self.worker.failed.connect(self._fail)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self._cleanup)
        self.thread.start()

    def _on_progress(self, n: int, mx: int) -> None:
        if mx:
            self.progress.setRange(0, mx)
            self.progress.setValue(min(n, mx))
        self.progress.setFormat(f"{n}건")

    def _stop(self) -> None:
        if self.worker:
            self.worker.stop()
            self._append("중지 요청... 진행 중인 페이지만 마치고 멈춥니다.")
            self.btn_stop.setEnabled(False)

    def _done(self, msg: str) -> None:
        self._append(msg)
        if self._batch:
            self._batch_step_done()

    def _fail(self, msg: str) -> None:
        self._append("오류: " + msg)
        if self._batch:
            self._batch_step_done()
        else:
            QMessageBox.warning(self, "오류", msg)

    def _cleanup(self) -> None:
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress.setVisible(False)
        if self.worker:
            self.worker.deleteLater()
        if self.thread:
            self.thread.deleteLater()
        self.worker = None
        self.thread = None

    def run_batch(self) -> None:
        """--run-all: 저장된 설정으로 긱톡 → 당근알바 차례로 돌리고 종료."""
        self._batch = True
        self._batch_queue = []
        if self.chk_auto.isChecked():
            self._batch_queue.append("gk")
        if self.dj_chk_auto.isChecked():
            self._batch_queue.append("dj")
        self._append("자동 실행 시작 (저장된 설정): " + (" → ".join("긱톡" if x == "gk" else "당근알바" for x in self._batch_queue) or "포함된 탭 없음"))
        self._batch_step_done()

    def _apply_style(self):
        self.setStyleSheet(APP_STYLE)

    def closeEvent(self, ev) -> None:
        self._save_settings()
        super().closeEvent(ev)


APP_STYLE = """
            QMainWindow {
                background: #1f2431;
            }
            QWidget#appRoot {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 1,
                    stop: 0 #30384a,
                    stop: 0.5 #242b3a,
                    stop: 1 #1c2230
                );
            }
            QWidget {
                color: #f8fafc;
                font-family: 'Segoe UI', 'Malgun Gothic', 'Yu Gothic UI', sans-serif;
                font-size: 12px;
            }
            QMessageBox {
                background: #ffffff;
            }
            QMessageBox QLabel {
                color: #111827;
                font-weight: 600;
            }
            QMessageBox QPushButton {
                background: #4f46e5;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 7px 14px;
                min-width: 84px;
                font-weight: 700;
            }
            QMessageBox QPushButton:hover { background: #4338ca; }
            QMessageBox QPushButton:pressed { background: #3730a3; }

            QTabWidget::pane {
                border: 1px solid #7c8da8;
                border-radius: 12px;
                background: rgba(250, 252, 255, 0.97);
                top: -1px;
            }
            QTabBar::tab {
                background: #c9d3e2;
                color: #253248;
                border: 1px solid #9caec6;
                border-bottom: none;
                padding: 10px 18px;
                margin-right: 6px;
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
                font-weight: 600;
            }
            QTabBar::tab:hover { background: #b9c7da; color: #1e293b; }
            QTabBar::tab:selected { background: #4f46e5; color: white; border-color: #4f46e5; }

            QGroupBox {
                border: 1px solid #d7e0ec;
                border-radius: 14px;
                margin-top: 12px;
                padding-top: 16px;
                background: rgba(249, 251, 255, 0.98);
                font-weight: 700;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                color: #334155;
                background: transparent;
            }

            QLabel { color: #f1f5f9; }
            QGroupBox QLabel { color: #0f172a; font-weight: 600; }
            QCheckBox { spacing: 6px; }
            QGroupBox QCheckBox { color: #111827; font-weight: 600; }
            QGroupBox QCheckBox[dimmed="true"] { color: #6b7280; font-weight: 700; }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border: 1px solid #a7b3c5;
                border-radius: 5px;
                background: #ffffff;
            }
            QCheckBox::indicator:checked {
                background: #4f46e5;
                border: 1px solid #4338ca;
            }
            QGroupBox QCheckBox[dimmed="true"]::indicator {
                border: 1px solid #9ca3af;
                background: #e5e7eb;
            }
            QGroupBox QCheckBox[dimmed="true"]::indicator:checked {
                border: 1px solid #6b7280;
                background: #6b7280;
            }

            QListWidget, QPlainTextEdit {
                background: #ffffff;
                color: #111827;
                border: 1px solid #cbd5e1;
                border-radius: 8px;
            }
            QListWidget::item {
                color: #111827;
                padding: 3px 4px;
            }
            QListWidget::item:selected {
                background: #dbe4f5;
                color: #111827;
            }
            QSpinBox {
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                padding: 4px 8px;
                background: #ffffff;
                color: #0f172a;
                min-width: 90px;
            }
            QLineEdit, QComboBox, QDateEdit {
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                padding: 6px 8px;
                background: #ffffff;
                color: #0f172a;
                selection-background-color: #4f46e5;
            }
            QLineEdit::placeholder {
                color: #64748b;
            }
            /* 거래유형 미선택 등으로 비활성화된 입력칸은 어둡게 표시 */
            QLineEdit:disabled {
                background: #e5e7eb;
                color: #9ca3af;
                border-color: #d1d5db;
            }
            QGroupBox QLabel:disabled { color: #b0b8c4; }
            QPushButton:disabled {
                background: #e5e7eb;
                color: #9ca3af;
                border-color: #d1d5db;
            }
            QComboBox QAbstractItemView {
                color: #0f172a;
                background: #ffffff;
                selection-background-color: #c7d2fe;
                selection-color: #111827;
                border: 1px solid #cbd5e1;
            }
            QDateEdit::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 22px;
                border-left: 1px solid #cbd5e1;
            }
            QDateEdit[dimmed="true"] {
                background: #e5e7eb;
                color: #94a3b8;
                border-color: #cbd5e1;
            }
            QLabel[dimmed="true"] {
                color: #94a3b8;
            }
            QCalendarWidget QWidget {
                background: #ffffff;
                color: #0f172a;
                selection-background-color: #4f46e5;
                selection-color: #ffffff;
            }
            QCalendarWidget QToolButton {
                color: #0f172a;
                background: #eef2ff;
                border: 1px solid #d4dce8;
                border-radius: 6px;
                font-weight: 700;
                padding: 4px 8px;
            }
            QCalendarWidget QToolButton:hover { background: #e0e7ff; }
            QCalendarWidget QSpinBox {
                color: #0f172a;
                background: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 2px 4px;
            }
            QCalendarWidget QMenu {
                background: #ffffff;
                color: #0f172a;
                border: 1px solid #cbd5e1;
            }
            QCalendarWidget QMenu::item:selected {
                background: #c7d2fe;
                color: #111827;
            }
            QCalendarWidget QAbstractItemView:enabled {
                color: #0f172a;
                background: #ffffff;
                selection-background-color: #4f46e5;
                selection-color: #ffffff;
            }
            QLineEdit:hover, QComboBox:hover, QDateEdit:hover { border-color: #94a3b8; }
            QLineEdit:focus, QComboBox:focus, QDateEdit:focus { border-color: #4f46e5; }

            QPushButton {
                background: #4f46e5;
                color: white;
                border: none;
                border-radius: 10px;
                padding: 9px 16px;
                font-weight: 700;
            }
            QPushButton:hover { background: #4338ca; }
            QPushButton:pressed { background: #3730a3; }
            QPushButton:disabled { background: #a5b4fc; color: #eef2ff; }
            QPushButton#rangePresetBtn {
                background: #f8fbff;
                color: #2f3f56;
                border: 1px solid #b8d2ef;
                border-radius: 5px;
                padding: 5px 8px;
                min-width: 34px;
                font-weight: 700;
            }
            QPushButton#rangePresetBtn:hover {
                background: #eef6ff;
                border-color: #8fb8e6;
            }
            QPushButton#rangePresetBtn[inRange="true"] {
                background: #b7d8f7;
                color: #1f3b5b;
                border-color: #84b8e8;
            }
            QPushButton#rangePresetBtn[inRange="true"]:hover {
                background: #a7cef3;
                border-color: #6ea9e2;
            }
            QPushButton#rangePresetBtn:checked {
                background: #5ba0e7;
                color: #ffffff;
                border-color: #4a8fd6;
            }
            QPushButton#rangePresetBtn:disabled {
                background: #f1f5f9;
                color: #94a3b8;
                border-color: #d7e2ef;
            }
            QPushButton#rangeResetBtn {
                background: #9ca3af;
                color: #ffffff;
                border: none;
                border-radius: 5px;
                padding: 5px 10px;
                min-width: 48px;
            }
            QPushButton#rangeResetBtn:hover { background: #6b7280; }
            QPushButton#rangeResetBtn:pressed { background: #4b5563; }
            QPushButton#rangeResetBtn:disabled { background: #cbd5e1; color: #f8fafc; }

            QSlider::groove:horizontal {
                border: 0;
                height: 12px;
                background: #dbe3ef;
                border-radius: 6px;
            }
            QSlider::handle:horizontal {
                width: 22px;
                margin: -6px 0;
                border-radius: 11px;
                background: #4f46e5;
                border: 2px solid #eef2ff;
            }
            QSlider::handle:horizontal:hover { background: #4338ca; }

            QWidget#sliderCard {
                background: #e8eef6;
                border: 1px solid #d8e1ed;
                border-radius: 12px;
            }

            QHeaderView::section {
                background: #eaf0f7;
                color: #111827;
                padding: 8px;
                border: 1px solid #d4dce8;
                font-weight: 700;
            }
            QTableWidget {
                background: #ffffff;
                alternate-background-color: #f8fafc;
                color: #0f172a;
                gridline-color: #e2e8f0;
                border: 1px solid #d4dce8;
                border-radius: 10px;
                selection-background-color: #a5b4fc;
                selection-color: #111827;
            }

            QProgressBar {
                border: 1px solid #cbd5e1;
                border-radius: 7px;
                text-align: center;
                background: #e2e8f0;
                min-height: 16px;
            }
            QProgressBar::chunk {
                background: #4f46e5;
                border-radius: 6px;
            }
            """


def _install_crash_guard() -> None:
    """창 모드 exe 는 stdout/stderr 가 없어 예외 출력 자체가 또 예외가 된다 → 파일로 돌리고 전역 예외는 기록만."""
    import io
    log_path = os.path.join(base_dir(), "오류기록.log")
    if getattr(sys, "frozen", False) or sys.stderr is None or sys.stdout is None:
        try:
            f = open(log_path, "a", encoding="utf-8", buffering=1)
            sys.stderr = f
            sys.stdout = f
        except Exception:
            sys.stderr = io.StringIO()
            sys.stdout = io.StringIO()

    def hook(t, v, tb):
        import traceback
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} 처리되지 않은 오류" + chr(10) + "".join(traceback.format_exception(t, v, tb)) + chr(10))
        except Exception:
            pass

    sys.excepthook = hook


def main() -> None:
    _install_crash_guard()
    argv = sys.argv[1:]
    batch = "--run-all" in argv
    app = QApplication.instance() or QApplication(sys.argv)
    w = MainWindow()
    if batch:
        w.showMinimized()
        QTimer.singleShot(800, w.run_batch)
    else:
        w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
