"""
v1 site 메인 GUI·크롤러 (엔트리/인증 제외)
"""
from __future__ import annotations

import json
import os
import random
import re
import sys
import time
from urllib.parse import parse_qs, urlparse
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

from PySide6.QtCore import QDate, QObject, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QFont, QIcon
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
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSlider,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from daangn_realty_crawler import DaangnRealtyCrawler
from peterpan_crawler import PeterpanCrawler
from onhouse_crawler import OnhouseCrawler
from naver_crawler import NaverCrawler
from app_main_common import (
    DetailFilters,
    DualSlider,
    MultiSelectCombo,
    RangeInput,
    UseCheckGroup,
    contains_any_keyword as _contains_any_keyword,
    daangn_detail_values,
    description_text_from_naver_row,
    naver_detail_values,
    open_path_in_os,
    parse_date_ymd as _parse_date_ymd,
    parse_keywords_csv as _parse_keywords_csv,
    parse_saved_output_path_from_finish_message,
    wrap_in_scroll,
)
from schedule_mixin import ScheduleMixin

class DaangnWorker(QObject):
    progress = Signal(int, int)
    row_ready = Signal(tuple)
    status = Signal(str)
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, params: Dict[str, Any]):
        super().__init__()
        self.params = params
        self._cancel = False

    def cancel(self):
        self._cancel = True

    @Slot()
    def run(self):
        try:
            crawler = DaangnRealtyCrawler()
            region_names = self.params["regions"]
            keywords = self.params.get("detail_keywords", [])
            detail_filters = DetailFilters(
                rooms=self.params.get("detail_rooms"),
                floors=self.params.get("detail_floors"),
                years=self.params.get("detail_years"),
                uses=self.params.get("detail_uses"),
            )

            def _matched(item: Any) -> bool:
                if not isinstance(item, dict):
                    return False
                if not _contains_any_keyword(item.get("상세_내용", ""), keywords):
                    return False
                if detail_filters.active:
                    rooms, floor, approve, use = daangn_detail_values(item)
                    if not detail_filters.passes(rooms=rooms, floor=floor, approve=approve, use=use):
                        return False
                return True

            total = len(region_names)
            if total == 0:
                self.finished.emit("선택된 지역이 없습니다.")
                return
            all_results: List[Dict[str, Any]] = []
            stopped = False
            processed = 0
            for idx, region_name in enumerate(region_names, 1):
                if self._cancel:
                    stopped = True
                    break
                self.status.emit(f"[{idx}/{total}] {region_name}")
                in_ = self.params["regions_name_to_incode"].get(region_name)
                if not in_:
                    processed = idx
                    self.progress.emit(processed, total)
                    continue
                try:
                    rows = crawler.crawl_realty(
                        in_=in_,
                        region_name=region_name,
                        monthly_pay_min=self.params["monthly_min"],
                        monthly_pay_max=self.params["monthly_max"],
                        month_price_min=self.params["deposit_min"],
                        month_price_max=self.params["deposit_max"],
                        borrow_price_min=self.params["borrow_min"],
                        borrow_price_max=self.params["borrow_max"],
                        buy_price_min=self.params["buy_min"],
                        buy_price_max=self.params["buy_max"],
                        area_min=self.params["area_min"],
                        area_max=self.params["area_max"],
                        sales_type=self.params["sales_type"],
                        trade_type=self.params["trade_type"],
                        return_results_only=True,
                        date_start=self.params["date_start"],
                        date_end=self.params["date_end"],
                        on_item=lambda item: self.row_ready.emit(MainWindow.item_to_display_row(item)) if _matched(item) else None,
                        is_cancelled=lambda: self._cancel,
                        writer_types=self.params.get("writer_types"),
                    )
                    if isinstance(rows, list):
                        all_results.extend([r for r in rows if _matched(r)])
                except Exception as e:
                    print(f"[당근] 지역 처리 실패: {region_name} - {e}")
                    self.status.emit(f"[{idx}/{total}] {region_name} 실패(건너뜀): {e}")
                    pass
                finally:
                    processed = idx
                    self.progress.emit(processed, total)
                # time.sleep(random.uniform(0.7, 1.2))
            if all_results:
                ts = self.params.get("timestamp", datetime.now().strftime("%y%m%d_%H%M%S"))
                out_dir = self.params.get("out_dir", os.getcwd())
                schedule_name = self.params.get("schedule_name")
                if schedule_name:
                    out = os.path.join(out_dir, f"{schedule_name}_{len(all_results)}건_{ts}.xlsx")
                else:
                    site = self.params.get("site_name", "사이트")
                    region = self.params.get("region_for_file", "전체_전체_전체")
                    out = os.path.join(out_dir, f"{site}_{region}_{len(all_results)}건_{ts}.xlsx")
                crawler._save_to_excel(all_results, filepath=out)
                prefix = "중단 저장 완료" if stopped else "저장 완료"
                self.finished.emit(f"{prefix}: {out} ({len(all_results)}건)")
            else:
                self.finished.emit("중단됨 (저장할 데이터 없음)" if stopped else "수집된 매물이 없습니다.")
        except Exception as e:
            self.failed.emit(str(e))


class PeterpanWorker(QObject):
    progress = Signal(int, int)
    row_ready = Signal(tuple)
    status = Signal(str)
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, params: Dict[str, Any]):
        super().__init__()
        self.params = params
        self._cancel = False

    def cancel(self):
        self._cancel = True

    @Slot()
    def run(self):
        try:
            crawler = PeterpanCrawler()
            region_names = self.params["regions"]
            keywords = self.params.get("detail_keywords", [])
            date_start = _parse_date_ymd(self.params.get("registered_date_start"))
            date_end = _parse_date_ymd(self.params.get("registered_date_end"))
            if not region_names:
                self.finished.emit("선택된 지역이 없습니다.")
                return

            all_rows: List[Dict[str, Any]] = []
            seen = set()
            total = len(region_names)
            stopped = False
            for idx, region_name in enumerate(region_names, 1):
                if self._cancel:
                    stopped = True
                    break
                self.status.emit(f"[{idx}/{total}] {region_name} 검색 중")
                bbox = self.params.get("regions_bbox", {}).get(region_name)
                if not bbox:
                    self.progress.emit(idx, total)
                    continue
                page_no = 0
                for page_ids in crawler.iter_search_page_ids(
                    query=region_name,
                    building_type=self.params.get("building_type", ""),
                    page_size=50,
                    latitude_min=bbox.get("lat_min"),
                    latitude_max=bbox.get("lat_max"),
                    longitude_min=bbox.get("lon_min"),
                    longitude_max=bbox.get("lon_max"),
                    check_deposit_min=self.params.get("deposit_min"),
                    check_deposit_max=self.params.get("deposit_max"),
                    check_month_min=self.params.get("month_min"),
                    check_month_max=self.params.get("month_max"),
                    check_real_size_min=self.params.get("size_min"),
                    check_real_size_max=self.params.get("size_max"),
                    check_price_min=self.params.get("price_min"),
                    check_price_max=self.params.get("price_max"),
                    contract_types=self.params.get("contract_types") or None,
                    building_types=self.params.get("building_types") or None,
                    is_cancelled=lambda: self._cancel,
                ):
                    page_no += 1
                    self.status.emit(f"[{idx}/{total}] {region_name} p{page_no} ({len(page_ids)}건)")
                    for hid in page_ids:
                        if self._cancel:
                            stopped = True
                            break
                        if hid in seen:
                            print(f"  이미 처리됨: {hid}")
                            continue
                        seen.add(hid)
                        try:
                            data = crawler.crawl_detail(str(hid), is_cancelled=lambda: self._cancel)
                            if date_start and date_end:
                                d = _parse_date_ymd(data.get("최초 등록일"))
                                if d is None or not (date_start <= d <= date_end):
                                    print(f"  날짜 필터 거절: {d}")
                                    continue
                            if not _contains_any_keyword(data.get("상세설명", ""), keywords):
                                print(f"  키워드 필터 거절: {data.get('상세설명')}")
                                continue
                            all_rows.append(data)
                            self.row_ready.emit(MainWindow.item_to_display_row(data))
                        except InterruptedError:
                            stopped = True
                            break
                        except Exception as e:
                            print(f"  실패: {e}")
                            pass
                        finally:
                            # time.sleep(random.uniform(0.1, 0.2))
                            pass
                    if stopped:
                        break
                self.progress.emit(idx, total)
                time.sleep(random.uniform(2, 3))
                if stopped:
                    break

            if not all_rows:
                self.finished.emit("중단됨 (저장할 데이터 없음)" if stopped else "수집된 매물이 없습니다.")
                return

            site = self.params.get("site_name", "피터팬")
            region = self.params.get("region_for_file", "전체_전체_전체")
            ts = self.params.get("timestamp", datetime.now().strftime("%y%m%d_%H%M%S"))
            out_dir = self.params.get("out_dir", os.getcwd())
            out_path = os.path.join(out_dir, f"{site}_{region}_{len(all_rows)}건_{ts}.xlsx")
            crawler.save_rows_to_excel(all_rows, out_path)
            prefix = "중단 저장 완료" if stopped else "저장 완료"
            self.finished.emit(f"{prefix}: {out_path} ({len(all_rows)}건)")
        except Exception as e:
            self.failed.emit(str(e))


class OnhouseWorker(QObject):
    progress = Signal(int, int)
    row_ready = Signal(tuple)
    status = Signal(str)
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, params: Dict[str, Any]):
        super().__init__()
        self.params = params
        self._cancel = False

    def cancel(self):
        self._cancel = True

    @Slot()
    def run(self):
        try:
            crawler = OnhouseCrawler(id=self.params["uid"], pwd=self.params["pwd"])
            self.status.emit("온하우스 로그인 중...")
            crawler.login()
            region_names = self.params["regions"]
            if not region_names:
                self.finished.emit("선택된 지역이 없습니다.")
                return

            all_rows: List[Dict[str, Any]] = []
            seen_ids: set = set()
            total = len(region_names)
            stopped = False
            for idx, region_name in enumerate(region_names, 1):
                if self._cancel:
                    stopped = True
                    break
                bbox = self.params.get("regions_bbox", {}).get(region_name)
                if not bbox:
                    self.progress.emit(idx, total)
                    continue
                self.status.emit(f"[{idx}/{total}] {region_name} 검색 중")
                page_num = 0
                while True:
                    if self._cancel:
                        stopped = True
                        break
                    page_ids = crawler.search(
                        sw_lat=bbox["lat_min"],
                        ne_lat=bbox["lat_max"],
                        sw_lng=bbox["lon_min"],
                        ne_lng=bbox["lon_max"],
                        trade_type=self.params["trade_types"],
                        room_type=self.params["room_type"],
                        limit=30,
                        page=page_num,
                        fetch_details=False,
                        refer_min_price=self.params.get("refer_min"),
                        refer_max_price=self.params.get("refer_max"),
                        min_price=self.params.get("price_min"),
                        max_price=self.params.get("price_max"),
                        min_month_price=self.params.get("month_min"),
                        max_month_price=self.params.get("month_max"),
                        min_area=self.params.get("area_min"),
                        max_area=self.params.get("area_max"),
                        is_cancelled=lambda: self._cancel,
                    )
                    page_ids = page_ids or []
                    if not page_ids:
                        break

                    self.status.emit(
                        f"[{idx}/{total}] {region_name} p{page_num + 1} ID {len(page_ids)}건 상세 수집 중"
                    )
                    for hid in page_ids:
                        if self._cancel:
                            stopped = True
                            break
                        hid_s = str(hid)
                        if hid_s in seen_ids:
                            continue
                        seen_ids.add(hid_s)
                        try:
                            row = crawler.crawl_detail(hid_s, is_cancelled=lambda: self._cancel)
                        except InterruptedError:
                            stopped = True
                            break
                        except Exception as e:
                            row = {"매물ID": hid_s, "URL": f"{crawler.DETAIL_URL}/{hid_s}", "오류": str(e)}
                        all_rows.append(row)
                        self.row_ready.emit(MainWindow.item_to_display_row(row))
                    if stopped:
                        break
                    self.status.emit(
                        f"[{idx}/{total}] {region_name} p{page_num + 1} 완료 (누적 {len(all_rows)}건)"
                    )
                    if len(page_ids) < 30:
                        break
                    page_num += 1

                self.progress.emit(idx, total)

            if not all_rows:
                self.finished.emit("중단됨 (저장할 데이터 없음)" if stopped else "수집된 매물이 없습니다.")
                return

            site = self.params.get("site_name", "온하우스")
            region = self.params.get("region_for_file", "전체_전체_전체")
            ts = self.params.get("timestamp", datetime.now().strftime("%y%m%d_%H%M%S"))
            out_dir = self.params.get("out_dir", os.getcwd())
            out_path = os.path.join(out_dir, f"{site}_{region}_{len(all_rows)}건_{ts}.xlsx")
            crawler.crawl_details_to_excel(rows=all_rows, output_path=out_path)
            prefix = "중단 저장 완료" if stopped else "저장 완료"
            self.finished.emit(f"{prefix}: {out_path} ({len(all_rows)}건)")
        except Exception as e:
            self.failed.emit(str(e))



