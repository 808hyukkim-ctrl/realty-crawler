from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt, QTime
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from schedule_manager import DAY_NAMES, ScheduleManager, ScheduledJob

SITE_LABELS = {"daangn": "당근", "naver": "네이버"}
DAY_LABELS = {"mon": "월", "tue": "화", "wed": "수", "thu": "목", "fri": "금", "sat": "토", "sun": "일"}

DG_TRADE_LABELS = {"month": "월세", "borrow": "전세", "buy": "매매", "short": "단기"}
DG_SALES_LABELS = {
    "one_room": "원룸", "two_room": "투룸", "officetel": "오피스텔",
    "apart": "아파트", "store": "상가", "etc": "기타",
}
NV_TYPE_CODE_TO_LABEL: dict[str, str] = {}
for _label, _codes in [
    ("재건축", "JGC"), ("분양중/예정", "IA01:IA02:IC01:IC02:IA04:IC03"),
    ("오피스텔분양권", "OBYG"), ("아파트", "APT"), ("아파트분양권", "ABYG"),
    ("재개발", "JGB"), ("오피스텔", "OPST"), ("빌라/연립", "VL"),
    ("원룸/투룸", "OR"), ("상가", "SG"), ("사무실", "SMS"), ("공장/창고", "GJCG"),
    ("지식산업센터", "APTHGJ"), ("건물", "GM"), ("토지", "TJ"),
]:
    for _c in _codes.split(":"):
        NV_TYPE_CODE_TO_LABEL[_c] = _label
NV_TRADE_LABELS = {"A1": "매매", "B1": "전세", "B2": "월세", "B3": "단기"}


def _fmt_range(lo, hi, unit="만원") -> str:
    if lo is None and hi is None:
        return "제한없음"
    lo_s = f"{lo:,}" if lo is not None else "0"
    hi_s = f"{hi:,}" if hi is not None else "∞"
    return f"{lo_s} ~ {hi_s} {unit}"


def _region_summary(s: dict) -> str:
    if "si_list" in s:  # 다중선택(신규) 형식
        dongs = s.get("dong_list") or []
        guns = s.get("gun_list") or []
        sis = s.get("si_list") or []
        if dongs:
            names = [" ".join(x) for x in dongs]
        elif guns:
            names = [" ".join(x) for x in guns]
        elif sis:
            names = list(sis)
        else:
            return "전체"
        if len(names) <= 3:
            return ", ".join(names)
        return f"{', '.join(names[:3])} 외 {len(names) - 3}곳"
    si = s.get("si", "전체")
    gun = s.get("gun", "전체")
    gu = s.get("gu", "전체")
    region_parts = [p for p in [si, gun, gu] if p and p != "전체"]
    return " ".join(region_parts) if region_parts else "전체"


def format_settings_summary(site: str, s: dict) -> str:
    lines = []
    lines.append(f"지역: {_region_summary(s)}")

    if site == "daangn":
        trades = [DG_TRADE_LABELS.get(t, t) for t in s.get("trade_type", "").split(",") if t]
        lines.append(f"거래유형: {', '.join(trades) if trades else '없음'}")

        sales = [DG_SALES_LABELS.get(t, t) for t in s.get("sales_type", "").split(",") if t]
        lines.append(f"매물유형: {', '.join(sales) if sales else '없음'}")

        if s.get("date_use") and s.get("date_start"):
            lines.append(f"날짜: {s['date_start']} ~ {s.get('date_end', '')}")
        else:
            lines.append("날짜: 전체")

        lines.append(f"월세: {s.get('monthly_min', 0):,} ~ {s.get('monthly_max', 3000):,} 만원")
        lines.append(f"보증금: {s.get('deposit_min', 0):,} ~ {s.get('deposit_max', 50000):,} 만원")
        lines.append(f"매매가: {s.get('buy_min', 0):,} ~ {s.get('buy_max', 1000000):,} 만원")
        lines.append(f"전세금: {s.get('borrow_min', 0):,} ~ {s.get('borrow_max', 1000000):,} 만원")
        lines.append(f"면적: {s.get('area_min', 0):,} ~ {s.get('area_max', 200):,} ㎡")

        kws = s.get("detail_keywords", [])
        lines.append(f"키워드: {', '.join(kws) if kws else '없음'}")

    elif site == "naver":
        seen: list[str] = []
        for code in s.get("realestate_type", "").split(":"):
            lbl = NV_TYPE_CODE_TO_LABEL.get(code)
            if lbl and lbl not in seen:
                seen.append(lbl)
        lines.append(f"매물종류: {', '.join(seen) if seen else '전체'}")

        trade_raw = s.get("trade_type") or ""
        trades = [NV_TRADE_LABELS.get(t, t) for t in trade_raw.split(":") if t]
        lines.append(f"거래방식: {', '.join(trades) if trades else '전체'}")

        lines.append(f"날짜: {s.get('date_preset', '전체')}")
        lines.append(f"매매/전세: {_fmt_range(s.get('min_deal'), s.get('max_deal'))}")
        lines.append(f"월세: {_fmt_range(s.get('min_rent'), s.get('max_rent'))}")
        lines.append(f"보증금: {_fmt_range(s.get('min_warr'), s.get('max_warr'))}")
        lines.append(f"면적: {_fmt_range(s.get('min_area'), s.get('max_area'), unit='㎡')}")

        kws = s.get("detail_keywords", [])
        lines.append(f"키워드: {', '.join(kws) if kws else '없음'}")

    return "\n".join(lines)


