from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime, date
from typing import Optional

DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAY_MAP = {0: "mon", 1: "tue", 2: "wed", 3: "thu", 4: "fri", 5: "sat", 6: "sun"}


@dataclass
class ScheduledJob:
    id: str
    name: str
    site: str           # "daangn" | "naver"
    settings: dict
    schedule_time: str  # "HH:MM"
    days: list          # subset of DAY_NAMES or ["daily"]
    enabled: bool = True
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    last_run_date: Optional[str] = None  # "YYYY-MM-DD"


class ScheduleManager:
    def __init__(self, path: str):
        self._path = path
        self._jobs: list[ScheduledJob] = []
        self._load()

    def _load(self):
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._jobs = [ScheduledJob(**j) for j in data.get("jobs", [])]
        except Exception:
            self._jobs = []

    def _save(self):
        try:
            data = {"jobs": [asdict(j) for j in self._jobs]}
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def get_all(self) -> list[ScheduledJob]:
        return list(self._jobs)

    def add(self, job: ScheduledJob):
        self._jobs.append(job)
        self._save()

    def update(self, job: ScheduledJob):
        for i, j in enumerate(self._jobs):
            if j.id == job.id:
                self._jobs[i] = job
                self._save()
                return

    def remove(self, job_id: str):
        self._jobs = [j for j in self._jobs if j.id != job_id]
        self._save()

    def mark_ran(self, job_id: str):
        today = date.today().isoformat()
        for j in self._jobs:
            if j.id == job_id:
                j.last_run_date = today
                self._save()
                return

    def get_due_jobs(self) -> list[ScheduledJob]:
        now = datetime.now()
        current_time = now.strftime("%H:%M")
        current_day = WEEKDAY_MAP[now.weekday()]
        today = date.today().isoformat()
        result = []
        for j in self._jobs:
            if not j.enabled:
                continue
            if j.schedule_time != current_time:
                continue
            if j.last_run_date == today:
                continue
            if "daily" in j.days or current_day in j.days:
                result.append(j)
        return result
