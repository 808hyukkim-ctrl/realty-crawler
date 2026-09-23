"""예약 수집 기능 mixin. app_v1_main / app_v1_site_main / app_v2_main의 MainWindow에서 상속."""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta
from typing import Optional

from PySide6.QtCore import QThread, QTimer
from PySide6.QtWidgets import QMessageBox

from app_main_common import RangeInput, parse_keywords_csv as _parse_keywords_csv
from schedule_dialog import ScheduleAddDialog, ScheduleListDialog
from schedule_manager import ScheduleManager, ScheduledJob


class ScheduleMixin:
    # ──────────────────────────────────────────────────────────────
    # 초기화: MainWindow.__init__ 끝에서 호출
    # ──────────────────────────────────────────────────────────────

    def _init_schedule(self):
        self._schedule_manager = ScheduleManager(
            os.path.join(self.base_dir, "schedules.json")
        )
        self._schedule_timer = QTimer(self)
        self._schedule_timer.timeout.connect(self._check_due_schedules)
        self._schedule_timer.start(30_000)  # 30초마다 만료 체크

    # ──────────────────────────────────────────────────────────────
    # 타이머 콜백
    # ──────────────────────────────────────────────────────────────

    def _check_due_schedules(self):
        if getattr(self, "worker", None) is not None:
            return  # 수집 중이면 건너뜀
        for job in self._schedule_manager.get_due_jobs():
            self._schedule_manager.mark_ran(job.id)
            self._run_scheduled_job(job)
            break  # 한 번에 하나씩

    # ──────────────────────────────────────────────────────────────
    # 예약 실행
    # ──────────────────────────────────────────────────────────────

    def _run_scheduled_job(self, job: ScheduledJob):
        if job.site == "daangn":
            params = self._scheduled_daangn_params(job.settings)
            if params:
                params["schedule_name"] = job.name
                params["file_name"] = (job.settings or {}).get("file_name") or ""
                worker = self._make_daangn_worker(params)
                self._launch_scheduled_worker(worker, params, f"당근(예약:{job.name})")
            else:
                self.progress_text.setText(f"예약 오류: {job.name} — 지역 없음")
        elif job.site == "naver":
            params = self._scheduled_naver_params(job.settings)
            if params:
                params["schedule_name"] = job.name
                params["file_name"] = (job.settings or {}).get("file_name") or ""
                worker = self._make_naver_worker(params)
                self._launch_scheduled_worker(worker, params, f"네이버(예약:{job.name})")
            else:
                self.progress_text.setText(f"예약 오류: {job.name} — 지역 없음")

    def _launch_scheduled_worker(self, worker, params: dict, label: str):
        self._prepare_worker_start()
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.progress_bar.setValue(0)
        self.progress_text.setText(f"{label} 수집 중")
        region_count = len(params.get("regions") or params.get("region_names", []))
        self.progress_count.setText(f"0/{region_count}")

        self.worker_thread = QThread(self)
        self.worker = worker
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

    # ──────────────────────────────────────────────────────────────
    # settings → worker params 변환
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    def _multi_region_args(s: dict) -> tuple:
        """설정 dict의 다중선택 키 → (_regions_from_multi 계열 인자) 튜플."""
        return (
            list(s.get("si_list") or []),
            [tuple(x) for x in (s.get("gun_list") or [])],
            [tuple(x) for x in (s.get("dong_list") or [])],
        )

    def _scheduled_daangn_params(self, s: dict) -> Optional[dict]:
        if "si_list" in s:  # 다중선택(신규) 형식
            sis, guns, dongs = self._multi_region_args(s)
            regions = self._regions_from_multi(sis, guns, dongs)
            region_for_file = self._region_label_multi(sis, guns, dongs)
        else:  # 단일선택(구버전) 형식
            regions = self._selected_regions_for(
                s.get("si", "전체"), s.get("gun", "전체"), s.get("gu", "전체")
            )
            region_for_file = self._region_for_filename(
                s.get("si", "전체"), s.get("gun", "전체"), s.get("gu", "전체")
            )
        if not regions:
            return None
        ts = datetime.now().strftime("%y%m%d_%H%M%S")
        out_dir = os.path.join(self.base_dir, "data")
        os.makedirs(out_dir, exist_ok=True)
        return {
            "regions": regions,
            "regions_name_to_incode": self.regions_name_to_incode,
            "monthly_min": s.get("monthly_min", 0),
            "monthly_max": s.get("monthly_max", 3000),
            "deposit_min": s.get("deposit_min", 0),
            "deposit_max": s.get("deposit_max", 50000),
            "buy_min": s.get("buy_min", 0),
            "buy_max": s.get("buy_max", 1000000),
            "borrow_min": s.get("borrow_min", 0),
            "borrow_max": s.get("borrow_max", 1000000),
            "area_min": s.get("area_min", 0),
            "area_max": s.get("area_max", 200),
            "sales_type": s.get("sales_type", "two_room"),
            "trade_type": s.get("trade_type", "month"),
            "date_start": s.get("date_start"),
            "date_end": s.get("date_end"),
            "detail_keywords": s.get("detail_keywords", []),
            "detail_uses": s.get("detail_uses", []),
            "writer_types": s.get("writer_types") or ["BROKER", "DIRECT_USER"],
            "site_name": "당근",
            "region_for_file": region_for_file,
            "timestamp": ts,
            "out_dir": out_dir,
        }

    def _scheduled_naver_params(self, s: dict) -> Optional[dict]:
        si = s.get("si", "전체")
        gun = s.get("gun", "전체")
        gu = s.get("gu", "전체")
        if "si_list" in s:  # 다중선택(신규) 형식
            sis, guns, dongs = self._multi_region_args(s)
            region_names = self._regions_from_multi_nv(sis, guns, dongs)
            region_for_file = self._region_label_multi(sis, guns, dongs)
        else:
            region_names = self._selected_regions_for_nv(si, gun, gu)
            region_for_file = self._region_for_filename(si, gun, gu)
        if not region_names:
            return None

        preset = s.get("date_preset", "전체")
        max_days = {"오늘": 1, "어제/오늘": 2, "일주일": 7, "한달": 30}.get(preset)
        min_date = (datetime.now() - timedelta(days=max_days)) if max_days else None

        ts = datetime.now().strftime("%y%m%d_%H%M%S")
        out_dir = os.path.join(self.base_dir, "data")
        os.makedirs(out_dir, exist_ok=True)
        return {
            "mode": "crawl",
            "rls_path": os.path.join(self.resource_dir, "naver_rls.json"),
            "realestate_type": s.get("realestate_type", "APT:OPST:VL:OR"),
            "trade_type": s.get("trade_type") or None,
            "regions_bbox": self.regions_bbox,
            "region_names": region_names,
            "min_date": min_date,
            "min_deal": s.get("min_deal"),
            "max_deal": s.get("max_deal"),
            "min_warr": s.get("min_warr"),
            "max_warr": s.get("max_warr"),
            "min_rent": s.get("min_rent"),
            "max_rent": s.get("max_rent"),
            "min_area": s.get("min_area"),
            "max_area": s.get("max_area"),
            "detail_keywords": s.get("detail_keywords", []),
            "detail_uses": s.get("detail_uses", []),
            "hosu_enabled": bool(s.get("hosu_enabled", True)),
            "site_name": "네이버",
            "region_for_file": region_for_file,
            "timestamp": ts,
            "out_dir": out_dir,
        }

    # ──────────────────────────────────────────────────────────────
    # UI 현재 설정 수집 (예약 저장용)
    # ──────────────────────────────────────────────────────────────

    def _collect_daangn_settings(self) -> Optional[dict]:
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
            return None
        sales = [k for k, cb in self.sales_checks.items() if cb.isChecked()] or ["two_room"]
        date_start = date_end = None
        if self.date_use.isChecked():
            date_start = self.date_start.date().toString("yyyyMMdd")
            date_end = self.date_end.date().toString("yyyyMMdd")
        if hasattr(self.cb_si, "checked_data"):  # 다중선택 콤보
            region_part = {
                "si_list": list(self.cb_si.checked_data()),
                "gun_list": [list(t) for t in self.cb_gun.checked_data()],
                "dong_list": [list(t) for t in self.cb_gu.checked_data()],
            }
        else:  # 단일선택 콤보 (구버전 UI)
            region_part = {
                "si": self.cb_si.currentText() or "전체",
                "gun": self.cb_gun.currentText() or "전체",
                "gu": self.cb_gu.currentText() or "전체",
            }
        return {
            **region_part,
            "trade_type": ",".join(trade),
            "sales_type": ",".join(sales),
            "date_use": self.date_use.isChecked(),
            "date_start": date_start,
            "date_end": date_end,
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
            "detail_keywords": _parse_keywords_csv(self.dg_detail_filter.text()),
            "detail_uses": self.dg_use_group.selected() if hasattr(self, "dg_use_group") else [],
            "writer_types": [
                w for w, cb in (("BROKER", getattr(self, "chk_dg_broker", None)), ("DIRECT_USER", getattr(self, "chk_dg_direct", None)))
                if cb is None or cb.isChecked()
            ],
        }

    def _collect_naver_settings(self) -> Optional[dict]:
        if hasattr(self.nv_cb_si, "checked_data"):  # 다중선택 콤보
            if not self.nv_cb_si.checked_data():
                QMessageBox.warning(self, "오류", "네이버: 시/도를 하나 이상 선택하세요.")
                return None
            region_part = {
                "si_list": list(self.nv_cb_si.checked_data()),
                "gun_list": [list(t) for t in self.nv_cb_gun.checked_data()],
                "dong_list": [list(t) for t in self.nv_cb_gu.checked_data()],
            }
        else:  # 단일선택 콤보 (구버전 UI)
            si = self.nv_cb_si.currentText()
            if si == "전체":
                QMessageBox.warning(self, "오류", "네이버: 시/도를 선택하세요.")
                return None
            region_part = {
                "si": si,
                "gun": self.nv_cb_gun.currentText() or "전체",
                "gu": self.nv_cb_gu.currentText() or "전체",
            }
        selected_types = [code for code, cb in self.nv_type_checks.items() if cb.isChecked()]
        realestate_type = ":".join(selected_types) if selected_types else "APT:ABYG:JGC:PRE"

        trade_tokens = []
        if self.nv_trade_buy.isChecked():
            trade_tokens.append("A1")
        if self.nv_trade_jeon.isChecked():
            trade_tokens.append("B1")
        if self.nv_trade_month.isChecked():
            trade_tokens.append("B2")
        if self.nv_trade_short.isChecked():
            trade_tokens.append("B3")
        trade_type = ":".join(trade_tokens) if trade_tokens else None

        def _bounds_or_none(values, full_min, full_max):
            # 빈 최소(기본값 이하)→None, 빈 최대(제한없음)→None (각각 독립 판정)
            lo, hi = values
            lo_out = None if lo <= full_min else lo
            hi_out = None if hi >= RangeInput.OPEN_MAX else hi
            return lo_out, hi_out

        min_deal, max_deal = _bounds_or_none(self.nv_sl_deal.values(), 0, 1_000_000)
        min_rent, max_rent = _bounds_or_none(self.nv_sl_rent.values(), 0, 3_000)
        min_area, max_area = _bounds_or_none(self.nv_sl_area.values(), 0, 231)

        month_on = self.nv_trade_month.isChecked() or self.nv_trade_short.isChecked()
        jeon_on = self.nv_trade_jeon.isChecked()
        warr_vals = []
        if month_on:
            lo, hi = _bounds_or_none(self.nv_sl_warr.values(), 0, 50_000)
            if lo is not None or hi is not None:
                warr_vals.append((lo, hi))
        if jeon_on:
            lo, hi = _bounds_or_none(self.nv_sl_jeon.values(), 0, 1_000_000)
            if lo is not None or hi is not None:
                warr_vals.append((lo, hi))
        if warr_vals:
            lows = [v[0] for v in warr_vals if v[0] is not None]
            highs = [v[1] for v in warr_vals if v[1] is not None]
            min_warr = min(lows) if lows else None
            max_warr = max(highs) if highs else None
        else:
            min_warr = max_warr = None

        return {
            **region_part,
            "realestate_type": realestate_type,
            "trade_type": trade_type,
            "date_preset": self.nv_date_preset.currentText(),
            "min_deal": min_deal,
            "max_deal": max_deal,
            "min_rent": min_rent,
            "max_rent": max_rent,
            "min_warr": min_warr,
            "max_warr": max_warr,
            "min_area": min_area,
            "max_area": max_area,
            "detail_keywords": self._naver_keywords() if hasattr(self, "_naver_keywords") else _parse_keywords_csv(self.nv_detail_filter.text()),
            "detail_uses": self.nv_use_group.selected() if hasattr(self, "nv_use_group") else [],
            "hosu_enabled": self.nv_hosu_check.isChecked() if hasattr(self, "nv_hosu_check") else True,
        }

    # ──────────────────────────────────────────────────────────────
    # 버튼 핸들러
    # ──────────────────────────────────────────────────────────────

    def _open_schedule_list(self):
        dlg = ScheduleListDialog(self._schedule_manager, self._run_job_by_id, self)
        dlg.exec()

    def _run_job_by_id(self, job_id: str):
        if getattr(self, "worker", None) is not None:
            QMessageBox.information(self, "안내", "수집이 이미 실행 중입니다. 완료 후 다시 시도하세요.")
            return
        for job in self._schedule_manager.get_all():
            if job.id == job_id:
                self._run_scheduled_job(job)
                return

    def _save_current_as_schedule(self):
        tab_idx = self.tabs.currentIndex()
        if tab_idx == 0:
            site = "daangn"
            settings = self._collect_daangn_settings()
        elif tab_idx == 1:
            site = "naver"
            settings = self._collect_naver_settings()
        else:
            QMessageBox.information(self, "안내", "예약 수집을 지원하지 않는 탭입니다.")
            return
        if settings is None:
            return
        dlg = ScheduleAddDialog(site, settings, self)
        if dlg.exec() == ScheduleAddDialog.DialogCode.Accepted:
            result = dlg.get_result()
            if result:
                name, time_str, days = (result + ("",))[:4] if len(result) == 3 else result
                settings = dict(settings)
                settings["file_name"] = (result[3] if len(result) > 3 else "") or ""
                job = ScheduledJob(
                    id=str(uuid.uuid4()),
                    name=name,
                    site=site,
                    settings=settings,
                    schedule_time=time_str,
                    days=days,
                )
                self._schedule_manager.add(job)
                from schedule_manager import DAY_NAMES, WEEKDAY_MAP
                days_label = "매일" if "daily" in days else " ".join(
                    {"mon":"월","tue":"화","wed":"수","thu":"목","fri":"금","sat":"토","sun":"일"}.get(d,d) for d in days
                )
                QMessageBox.information(
                    self, "예약 완료",
                    f"예약이 저장되었습니다.\n\n이름: {name}\n시간: {time_str}\n요일: {days_label}"
                )

    # ──────────────────────────────────────────────────────────────
    # 서브클래스에서 구현 필요한 팩토리 메서드 (타입 힌트용)
    # ──────────────────────────────────────────────────────────────

    def _make_daangn_worker(self, params: dict):
        raise NotImplementedError

    def _make_naver_worker(self, params: dict):
        raise NotImplementedError
