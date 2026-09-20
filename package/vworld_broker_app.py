# -*- coding: utf-8 -*-
"""
중개업소 신규개업 수집기 (브이월드 국가중점데이터) - 단독 실행 GUI.

핵심: 전국 부동산중개업사무소 파일에서 '최근 등록(=신규 개업)'만 지역별로 뽑아
      엑셀로 만들고 메일/텔레그램으로 보낸다. 이미 받은 곳은 다시 보내지 않는다.

무인 실행:  프로그램.exe --run-all   (저장된 설정으로 한 번 돌리고 스스로 종료)
"""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QDate, QObject, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFileDialog,
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
import vworld_broker as vb

APP_TITLE = "중개업소 신규개업 수집기"
SETTINGS_FILE = "vworld_settings.json"
SEEN_FILE = "vworld_seen.json"
SEND_FILE = "send_config.json"

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


def resource_path(name: str) -> str:
    """PyInstaller 로 묶인 경우 임시 해제 폴더에서 찾는다."""
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, name)


def builtin_regions() -> Dict[str, List[str]]:
    """프로그램에 들어 있는 전국 시도·시군구 목록 (파일을 받기 전에도 고를 수 있게)."""
    import json

    for cand in (resource_path("vworld_regions_builtin.json"),
                 os.path.join(base_dir(), "vworld_regions_builtin.json")):
        try:
            if os.path.exists(cand):
                with open(cand, "r", encoding="utf-8") as f:
                    d = json.load(f)
                if d:
                    return d
        except Exception:
            pass
    return {}


def base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def read_json(path: str) -> Dict[str, Any]:
    import json

    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f) or {}
    except Exception:
        pass
    return {}


def write_json(path: str, data: Dict[str, Any]) -> None:
    import json

    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


class CheckList(QListWidget):
    """체크박스 목록 (지역 선택용)."""

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