# 네이버 호수 특정(건축물대장 조회) 기본값. False면 호수 컬럼은 빈칸이고 수집이 훨씬 빠르다(건물 첫 조회 약 10초 → 0.3초).
# 파라미터 hosu_enabled 가 넘어오면(UI 체크박스) 그 값을 우선한다.
NAVER_HOSU_ENABLED = True

# 네이버 상세 텍스트 필터 — 자주 쓰는 키워드 체크박스 (체크한 것 + 입력한 키워드를 OR 로 검색)
NAVER_KEYWORD_PRESETS = ["LH", "SH", "보증보험", "전세대출", "HUG", "허그", "대출", "애완", "반려", "동물", "통임대", "통매매", "통건물", "건물전체"]
# 엑셀에서 키워드가 들어간 설명 셀: 셀 배경 노란색, 키워드 글자는 빨간색 굵게
KEYWORD_HIGHLIGHT_COLUMNS = ("간략설명", "설명")

# 네이버 엑셀 출력 컬럼 순서 (사용자 지정, 2026-09-14)
NAVER_EXCEL_COLUMNS = [
    "매물번호", "세부주소", "호수", "종류", "거래방식", "매물명", "아파트동",
    "공급/계약/대지", "전용/연", "해당층", "전체층", "매매/전세금", "월세", "관리비",
    "방수", "화장실수", "입주가능일", "간략설명", "설명", "사용승인일",
    "중개사무소", "중개사명", "중개사주소", "중개사전화", "중개사휴대폰",
]

class NaverWorker(QObject):
    progress = Signal(int, int)
    row_ready = Signal(tuple)
    status = Signal(str)
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, params: Dict[str, Any]):
        super().__init__()
        self.params = params
        self._cancel = False
        self._phase = "idle"  # idle | crawling

    def cancel(self):
        self._cancel = True

    @staticmethod
    def _article_no_short_for_log(raw: Any) -> str:
        """수집 로그용: 네이버 매물번호 열은 URL이면 articleNo 숫자만 표시."""
        v = str(raw or "").strip()
        if not v:
            return "-"
        if "articleNo=" not in v or "land.naver.com" not in v.lower():
            return v
        try:
            q = parse_qs(urlparse(v).query)
            ano = (q.get("articleNo") or [None])[0]
            if ano:
                return str(ano)
        except Exception:
            pass
        m = re.search(r"articleNo=(\d+)", v, re.I)
        return m.group(1) if m else v

    @staticmethod
    def _display_row_from_naver(row: Any) -> tuple:
        # naver_crawler extract_detail_v2 리스트 인덱스: 종류 7, 거래 8, 매물명 9, 소재지 45 (호수 컬럼 포함 행이면 46)
        if isinstance(row, (list, tuple)) and len(row) >= 9:
            no = NaverWorker._article_no_short_for_log(row[3]) if len(row) > 3 else "-"
            _ri = 46 if len(row) >= 61 else 45
            region = str(row[_ri] if len(row) > _ri and row[_ri] else "")
            if not region:
                si = str(row[0]) if len(row) > 0 else ""
                gu = str(row[1]) if len(row) > 1 else ""
                dong = str(row[2]) if len(row) > 2 else ""
                region = " ".join([x for x in (si, gu, dong) if x]).strip()
            kind = str(row[7]) if len(row) > 7 else "-"
            trade = str(row[8]) if len(row) > 8 else "-"
            name = str(row[9]) if len(row) > 9 else "-"
            return (no or "-", region or "-", kind or "-", trade or "-", name or "-")
        return MainWindow.item_to_display_row(row)

    @Slot()
    def run(self):
        try:
            self._phase = "crawling"
            crawler = NaverCrawler(
                rls_path=self.params["rls_path"],
                on_log=lambda m: self.status.emit(str(m).strip()),
                on_progress=lambda c, t, n: (self.progress.emit(c, t), self.status.emit(f"지역 {c}/{t} | {n}")),
                is_cancelled=lambda: self._cancel,
            )

            keywords = self.params.get("detail_keywords", [])
            detail_filters = DetailFilters(
                rooms=self.params.get("detail_rooms"),
                floors=self.params.get("detail_floors"),
                years=self.params.get("detail_years"),
                uses=self.params.get("detail_uses"),
            )

            hosu_on = bool(self.params.get("hosu_enabled", NAVER_HOSU_ENABLED))

            def _detail_ok(row: Any) -> bool:
                if not detail_filters.active:
                    return True
                rooms, floor, approve, use = naver_detail_values(row, has_hosu=hosu_on)
                return detail_filters.passes(rooms=rooms, floor=floor, approve=approve, use=use)

            matched_rows: List[Any] = []
            region_names = self.params.get("region_names", [])
            self.status.emit(f"네이버: 매물 수집 중... ({len(region_names)}개 동 대상, 호수 특정 {'켬' if hosu_on else '끔'})")

            # for row in crawler.crawl_complexes_v2(
            #     realestate_type=self.params["realestate_type"],
            #     trade_type=self.params.get("trade_type", ""),
            #     regions_bbox=self.params.get("regions_bbox", {}),
            #     region_names=region_names,
            #     min_date=self.params.get("min_date"),
            #     wprc_min=self.params.get("min_warr"),
            #     wprc_max=self.params.get("max_warr"),
            #     rprc_min=self.params.get("min_rent"),
            #     rprc_max=self.params.get("max_rent"),
            #     dprc_min=self.params.get("min_deal"),
            #     dprc_max=self.params.get("max_deal"),
            #     spc_min=self.params.get("min_area"),
            #     spc_max=self.params.get("max_area"),
            # ):
            for row in crawler.crawl_complexes_v1(
                realestate_type=self.params["realestate_type"],
                trade_type=self.params.get("trade_type", ""),
                region_names=region_names,
                min_date=self.params.get("min_date"),
                min_deal_price=self.params.get("min_deal"),
                max_deal_price=self.params.get("max_deal"),
                min_warranty_price=self.params.get("min_warr"),
                max_warranty_price=self.params.get("max_warr"),
                min_rent_price=self.params.get("min_rent"),
                max_rent_price=self.params.get("max_rent"),
                min_area=self.params.get("min_area"),
                max_area=self.params.get("max_area"),
                is_hosu_needed=hosu_on
            ):
                if self._cancel:
                    break
                if not _contains_any_keyword(
                    description_text_from_naver_row(row, naver_row_has_hosu_column=hosu_on),
                    keywords,
                ):
                    continue
                if not _detail_ok(row):
                    continue
                matched_rows.append(row)
                self.row_ready.emit(self._display_row_from_naver(row))
                self.status.emit(f"네이버: 매물 수집 중... (필터 매칭 {len(matched_rows)}건)")

            if not matched_rows:
                self.finished.emit("필터 조건에 맞는 매물이 없습니다.")
                return

            _sched = self.params.get("schedule_name")
            if _sched:
                _fname = f"{_sched}_{len(matched_rows)}건_{self.params['timestamp']}.xlsx"
            else:
                _fname = f"{self.params['site_name']}_{self.params['region_for_file']}_{len(matched_rows)}건_{self.params['timestamp']}.xlsx"
            out_path = os.path.join(self.params["out_dir"], _fname)
            import pandas as pd
            from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

            df = pd.DataFrame(matched_rows)
            # extract_detail_v2(is_hosu_needed=True) 행 레이아웃: '호수'가 아파트동 다음(인덱스 11)에 삽입됨
            headers = [
                "시", "구", "동", "매물번호", "이미지URL", "등록/확인일", "집주인/확인", "종류", "거래방식", "매물명", "아파트동",
                "호수",
                "공급/계약/대지", "전용/연", "건면적", "전용률", "용적률", "건폐율", "해당층", "전체층", "방향",
                "매매/전세금", "월세", "평단가", "공시기준일", "공시가(최저)", "공시가(최고)", "권리금", "융자금",
                "기보증금", "기월세", "프리미엄", "사업시행단계", "용도지역", "관리비", "방수", "화장실수", "난방",
                "현재업종", "추천업종", "건축물용도", "지상층/지하층", "입주가능일", "간략설명", "설명", "소재지", "주소",
                "세부주소", "위도/경도", "건설사", "사용승인일", "세대수", "동수", "주차가능수", "중개사수",
                "중개사무소", "중개사명", "중개사주소", "중개사등록번호", "중개사전화", "중개사휴대폰",
            ]
            if df.shape[1] == len(headers):
                df.columns = headers
                # 엑셀 출력 컬럼과 순서 (고정). 매물번호 셀은 저장 후 하이퍼링크(매물 링크)로 변환됨.
                cols = [c for c in NAVER_EXCEL_COLUMNS if c in df.columns]
                df = df[cols]
            elif df.shape[1] == len(headers) - 1:
                # 호수 없는 구버전 레이아웃 (안전장치)
                df.columns = [h for h in headers if h != "호수"]
                cols = [c for c in NAVER_EXCEL_COLUMNS if c in df.columns]
                df = df[cols]
            df = df.map(lambda x: ILLEGAL_CHARACTERS_RE.sub(r"", x) if isinstance(x, str) else x)
            df.to_excel(out_path, index=False)
            self._apply_excel_hyperlinks(out_path)
            if keywords:
                self._apply_keyword_highlight(out_path, keywords)
            prefix = "중단 저장 완료" if self._cancel else "저장 완료"
            self.finished.emit(f"{prefix}: {out_path} ({len(matched_rows)}건)")
        except Exception as e:
            self.failed.emit(str(e))
        finally:
            self._phase = "idle"

    @staticmethod
    def _apply_keyword_highlight(path: str, keywords: List[str]) -> None:
        """설명 컬럼에서 키워드가 들어간 셀: 배경 노란색, 키워드 글자만 빨간색 굵게(리치 텍스트).
        엑셀은 글자 단위 배경색(형광펜)을 지원하지 않아 글자색으로 표시한다."""
        kws = [str(k).strip() for k in (keywords or []) if str(k).strip()]
        if not kws:
            return
        try:
            import openpyxl
            from openpyxl.cell.rich_text import CellRichText, TextBlock
            from openpyxl.cell.text import InlineFont
            from openpyxl.styles import PatternFill
            from openpyxl.styles.colors import Color
        except Exception:
            return
        pattern = re.compile("|".join(re.escape(k) for k in sorted(kws, key=len, reverse=True)), re.IGNORECASE)
        red_bold = InlineFont(b=True, color=Color(rgb="FFFF0000"))
        yellow = PatternFill(fill_type="solid", fgColor="FFFFFF00")
        try:
            wb = openpyxl.load_workbook(path)
            ws = wb.active
            target_cols = [
                ci for ci in range(1, ws.max_column + 1)
                if str(ws.cell(row=1, column=ci).value or "").strip() in KEYWORD_HIGHLIGHT_COLUMNS
            ]
            if not target_cols:
                wb.close()
                return
            for r in range(2, ws.max_row + 1):
                for ci in target_cols:
                    cell = ws.cell(row=r, column=ci)
                    text = cell.value
                    if not isinstance(text, str) or not text or not pattern.search(text):
                        continue
                    parts: list = []
                    pos = 0
                    for m in pattern.finditer(text):
                        if m.start() > pos:
                            parts.append(text[pos:m.start()])
                        parts.append(TextBlock(red_bold, m.group(0)))
                        pos = m.end()
                    if pos < len(text):
                        parts.append(text[pos:])
                    cell.value = CellRichText(parts)
                    cell.fill = yellow
            wb.save(path)
            wb.close()
        except Exception as e:
            print(f"[엑셀] 키워드 강조 실패: {e}")

    @staticmethod
    def _apply_excel_hyperlinks(path: str) -> None:
        """저장된 엑셀의 URL/링크 컬럼을 하이퍼링크 셀로 변환. 네이버 '매물번호' 열은 전체 URL을 표시하고 동일 URL로 링크."""
        try:
            import openpyxl
            from openpyxl.styles import Font
        except Exception:
            return

        def _naver_article_display_and_url(cell_value: str) -> tuple[str | None, str | None]:
            v = str(cell_value or "").strip()
            if not v.lower().startswith("https://") or "new.land.naver.com" not in v or "articleNo=" not in v:
                return None, None
            try:
                q = parse_qs(urlparse(v).query)
                ano = (q.get("articleNo") or [None])[0]
                if ano:
                    return str(ano), v
            except Exception:
                pass
            return None, None

        try:
            wb = openpyxl.load_workbook(path)
            ws = wb.active
            link_font = Font(color="0563C1", underline="single")

            mawol_col: int | None = None
            for col_idx in range(1, ws.max_column + 1):
                if str(ws.cell(row=1, column=col_idx).value or "").strip() == "매물번호":
                    mawol_col = col_idx
                    break

            url_col_indices: list[int] = []
            for col_idx in range(1, ws.max_column + 1):
                header = str(ws.cell(row=1, column=col_idx).value or "")
                h = header.strip().lower()
                if ("url" in h) or ("link" in h) or ("링크" in header):
                    url_col_indices.append(col_idx)

            if not mawol_col and not url_col_indices:
                wb.close()
                return

            if mawol_col:
                for row_idx in range(2, ws.max_row + 1):
                    cell = ws.cell(row=row_idx, column=mawol_col)
                    value = str(cell.value or "").strip()
                    ano, url = _naver_article_display_and_url(value)
                    if ano and url:
                        cell.hyperlink = url
                        cell.value = url
                        cell.font = link_font

            for row_idx in range(2, ws.max_row + 1):
                for col_idx in url_col_indices:
                    cell = ws.cell(row=row_idx, column=col_idx)
                    value = str(cell.value or "").strip()
                    if value.lower().startswith(("http://", "https://")):
                        cell.hyperlink = value
                        cell.font = link_font
            wb.save(path)
            wb.close()
        except Exception:
            pass


