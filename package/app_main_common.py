"""
app_v1_main / app_v1_site_main / app_v2_main 에서 공통으로 쓰는 유틸·위젯.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from typing import Any, List, Optional

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QIntValidator,
    QPainter,
    QPen,
    QStandardItem,
    QStandardItemModel,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


def parse_keywords_csv(raw: str) -> List[str]:
    return [x.strip() for x in str(raw or "").split(",") if x.strip()]


def contains_any_keyword(text: Any, keywords: List[str]) -> bool:
    """키워드 중 하나라도 본문에 있으면 True (OR). 영문 대소문자는 무시한다 (lh == LH)."""
    if not keywords:
        return True
    t = str(text or "").lower()
    return any(str(k).lower() in t for k in keywords if str(k).strip())


def parse_saved_output_path_from_finish_message(msg: str) -> Optional[str]:
    """Worker finished 메시지에서 저장된 파일 경로 추출. (저장 완료|중단 저장 완료): path (N건) 형식."""
    s = str(msg or "").strip()
    if "저장 완료" not in s and "중단 저장 완료" not in s:
        return None
    m = re.match(
        r"^(?:중단 저장 완료|저장 완료)\s*:\s*(.+)\s+\(\d+건\)\s*$",
        s,
    )
    if not m:
        return None
    path = os.path.normpath(m.group(1).strip().strip('"'))
    return path if os.path.isfile(path) else None


def open_path_in_os(path: str) -> None:
    """파일을 OS 기본 연결 프로그램으로 연다."""
    p = os.path.abspath(os.path.expanduser(str(path)))
    if not os.path.isfile(p):
        raise FileNotFoundError(p)
    if sys.platform == "win32":
        os.startfile(p)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.run(["open", p], check=False)
    else:
        subprocess.run(["xdg-open", p], check=False)


def parse_date_ymd(text: Any):
    s = str(text or "").strip()
    if not s:
        return None
    m = re.search(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", s)
    if not m:
        return None
    try:
        from datetime import date

        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except Exception:
        return None


def description_text_from_naver_row(row: Any, *, naver_row_has_hosu_column: bool = False) -> str:
    """네이버 extract_detail_v2 행에서 상세 텍스트 필터용 문자열(간략설명+설명)을 만든다.
    naver_row_has_hosu_column=True: 호수가 인덱스 11에 삽입된 행(기본 60열 + 호수 = 61열 이상이면 간략/설명 인덱스 43,44).
    """
    if isinstance(row, (list, tuple)):
        if naver_row_has_hosu_column:
            if len(row) >= 61:
                a = str(row[43]) if len(row) > 43 else ""
                b = str(row[44]) if len(row) > 44 else ""
            else:
                a = str(row[42]) if len(row) > 42 else ""
                b = str(row[43]) if len(row) > 43 else ""
        else:
            a = str(row[42]) if len(row) > 42 else ""
            b = str(row[43]) if len(row) > 43 else ""
        return "\n".join(x for x in (a, b) if x)
    if isinstance(row, dict):
        a = str(row.get("간략설명", "") or "")
        b = str(row.get("설명", "") or "")
        return "\n".join(x for x in (a, b) if x)
    return ""


class RangeInput(QWidget):
    """숫자 직접 입력식 범위 필터 (최소 ~ 최대).

    - 최소값 빈칸 = 0, 최대값 빈칸 = 제한없음.
    - unit_toggle=(다른단위, 배율)을 주면 단위 변환 버튼이 생긴다.
      배율은 "기본단위 → 다른단위" 곱셈 계수이며 values()는 항상 기본단위로 반환.
    - DualSlider와 동일하게 values() -> (lo, hi), set_enabled() 인터페이스 제공.
    """

    OPEN_MAX = 10**9

    def __init__(
        self,
        title: str,
        unit: str = "",
        default_min_text: str = "",
        unit_toggle: Optional[tuple] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setObjectName("rangeCard")
        self._base_unit = unit
        self._alt = unit_toggle  # (다른단위, 배율) 또는 None
        self._in_alt = False
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(6)
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("font-weight:600;")
        self.title_label.setFixedWidth(80)  # 라벨 폭 통일 → 입력칸 세로 정렬 맞춤
        self.edt_min = QLineEdit()
        self.edt_max = QLineEdit()
        for e in (self.edt_min, self.edt_max):
            e.setValidator(QIntValidator(0, 2_000_000_000, self))
            e.setFixedWidth(96)
            e.setAlignment(Qt.AlignRight)
        self.edt_min.setPlaceholderText("0")
        self.edt_max.setPlaceholderText("제한없음")
        if default_min_text:
            self.edt_min.setText(str(default_min_text))
        self.sep_label = QLabel("~")
        self.unit_label = QLabel(unit)
        self.unit_label.setStyleSheet("color:#64748b;")
        row.addWidget(self.title_label)
        row.addWidget(self.edt_min)
        row.addWidget(self.sep_label)
        row.addWidget(self.edt_max)
        row.addWidget(self.unit_label)
        self.btn_unit: Optional[QPushButton] = None
        if self._alt:
            self.btn_unit = QPushButton(f"{self._alt[0]}로 보기")
            self.btn_unit.setObjectName("rangeResetBtn")
            self.btn_unit.clicked.connect(self._toggle_unit)
            row.addWidget(self.btn_unit)
        row.addStretch(1)

    @staticmethod
    def _num(edit: QLineEdit) -> Optional[int]:
        t = edit.text().strip().replace(",", "")
        if not t:
            return None
        try:
            return int(t)
        except ValueError:
            return None

    def values(self) -> tuple:
        lo = self._num(self.edt_min) or 0
        hi = self._num(self.edt_max)
        hi = self.OPEN_MAX if hi is None else hi
        if self._alt and self._in_alt:  # 변환 단위로 입력 중이면 기본단위로 환산
            factor = self._alt[1]
            lo = int(round(lo / factor))
            if hi != self.OPEN_MAX:
                hi = int(round(hi / factor))
        if lo > hi:
            lo, hi = hi, lo
        return lo, hi

    def _toggle_unit(self):
        alt_unit, factor = self._alt
        conv = (lambda v: v * factor) if not self._in_alt else (lambda v: v / factor)
        for e in (self.edt_min, self.edt_max):
            v = self._num(e)
            if v is not None:
                e.setText(str(int(round(conv(v)))))
        self._in_alt = not self._in_alt
        self.unit_label.setText(alt_unit if self._in_alt else self._base_unit)
        self.btn_unit.setText(
            f"{self._base_unit}로 보기" if self._in_alt else f"{alt_unit}로 보기"
        )

    def set_enabled(self, enabled: bool):
        for w in (self.title_label, self.edt_min, self.edt_max, self.sep_label, self.unit_label):
            w.setEnabled(enabled)
        if self.btn_unit is not None:
            self.btn_unit.setEnabled(enabled)


class MultiSelectCombo(QComboBox):
    """체크박스로 여러 항목을 동시에 선택할 수 있는 콤보박스.

    - 첫 항목은 항상 "전체". 전체를 체크하면 나머지가 해제되고,
      개별 항목을 체크하면 전체가 해제된다. 아무것도 선택하지 않은 상태는 "전체"로 유지.
    - 각 항목은 (표시 라벨, 내부 데이터) 쌍으로 등록한다.
    - checked_data(): 체크된 항목들의 내부 데이터 목록. 빈 목록이면 "전체"를 뜻한다.
    """

    selection_changed = Signal()
    ALL_LABEL = "전체"

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setEditable(True)
        self.lineEdit().setReadOnly(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.setModel(QStandardItemModel(self))
        self.view().viewport().installEventFilter(self)
        self.lineEdit().installEventFilter(self)
        self._updating = False
        self.model().itemChanged.connect(self._on_item_changed)
        self.set_entries([])

    # ── 항목 관리 ────────────────────────────────────────────────
    def set_entries(self, entries: List[tuple]) -> None:
        """entries: [(label, data), ...]. 기존 선택은 초기화("전체")된다."""
        self._updating = True
        m: QStandardItemModel = self.model()
        m.clear()
        all_item = QStandardItem(self.ALL_LABEL)
        all_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
        all_item.setData(None, Qt.UserRole)
        all_item.setCheckState(Qt.Checked)
        m.appendRow(all_item)
        for label, data in entries:
            it = QStandardItem(str(label))
            it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Unchecked)
            it.setData(data, Qt.UserRole)
            m.appendRow(it)
        self._updating = False
        self._sync_text()
        self.selection_changed.emit()

    def set_checked_labels(self, labels: List[str]) -> None:
        """라벨 목록으로 체크 상태 지정 (없는 라벨은 무시)."""
        want = set(labels or [])
        self._updating = True
        m: QStandardItemModel = self.model()
        any_checked = False
        for r in range(1, m.rowCount()):
            it = m.item(r)
            on = it.text() in want
            it.setCheckState(Qt.Checked if on else Qt.Unchecked)
            any_checked = any_checked or on
        m.item(0).setCheckState(Qt.Unchecked if any_checked else Qt.Checked)
        self._updating = False
        self._sync_text()
        self.selection_changed.emit()

    # ── 선택 상태 조회 ───────────────────────────────────────────
    def checked_labels(self) -> List[str]:
        m: QStandardItemModel = self.model()
        return [
            m.item(r).text()
            for r in range(1, m.rowCount())
            if m.item(r).checkState() == Qt.Checked
        ]

    def checked_data(self) -> List[Any]:
        m: QStandardItemModel = self.model()
        return [
            m.item(r).data(Qt.UserRole)
            for r in range(1, m.rowCount())
            if m.item(r).checkState() == Qt.Checked
        ]

    def is_all(self) -> bool:
        return not self.checked_labels()

    # ── 내부 동작 ───────────────────────────────────────────────
    def _on_item_changed(self, item: QStandardItem) -> None:
        if self._updating:
            return
        self._updating = True
        m: QStandardItemModel = self.model()
        if item.row() == 0:
            if item.checkState() == Qt.Checked:
                for r in range(1, m.rowCount()):
                    m.item(r).setCheckState(Qt.Unchecked)
            elif not any(
                m.item(r).checkState() == Qt.Checked for r in range(1, m.rowCount())
            ):
                item.setCheckState(Qt.Checked)  # 전체 해제 불가(빈 선택 방지)
        else:
            if item.checkState() == Qt.Checked:
                m.item(0).setCheckState(Qt.Unchecked)
            elif not any(
                m.item(r).checkState() == Qt.Checked for r in range(1, m.rowCount())
            ):
                m.item(0).setCheckState(Qt.Checked)
        self._updating = False
        self._sync_text()
        self.selection_changed.emit()

    def _sync_text(self) -> None:
        labels = self.checked_labels()
        if not labels:
            text = self.ALL_LABEL
        elif len(labels) <= 2:
            text = ", ".join(labels)
        else:
            text = f"{labels[0]} 외 {len(labels) - 1}곳"
        self.lineEdit().setText(text)
        self.lineEdit().setCursorPosition(0)

    def eventFilter(self, obj, ev):
        # 팝업 안에서 클릭 시 체크만 토글하고 팝업은 닫지 않는다.
        if obj is self.view().viewport() and ev.type() == QEvent.MouseButtonRelease:
            idx = self.view().indexAt(ev.position().toPoint())
            it = self.model().itemFromIndex(idx)
            if it is not None:
                it.setCheckState(
                    Qt.Unchecked if it.checkState() == Qt.Checked else Qt.Checked
                )
            return True
        # 읽기전용 입력칸 클릭으로도 팝업 열기
        if obj is self.lineEdit() and ev.type() == QEvent.MouseButtonRelease:
            self.showPopup()
            return True
        return super().eventFilter(obj, ev)


def wrap_in_scroll(inner: QWidget) -> QScrollArea:
    """탭/섹션 콘텐츠를 세로 스크롤 영역으로 감싼다.

    창이 작아 아래쪽 섹션(가격/면적/등록일 등)이 잘리면 스크롤로 볼 수 있게 한다.
    setWidgetResizable(True) 라 가로 폭은 뷰포트에 맞춰지고 세로 스크롤만 필요 시 생긴다.
    """
    sa = QScrollArea()
    sa.setObjectName("sectionScroll")
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.NoFrame)
    sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    sa.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    sa.setWidget(inner)
    # 스크롤 영역/뷰포트 배경을 투명하게 두어 탭 pane 배경이 그대로 보이게 한다.
    sa.setStyleSheet(
        "#sectionScroll, #sectionScroll > QWidget > QWidget { background: transparent; }"
    )
    return sa


class _RangeBar(QWidget):
    """points 인덱스에 스냅되는 2-핸들 드래그 슬라이더 (커스텀 페인팅)."""

    MARGIN_X = 16
    TRACK_Y = 34
    TRACK_H = 8
    HANDLE_R = 9

    def __init__(self, n_points: int, label_fn, on_change, parent: QWidget | None = None):
        super().__init__(parent)
        self._n = max(1, n_points)
        self._label_fn = label_fn
        self._on_change = on_change
        self._lo = 0
        self._hi = self._n - 1
        self._active: Optional[str] = None
        self._hover: Optional[str] = None
        self._enabled = True
        self.setMinimumHeight(52)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)

    # --- 좌표 <-> 인덱스 변환 ---
    def _usable(self) -> float:
        return max(1.0, self.width() - 2 * self.MARGIN_X)

    def _x_of(self, idx: int) -> float:
        if self._n <= 1:
            return float(self.MARGIN_X)
        return self.MARGIN_X + self._usable() * (idx / (self._n - 1))

    def _idx_of(self, x: float) -> int:
        if self._n <= 1:
            return 0
        r = (x - self.MARGIN_X) / self._usable()
        return max(0, min(self._n - 1, round(r * (self._n - 1))))

    def _handle_at(self, x: float) -> str:
        d_lo = abs(x - self._x_of(self._lo))
        d_hi = abs(x - self._x_of(self._hi))
        if abs(d_lo - d_hi) < 1.0:
            return "lo" if x <= self._x_of(self._lo) else "hi"
        return "lo" if d_lo < d_hi else "hi"

    # --- 상태 변경 ---
    def set_range(self, lo: int, hi: int):
        self._lo = max(0, min(self._n - 1, lo))
        self._hi = max(0, min(self._n - 1, hi))
        if self._lo > self._hi:
            self._lo, self._hi = self._hi, self._lo
        self.update()
        if self._on_change:
            self._on_change()

    def set_bar_enabled(self, enabled: bool):
        self._enabled = enabled
        self.setCursor(Qt.PointingHandCursor if enabled else Qt.ArrowCursor)
        self.update()

    def _move_active_to(self, x: float):
        idx = self._idx_of(x)
        if self._active == "lo":
            self._lo = min(idx, self._hi)
        elif self._active == "hi":
            self._hi = max(idx, self._lo)
        self.update()
        if self._on_change:
            self._on_change()

    # --- 마우스 ---
    def mousePressEvent(self, e):
        if not self._enabled:
            return
        x = e.position().x()
        self._active = self._handle_at(x)
        self._move_active_to(x)

    def mouseMoveEvent(self, e):
        x = e.position().x()
        if self._active and self._enabled:
            self._move_active_to(x)
            return
        h = self._handle_at(x) if self._enabled else None
        if h != self._hover:
            self._hover = h
            self.update()

    def mouseReleaseEvent(self, e):
        self._active = None

    def leaveEvent(self, e):
        if self._hover is not None:
            self._hover = None
            self.update()

    # --- 페인팅 ---
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        x0 = self._x_of(0)
        x1 = self._x_of(self._n - 1)
        x_lo = self._x_of(self._lo)
        x_hi = self._x_of(self._hi)
        ty = self.TRACK_Y
        th = self.TRACK_H

        groove = QColor("#dbe3ef") if self._enabled else QColor("#e6ebf2")
        fill = QColor("#5ba0e7") if self._enabled else QColor("#c3d5ea")
        handle = QColor("#4f46e5") if self._enabled else QColor("#b7bce8")

        # 전체 트랙
        p.setPen(Qt.NoPen)
        p.setBrush(groove)
        p.drawRoundedRect(x0, ty - th / 2, x1 - x0, th, th / 2, th / 2)
        # 선택 구간
        p.setBrush(fill)
        p.drawRoundedRect(x_lo, ty - th / 2, max(1.0, x_hi - x_lo), th, th / 2, th / 2)

        # 핸들 위 값 라벨
        font = QFont(self.font())
        font.setBold(True)
        font.setPointSizeF(max(8.0, font.pointSizeF() - 0.5))
        p.setFont(font)
        fm = QFontMetrics(font)
        label_color = QColor("#1f3b5b") if self._enabled else QColor("#94a3b8")

        for idx, x in ((self._lo, x_lo), (self._hi, x_hi)):
            txt = self._label_fn(idx)
            tw = fm.horizontalAdvance(txt)
            tx = min(max(x - tw / 2, 2), self.width() - tw - 2)
            p.setPen(label_color)
            p.drawText(int(tx), 16, txt)

        # 핸들
        for x in (x_lo, x_hi):
            r = self.HANDLE_R
            p.setPen(QPen(QColor("#eef2ff"), 2))
            p.setBrush(handle)
            p.drawEllipse(int(x - r), int(ty - r), int(2 * r), int(2 * r))
        p.end()


class DualSlider(QWidget):
    # 상단 핸들이 맨 우측(마지막 눈금)일 때 values()의 상한으로 쓰는 값 = 상방 무제한.
    # 모든 슬라이더의 max_value보다 크므로 크롤러/필터에서 사실상 '제한 없음'으로 동작한다.
    OPEN_MAX = 10 ** 9

    def __init__(self, title: str, min_value: int, max_value: int, step: int = 1, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("sliderCard")
        self.title_text = title
        self.min_value = min_value
        self.max_value = max_value
        self.step = max(1, step)
        self.points = self._build_points(title, min_value, max_value, self.step)
        self._is_money = ("만" in title) or ("매매" in title) or ("보증금" in title) or ("전세" in title) or ("기준가" in title) or ("월세" in title)
        self._is_year = "년도" in title

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(6)

        row = QHBoxLayout()
        self.title_label = QLabel(title)
        self.value_label = QLabel()
        self.value_label.setStyleSheet("color:#64748b;")
        self.btn_reset = QPushButton("초기화")
        self.btn_reset.setObjectName("rangeResetBtn")
        self.btn_reset.clicked.connect(self._reset)
        row.addWidget(self.title_label)
        row.addStretch(1)
        row.addWidget(self.value_label)
        row.addWidget(self.btn_reset)
        root.addLayout(row)

        self.bar = _RangeBar(len(self.points), self._handle_text, self._on_bar_change)
        root.addWidget(self.bar)
        self._sync_ui()

    def _fmt_val(self, v: int) -> str:
        if self._is_year:
            return str(v)
        return self._format_unit(v, self._is_money)

    def _handle_text(self, idx: int) -> str:
        idx = max(0, min(len(self.points) - 1, idx))
        txt = self._fmt_val(self.points[idx])
        # 맨 우측 눈금은 '이상'(상방 무제한)을 뜻하므로 '+'를 붙인다.
        if idx == len(self.points) - 1 and len(self.points) > 1:
            txt = f"{txt}+"
        return txt

    def _on_bar_change(self):
        self._sync_ui()

    def _build_points(self, title: str, min_value: int, max_value: int, step: int) -> List[int]:
        t = title.replace(" ", "")
        if "월세" in t:
            base = [min_value, 20, 30, 40, 50, 60, 70, 80, 90, 100, 200, 300, 400, 500, 1000, 2000, 3000]
        elif "보증금" in t:
            base = [min_value, 1000, 2000, 3000, 4000, 5000, 6000, 7000, 8000, 9000, 10000, 20000, 30000, 40000, 50000]
        elif "매매" in t or "전세" in t or "기준가" in t:
            base = [min_value, 5000, 10000, 20000, 30000, 40000, 50000, 60000, 70000, 80000, 90000, 100000, 200000, 300000, 400000, 500000, 1000000]
        elif "면적" in t or "평수" in t:
            base = [min_value, 10, 20, 30, 50, 70, 100, 150, 200, 231, 500]
        else:
            base = list(range(min_value, max_value + 1, step))

        pts = sorted(set([x for x in base if min_value <= x <= max_value] + [min_value, max_value]))
        return pts

    @staticmethod
    def _format_unit(v: int, is_money: bool) -> str:
        if not is_money:
            return f"{v:,}"
        if v >= 10000:
            if v % 10000 == 0:
                return f"{v // 10000}억"
            return f"{v:,}"
        if v >= 1000 and v % 1000 == 0:
            return f"{v // 1000}천"
        if v >= 100 and v % 100 == 0:
            return f"{v // 100}백"
        return f"{v:,}"

    def _reset(self):
        self.bar.set_range(0, len(self.points) - 1)
        self._sync_ui()

    def _sync_ui(self):
        last = len(self.points) - 1
        lo_idx, hi_idx = self.bar._lo, self.bar._hi
        open_hi = hi_idx >= last  # 맨 우측 = 상방 무제한
        lo_txt = self._fmt_val(self.points[lo_idx])
        hi_txt = self._fmt_val(self.points[hi_idx])
        if lo_idx <= 0 and open_hi:
            text = "전체"
        elif open_hi:
            text = f"{lo_txt} 이상"
        elif lo_idx <= 0:
            text = f"~{hi_txt}"
        else:
            text = f"{lo_txt} ~ {hi_txt}"
        self.value_label.setText(text)

    def values(self) -> tuple[int, int]:
        """(하한, 상한). 상단 핸들이 맨 우측이면 상한은 OPEN_MAX(상방 무제한)."""
        lo = self.points[self.bar._lo]
        if self.bar._hi >= len(self.points) - 1:
            return lo, self.OPEN_MAX
        return lo, self.points[self.bar._hi]

    def set_enabled(self, enabled: bool):
        self.title_label.setEnabled(enabled)
        self.value_label.setEnabled(enabled)
        self.btn_reset.setEnabled(enabled)
        self.bar.set_bar_enabled(enabled)


# 건축물용도 다중선택 옵션 (데이터 값에 부분일치로 매칭)
# 건축물용도 선택지. 당근(realty.daangn.com buildingUsage 한글 라벨)과 네이버(buildingUse 문자열) 값을
# 공백/구분자 제거 후 부분일치로 비교하므로 "제2종 근린생활시설"도 "제2종근린생활시설"에 걸린다.
BUILDING_USE_OPTIONS = [
    "단독주택", "공동주택", "다가구주택", "다세대주택", "연립주택", "아파트",
    "오피스텔", "제1종근린생활시설", "제2종근린생활시설", "업무시설", "판매시설", "숙박시설",
    "의료시설", "교육연구시설", "노유자시설", "문화및집회시설", "종교시설", "운동시설",
    "위락시설", "공장", "창고시설", "자동차관련시설", "동물및식물관련시설", "운수시설",
]


def _leading_int(s: Any) -> Optional[int]:
    """문자열에서 맨 앞 정수를 뽑는다. 예: '3/2' -> 3, '5개' -> 5."""
    m = re.search(r"\d+", str(s or "").replace(",", ""))
    return int(m.group()) if m else None


def _year4(s: Any) -> Optional[int]:
    """문자열에서 4자리 연도를 뽑는다. 예: '2001.05.20' -> 2001."""
    m = re.search(r"(19|20)\d{2}", str(s or ""))
    return int(m.group()) if m else None


class DetailFilters:
    """방수/층수/준공년도/건축물용도 후처리 필터.

    - rooms/floors/years: (min, max) 튜플 또는 None(미적용)
    - uses: 선택된 건축물용도 라벨 리스트 (빈 리스트=미적용)
    모든 필드는 데이터 값이 비어 있으면 관대하게 통과한다(알 수 있는 값만 걸러냄).
    건축물용도는 값이 있으면 선택 라벨과 부분일치해야 통과.
    """

    def __init__(self, rooms=None, floors=None, years=None, uses=None):
        self.rooms = rooms
        self.floors = floors
        self.years = years
        self.uses = [str(u) for u in (uses or []) if str(u).strip()]

    @property
    def active(self) -> bool:
        return bool(self.rooms or self.floors or self.years or self.uses)

    @staticmethod
    def _num_ok(bound, s) -> bool:
        if not bound:
            return True
        v = _leading_int(s)
        if v is None:
            return True
        lo, hi = bound
        return lo <= v <= hi

    def _year_ok(self, s) -> bool:
        if not self.years:
            return True
        y = _year4(s)
        if y is None:
            return True
        lo, hi = self.years
        return lo <= y <= hi

    def _use_ok(self, s) -> bool:
        if not self.uses:
            return True
        val = re.sub(r"[\s/·,()\[\]]", "", str(s or ""))
        if not val:
            return True  # 용도 값이 없으면 관대하게 통과(당근 목록에 값이 비는 경우 대비)
        for u in self.uses:
            uu = re.sub(r"[\s/·,()\[\]]", "", u)
            if uu and (uu in val or val in uu):
                return True
        return False

    def _floor_ok(self, s) -> bool:
        """층수 필터. 반지하/지하(B1 등)는 0층으로 취급한다."""
        if not self.floors:
            return True
        t = str(s or "")
        if "반지하" in t or "지하" in t or t.strip().upper().startswith("B"):
            v = 0
        else:
            v = _leading_int(t)
        if v is None:
            return True
        lo, hi = self.floors
        return lo <= v <= hi

    def passes(self, *, rooms: str = "", floor: str = "", approve: str = "", use: str = "") -> bool:
        return (
            self._num_ok(self.rooms, rooms)
            and self._floor_ok(floor)
            and self._year_ok(approve)
            and self._use_ok(use)
        )


def naver_detail_values(row: Any, has_hosu: bool = False) -> tuple[str, str, str, str]:
    """네이버 상세 행에서 (방수, 해당층, 사용승인일, 건축물용도) 문자열을 뽑는다.

    has_hosu=True: '호수' 컬럼이 인덱스 11에 삽입된 레이아웃(app_v2)이라 11 이후 인덱스가 +1 밀린다.
    """
    shift = 1 if has_hosu else 0

    def _get(i: int) -> str:
        j = i + shift if i >= 11 else i
        if isinstance(row, (list, tuple)) and len(row) > j and row[j] is not None:
            return str(row[j]).strip()
        return ""
    # 기본 인덱스: 34 방수, 17 해당층, 49 사용승인일, 39 건축물용도
    return _get(34), _get(17), _get(49), _get(39)


def _dict_find(item: dict, includes, excludes=()) -> str:
    """dict에서 키가 includes 문자열을 모두 포함하고 excludes는 포함하지 않는 첫 값(문자열)을 반환."""
    for k, v in item.items():
        ks = str(k)
        if all(i in ks for i in includes) and not any(e in ks for e in excludes):
            sv = str(v).strip()
            if sv:
                return sv
    return ""


def daangn_detail_values(item: Any) -> tuple[str, str, str, str]:
    """당근 매물 dict에서 (방수, 층수, 사용승인일, 건축물용도) 문자열을 best-effort로 뽑는다.

    당근 상세 라벨(dt/dd)이 그대로 키가 되므로 유동적 → 부분 키매칭 사용.
    """
    if not isinstance(item, dict):
        return "", "", "", ""
    rooms = _dict_find(item, ["방"], excludes=["방향", "방문"])
    floor = _dict_find(item, ["층"])
    approve = _dict_find(item, ["사용승인"]) or _dict_find(item, ["준공"])
    use = _dict_find(item, ["건축물용도"]) or _dict_find(item, ["용도"], excludes=["용도지역"])
    return rooms, floor, approve, use


class UseCheckGroup(QGroupBox):
    """건축물용도 다중선택 체크박스 그룹. selected()로 체크된 라벨 리스트 반환."""

    def __init__(self, title: str = "건축물용도", options: Optional[List[str]] = None, columns: int = 4, parent: QWidget | None = None):
        super().__init__(title, parent)
        self._checks: dict[str, QCheckBox] = {}
        opts = options if options is not None else BUILDING_USE_OPTIONS
        grid = QGridLayout(self)
        grid.setContentsMargins(12, 14, 12, 12)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        for i, name in enumerate(opts):
            cb = QCheckBox(name)
            self._checks[name] = cb
            grid.addWidget(cb, i // columns, i % columns)

    def selected(self) -> List[str]:
        return [n for n, cb in self._checks.items() if cb.isChecked()]

    def set_selected(self, names: List[str]) -> None:
        wanted = set(names or [])
        for n, cb in self._checks.items():
            cb.setChecked(n in wanted)

    def set_enabled(self, enabled: bool) -> None:
        for cb in self._checks.values():
            cb.setEnabled(enabled)


__all__ = [
    "BUILDING_USE_OPTIONS",
    "DetailFilters",
    "DualSlider",
    "MultiSelectCombo",
    "RangeInput",
    "UseCheckGroup",
    "daangn_detail_values",
    "naver_detail_values",
    "contains_any_keyword",
    "description_text_from_naver_row",
    "open_path_in_os",
    "parse_date_ymd",
    "parse_keywords_csv",
    "parse_saved_output_path_from_finish_message",
    "wrap_in_scroll",
]