class Worker(QObject):
    log = Signal(str)
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, p: Dict[str, Any]):
        super().__init__()
        self.p = p

    @Slot()
    def run(self) -> None:
        try:
            p = self.p
            path = ""
            if p["source"] == "download":
                self.log.emit("브이월드 로그인...")
                cli = vb.VworldClient(self.log.emit)
                ok, msg = cli.login(p["vw_id"], p["vw_pw"])
                self.log.emit("  " + msg)
                if not ok:
                    self.failed.emit(msg + "  (받아둔 파일로 돌리려면 '내 폴더의 파일 사용'을 선택하세요)")
                    return
                self.log.emit("파일 목록 확인...")
                files = cli.file_list()
                office = next((f for f in files if f["kind"] == "office"), None)
                agent = next((f for f in files if f["kind"] == "agent"), None)
                if not office:
                    self.failed.emit("브이월드에서 사무소정보 파일을 찾지 못했습니다.")
                    return
                self.log.emit(f"내려받는 중: {office['label']}")
                path = cli.download(office["key"], p["folder"], self.log.emit)
                if agent and p["with_agent"]:
                    try:
                        self.log.emit(f"내려받는 중: {agent['label']}")
                        cli.download(agent["key"], p["folder"], self.log.emit)
                    except Exception as e:
                        self.log.emit(f"  중개업자 파일은 건너뜁니다: {e}")
            else:
                path = vb.find_local_file(p["folder"])
                if not path:
                    self.failed.emit(
                        f"폴더에서 AL_D171 파일을 찾지 못했습니다: {p['folder']}\n"
                        "브이월드에서 '부동산중개업사무소정보(CSV)'를 받아 이 폴더에 두세요."
                    )
                    return
                self.log.emit(f"파일 사용: {os.path.basename(path)}")

            rows = vb.read_offices(path, self.log.emit)
            base = vb.data_base_date(rows)
            self.log.emit(f"  데이터 기준일: {base}")

            seen_path = os.path.join(p["base_dir"], SEEN_FILE)
            seen = vb.load_seen(seen_path) if p["skip_seen"] else {}
            new = vb.filter_new(
                rows,
                sidos=p["sidos"],
                sigungus=p["sigungus"],
                start=p["start"],
                end=p["end"],
                only_open=p["only_open"],
                exclude_regnos=set(seen.keys()) if p["skip_seen"] else None,
            )
            self.log.emit(
                f"신규 개업 {len(new)}건 "
                f"(개업일 {p['start']} ~ {p['end']}"
                + (f", 이미 받은 {len(seen)}곳 제외" if p["skip_seen"] else "")
                + ")"
            )
            if not new:
                self.finished.emit("새로 생긴 중개업소가 없습니다. (파일 기준일 " + base + ")")
                return

            agent_path = vb.find_local_file(p["folder"], vb.AGENT_PREFIX)
            if p["with_agent"] and agent_path:
                vb.attach_agents(new, agent_path, self.log.emit)

            region = "전국"
            if p["sigungus"]:
                region = p["sigungus"][0] + (f" 외 {len(p['sigungus']) - 1}곳" if len(p["sigungus"]) > 1 else "")
            elif p["sidos"]:
                region = p["sidos"][0] + (f" 외 {len(p['sidos']) - 1}곳" if len(p["sidos"]) > 1 else "")
            out_dir = os.path.join(p["base_dir"], "data")
            fname = f"중개업소_신규개업_{region}_{len(new)}곳_{datetime.now():%y%m%d_%H%M%S}.xlsx"
            out_path = vb.save_excel(new, os.path.join(out_dir, fname))
            self.log.emit(f"저장: {out_path}")

            if p["skip_seen"]:
                for r in new:
                    if r["등록번호"]:
                        seen[r["등록번호"]] = r["개업일"]
                vb.save_seen(seen_path, seen)
                self.log.emit(f"  받은 곳 기록: 총 {len(seen)}곳")

            cfg = p.get("send") or {}
            if cfg.get("mail_on") or cfg.get("tg_on"):
                self.log.emit("자동 전송 중...")
                caption = f"[신규 개업 중개업소] {region} {len(new)}곳 / 기준일 {base}"
                auto_send.deliver(cfg, out_path, caption, self.log.emit)

            self.finished.emit(f"완료: {region} 신규 개업 {len(new)}곳 — {out_path}")
        except Exception as e:
            self.failed.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1000, 880)
        self.base_dir = base_dir()
        self.worker: Optional[Worker] = None
        self.thread: Optional[QThread] = None
        self._batch = False
        self.region_cache: Dict[str, List[str]] = {}
        self._build_ui()
        self._load_settings()
        self._load_region_cache()

    # ---------- UI ----------
    def _build_ui(self) -> None:
        w = QWidget()
        w.setObjectName("appRoot")
        self.setCentralWidget(w)
        outer = QVBoxLayout(w)
        title = QLabel(APP_TITLE)
        title.setObjectName("appTitle")
        subtitle = QLabel("브이월드 국가중점데이터에서 개업일 기준으로 새로 생긴 중개업소만 뽑아옵니다")
        subtitle.setObjectName("appSubtitle")
        outer.addWidget(title)
        outer.addWidget(subtitle)
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)

        page = QWidget()
        v = QVBoxLayout(page)

        src = QGroupBox("1. 자료 가져오는 방법")
        sg = QGridLayout(src)
        self.cb_source = QComboBox()
        self.cb_source.addItems(["브이월드에서 자동으로 받기 (로그인 필요)", "내 폴더의 파일 사용 (직접 받아둔 파일)"])
        self.ed_vw_id = QLineEdit()
        self.ed_vw_id.setPlaceholderText("브이월드 아이디")
        self.ed_vw_pw = QLineEdit()
        self.ed_vw_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.ed_vw_pw.setPlaceholderText("브이월드 비밀번호")
        self.ed_folder = QLineEdit(os.path.join(self.base_dir, "자료"))
        self.btn_folder = QPushButton("폴더 선택")
        self.btn_folder.clicked.connect(self._pick_folder)
        self.btn_load = QPushButton("파일 읽어 지역 목록 채우기")
        self.btn_load.clicked.connect(self._load_regions_from_file)
        sg.addWidget(QLabel("방법"), 0, 0)
        sg.addWidget(self.cb_source, 0, 1, 1, 3)
        sg.addWidget(QLabel("브이월드 계정"), 1, 0)
        sg.addWidget(self.ed_vw_id, 1, 1)
        sg.addWidget(self.ed_vw_pw, 1, 2, 1, 2)
        sg.addWidget(QLabel("자료 폴더"), 2, 0)
        sg.addWidget(self.ed_folder, 2, 1, 1, 2)
        sg.addWidget(self.btn_folder, 2, 3)
        sg.addWidget(self.btn_load, 3, 3)
        sg.addWidget(
            QLabel("브이월드 www.vworld.kr 에서 '부동산중개업사무소정보(CSV)'를 받는 자료입니다. 전국 약 10만 곳."),
            3, 0, 1, 3,
        )
        sg.setColumnStretch(1, 1)
        sg.setColumnStretch(2, 1)
        v.addWidget(src)

        reg = QGroupBox("2. 지역 고르기 (아무것도 안 고르면 전국)")
        rg = QGridLayout(reg)
        self.lst_sido = CheckList(160)
        self.lst_sido.set_items(vb.SIDO_LIST)
        self.lst_sido.itemChanged.connect(self._on_sido_changed)
        self.lst_gun = CheckList(160)
        self.btn_sido_all = QPushButton("시도 전체 해제")
        self.btn_sido_all.clicked.connect(lambda: self.lst_sido.check_all(False))
        self.btn_gun_all = QPushButton("시군구 전체 해제")
        self.btn_gun_all.clicked.connect(lambda: self.lst_gun.check_all(False))
        self.btn_gun_pick_all = QPushButton("보이는 시군구 전체 선택")
        self.btn_gun_pick_all.clicked.connect(lambda: self.lst_gun.check_all(True))
        self.ed_gun_find = QLineEdit()
        self.ed_gun_find.setPlaceholderText("시군구 찾기 (예: 강남)")
        self.ed_gun_find.textChanged.connect(self._filter_gun)
        rg.addWidget(QLabel("시 · 도"), 0, 0)
        rg.addWidget(QLabel("시 · 군 · 구  (시도를 고르면 채워집니다)"), 0, 1)
        rg.addWidget(self.lst_sido, 1, 0)
        rg.addWidget(self.lst_gun, 1, 1)
        rg.addWidget(self.ed_gun_find, 2, 1)
        gunrow = QHBoxLayout()
        gunrow.addWidget(self.btn_gun_pick_all)
        gunrow.addWidget(self.btn_gun_all)
        rg.addWidget(self.btn_sido_all, 3, 0)
        rg.addLayout(gunrow, 3, 1)
        rg.setColumnStretch(0, 1)
        rg.setColumnStretch(1, 2)
        v.addWidget(reg)

        cond = QGroupBox("3. 조건")
        cg = QGridLayout(cond)
        self.cb_period = QComboBox()
        self.cb_period.addItems([p[0] for p in PERIODS])
        self.cb_period.setCurrentIndex(3)
        self.cb_period.currentIndexChanged.connect(self._on_period_changed)
        self.de_from = QDateEdit(QDate.currentDate().addDays(-7))
        self.de_from.setCalendarPopup(True)
        self.de_from.setDisplayFormat("yyyy-MM-dd")
        self.de_to = QDateEdit(QDate.currentDate())
        self.de_to.setCalendarPopup(True)
        self.de_to.setDisplayFormat("yyyy-MM-dd")
        for _de in (self.de_from, self.de_to):
            _de.setMinimumWidth(170)   # 날짜 마지막 글자가 잘리지 않도록
            _de.setMinimumHeight(34)
        self.de_from.setEnabled(False)
        self.de_to.setEnabled(False)
        self.chk_open = QCheckBox("영업중만")
        self.chk_open.setChecked(True)
        self.chk_seen = QCheckBox("이미 받은 곳은 빼기 (매일 받을 때 켜세요)")
        self.chk_seen.setChecked(True)
        self.chk_agent = QCheckBox("대표자 종별(공인중개사/중개인)도 붙이기")
        self.chk_agent.setChecked(True)
        cg.addWidget(QLabel("개업일 기준 기간"), 0, 0)
        cg.addWidget(self.cb_period, 0, 1)
        cg.addWidget(self.de_from, 0, 2)
        cg.addWidget(QLabel("~"), 0, 3)
        cg.addWidget(self.de_to, 0, 4)
        cg.addWidget(self.chk_open, 0, 5)
        cg.addWidget(self.chk_seen, 1, 0, 1, 3)
        cg.addWidget(self.chk_agent, 1, 3, 1, 3)
        cg.setColumnStretch(6, 1)
        v.addWidget(cond)

        snd = QGroupBox("4. 다 되면 보내기 (한 번만 입력해두면 자동 실행에도 그대로 씁니다)")
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

        row = QHBoxLayout()
        self.btn_start = QPushButton("지금 뽑기")
        self.btn_start.clicked.connect(self._start)
        self.btn_open = QPushButton("결과 폴더 열기")
        self.btn_open.clicked.connect(self._open_out)
        self.btn_reset_seen = QPushButton("받은 기록 지우기")
        self.btn_reset_seen.clicked.connect(self._reset_seen)
        row.addWidget(self.btn_start)
        row.addWidget(self.btn_open)
        row.addWidget(self.btn_reset_seen)
        row.addStretch(1)
        v.addLayout(row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        self.lbl_status = QLabel("대기")
        v.addWidget(self.progress)
        v.addWidget(self.lbl_status)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(4000)
        v.addWidget(self.log, 1)

        send_page = QWidget()
        sv = QVBoxLayout(send_page)
        sv.addWidget(snd)
        auto = QGroupBox("5. 시간 자동화 (PC가 자고 있어도 정해진 시각에 자동으로)")
        av = QVBoxLayout(auto)
        av.addWidget(QLabel(
            "1. 위 조건을 정하고 [지금 뽑기]로 한 번 돌려 확인하세요. 그 설정이 그대로 저장됩니다." + chr(10)
            + "2. 프로그램 폴더의  자동실행_설정.bat  을 관리자 권한으로 실행하고 시각을 정하세요." + chr(10)
            + "3. 그 시각에 PC가 깨어나 새로 생긴 중개업소만 뽑아 메일과 텔레그램으로 보내고 스스로 닫힙니다." + chr(10)
            + "   끄려면  자동실행_해제.bat  을 실행하세요. 전원을 완전히 끄면 깨어나지 못합니다."
        ))
        self.btn_open_folder = QPushButton("프로그램 폴더 열기")
        self.btn_open_folder.clicked.connect(self._open_base)
        av.addWidget(self.btn_open_folder)
        sv.addWidget(auto)
        sv.addStretch(1)

        self.tabs.addTab(page, "수집 조건")
        self.tabs.addTab(send_page, "보내기 · 자동화")
        self._apply_style()
        self.setStyleSheet(
            self.styleSheet()
            + """
            QDateEdit {
                min-width: 170px;
                padding: 6px 30px 6px 10px;
                color: #111827;
                background: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 8px;
            }
            QDateEdit::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: center right;
                width: 24px;
                border-left: 1px solid #cbd5e1;
            }
            QListWidget {
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
            """
        )

    # ---------- 도우미 ----------
    def _append(self, line: str) -> None:
        self.log.appendPlainText(line)
        self.lbl_status.setText(line.strip()[:120])
        try:
            with open(os.path.join(self.base_dir, "실행기록.log"), "a", encoding="utf-8") as f:
                f.write("[{0:%Y-%m-%d %H:%M:%S}] {1}".format(datetime.now(), line.strip()) + chr(10))
        except Exception:
            pass

    def _pick_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "자료 폴더 선택", self.ed_folder.text() or self.base_dir)
        if d:
            self.ed_folder.setText(d)

    def _on_period_changed(self, idx: int) -> None:
        custom = PERIODS[idx][1] == -1
        self.de_from.setEnabled(custom)
        self.de_to.setEnabled(custom)

    def _date_range(self):
        days = PERIODS[self.cb_period.currentIndex()][1]
        if days == -1:
            return self.de_from.date().toPython(), self.de_to.date().toPython()
        return date.today() - timedelta(days=days), date.today()

    def _on_sido_changed(self, *_a) -> None:
        picked = self.lst_sido.checked()
        guns: List[str] = []
        for s in picked:
            guns.extend(self.region_cache.get(s, []))
        keep = self.lst_gun.checked()
        self.lst_gun.set_items(sorted(set(guns)), checked=keep)
        if hasattr(self, "ed_gun_find"):
            self._filter_gun(self.ed_gun_find.text())

    def _filter_gun(self, text: str) -> None:
        t = (text or "").strip()
        for i in range(self.lst_gun.count()):
            it = self.lst_gun.item(i)
            it.setHidden(bool(t) and t not in it.text())

    def _load_region_cache(self) -> None:
        d = read_json(os.path.join(self.base_dir, "vworld_regions.json")) or builtin_regions()
        if d:
            self.region_cache = d
            self._on_sido_changed()
            if getattr(self, "_pending_regions", None):
                self.lst_gun.set_checked(self._pending_regions[1])

    def _load_regions_from_file(self) -> None:
        path = vb.find_local_file(self.ed_folder.text())
        if not path:
            QMessageBox.information(
                self, "파일 없음",
                "폴더에서 AL_D171 파일을 찾지 못했습니다.\n"
                "브이월드에서 '부동산중개업사무소정보(CSV)'를 받아 이 폴더에 넣거나,\n"
                "'브이월드에서 자동으로 받기'로 한 번 돌리세요.",
            )
            return
        self._append(f"지역 목록 만드는 중: {os.path.basename(path)}")
        try:
            rows = vb.read_offices(path, self._append)
        except Exception as e:
            QMessageBox.warning(self, "읽기 실패", str(e))
            return
        self.region_cache = vb.region_map(rows)
        write_json(os.path.join(self.base_dir, "vworld_regions.json"), self.region_cache)
        self._on_sido_changed()
        self._append(f"  지역 목록 완성: 시도 {len(self.region_cache)}개")

    def _open_base(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.base_dir))

    def _open_out(self) -> None:
        d = os.path.join(self.base_dir, "data")
        os.makedirs(d, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(d))

    def _reset_seen(self) -> None:
        p = os.path.join(self.base_dir, SEEN_FILE)
        if QMessageBox.question(self, "받은 기록 지우기", "이미 받은 곳 기록을 지울까요?\n다음 실행에서 기간 안의 모든 곳이 다시 나옵니다.") != QMessageBox.StandardButton.Yes:
            return
        try:
            if os.path.exists(p):
                os.remove(p)
            self._append("받은 기록을 지웠습니다.")
        except Exception as e:
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
                f.write("중개업소 신규개업 수집기 전송 테스트 {0:%Y-%m-%d %H:%M:%S}".format(datetime.now()) + chr(10))
        except Exception as e:
            QMessageBox.warning(self, "테스트 전송", str(e))
            return
        auto_send.deliver(cfg, p, "중개업소 신규개업 수집기 전송 테스트", self._append)
        try:
            os.remove(p)
        except Exception:
            pass
        QMessageBox.information(self, "테스트 전송", "결과를 아래 기록에서 확인하세요.")

    # ---------- 설정 ----------
    def _settings(self) -> Dict[str, Any]:
        f, t = self._date_range()
        return {
            "source": "download" if self.cb_source.currentIndex() == 0 else "local",
            "vw_id": self.ed_vw_id.text().strip(),
            "vw_pw": self.ed_vw_pw.text().strip(),
            "folder": self.ed_folder.text().strip(),
            "sidos": self.lst_sido.checked(),
            "sigungus": self.lst_gun.checked(),
            "period_idx": self.cb_period.currentIndex(),
            "date_from": f.isoformat(),
            "date_to": t.isoformat(),
            "only_open": self.chk_open.isChecked(),
            "skip_seen": self.chk_seen.isChecked(),
            "with_agent": self.chk_agent.isChecked(),
        }

    def _save_settings(self) -> None:
        write_json(os.path.join(self.base_dir, SETTINGS_FILE), self._settings())
        self._send_config(save=True)

    def _load_settings(self) -> None:
        s = read_json(os.path.join(self.base_dir, SETTINGS_FILE))
        if s:
            self.cb_source.setCurrentIndex(0 if s.get("source", "download") == "download" else 1)
            self.ed_vw_id.setText(s.get("vw_id", ""))
            self.ed_vw_pw.setText(s.get("vw_pw", ""))
            self.ed_folder.setText(s.get("folder") or os.path.join(self.base_dir, "자료"))
            self.cb_period.setCurrentIndex(int(s.get("period_idx", 2)))
            if s.get("date_from"):
                self.de_from.setDate(QDate.fromString(s["date_from"], "yyyy-MM-dd"))
            if s.get("date_to"):
                self.de_to.setDate(QDate.fromString(s["date_to"], "yyyy-MM-dd"))
            self.chk_open.setChecked(bool(s.get("only_open", True)))
            self.chk_seen.setChecked(bool(s.get("skip_seen", True)))
            self.chk_agent.setChecked(bool(s.get("with_agent", True)))
            self._pending_regions = (s.get("sidos") or [], s.get("sigungus") or [])
            self.lst_sido.set_checked(self._pending_regions[0])
        cfg = auto_send.load_config(os.path.join(self.base_dir, SEND_FILE))
        self.chk_mail.setChecked(bool(cfg.get("mail_on")))
        self.ed_mail_from.setText(cfg.get("mail_from", ""))
        self.ed_mail_pw.setText(cfg.get("mail_pw", ""))
        self.ed_mail_to.setText(cfg.get("mail_to", ""))
        self.chk_tg.setChecked(bool(cfg.get("tg_on")))
        self.ed_tg_token.setText(cfg.get("tg_token", ""))
        self.ed_tg_chat.setText(cfg.get("tg_chat", ""))

    # ---------- 실행 ----------
    def _start(self, auto: bool = False) -> None:
        if self.thread and self.thread.isRunning():
            return
        self._save_settings()
        s = self._settings()
        f, t = self._date_range()
        p = dict(s)
        p.update(
            {
                "start": f,
                "end": t,
                "base_dir": self.base_dir,
                "send": self._send_config(),
                "folder": s["folder"] or os.path.join(self.base_dir, "자료"),
            }
        )
        if p["source"] == "download" and not (p["vw_id"] and p["vw_pw"]):
            msg = "브이월드 아이디와 비밀번호를 넣거나, 자료 가져오는 방법을 '내 폴더의 파일 사용'으로 바꾸세요."
            if auto or self._batch:
                self._append("실행 불가: " + msg)
                QTimer.singleShot(1500, QApplication.quit)
            else:
                QMessageBox.information(self, "확인", msg)
            return
        os.makedirs(p["folder"], exist_ok=True)

        self.log.clear()
        self._append(
            f"시작 {datetime.now():%Y-%m-%d %H:%M} — "
            f"{'브이월드 자동 받기' if p['source'] == 'download' else '내 폴더 파일'} / "
            f"개업일 {f} ~ {t} / 지역 "
            + (", ".join(p["sigungus"]) if p["sigungus"] else (", ".join(p["sidos"]) if p["sidos"] else "전국"))
        )
        self.btn_start.setEnabled(False)
        self.progress.setVisible(True)

        self.thread = QThread(self)
        self.worker = Worker(p)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.log.connect(self._append)
        self.worker.finished.connect(self._done)
        self.worker.failed.connect(self._fail)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self._cleanup)
        self.thread.start()

    def _done(self, msg: str) -> None:
        self._append(msg)
        if self._batch:
            self._append("자동 실행 완료 — 프로그램을 닫습니다.")
            QTimer.singleShot(2000, QApplication.quit)

    def _fail(self, msg: str) -> None:
        self._append("오류: " + msg)
        if self._batch:
            QTimer.singleShot(2500, QApplication.quit)
        else:
            QMessageBox.warning(self, "오류", msg)

    def _cleanup(self) -> None:
        self.btn_start.setEnabled(True)
        self.progress.setVisible(False)
        if self.worker:
            self.worker.deleteLater()
        if self.thread:
            self.thread.deleteLater()
        self.worker = None
        self.thread = None

    def run_batch(self) -> None:
        """--run-all: 저장된 설정으로 한 번 돌리고 종료."""
        self._batch = True
        self._append("자동 실행 시작 (저장된 설정)")
        self._start(auto=True)

    def _apply_style(self):
        self.setStyleSheet(
            """
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
        )

    def closeEvent(self, ev) -> None:
        self._save_settings()
        super().closeEvent(ev)


def main() -> None:
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