class ScheduleAddDialog(QDialog):
    def __init__(self, site: str, settings: dict, parent=None):
        super().__init__(parent)
        self._site = site
        self._settings = settings
        self._result: Optional[tuple] = None

        self.setWindowTitle("예약 수집 설정")
        self.setMinimumWidth(440)
        lay = QVBoxLayout(self)
        lay.setSpacing(12)

        # 예약 이름
        name_row = QHBoxLayout()
        name_lbl = QLabel("예약 이름:")
        name_lbl.setStyleSheet("color: black;")
        name_row.addWidget(name_lbl)
        self._name_edit = QLineEdit()
        self._name_edit.setStyleSheet("color: black;")
        site_label = SITE_LABELS.get(site, site)
        self._name_edit.setPlaceholderText(f"{site_label} 자동 수집")
        name_row.addWidget(self._name_edit)
        lay.addLayout(name_row)

        # 수집 시간
        time_row = QHBoxLayout()
        time_lbl = QLabel("수집 시간:")
        time_lbl.setStyleSheet("color: black;")
        time_row.addWidget(time_lbl)
        self._time_edit = QTimeEdit()
        self._time_edit.setStyleSheet("color: black;")
        self._time_edit.setDisplayFormat("HH:mm")
        self._time_edit.setTime(QTime(9, 0))
        self._time_edit.setFixedWidth(90)
        time_row.addWidget(self._time_edit)
        time_row.addStretch(1)
        lay.addLayout(time_row)

        # 요일 선택
        days_box = QGroupBox("수집 요일")
        days_lay = QHBoxLayout(days_box)
        self._daily_chk = QCheckBox("매일")
        self._daily_chk.setChecked(True)
        self._daily_chk.toggled.connect(self._on_daily_toggled)
        days_lay.addWidget(self._daily_chk)
        days_lay.addSpacing(12)
        self._day_checks: dict[str, QCheckBox] = {}
        for day_key in DAY_NAMES:
            cb = QCheckBox(DAY_LABELS[day_key])
            cb.setEnabled(False)
            self._day_checks[day_key] = cb
            days_lay.addWidget(cb)
        days_lay.addStretch(1)
        lay.addWidget(days_box)

        # 현재 설정 요약
        summary_box = QGroupBox("현재 설정")
        summary_lay = QVBoxLayout(summary_box)
        summary_lay.setContentsMargins(8, 6, 8, 6)
        header_lbl = QLabel(f"사이트: {site_label}")
        header_lbl.setStyleSheet("color:#374151; font-size:12px; font-weight:600;")
        summary_lay.addWidget(header_lbl)
        detail_lbl = QLabel(format_settings_summary(site, settings))
        detail_lbl.setStyleSheet("color:#374151; font-size:12px;")
        detail_lbl.setWordWrap(True)
        summary_lay.addWidget(detail_lbl)
        lay.addWidget(summary_box)

        # 버튼
        btn_row = QHBoxLayout()
        btn_ok = QPushButton("저장")
        btn_cancel = QPushButton("취소")
        btn_ok.setMinimumWidth(80)
        btn_cancel.setMinimumWidth(80)
        btn_ok.clicked.connect(self._on_accept)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addStretch(1)
        btn_row.addWidget(btn_ok)
        btn_row.addWidget(btn_cancel)
        lay.addLayout(btn_row)

    def _on_daily_toggled(self, checked: bool):
        for cb in self._day_checks.values():
            cb.setEnabled(not checked)
            if checked:
                cb.setChecked(False)

    def _on_accept(self):
        name = self._name_edit.text().strip()
        if not name:
            name = f"{SITE_LABELS.get(self._site, self._site)} 자동 수집"

        if self._daily_chk.isChecked():
            days = ["daily"]
        else:
            days = [k for k, cb in self._day_checks.items() if cb.isChecked()]
            if not days:
                QMessageBox.warning(self, "오류", "요일을 하나 이상 선택하거나 '매일'을 체크하세요.")
                return

        self._result = (name, self._time_edit.time().toString("HH:mm"), days)
        self.accept()

    def get_result(self) -> Optional[tuple]:
        return self._result