class MainWindow(QMainWindow, ScheduleMixin):
    def __init__(self):
        super().__init__()
        if getattr(sys, "frozen", False):
            # onefile exe: 리소스는 _MEIPASS, 저장 경로는 exe 폴더 사용
            self.base_dir = os.path.dirname(sys.executable)
            self.resource_dir = getattr(sys, "_MEIPASS", self.base_dir)
        else:
            self.base_dir = os.path.dirname(os.path.abspath(__file__))
            self.resource_dir = self.base_dir
        self.onhouse_cred_path = os.path.join(self.base_dir, "onhouse_credentials.json")
        self.naver_rls: Dict[str, Any] = {}
        self.regions_name_to_incode: Dict[str, str] = {}
        self.regions_bbox: Dict[str, Dict[str, float]] = {}
        self._region_si_list: List[str] = ["전체"]
        self._region_si_gun_map: Dict[str, List[str]] = {}
        self._region_si_gun_gu_map: Dict[str, List[str]] = {}
        self._load_regions()
        self._load_naver_rls()
        self.worker_thread: QThread | None = None
        self.worker: QObject | None = None
        self.log_rows: List[tuple] = []
        self.log_dialog: QDialog | None = None
        self.log_dialog_table: QTableWidget | None = None
        self._last_output_path: str | None = None
        self.setWindowTitle("전국 부동산 매물 수집기 v1")
        self.resize(1600, 1020)
        self.setMinimumSize(1280, 820)
        self._setup_ui()
        self._load_onhouse_credentials()
        self._apply_style()
        self._init_schedule()

    def _load_regions(self):
        p = os.path.join(self.resource_dir, "regions.json")
        if not os.path.exists(p):
            p = os.path.join(self.base_dir, "regions.json")
        try:
            with open(p, "r", encoding="utf-8") as f:
                regions_json = json.load(f)
        except Exception:
            regions_json = {"서울특별시 강남구 역삼동": "6035"}
        bbox_path = os.path.join(self.resource_dir, "regions_bbox.json")
        if not os.path.exists(bbox_path):
            bbox_path = os.path.join(self.base_dir, "regions_bbox.json")
        try:
            with open(bbox_path, "r", encoding="utf-8") as f:
                self.regions_bbox = json.load(f)
        except Exception:
            self.regions_bbox = {}
        self.regions_name_to_incode = {name: f"{name.split()[-1]}-{rid}" for name, rid in regions_json.items()}
        all_names = sorted(set(self.regions_name_to_incode.keys()) | set(self.regions_bbox.keys()))
        self._region_si_list = ["전체"]
        for name in all_names:
            parts = name.split()
            if not parts:
                continue
            si = parts[0]
            if si not in self._region_si_gun_map:
                self._region_si_list.append(si)
                self._region_si_gun_map[si] = ["전체"]
            if len(parts) >= 2:
                gun = parts[1]
                if gun not in self._region_si_gun_map[si]:
                    self._region_si_gun_map[si].append(gun)
                si_gun = f"{si} {gun}"
                if si_gun not in self._region_si_gun_gu_map:
                    self._region_si_gun_gu_map[si_gun] = ["전체"]
                if len(parts) >= 3 and parts[2] not in self._region_si_gun_gu_map[si_gun]:
                    self._region_si_gun_gu_map[si_gun].append(parts[2])

        # regions_bbox 전용 지역 목록 (네이버 등 bbox 기반 탭 전용)
        self._bbox_si_list: List[str] = ["전체"]
        self._bbox_si_gun_map: Dict[str, List[str]] = {}
        self._bbox_si_gun_gu_map: Dict[str, List[str]] = {}
        for name in sorted(self.regions_bbox.keys()):
            parts = name.split()
            if not parts:
                continue
            si = parts[0]
            if si not in self._bbox_si_gun_map:
                self._bbox_si_list.append(si)
                self._bbox_si_gun_map[si] = ["전체"]
            if len(parts) >= 2:
                gun = parts[1]
                if gun not in self._bbox_si_gun_map[si]:
                    self._bbox_si_gun_map[si].append(gun)
                si_gun = f"{si} {gun}"
                if si_gun not in self._bbox_si_gun_gu_map:
                    self._bbox_si_gun_gu_map[si_gun] = ["전체"]
                if len(parts) >= 3 and parts[2] not in self._bbox_si_gun_gu_map[si_gun]:
                    self._bbox_si_gun_gu_map[si_gun].append(parts[2])

    def _load_naver_rls(self):
        p = os.path.join(self.resource_dir, "naver_rls.json")
        if not os.path.exists(p):
            p = os.path.join(self.base_dir, "naver_rls.json")
        try:
            with open(p, "r", encoding="utf-8") as f:
                self.naver_rls = json.load(f)
        except Exception:
            self.naver_rls = {}
        self._build_naver_rls_ui_maps()

    def _build_naver_rls_ui_maps(self) -> None:
        """네이버 탭 콤보용: naver_rls.json 시도 → 시군구 → 읍면동 계층."""
        self._nv_rls_si_list: List[str] = ["전체"]
        self._nv_rls_si_gu_map: Dict[str, List[str]] = {}
        self._nv_rls_si_gu_dong_map: Dict[str, List[str]] = {}
        rls = self.naver_rls or {}
        for si in sorted(rls.keys()):
            self._nv_rls_si_list.append(si)
            gu_map = rls[si]
            self._nv_rls_si_gu_map[si] = ["전체"]
            for gu in sorted(gu_map.keys()):
                self._nv_rls_si_gu_map[si].append(gu)
                key_sg = f"{si} {gu}"
                dong_map = gu_map[gu]
                self._nv_rls_si_gu_dong_map[key_sg] = ["전체"]
                for dong in sorted(dong_map.keys()):
                    self._nv_rls_si_gu_dong_map[key_sg].append(dong)

    def _selected_regions_for_nv(self, si: str, gun: str, gu: str) -> List[str]:
        """naver_rls 기준 동 단위 지역명 목록 (크롤러 _resolve_rls_keys와 동일한 공백 구분 문자열)."""
        rls = self.naver_rls or {}
        out: List[str] = []
        for s_k, gu_map in rls.items():
            if si != "전체" and s_k != si:
                continue
            for gu_k, dong_map in gu_map.items():
                if gun != "전체" and gu_k != gun:
                    continue
                for dong_k in dong_map.keys():
                    if gu != "전체" and dong_k != gu:
                        continue
                    out.append(f"{s_k} {gu_k} {dong_k}")
        return sorted(out)

    def _setup_ui(self):
        central = QWidget()
        central.setObjectName("appRoot")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self.tabs.addTab(wrap_in_scroll(self._build_daangn_tab()), "당근")
        self.tabs.addTab(wrap_in_scroll(self._build_naver_tab()), "네이버")
        ctrl = QHBoxLayout()
        self.btn_start = QPushButton("수집 시작")
        self.btn_stop = QPushButton("중단")
        self.btn_clear = QPushButton("수집 로그 지우기")
        self.btn_log = QPushButton("수집 로그 보기")
        self.btn_open_output = QPushButton("수집된 파일 열기")
        self.btn_open_output.setToolTip(
            "마지막으로 저장된 엑셀 파일을 엽니다. 없으면 data 폴더의 최신 파일 또는 폴더를 엽니다."
        )
        self.btn_stop.setEnabled(False)
        self.btn_start.clicked.connect(self._on_start)
        self.btn_stop.clicked.connect(self._on_stop)
        self.btn_clear.clicked.connect(self._clear_log)
        self.btn_log.clicked.connect(self._show_log_dialog)
        self.btn_open_output.clicked.connect(self._on_open_output_file)
        self.btn_schedule_add = QPushButton("현재 설정 예약")
        self.btn_schedule_list = QPushButton("예약 관리")
        self.btn_schedule_add.setToolTip("현재 탭의 수집 설정을 예약으로 저장합니다.")
        self.btn_schedule_list.setToolTip("예약된 수집 목록을 보고 관리합니다.")
        self.btn_schedule_add.clicked.connect(self._save_current_as_schedule)
        self.btn_schedule_list.clicked.connect(self._open_schedule_list)
        ctrl.addWidget(self.btn_start)
        ctrl.addWidget(self.btn_stop)
        ctrl.addWidget(self.btn_clear)
        ctrl.addWidget(self.btn_log)
        ctrl.addWidget(self.btn_open_output)
        ctrl.addWidget(self.btn_schedule_add)
        ctrl.addWidget(self.btn_schedule_list)
        ctrl.addStretch(1)
        root.addLayout(ctrl)
        pr = QHBoxLayout()
        self.progress_text = QLabel("대기 중")
        self.progress_count = QLabel("0/0")
        self.progress_count.setStyleSheet("color:#1e293b; font-weight:600;")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        pr.addWidget(self.progress_text)
        pr.addWidget(self.progress_count)
        pr.addWidget(self.progress_bar, 1)
        root.addLayout(pr)

        self._refresh_trade_controls()
        self._update_date_filter_visuals()

    def _build_daangn_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        region_box = QGroupBox("지역 (체크박스로 여러 곳 동시 선택 가능)")
        row = QHBoxLayout(region_box)
        self.cb_si = MultiSelectCombo()
        self.cb_si.set_entries([(si, si) for si in self._region_si_list if si != "전체"])
        self.cb_gun = MultiSelectCombo()
        self.cb_gu = MultiSelectCombo()
        # 지역명이 길어 잘리지 않도록 콤보박스 가로폭 확보
        self.cb_si.setMinimumWidth(170)
        self.cb_gun.setMinimumWidth(170)
        self.cb_gu.setMinimumWidth(220)
        row.addWidget(QLabel("시/도"))
        row.addWidget(self.cb_si)
        row.addWidget(QLabel("시군"))
        row.addWidget(self.cb_gun)
        row.addWidget(QLabel("시군구"))
        row.addWidget(self.cb_gu)
        row.addStretch(1)
        self.cb_si.selection_changed.connect(self._on_si_changed)
        self.cb_gun.selection_changed.connect(self._on_gun_changed)
        self._on_si_changed()
        v.addWidget(region_box)
        date_box = QGroupBox("등록일")
        dr = QHBoxLayout(date_box)
        self.date_use = QCheckBox("날짜 필터")
        self.date_start = QDateEdit()
        self.date_end = QDateEdit()
        for de in (self.date_start, self.date_end):
            de.setCalendarPopup(True)
            de.setDisplayFormat("yyyy-MM-dd")
            de.setDate(QDate.currentDate())
        self.date_start.setDate(QDate.currentDate().addDays(-7))
        self.date_use.toggled.connect(self.date_start.setEnabled)
        self.date_use.toggled.connect(self.date_end.setEnabled)
        self.date_use.toggled.connect(lambda _checked=False: self._update_date_filter_visuals())
        self.date_start.setEnabled(False)
        self.date_end.setEnabled(False)
        self.date_range_sep = QLabel("~")
        dr.addWidget(self.date_use)
        dr.addWidget(self.date_start)
        dr.addWidget(self.date_range_sep)
        dr.addWidget(self.date_end)
        dr.addStretch(1)
        v.addWidget(date_box)
        price_box = QGroupBox("가격/면적 (직접 입력, 빈칸=제한없음)")
        grid = QGridLayout(price_box)
        self.sl_deposit = RangeInput("보증금", unit="만원")
        self.sl_month = RangeInput("월세", unit="만원")
        self.sl_buy = RangeInput("매매", unit="만원")
        self.sl_borrow = RangeInput("전세", unit="만원")
        self.sl_area = RangeInput("면적", unit="평", unit_toggle=("㎡", 3.3058))
        grid.addWidget(self.sl_deposit, 0, 0)
        grid.addWidget(self.sl_month, 0, 1)
        grid.addWidget(self.sl_buy, 1, 0)
        grid.addWidget(self.sl_borrow, 1, 1)
        grid.addWidget(self.sl_area, 2, 0)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(4)
        v.addWidget(price_box)
        detail_box = QGroupBox("상세 조건 (방수/층수/사용승인일)")
        dgrid = QGridLayout(detail_box)
        self.dg_sl_rooms = RangeInput("방수", unit="개")
        self.dg_sl_floor = RangeInput("층수", unit="층 (반지하/지하=0)")
        self.dg_sl_builtyear = RangeInput("사용승인일", unit="년", default_min_text="1950")
        dgrid.addWidget(self.dg_sl_rooms, 0, 0)
        dgrid.addWidget(self.dg_sl_floor, 0, 1)
        dgrid.addWidget(self.dg_sl_builtyear, 1, 0)
        dgrid.setColumnStretch(0, 1)
        dgrid.setColumnStretch(1, 1)
        dgrid.setHorizontalSpacing(16)
        dgrid.setVerticalSpacing(4)
        v.addWidget(detail_box)
        trade_box = QGroupBox("거래유형 / 거래주체")
        tr = QHBoxLayout(trade_box)
        self.chk_month = QCheckBox("월세")
        self.chk_buy = QCheckBox("매매")
        self.chk_borrow = QCheckBox("전세")
        self.chk_short = QCheckBox("단기")
        self.chk_month.setChecked(True)
        for c in (self.chk_month, self.chk_buy, self.chk_borrow, self.chk_short):
            tr.addWidget(c)
            c.toggled.connect(lambda _checked=False: self._refresh_trade_controls())
        tr.addSpacing(24)
        # 거래주체: 당근 목록의 writerTypeV2 (BROKER / DIRECT_USER). 목록 단계에서 걸러 상세 요청을 줄인다
        tr.addWidget(QLabel("거래주체"))
        self.chk_dg_broker = QCheckBox("공인중개사 매물")
        self.chk_dg_direct = QCheckBox("직거래 (집주인/세입자)")
        self.chk_dg_broker.setChecked(True)
        self.chk_dg_direct.setChecked(True)
        tr.addWidget(self.chk_dg_broker)
        tr.addWidget(self.chk_dg_direct)
        tr.addStretch(1)
        v.addWidget(trade_box)
        kind_box = QGroupBox("매물유형")
        kr = QHBoxLayout(kind_box)
        self.sales_checks: Dict[str, QCheckBox] = {}
        for api, label in DaangnRealtyCrawler.SALES_TYPE_MAP.items():
            cb = QCheckBox(label)
            cb.setChecked(api == "two_room")
            self.sales_checks[api] = cb
            kr.addWidget(cb)
        kr.addStretch(1)
        v.addWidget(kind_box)
        # 건축물용도 다중선택 (체크 없음 = 전체). 당근 상세의 buildingUsage(한글 변환)와 부분일치로 비교.
        # 항목이 많아(24종) 기존 컨트롤이 아래로 밀리지 않도록 매물유형 다음에 둔다.
        self.dg_use_group = UseCheckGroup("건축물용도 (체크한 용도만 수집, 체크 없으면 전체)", columns=6)
        v.addWidget(self.dg_use_group)
        text_box = QGroupBox("상세 텍스트 필터")
        fr = QHBoxLayout(text_box)
        self.dg_detail_filter = QLineEdit()
        self.dg_detail_filter.setPlaceholderText("상세_내용 키워드,콤마로구분 (예: 리모델링,풀옵션)")
        fr.addWidget(QLabel("키워드"))
        fr.addWidget(self.dg_detail_filter, 1)
        v.addWidget(text_box)
        v.addStretch(1)
        return w

    def _build_peterpan_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)

        region_box = QGroupBox("지역")
        row = QHBoxLayout(region_box)
        self.pp_cb_si = QComboBox()
        self.pp_cb_si.addItems(self._bbox_si_list)
        self.pp_cb_gun = QComboBox()
        self.pp_cb_gu = QComboBox()
        self.pp_cb_si.setMinimumWidth(170)
        self.pp_cb_gun.setMinimumWidth(170)
        self.pp_cb_gu.setMinimumWidth(220)
        row.addWidget(QLabel("시/도"))
        row.addWidget(self.pp_cb_si)
        row.addWidget(QLabel("시군"))
        row.addWidget(self.pp_cb_gun)
        row.addWidget(QLabel("시군구"))
        row.addWidget(self.pp_cb_gu)
        row.addStretch(1)
        self.pp_cb_si.currentTextChanged.connect(self._on_pp_si_changed)
        self.pp_cb_gun.currentTextChanged.connect(self._on_pp_gun_changed)
        self._on_pp_si_changed(self.pp_cb_si.currentText())
        v.addWidget(region_box)

        price_box = QGroupBox("가격/면적")
        grid = QGridLayout(price_box)
        self.pp_sl_deposit = DualSlider("보증금(만)", 0, 50000, 1000)
        self.pp_sl_month = DualSlider("월세(만)", 0, 3000, 10)
        self.pp_sl_jeon = DualSlider("전세(만)", 0, 1000000, 5000)
        self.pp_sl_price = DualSlider("매매가(만)", 0, 1000000, 5000)
        self.pp_sl_size = DualSlider("면적(㎡)", 0, 500, 10)
        grid.addWidget(self.pp_sl_month, 0, 0)
        grid.addWidget(self.pp_sl_deposit, 0, 1)
        grid.addWidget(self.pp_sl_price, 1, 0)
        grid.addWidget(self.pp_sl_jeon, 1, 1)
        grid.addWidget(self.pp_sl_size, 2, 0)
        v.addWidget(price_box)

        trade_box = QGroupBox("거래유형")
        tr = QHBoxLayout(trade_box)
        self.pp_contract_checks: Dict[str, QCheckBox] = {}
        for label in ("월세", "전세", "단기임대", "매매"):
            cb = QCheckBox(label)
            self.pp_contract_checks[label] = cb
            tr.addWidget(cb)
            cb.toggled.connect(lambda _checked=False: self._refresh_trade_controls())
        self.pp_contract_checks["월세"].setChecked(True)
        tr.addStretch(1)
        v.addWidget(trade_box)

        building_box = QGroupBox("매물유형")
        br = QHBoxLayout(building_box)
        self.pp_building_checks: Dict[str, QCheckBox] = {}
        for label in ("원/투룸", "빌라/주택", "오피스텔", "아파트"):
            cb = QCheckBox(label)
            self.pp_building_checks[label] = cb
            br.addWidget(cb)
        self.pp_building_checks["원/투룸"].setChecked(True)
        br.addStretch(1)
        v.addWidget(building_box)

        date_box = QGroupBox("등록일")
        dr = QHBoxLayout(date_box)
        self.pp_date_use = QCheckBox("날짜 필터")
        self.pp_date_start = QDateEdit()
        self.pp_date_end = QDateEdit()
        for de in (self.pp_date_start, self.pp_date_end):
            de.setCalendarPopup(True)
            de.setDisplayFormat("yyyy-MM-dd")
            de.setDate(QDate.currentDate())
        self.pp_date_start.setDate(QDate.currentDate().addDays(-30))
        self.pp_date_use.toggled.connect(self.pp_date_start.setEnabled)
        self.pp_date_use.toggled.connect(self.pp_date_end.setEnabled)
        self.pp_date_use.toggled.connect(lambda _checked=False: self._update_date_filter_visuals())
        self.pp_date_start.setEnabled(False)
        self.pp_date_end.setEnabled(False)
        self.pp_date_range_sep = QLabel("~")
        dr.addWidget(self.pp_date_use)
        dr.addWidget(self.pp_date_start)
        dr.addWidget(self.pp_date_range_sep)
        dr.addWidget(self.pp_date_end)
        dr.addStretch(1)
        v.addWidget(date_box)

        text_box = QGroupBox("상세 텍스트 필터")
        fr = QHBoxLayout(text_box)
        self.pp_detail_filter = QLineEdit()
        self.pp_detail_filter.setPlaceholderText("상세설명 키워드,콤마로구분 (예: 신축,반려동물)")
        fr.addWidget(QLabel("키워드"))
        fr.addWidget(self.pp_detail_filter, 1)
        v.addWidget(text_box)
        v.addStretch(1)
        return w

    def _build_onhouse_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)

        login_box = QGroupBox("계정")
        lr = QHBoxLayout(login_box)
        self.oh_id = QLineEdit()
        self.oh_pwd = QLineEdit()
        self.oh_pwd.setEchoMode(QLineEdit.EchoMode.Password)
        self.oh_id.setPlaceholderText("온하우스 아이디")
        self.oh_pwd.setPlaceholderText("온하우스 비밀번호")
        self.oh_save_credentials = QCheckBox("아이디/비밀번호 저장")
        lr.addWidget(QLabel("아이디"))
        lr.addWidget(self.oh_id, 1)
        lr.addWidget(QLabel("비밀번호"))
        lr.addWidget(self.oh_pwd, 1)
        lr.addWidget(self.oh_save_credentials)
        v.addWidget(login_box)

        region_box = QGroupBox("지역")
        rr = QHBoxLayout(region_box)
        self.oh_cb_si = QComboBox()
        self.oh_cb_si.addItems(self._bbox_si_list)
        self.oh_cb_gun = QComboBox()
        self.oh_cb_gu = QComboBox()
        self.oh_cb_si.setMinimumWidth(170)
        self.oh_cb_gun.setMinimumWidth(170)
        self.oh_cb_gu.setMinimumWidth(220)
        rr.addWidget(QLabel("시/도"))
        rr.addWidget(self.oh_cb_si)
        rr.addWidget(QLabel("시군"))
        rr.addWidget(self.oh_cb_gun)
        rr.addWidget(QLabel("시군구"))
        rr.addWidget(self.oh_cb_gu)
        rr.addStretch(1)
        self.oh_cb_si.currentTextChanged.connect(self._on_oh_si_changed)
        self.oh_cb_gun.currentTextChanged.connect(self._on_oh_gun_changed)
        self._on_oh_si_changed(self.oh_cb_si.currentText())
        v.addWidget(region_box)

        type_box = QGroupBox("유형")
        tr = QHBoxLayout(type_box)
        self.oh_trade_month = QCheckBox("월세")
        self.oh_trade_buy = QCheckBox("매매")
        self.oh_trade_buy.setChecked(True)
        self.oh_room_type = QComboBox()
        self.oh_room_type.addItems(["전체", "주택", "오피", "주택/오피", "사무실", "상가", "사무실/상가", "분양사무실"])
        tr.addWidget(self.oh_trade_month)
        tr.addWidget(self.oh_trade_buy)
        tr.addSpacing(16)
        tr.addWidget(QLabel("방유형"))
        tr.addWidget(self.oh_room_type)
        tr.addStretch(1)
        v.addWidget(type_box)

        price_box = QGroupBox("가격/면적")
        grid = QGridLayout(price_box)
        self.oh_sl_refer = DualSlider("기준가(만)", 0, 1000000, 1000)
        self.oh_sl_price = DualSlider("보증금/매매가(만)", 0, 100000, 1000)
        self.oh_sl_month = DualSlider("월세(만)", 0, 3000, 10)
        self.oh_sl_area = DualSlider("평수", 0, 200, 10)
        grid.addWidget(self.oh_sl_refer, 0, 0)
        grid.addWidget(self.oh_sl_price, 0, 1)
        grid.addWidget(self.oh_sl_month, 1, 0)
        grid.addWidget(self.oh_sl_area, 1, 1)
        v.addWidget(price_box)
        self.oh_trade_month.toggled.connect(self._on_oh_trade_changed)
        self.oh_trade_buy.toggled.connect(self._on_oh_trade_changed)
        self._on_oh_trade_changed()

        v.addStretch(1)
        return w

    def _build_naver_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)

        region_box = QGroupBox("지역 (체크박스로 여러 곳 동시 선택 가능)")
        rr = QHBoxLayout(region_box)
        self.nv_cb_si = MultiSelectCombo()
        self.nv_cb_si.set_entries(
            [(si, si) for si in getattr(self, "_nv_rls_si_list", ["전체"]) if si != "전체"]
        )
        self.nv_cb_gun = MultiSelectCombo()
        self.nv_cb_gu = MultiSelectCombo()
        self.nv_cb_si.setMinimumWidth(170)
        self.nv_cb_gun.setMinimumWidth(170)
        self.nv_cb_gu.setMinimumWidth(220)
        rr.addWidget(QLabel("시/도"))
        rr.addWidget(self.nv_cb_si)
        rr.addWidget(QLabel("시·군·구"))
        rr.addWidget(self.nv_cb_gun)
        rr.addWidget(QLabel("읍·면·동"))
        rr.addWidget(self.nv_cb_gu)
        rr.addStretch(1)
        self.nv_cb_si.selection_changed.connect(self._on_nv_si_changed)
        self.nv_cb_gun.selection_changed.connect(self._on_nv_gun_changed)
        # 네이버 탭 기본값: 서울시 - 전체 - 전체 (naver_rls 키)
        self.nv_cb_si.set_checked_labels(["서울시"])
        v.addWidget(region_box)

        kind_box = QGroupBox("매물유형")
        kr = QGridLayout(kind_box)
        self.nv_type_checks: Dict[str, QCheckBox] = {}
        type_defs = [
            ("재건축", "JGC"), ("분양중/예정", "IA01:IA02:IC01:IC02:IA04:IC03"), ("오피스텔분양권", "OBYG"), ("아파트", "APT"),
            ("아파트분양권", "ABYG"), ("재개발", "JGB"), ("오피스텔", "OPST"), ("빌라/연립", "VL"),
            ("단독/다가구", "DDDGG"), ("전원주택", "JWJT"), ("상가주택", "SGJT"), ("한옥주택", "HOJT"),
            ("원룸/투룸", "OR"), ("상가", "SG"), ("사무실", "SMS"), ("공장/창고", "GJCG"),
            ("지식산업센터", "APTHGJ"), ("건물", "GM"), ("토지", "TJ"),
        ]
        for i, (label, code) in enumerate(type_defs):
            cb = QCheckBox(label)
            # 네이버 탭 기본값: 아파트/오피스텔/빌라연립/원룸투룸만 선택
            cb.setChecked(code in ("APT", "OPST", "VL", "OR"))
            self.nv_type_checks[code] = cb
            kr.addWidget(cb, i // 4, i % 4)
        v.addWidget(kind_box)

        trade_box = QGroupBox("거래유형")
        tr = QHBoxLayout(trade_box)
        self.nv_trade_buy = QCheckBox("매매")
        self.nv_trade_jeon = QCheckBox("전세")
        self.nv_trade_month = QCheckBox("월세")
        self.nv_trade_short = QCheckBox("단기임대")
        self.nv_trade_buy.setChecked(False)
        self.nv_trade_jeon.setChecked(False)
        self.nv_trade_month.setChecked(True)
        self.nv_trade_short.setChecked(False)
        for c in (self.nv_trade_buy, self.nv_trade_jeon, self.nv_trade_month, self.nv_trade_short):
            tr.addWidget(c)
            c.toggled.connect(lambda _checked=False: self._refresh_trade_controls())
        tr.addStretch(1)
        v.addWidget(trade_box)

        price_box = QGroupBox("가격/면적/등록일 (직접 입력, 빈칸=제한없음)")
        pg = QGridLayout(price_box)
        self.nv_sl_warr = RangeInput("보증금", unit="만원")
        self.nv_sl_rent = RangeInput("월세", unit="만원")
        self.nv_sl_deal = RangeInput("매매가", unit="만원")
        self.nv_sl_jeon = RangeInput("전세", unit="만원")
        self.nv_sl_area = RangeInput("면적", unit="㎡", unit_toggle=("평", 0.3025))
        pg.addWidget(self.nv_sl_warr, 0, 0)
        pg.addWidget(self.nv_sl_rent, 0, 1)
        pg.addWidget(self.nv_sl_deal, 1, 0)
        pg.addWidget(self.nv_sl_jeon, 1, 1)
        pg.addWidget(self.nv_sl_area, 2, 0)
        pg.setColumnStretch(0, 1)
        pg.setColumnStretch(1, 1)
        pg.setHorizontalSpacing(16)
        pg.setVerticalSpacing(4)
        self.nv_date_preset = QComboBox()
        self.nv_date_preset.addItems(["전체", "오늘", "어제/오늘", "일주일", "한달"])
        self.nv_date_preset.setMinimumWidth(180)
        nv_date_wrap = QWidget()
        nv_date_row = QHBoxLayout(nv_date_wrap)
        nv_date_row.setContentsMargins(0, 0, 0, 0)
        nv_date_row.setSpacing(8)
        nv_date_row.addWidget(QLabel("등록일"))
        nv_date_row.addWidget(self.nv_date_preset)
        nv_date_row.addStretch(1)
        pg.addWidget(nv_date_wrap, 2, 1)
        v.addWidget(price_box)
        nv_detail_box = QGroupBox("상세 조건 (방수/층수/사용승인일)")
        nv_dgrid = QGridLayout(nv_detail_box)
        self.nv_sl_rooms = RangeInput("방수", unit="개")
        self.nv_sl_floor = RangeInput("층수", unit="층 (반지하/지하=0)")
        self.nv_sl_builtyear = RangeInput("사용승인일", unit="년", default_min_text="1950")
        nv_dgrid.addWidget(self.nv_sl_rooms, 0, 0)
        nv_dgrid.addWidget(self.nv_sl_floor, 0, 1)
        nv_dgrid.addWidget(self.nv_sl_builtyear, 1, 0)
        nv_dgrid.setColumnStretch(0, 1)
        nv_dgrid.setColumnStretch(1, 1)
        nv_dgrid.setHorizontalSpacing(16)
        nv_dgrid.setVerticalSpacing(4)
        v.addWidget(nv_detail_box)
        text_box = QGroupBox("상세 텍스트 필터 (입력 키워드 + 체크 키워드 중 하나라도 설명에 있으면 수집 · 엑셀에서 키워드 강조)")
        fr = QHBoxLayout(text_box)
        fr.setSpacing(12)
        left = QWidget()
        lf = QHBoxLayout(left)
        lf.setContentsMargins(0, 0, 0, 0)
        self.nv_detail_filter = QLineEdit()
        self.nv_detail_filter.setPlaceholderText("설명 키워드,콤마로구분 (예: 역세권,신축)")
        lf.addWidget(QLabel("키워드"))
        lf.addWidget(self.nv_detail_filter, 1)
        right = QWidget()
        rg = QGridLayout(right)
        rg.setContentsMargins(0, 0, 0, 0)
        rg.setHorizontalSpacing(10)
        rg.setVerticalSpacing(2)
        self.nv_kw_checks: Dict[str, QCheckBox] = {}
        for i, kw in enumerate(NAVER_KEYWORD_PRESETS):
            cb = QCheckBox(kw)
            self.nv_kw_checks[kw] = cb
            rg.addWidget(cb, i // 5, i % 5)
        fr.addWidget(left, 1)
        fr.addWidget(right, 1)
        v.addWidget(text_box)
        # 건축물용도 다중선택 (체크 없음 = 전체). 네이버 상세의 '건축물용도' 컬럼과 부분일치로 비교. 맨 아래 배치.
        self.nv_use_group = UseCheckGroup("건축물용도 (체크한 용도만 수집, 체크 없으면 전체)", columns=6)
        v.addWidget(self.nv_use_group)
        # 호수 특정 on/off. 끄면 호수 컬럼은 빈칸이고 수집이 훨씬 빠르다.
        self.nv_hosu_check = QCheckBox("호수 특정 (건축물대장 조회 · 후보 여러 개면 모두 표시 · 건물 첫 조회 시 수 초 소요)")
        self.nv_hosu_check.setChecked(NAVER_HOSU_ENABLED)
        v.addWidget(self.nv_hosu_check)

        self._refresh_trade_controls()
        v.addStretch(1)
        return w

    def _load_onhouse_credentials(self):
        if not os.path.exists(self.onhouse_cred_path):
            return
        try:
            with open(self.onhouse_cred_path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            remember = bool(saved.get("remember", False))
            if not remember:
                return
            uid = str(saved.get("id", "")).strip()
            pwd = str(saved.get("pwd", "")).strip()
            if uid:
                self.oh_id.setText(uid)
            if pwd:
                self.oh_pwd.setText(pwd)
            self.oh_save_credentials.setChecked(True)
        except Exception:
            pass

    def _persist_onhouse_credentials(self, uid: str, pwd: str):
        if self.oh_save_credentials.isChecked():
            payload = {"remember": True, "id": uid, "pwd": pwd}
            try:
                with open(self.onhouse_cred_path, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
            return
        try:
            if os.path.exists(self.onhouse_cred_path):
                os.remove(self.onhouse_cred_path)
        except Exception:
            pass

    def _build_placeholder_tab(self, name: str) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel(f"{name} 탭은 다음 단계에서 엔진 연동 예정"))
        lay.addStretch(1)
        return w

    def _on_si_changed(self):
        sis = self.cb_si.checked_data()  # 빈 목록 = 전체
        entries: List[tuple] = []
        multi = len(sis) > 1
        for si in sis:
            for gun in self._region_si_gun_map.get(si, []):
                if gun == "전체":
                    continue
                label = f"{si} {gun}" if multi else gun
                entries.append((label, (si, gun)))
        self.cb_gun.set_entries(entries)  # selection_changed 발생 → _on_gun_changed

    def _on_gun_changed(self):
        guns = self.cb_gun.checked_data()  # [(si, gun), ...] / 빈 목록 = 전체
        entries: List[tuple] = []
        multi = len(guns) > 1
        for si, gun in guns:
            for dong in self._region_si_gun_gu_map.get(f"{si} {gun}", []):
                if dong == "전체":
                    continue
                label = f"{gun} {dong}" if multi else dong
                entries.append((label, (si, gun, dong)))
        self.cb_gu.set_entries(entries)

    def _on_pp_si_changed(self, si: str):
        vals = self._bbox_si_gun_map.get(si, ["전체"]) if si != "전체" else ["전체"]
        self.pp_cb_gun.blockSignals(True)
        self.pp_cb_gun.clear()
        self.pp_cb_gun.addItems(vals)
        self.pp_cb_gun.blockSignals(False)
        self._on_pp_gun_changed(self.pp_cb_gun.currentText())

    def _on_pp_gun_changed(self, gun: str):
        si = self.pp_cb_si.currentText()
        if si == "전체" or gun == "전체":
            vals = ["전체"]
        else:
            vals = self._bbox_si_gun_gu_map.get(f"{si} {gun}", ["전체"])
        self.pp_cb_gu.clear()
        self.pp_cb_gu.addItems(vals)

    def _on_oh_si_changed(self, si: str):
        vals = self._bbox_si_gun_map.get(si, ["전체"]) if si != "전체" else ["전체"]
        self.oh_cb_gun.blockSignals(True)
        self.oh_cb_gun.clear()
        self.oh_cb_gun.addItems(vals)
        self.oh_cb_gun.blockSignals(False)
        self._on_oh_gun_changed(self.oh_cb_gun.currentText())

    def _on_oh_gun_changed(self, gun: str):
        si = self.oh_cb_si.currentText()
        if si == "전체" or gun == "전체":
            vals = ["전체"]
        else:
            vals = self._bbox_si_gun_gu_map.get(f"{si} {gun}", ["전체"])
        self.oh_cb_gu.clear()
        self.oh_cb_gu.addItems(vals)

    def _on_oh_trade_changed(self):
        self._refresh_trade_controls()

    def _refresh_trade_controls(self):
        # 당근: 월세/매매/전세 체크에 따라 각 범위 입력 활성화
        if hasattr(self, "chk_month"):
            month = self.chk_month.isChecked()
            buy = self.chk_buy.isChecked()
            jeon = self.chk_borrow.isChecked()
            short = self.chk_short.isChecked()
            self.sl_month.set_enabled(month or short)
            self.sl_buy.set_enabled(buy)
            self.sl_deposit.set_enabled(month or jeon or short)
            self.sl_borrow.set_enabled(jeon)

        # 피터팬: 월세/단기면 보증금+월세, 전세면 전세, 매매면 매매가 활성화
        if hasattr(self, "pp_contract_checks"):
            month_cb = self.pp_contract_checks.get("월세")
            jeon_cb = self.pp_contract_checks.get("전세")
            buy_cb = self.pp_contract_checks.get("매매")
            short_cb = self.pp_contract_checks.get("단기임대")
            month = month_cb.isChecked() if month_cb else False
            jeon = jeon_cb.isChecked() if jeon_cb else False
            buy = buy_cb.isChecked() if buy_cb else False
            short = short_cb.isChecked() if short_cb else False
            self.pp_sl_month.set_enabled(month or short)
            self.pp_sl_deposit.set_enabled(month or short)
            self.pp_sl_jeon.set_enabled(jeon)
            self.pp_sl_price.set_enabled(buy)

        # 온하우스: 월세 체크 시 월세 활성화, 매매 체크 시 기준가 활성화
        if hasattr(self, "oh_trade_month"):
            month = self.oh_trade_month.isChecked()
            buy = self.oh_trade_buy.isChecked()
            self.oh_sl_month.set_enabled(month)
            self.oh_sl_refer.set_enabled(buy)
            self.oh_sl_price.set_enabled(month or buy)

        # 네이버: 월세/단기면 보증금+월세, 전세면 전세, 매매면 매매가 활성화
        if hasattr(self, "nv_trade_month"):
            month = self.nv_trade_month.isChecked()
            jeon = self.nv_trade_jeon.isChecked()
            buy = self.nv_trade_buy.isChecked()
            short = self.nv_trade_short.isChecked()
            self.nv_sl_rent.set_enabled(month or short)
            self.nv_sl_warr.set_enabled(month or short)
            self.nv_sl_jeon.set_enabled(jeon)
            self.nv_sl_deal.set_enabled(buy)

        self._update_trade_visuals()

    def _update_trade_visuals(self):
        def _apply(month_cb: QCheckBox | None, buy_cb: QCheckBox | None):
            if month_cb is None or buy_cb is None:
                return
            # 월세만 선택된 상태에서만 매매를 어둡게 표시
            buy_cb.setProperty("dimmed", month_cb.isChecked() and not buy_cb.isChecked())
            buy_cb.style().unpolish(buy_cb)
            buy_cb.style().polish(buy_cb)
            buy_cb.update()

        _apply(getattr(self, "chk_month", None), getattr(self, "chk_buy", None))
        _apply(
            self.pp_contract_checks.get("월세") if hasattr(self, "pp_contract_checks") else None,
            self.pp_contract_checks.get("매매") if hasattr(self, "pp_contract_checks") else None,
        )
        _apply(getattr(self, "oh_trade_month", None), getattr(self, "oh_trade_buy", None))
        _apply(getattr(self, "nv_trade_month", None), getattr(self, "nv_trade_buy", None))

    def _update_date_filter_visuals(self):
        def _apply(use_cb: QCheckBox | None, start_de: QDateEdit | None, end_de: QDateEdit | None, sep_label: QLabel | None):
            if use_cb is None or start_de is None or end_de is None:
                return
            enabled = use_cb.isChecked()
            for w in (start_de, end_de):
                w.setProperty("dimmed", not enabled)
                w.style().unpolish(w)
                w.style().polish(w)
                w.update()
            if sep_label is not None:
                sep_label.setProperty("dimmed", not enabled)
                sep_label.style().unpolish(sep_label)
                sep_label.style().polish(sep_label)
                sep_label.update()

        _apply(
            getattr(self, "date_use", None),
            getattr(self, "date_start", None),
            getattr(self, "date_end", None),
            getattr(self, "date_range_sep", None),
        )
        _apply(
            getattr(self, "pp_date_use", None),
            getattr(self, "pp_date_start", None),
            getattr(self, "pp_date_end", None),
            getattr(self, "pp_date_range_sep", None),
        )

    def _on_nv_si_changed(self):
        sis = self.nv_cb_si.checked_data()
        entries: List[tuple] = []
        multi = len(sis) > 1
        for si in sis:
            for gu in self._nv_rls_si_gu_map.get(si, []):
                if gu == "전체":
                    continue
                label = f"{si} {gu}" if multi else gu
                entries.append((label, (si, gu)))
        self.nv_cb_gun.set_entries(entries)

    def _on_nv_gun_changed(self):
        guns = self.nv_cb_gun.checked_data()
        entries: List[tuple] = []
        multi = len(guns) > 1
        for si, gu in guns:
            for dong in self._nv_rls_si_gu_dong_map.get(f"{si} {gu}", []):
                if dong == "전체":
                    continue
                label = f"{gu} {dong}" if multi else dong
                entries.append((label, (si, gu, dong)))
        self.nv_cb_gu.set_entries(entries)

    def _selected_regions_for(self, si: str, gun: str, gu: str, source: str = "daangn") -> List[str]:
        all_names = list(self.regions_bbox.keys()) if source == "bbox" else list(self.regions_name_to_incode.keys())
        if si == "전체":
            return sorted(all_names)
        if gun == "전체":
            return sorted([n for n in all_names if n.startswith(si + " ")])
        prefix = f"{si} {gun}"
        if gu == "전체":
            return sorted([n for n in all_names if n.startswith(prefix + " ")])
        return sorted([n for n in all_names if n.startswith(prefix + " " + gu)])

    def _regions_from_multi(self, sis: List[str], guns: List[tuple], dongs: List[tuple], source: str = "daangn") -> List[str]:
        """다중선택 체크 상태 → 지역명 목록. 가장 하위(동) 선택이 있으면 그것만 사용."""
        all_names = list(self.regions_bbox.keys()) if source == "bbox" else list(self.regions_name_to_incode.keys())
        if dongs:
            prefixes = [f"{si} {gun} {dong}" for (si, gun, dong) in dongs]
        elif guns:
            prefixes = [f"{si} {gun} " for (si, gun) in guns]
        elif sis:
            prefixes = [f"{si} " for si in sis]
        else:
            return sorted(all_names)
        return sorted({n for n in all_names if any(n.startswith(p) for p in prefixes)})

    def _regions_from_multi_nv(self, sis: List[str], guns: List[tuple], dongs: List[tuple]) -> List[str]:
        """naver_rls 기준 다중선택 → '시 구 동' 지역명 목록."""
        rls = self.naver_rls or {}
        out: set = set()
        if dongs:
            for si, gu, dong in dongs:
                if dong in (rls.get(si, {}).get(gu, {}) or {}):
                    out.add(f"{si} {gu} {dong}")
        elif guns:
            for si, gu in guns:
                for dong in (rls.get(si, {}).get(gu, {}) or {}):
                    out.add(f"{si} {gu} {dong}")
        elif sis:
            for si in sis:
                for gu, dong_map in (rls.get(si) or {}).items():
                    for dong in dong_map:
                        out.add(f"{si} {gu} {dong}")
        else:
            for si, gu_map in rls.items():
                for gu, dong_map in gu_map.items():
                    for dong in dong_map:
                        out.add(f"{si} {gu} {dong}")
        return sorted(out)

    @staticmethod
    def _region_label_multi(sis: List[str], guns: List[tuple], dongs: List[tuple]) -> str:
        """다중선택 → 파일명용 지역 라벨 (예: 서울시_강남구_역삼동외2)."""
        def part(vals, pick):
            if not vals:
                return "전체"
            first = pick(vals[0])
            return first if len(vals) == 1 else f"{first}외{len(vals) - 1}"

        s = "_".join(
            [
                part(sis, lambda v: v),
                part(guns, lambda v: v[1]),
                part(dongs, lambda v: v[2]),
            ]
        )
        s = s.replace(" ", "_").replace("/", "_")
        for ch in '\\/:*?"<>|':
            s = s.replace(ch, "")
        return s or "전체_전체_전체"

    @staticmethod
    def _region_for_filename(si: str, gun: str, gu: str) -> str:
        s = f"{si}_{gun}_{gu}".strip("_")
        s = s.replace(" ", "_")
        s = s.replace("/", "_")
        for ch in '\\/:*?"<>|':
            s = s.replace(ch, "")
        return s if s else "전체_전체_전체"

    def _pp_deposit_min(self) -> int:
        """피터팬: 월세 보증금 / 전세 중 활성화된 슬라이더의 min 값 (만→원 변환)."""
        month_on = self.pp_contract_checks.get("월세", QCheckBox()).isChecked() or self.pp_contract_checks.get("단기임대", QCheckBox()).isChecked()
        jeon_on = self.pp_contract_checks.get("전세", QCheckBox()).isChecked()
        vals = []
        if month_on:
            vals.append(self.pp_sl_deposit.values()[0] * 10000)
        if jeon_on:
            vals.append(self.pp_sl_jeon.values()[0] * 10000)
        return min(vals) if vals else 0

    def _pp_deposit_max(self) -> int:
        month_on = self.pp_contract_checks.get("월세", QCheckBox()).isChecked() or self.pp_contract_checks.get("단기임대", QCheckBox()).isChecked()
        jeon_on = self.pp_contract_checks.get("전세", QCheckBox()).isChecked()
        vals = []
        if month_on:
            vals.append(self.pp_sl_deposit.values()[1] * 10000)
        if jeon_on:
            vals.append(self.pp_sl_jeon.values()[1] * 10000)
        return max(vals) if vals else 500000000

    def _make_daangn_worker(self, params: dict):
        return DaangnWorker(params)

    def _make_naver_worker(self, params: dict):
        return NaverWorker(params)

    def _on_start(self):
        tab_idx = self.tabs.currentIndex()
        if tab_idx == 0:
            self._start_daangn()
            return
        if tab_idx == 1:
            self._start_naver()
            return
        QMessageBox.information(self, "안내", "지원하지 않는 탭입니다.")

    def _start_daangn(self):
        trade = []
        if self.chk_month.isChecked():
            trade.append("month")
        if self.chk_buy.isChecked():
            trade.append("buy")
        if self.chk_borrow.isChecked():
            trade.append("borrow")
        if self.chk_short.isChecked():
            trade.append("short")
        if not trade:
            QMessageBox.warning(self, "오류", "거래유형을 하나 이상 선택하세요.")
            return
        sales = [k for k, cb in self.sales_checks.items() if cb.isChecked()]
        if not sales:
            sales = ["two_room"]
        writer_types = []
        if self.chk_dg_broker.isChecked():
            writer_types.append("BROKER")
        if self.chk_dg_direct.isChecked():
            writer_types.append("DIRECT_USER")
        if not writer_types:
            QMessageBox.warning(self, "오류", "거래주체(공인중개사/직거래)를 하나 이상 선택하세요.")
            return
        date_start = date_end = None
        if self.date_use.isChecked():
            date_start = self.date_start.date().toString("yyyyMMdd")
            date_end = self.date_end.date().toString("yyyyMMdd")

        def _rng(values, full_min, full_max):
            # 직접입력(RangeInput): 최소가 기본값 이하이고 최대가 빈칸(제한없음)일 때만 필터 미적용
            lo, hi = values
            return None if (lo <= full_min and hi >= RangeInput.OPEN_MAX) else (lo, hi)

        ts = datetime.now().strftime("%y%m%d_%H%M%S")
        out_dir = os.path.join(self.base_dir, "data")
        os.makedirs(out_dir, exist_ok=True)
        dg_sis = self.cb_si.checked_data()
        dg_guns = self.cb_gun.checked_data()
        dg_dongs = self.cb_gu.checked_data()
        region_for_file = self._region_label_multi(dg_sis, dg_guns, dg_dongs)
        params = {
            "regions": self._regions_from_multi(dg_sis, dg_guns, dg_dongs),
            "regions_name_to_incode": self.regions_name_to_incode,
            "monthly_min": self.sl_month.values()[0],
            "monthly_max": self.sl_month.values()[1],
            "deposit_min": self.sl_deposit.values()[0],
            "deposit_max": self.sl_deposit.values()[1],
            "buy_min": self.sl_buy.values()[0],
            "buy_max": self.sl_buy.values()[1],
            "borrow_min": self.sl_borrow.values()[0],
            "borrow_max": self.sl_borrow.values()[1],
            "area_min": self.sl_area.values()[0],
            "area_max": self.sl_area.values()[1],
            "sales_type": ",".join(sales),
            "trade_type": ",".join(trade),
            "date_start": date_start,
            "date_end": date_end,
            "detail_keywords": _parse_keywords_csv(self.dg_detail_filter.text()),
            "detail_rooms": _rng(self.dg_sl_rooms.values(), 0, 10),
            "detail_floors": _rng(self.dg_sl_floor.values(), 0, 50),
            "detail_years": _rng(self.dg_sl_builtyear.values(), 1970, 2026),
            "detail_uses": self.dg_use_group.selected(),
            "writer_types": writer_types,
            "site_name": "당근",
            "region_for_file": region_for_file,
            "timestamp": ts,
            "out_dir": out_dir,
        }
        self._prepare_worker_start()
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.progress_bar.setValue(0)
        self.progress_text.setText("실행 중")
        self.progress_count.setText(f"0/{len(params['regions'])}")
        self.worker_thread = QThread(self)
        self.worker = DaangnWorker(params)
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.row_ready.connect(self._append_log)
        self.worker.status.connect(self.progress_text.setText)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.failed.connect(self.worker_thread.quit)
        self.worker_thread.finished.connect(self._cleanup_worker)
        self.worker_thread.start()
        self._show_log_dialog()

    def _start_peterpan(self):
        contract_types = [k for k, cb in self.pp_contract_checks.items() if cb.isChecked()]
        building_types = [k for k, cb in self.pp_building_checks.items() if cb.isChecked()]
        if not contract_types:
            QMessageBox.warning(self, "오류", "거래유형을 하나 이상 선택하세요.")
            return
        building = "원/투룸" if not building_types else None
        only_onetwo = (not building_types) or (building_types == ["원/투룸"])
        reg_start = reg_end = None
        if self.pp_date_use.isChecked():
            reg_start = self.pp_date_start.date().toString("yyyy-MM-dd")
            reg_end = self.pp_date_end.date().toString("yyyy-MM-dd")
        ts = datetime.now().strftime("%y%m%d_%H%M%S")
        out_dir = os.path.join(self.base_dir, "data")
        os.makedirs(out_dir, exist_ok=True)
        region_for_file = self._region_for_filename(
            self.pp_cb_si.currentText() or "전체",
            self.pp_cb_gun.currentText() or "전체",
            self.pp_cb_gu.currentText() or "전체",
        )
        params = {
            "regions": self._selected_regions_for(
                self.pp_cb_si.currentText(),
                self.pp_cb_gun.currentText(),
                self.pp_cb_gu.currentText(),
                source="bbox",
            ),
            "regions_bbox": self.regions_bbox,
            "building_type": building or "",
            "deposit_min": self._pp_deposit_min(),
            "deposit_max": self._pp_deposit_max(),
            "month_min": self.pp_sl_month.values()[0] * 10000,
            "month_max": self.pp_sl_month.values()[1] * 10000,
            "size_min": float(self.pp_sl_size.values()[0]),
            "size_max": float(self.pp_sl_size.values()[1]),
            "price_min": (self.pp_sl_price.values()[0] * 10000) if not only_onetwo else None,
            "price_max": (self.pp_sl_price.values()[1] * 10000) if not only_onetwo else None,
            "contract_types": contract_types,
            "building_types": building_types if building_types else None,
            "detail_keywords": _parse_keywords_csv(self.pp_detail_filter.text()),
            "registered_date_start": reg_start,
            "registered_date_end": reg_end,
            "site_name": "피터팬",
            "region_for_file": region_for_file,
            "timestamp": ts,
            "out_dir": out_dir,
        }
        self._prepare_worker_start()
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.progress_bar.setValue(0)
        self.progress_text.setText("실행 중")
        self.progress_count.setText(f"0/{len(params['regions'])}")
        self.worker_thread = QThread(self)
        self.worker = PeterpanWorker(params)
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.row_ready.connect(self._append_log)
        self.worker.status.connect(self.progress_text.setText)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.failed.connect(self.worker_thread.quit)
        self.worker_thread.finished.connect(self._cleanup_worker)
        self.worker_thread.start()

    def _start_onhouse(self):
        uid = self.oh_id.text().strip()
        pwd = self.oh_pwd.text().strip()
        if not uid or not pwd:
            QMessageBox.warning(self, "오류", "온하우스 아이디/비밀번호를 입력하세요.")
            return

        trade_types: List[str] = []
        if self.oh_trade_month.isChecked():
            trade_types.append("월세")
        if self.oh_trade_buy.isChecked():
            trade_types.append("매매")
        if not trade_types:
            QMessageBox.warning(self, "오류", "거래유형(월세/매매)을 하나 이상 선택하세요.")
            return
        self._persist_onhouse_credentials(uid, pwd)

        def _bounds_or_none(values: tuple[int, int], full_min: int, full_max: int) -> tuple[int | None, int | None]:
            lo, hi = values
            if lo <= full_min and hi >= full_max:
                return None, None
            return lo, hi

        month_min = month_max = None
        if self.oh_trade_month.isChecked():
            month_min, month_max = _bounds_or_none(self.oh_sl_month.values(), 0, 3000)

        price_min = price_max = None
        if self.oh_trade_month.isChecked() or self.oh_trade_buy.isChecked():
            price_min, price_max = _bounds_or_none(self.oh_sl_price.values(), 0, 100000)

        refer_min, refer_max = _bounds_or_none(self.oh_sl_refer.values(), 0, 1000000)
        area_min, area_max = _bounds_or_none(self.oh_sl_area.values(), 0, 200)

        ts = datetime.now().strftime("%y%m%d_%H%M%S")
        out_dir = os.path.join(self.base_dir, "data")
        os.makedirs(out_dir, exist_ok=True)
        region_for_file = self._region_for_filename(
            self.oh_cb_si.currentText() or "전체",
            self.oh_cb_gun.currentText() or "전체",
            self.oh_cb_gu.currentText() or "전체",
        )
        params = {
            "uid": uid,
            "pwd": pwd,
            "regions": self._selected_regions_for(
                self.oh_cb_si.currentText(),
                self.oh_cb_gun.currentText(),
                self.oh_cb_gu.currentText(),
                source="bbox",
            ),
            "regions_bbox": self.regions_bbox,
            "trade_types": trade_types,
            "room_type": "all" if (self.oh_room_type.currentText() or "전체") == "전체" else self.oh_room_type.currentText(),
            "refer_min": refer_min,
            "refer_max": refer_max,
            "price_min": price_min,
            "price_max": price_max,
            "month_min": month_min,
            "month_max": month_max,
            "area_min": area_min,
            "area_max": area_max,
            "site_name": "온하우스",
            "region_for_file": region_for_file,
            "timestamp": ts,
            "out_dir": out_dir,
        }
        self._prepare_worker_start()
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.progress_bar.setValue(0)
        self.progress_text.setText("실행 중")
        self.progress_count.setText(f"0/{len(params['regions'])}")
        self.worker_thread = QThread(self)
        self.worker = OnhouseWorker(params)
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.row_ready.connect(self._append_log)
        self.worker.status.connect(self.progress_text.setText)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.failed.connect(self.worker_thread.quit)
        self.worker_thread.finished.connect(self._cleanup_worker)
        self.worker_thread.start()

    def _naver_keywords(self) -> List[str]:
        """입력 키워드 + 체크된 키워드 (중복 제거, 순서 유지)."""
        out: List[str] = []
        for k in _parse_keywords_csv(self.nv_detail_filter.text()):
            if k and k.lower() not in [x.lower() for x in out]:
                out.append(k)
        for kw, cb in getattr(self, "nv_kw_checks", {}).items():
            if cb.isChecked() and kw.lower() not in [x.lower() for x in out]:
                out.append(kw)
        return out

    def _start_naver(self):
        nv_sis = self.nv_cb_si.checked_data()
        nv_guns = self.nv_cb_gun.checked_data()
        nv_dongs = self.nv_cb_gu.checked_data()
        if not nv_sis:
            QMessageBox.warning(self, "오류", "네이버: 시/도를 하나 이상 선택하세요.")
            return

        selected_types = [code for code, cb in self.nv_type_checks.items() if cb.isChecked()]
        realestate_type = ":".join(selected_types) if selected_types else "APT:ABYG:JGC:PRE"

        trade_tokens: List[str] = []
        if self.nv_trade_buy.isChecked():
            trade_tokens.append("A1")
        if self.nv_trade_jeon.isChecked():
            trade_tokens.append("B1")
        if self.nv_trade_month.isChecked():
            trade_tokens.append("B2")
        if self.nv_trade_short.isChecked():
            trade_tokens.append("B3")
        trade_type = ":".join(trade_tokens) if trade_tokens else None

        def _bounds_or_none(values: tuple[int, int], full_min: int, full_max: int) -> tuple[int | None, int | None]:
            # 직접입력(RangeInput): 빈 최소(0)→None, 빈 최대(제한없음)→None (각각 독립 판정)
            lo, hi = values
            lo_out = None if lo <= full_min else lo
            hi_out = None if hi >= RangeInput.OPEN_MAX else hi
            return lo_out, hi_out

        # 상세 필터(방수/층수/사용승인일)는 DetailFilters가 None(미적용) 또는 (lo, hi) 튜플을 받는다.
        # (None, None) 튜플을 넘기면 DetailFilters._num_ok에서 None 비교로 예외가 나므로 전체 범위는 None으로 준다.
        def _rng(values: tuple[int, int], full_min: int, full_max: int):
            lo, hi = values
            return None if (lo <= full_min and hi >= RangeInput.OPEN_MAX) else (lo, hi)

        min_deal, max_deal = _bounds_or_none(self.nv_sl_deal.values(), 0, 1000000)
        min_rent, max_rent = _bounds_or_none(self.nv_sl_rent.values(), 0, 3000)
        min_area, max_area = _bounds_or_none(self.nv_sl_area.values(), 0, 231)

        # 보증금(월세용) + 전세 슬라이더를 합산하여 wprc 파라미터 생성
        month_on = self.nv_trade_month.isChecked() or self.nv_trade_short.isChecked()
        jeon_on = self.nv_trade_jeon.isChecked()
        warr_vals = []
        if month_on:
            lo, hi = _bounds_or_none(self.nv_sl_warr.values(), 0, 50000)
            if lo is not None or hi is not None:
                warr_vals.append((lo, hi))
        if jeon_on:
            lo, hi = _bounds_or_none(self.nv_sl_jeon.values(), 0, 1000000)
            if lo is not None or hi is not None:
                warr_vals.append((lo, hi))
        if warr_vals:
            lows = [v[0] for v in warr_vals if v[0] is not None]
            highs = [v[1] for v in warr_vals if v[1] is not None]
            min_warr = min(lows) if lows else None
            max_warr = max(highs) if highs else None
        else:
            min_warr, max_warr = None, None
        max_days = {"전체": None, "오늘": 1, "어제/오늘": 2, "일주일": 7, "한달": 30}.get(self.nv_date_preset.currentText(), None)
        min_date = (datetime.now() - timedelta(days=max_days)) if max_days else None

        region_names = self._regions_from_multi_nv(nv_sis, nv_guns, nv_dongs)
        if not region_names:
            QMessageBox.warning(self, "오류", "선택한 지역에 해당하는 동이 없습니다. (naver_rls.json 확인)")
            return

        ts = datetime.now().strftime("%y%m%d_%H%M%S")
        out_dir = os.path.join(self.base_dir, "data")
        os.makedirs(out_dir, exist_ok=True)
        region_for_file = self._region_label_multi(nv_sis, nv_guns, nv_dongs)
        params = {
            "rls_path": os.path.join(self.resource_dir, "naver_rls.json"),
            "realestate_type": realestate_type,
            "trade_type": trade_type,
            "regions_bbox": self.regions_bbox,
            "region_names": region_names,
            "min_date": min_date,
            "min_deal": min_deal,
            "max_deal": max_deal,
            "min_warr": min_warr,
            "max_warr": max_warr,
            "min_rent": min_rent,
            "max_rent": max_rent,
            "min_area": min_area,
            "max_area": max_area,
            "detail_keywords": self._naver_keywords(),
            "detail_rooms": _rng(self.nv_sl_rooms.values(), 0, 10),
            "detail_floors": _rng(self.nv_sl_floor.values(), 0, 50),
            "detail_years": _rng(self.nv_sl_builtyear.values(), 1970, 2026),
            "detail_uses": self.nv_use_group.selected(),
            "hosu_enabled": self.nv_hosu_check.isChecked(),
            "site_name": "네이버",
            "region_for_file": region_for_file,
            "timestamp": ts,
            "out_dir": out_dir,
        }
        self._prepare_worker_start()
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.progress_bar.setValue(0)
        self.progress_text.setText("실행 중")
        self.progress_count.setText("0/0")
        self.worker_thread = QThread(self)
        self.worker = NaverWorker(params)
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.row_ready.connect(self._append_log)
        self.worker.status.connect(self._on_naver_status)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.failed.connect(self.worker_thread.quit)
        self.worker_thread.finished.connect(self._cleanup_worker)
        self.worker_thread.start()
        self._show_log_dialog()

    def _on_stop(self):
        if self.worker:
            self.worker.cancel()
            self.progress_text.setText("중단 요청됨...")

    def _prepare_worker_start(self):
        self._last_output_path = None

    def _data_dir(self) -> str:
        d = os.path.join(self.base_dir, "data")
        os.makedirs(d, exist_ok=True)
        return d

    def _latest_output_in_data_dir(self):
        try:
            d = self._data_dir()
            files = [
                os.path.join(d, f)
                for f in os.listdir(d)
                if f.lower().endswith(".xlsx") and not f.startswith("~$")
            ]
            files = [f for f in files if os.path.isfile(f)]
            return max(files, key=os.path.getmtime) if files else None
        except Exception:
            return None

    def _on_open_output_file(self):
        # 1) 이번 세션 마지막 저장 파일 → 2) data 폴더 최신 엑셀 → 3) data 폴더
        target = self._last_output_path
        if not (target and os.path.isfile(target)):
            target = self._latest_output_in_data_dir()
        try:
            if target:
                open_path_in_os(target)
            else:
                d = self._data_dir()
                if sys.platform == "win32":
                    os.startfile(d)  # type: ignore[attr-defined]
                else:
                    import subprocess

                    subprocess.run(
                        ["open" if sys.platform == "darwin" else "xdg-open", d],
                        check=False,
                    )
        except Exception as e:
            QMessageBox.warning(self, "파일 열기 실패", str(e))

    def _on_progress(self, current: int, total: int):
        self.progress_bar.setRange(0, 100)
        pct = int(100 * current / max(1, total))
        self.progress_bar.setValue(pct)
        self.progress_count.setText(f"{current}/{total}")

    def _on_naver_status(self, msg: str):
        text = str(msg or "").strip()
        self.progress_text.setText(text)

    def _on_finished(self, msg: str):
        self.progress_bar.setRange(0, 100)
        self.progress_text.setText(msg)
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self._last_output_path = parse_saved_output_path_from_finish_message(msg)

    def _on_failed(self, msg: str):
        self.progress_bar.setRange(0, 100)
        QMessageBox.critical(self, "실패", msg)
        self.progress_text.setText("실패")
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self._last_output_path = None

    def _cleanup_worker(self):
        self.worker = None
        self.worker_thread = None

    @staticmethod
    def item_to_display_row(row: Any) -> tuple:
        r = row if isinstance(row, dict) else {}

        # 온하우스 상세 키가 있으면 온하우스 전용 매핑을 우선 사용
        if any(k in r for k in ("건물명", "전체주소", "주소_호실", "물건번호")):
            no = str(r.get("매물ID") or r.get("물건번호") or "-").strip()
            region = str(r.get("전체주소") or r.get("주소_호실") or r.get("지번") or "-").strip()
            kind = str(
                r.get("매물종류")
                or r.get("매물유형")
                or r.get("종류")
                or "-"
            ).strip()
            trade = str(
                r.get("거래유형/가격")
                or r.get("거래유형")
                or r.get("거래방식")
                or "-"
            ).strip()
            name = str(r.get("건물명") or r.get("물건번호") or no or "-").strip()
            return (no or "-", region or "-", kind or "-", trade or "-", name or "-")

        def _pick(*exact_keys: str) -> str:
            for k in exact_keys:
                v = r.get(k)
                if v is not None and str(v).strip():
                    return str(v).strip()
            return ""

        def _pick_by_key_contains(*needles: str) -> str:
            for k, v in r.items():
                key = str(k)
                if all(n in key for n in needles):
                    if v is not None and str(v).strip():
                        return str(v).strip()
            return ""

        no = (
            _pick("매물번호", "매물ID", "id")
            or _pick_by_key_contains("매물", "번호")
            or _pick_by_key_contains("ID")
            or "-"
        )
        region = (
            _pick("지번주소", "주소", "전체주소", "위치정보_주소", "주소_도로명", "매물지역")
            or _pick_by_key_contains("주소")
            or _pick_by_key_contains("위치")
            or _pick_by_key_contains("지역")
            or "-"
        )
        kind = (
            _pick("부동산종류", "매물유형", "매물정보_매물종류", "매물정보_유형")
            or _pick_by_key_contains("종류")
            or _pick_by_key_contains("유형")
            or "-"
        )
        trade = (
            _pick("거래방식", "거래유형", "거래정보_거래형태", "거래정보_거래유형", "거래정보_거래가격")
            or _pick_by_key_contains("거래", "형태")
            or _pick_by_key_contains("거래", "유형")
            or _pick_by_key_contains("거래", "가격")
            or _pick_by_key_contains("거래")
            or "-"
        )
        name = (
            _pick("매물명", "제목", "매물정보_제목", "건물명")
            or _pick_by_key_contains("제목")
            or _pick("물건번호")
            or "-"
        )
        return (no, region, kind, trade, name)

    def _append_log(self, row: Iterable[str]):
        row_tuple = tuple(str(v) for v in row)
        self.log_rows.append(row_tuple)
        if self.log_dialog_table is not None:
            sb = self.log_dialog_table.verticalScrollBar()
            follow_tail = sb.value() >= (sb.maximum() - max(2, sb.singleStep()))
            r = self.log_dialog_table.rowCount()
            self.log_dialog_table.insertRow(r)
            for i, v in enumerate(self._format_log_row_for_display(row_tuple)):
                item = QTableWidgetItem(v)
                if i < len(row_tuple):
                    item.setToolTip(row_tuple[i])
                self.log_dialog_table.setItem(r, i, item)
            if follow_tail:
                # insertRow 직후에는 스크롤 최대값이 아직 갱신 전일 수 있어 다음 틱에 이동
                QTimer.singleShot(0, self.log_dialog_table.scrollToBottom)

    def _clear_log(self):
        self.log_rows.clear()
        if self.log_dialog_table is not None:
            self.log_dialog_table.setRowCount(0)
        self.progress_text.setText("대기 중")
        self.progress_bar.setValue(0)
        self.progress_count.setText("0/0")

    def _show_log_dialog(self):
        if self.log_dialog is None:
            dlg = QDialog(self)
            dlg.setModal(False)
            dlg.setWindowTitle("수집 로그")
            # 최소화(-)/최대화 버튼 추가 — X만 있으면 닫을 때 수집이 멈출까 불안해하므로
            dlg.setWindowFlags(
                dlg.windowFlags()
                | Qt.WindowMinimizeButtonHint
                | Qt.WindowMaximizeButtonHint
            )
            dlg.resize(1050, 520)
            lay = QVBoxLayout(dlg)
            notice = QLabel(
                "ℹ 이 창은 보기용입니다. 닫거나(✕) 최소화(－)해도 수집은 멈추지 않고 계속 진행됩니다 — 다른 작업을 하셔도 됩니다."
            )
            notice.setWordWrap(True)
            notice.setStyleSheet(
                "color:#94a3b8; font-size:11px; font-weight:400; padding:2px 4px;"
            )
            lay.addWidget(notice)
            table = QTableWidget(0, 5)
            table.setHorizontalHeaderLabels(["매물번호", "매물지역", "부동산종류", "거래방식", "매물명"])
            table.setColumnWidth(0, 110)
            table.setColumnWidth(1, 240)
            table.setColumnWidth(2, 130)
            table.setColumnWidth(3, 160)
            table.setColumnWidth(4, 520)
            table.horizontalHeader().setStretchLastSection(True)
            table.setAlternatingRowColors(True)
            table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            lay.addWidget(table)
            self.log_dialog = dlg
            self.log_dialog_table = table
        # 매번 최신 데이터로 동기화
        self.log_dialog_table.setRowCount(0)
        for row in self.log_rows:
            r = self.log_dialog_table.rowCount()
            self.log_dialog_table.insertRow(r)
            for i, v in enumerate(self._format_log_row_for_display(row)):
                item = QTableWidgetItem(v)
                if i < len(row):
                    item.setToolTip(row[i])
                self.log_dialog_table.setItem(r, i, item)
        self.log_dialog_table.scrollToBottom()
        self.log_dialog.show()
        self.log_dialog.raise_()
        self.log_dialog.activateWindow()

    @staticmethod
    def _format_log_row_for_display(row: Iterable[str]) -> tuple:
        vals = [str(v) for v in row]
        return tuple(vals[i] if i < len(vals) else "-" for i in range(5))

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