class ScheduleDetailDialog(QDialog):
    def __init__(self, job: ScheduledJob, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"예약 상세 — {job.name}")
        self.setMinimumWidth(360)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        site_label = SITE_LABELS.get(job.site, job.site)
        days_str = "매일" if "daily" in job.days else " ".join(DAY_LABELS.get(d, d) for d in job.days)

        meta_box = QGroupBox("예약 정보")
        meta_lay = QVBoxLayout(meta_box)
        meta_lay.setContentsMargins(8, 6, 8, 6)
        for text in [
            f"이름: {job.name}",
            f"사이트: {site_label}",
            f"시간: {job.schedule_time}",
            f"요일: {days_str}",
            f"마지막 실행: {job.last_run_date or '없음'}",
            f"활성: {'예' if job.enabled else '아니오'}",
        ]:
            lbl = QLabel(text)
            lbl.setStyleSheet("font-size:13px;")
            meta_lay.addWidget(lbl)
        lay.addWidget(meta_box)

        settings_box = QGroupBox("수집 설정")
        settings_lay = QVBoxLayout(settings_box)
        settings_lay.setContentsMargins(8, 6, 8, 6)
        summary_text = format_settings_summary(job.site, job.settings)
        for line in summary_text.split("\n"):
            lbl = QLabel(line)
            lbl.setStyleSheet("font-size:13px;")
            lbl.setWordWrap(True)
            settings_lay.addWidget(lbl)
        lay.addWidget(settings_box)

        btn_row = QHBoxLayout()
        btn_close = QPushButton("닫기")
        btn_close.setMinimumWidth(80)
        btn_close.clicked.connect(self.accept)
        btn_row.addStretch(1)
        btn_row.addWidget(btn_close)
        lay.addLayout(btn_row)


class ScheduleListDialog(QDialog):
    def __init__(self, manager: ScheduleManager, on_run_now: Callable, parent=None):
        super().__init__(parent)
        self._manager = manager
        self._on_run_now = on_run_now
        self.setWindowTitle("예약 수집 관리")
        self.resize(1000, 500)
        lay = QVBoxLayout(self)

        lbl = QLabel("예약된 수집 목록입니다. 활성 토글로 켜고 끌 수 있습니다.")
        lbl.setStyleSheet("color:#6b7280; font-size:12px;")
        lay.addWidget(lbl)

        self._table = QTableWidget(0, 9)
        self._table.setHorizontalHeaderLabels(
            ["이름", "사이트", "시간", "요일", "마지막 실행", "활성", "지금 실행", "상세", "삭제"]
        )
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col, w in enumerate([None, 75, 65, 175, 105, 50, 70, 55, 55], start=1):
            if w:
                self._table.setColumnWidth(col, w)
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        lay.addWidget(self._table)

        btn_row = QHBoxLayout()
        btn_close = QPushButton("닫기")
        btn_close.clicked.connect(self.accept)
        btn_row.addStretch(1)
        btn_row.addWidget(btn_close)
        lay.addLayout(btn_row)

        self._refresh()

    def _refresh(self):
        self._table.setRowCount(0)
        for job in self._manager.get_all():
            r = self._table.rowCount()
            self._table.insertRow(r)

            self._table.setItem(r, 0, QTableWidgetItem(job.name))
            self._table.setItem(r, 1, QTableWidgetItem(SITE_LABELS.get(job.site, job.site)))
            self._table.setItem(r, 2, QTableWidgetItem(job.schedule_time))

            days_str = "매일" if "daily" in job.days else " ".join(DAY_LABELS.get(d, d) for d in job.days)
            self._table.setItem(r, 3, QTableWidgetItem(days_str))
            self._table.setItem(r, 4, QTableWidgetItem(job.last_run_date or "없음"))

            # 활성 토글
            chk = QCheckBox()
            chk.setChecked(job.enabled)
            chk_w = _centered_widget(chk)
            job_id = job.id
            chk.toggled.connect(lambda checked, jid=job_id: self._toggle_enabled(jid, checked))
            self._table.setCellWidget(r, 5, chk_w)

            # 지금 실행
            btn_run = QPushButton("실행")
            btn_run.setFixedHeight(26)
            btn_run.clicked.connect(lambda _, jid=job_id: self._run_now(jid))
            self._table.setCellWidget(r, 6, _centered_widget(btn_run))

            # 상세보기
            btn_detail = QPushButton("상세")
            btn_detail.setFixedHeight(26)
            btn_detail.clicked.connect(lambda _, j=job: self._show_detail(j))
            self._table.setCellWidget(r, 7, _centered_widget(btn_detail))

            # 삭제
            btn_del = QPushButton("삭제")
            btn_del.setFixedHeight(26)
            btn_del.clicked.connect(lambda _, jid=job_id: self._delete_job(jid))
            self._table.setCellWidget(r, 8, _centered_widget(btn_del))

    def _toggle_enabled(self, job_id: str, enabled: bool):
        for job in self._manager.get_all():
            if job.id == job_id:
                job.enabled = enabled
                self._manager.update(job)
                return

    def _run_now(self, job_id: str):
        self._on_run_now(job_id)
        self.accept()

    def _show_detail(self, job: ScheduledJob):
        dlg = ScheduleDetailDialog(job, self)
        dlg.exec()

    def _delete_job(self, job_id: str):
        reply = QMessageBox.question(
            self, "삭제 확인", "이 예약을 삭제하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._manager.remove(job_id)
            self._refresh()


def _centered_widget(child: QWidget) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.addWidget(child)
    lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lay.setContentsMargins(2, 2, 2, 2)
    return w
