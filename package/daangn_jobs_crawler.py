# -*- coding: utf-8 -*-
"""
당근알바(jobs.daangn.com) 수집 - 데이터 모듈.

사실(2026-10-12 확인)
- GraphQL: POST https://jobs.kr.karrotmarket.com/graphql  {id:<persisted id>, query:"", variables}  (로그인 불필요)
    routeSearchResultsQuery      b479f2c2… : {where:{searchKeyword, region:<동 _id>, regionRange:"RANGE_4"}, first, filter, isStaffCuration:false, after, othersFilter, priorityFilter}
    SearchResultsPaginationQuery daf6296e… : {where, first, filter, after}
    routeJobPostByPublicIdQuery  53f9195a… : {publicId}  → permalinkPairByPublicId.daangnPermalink.model (content, 주소, 조회수, 지원자수…)
    regionCascadeSelectColumnQuery 3b922919… : {parentRegionId:<int|null>} → regionsByParentRegionId (시도→시군구→동)
    keywordResultsQuery          e5eb7d7e… : {query, first:20} → searchRegions (동 이름 검색)
- where.region 은 동(depth 3) _id 만 됨(구·시도 id 는 0건). RANGE_4 가 가장 넓음(이웃 동 포함). 한 쪽 최대 50건쯤(first=50 → 39).
- filter.workPeriod LESS_THAN_A_MONTH = 단기, MORE_THAN_A_MONTH = 1개월 이상. employmentType STAFF 정직원 / PART_TIME_JOB 알바.
- 웹 주소: https://jobs.daangn.com/job-posts/<slug>-<publicId>  (slug 없이 publicId 만으로도 열림)
"""
from __future__ import annotations

import json
import os
import random
import time
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import requests

GQL = "https://jobs.kr.karrotmarket.com/graphql"
Q_SEARCH = "b479f2c233edf0d921b4b954b8e1a0ff"
Q_PAGE = "daf6296ed9995299770c6ade90b9d80c"
Q_DETAIL = "53f9195a00c59634ffdabca4178f7581"
Q_REGION_CHILDREN = "3b92291962883ef85597e461e8908e89"
Q_REGION_SEARCH = "e5eb7d7e6ca3a71821db69609e66d47d"
POST_URL = "https://jobs.daangn.com/job-posts/{pid}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "content-type": "application/json",
    "Origin": "https://jobs.daangn.com",
    "Referer": "https://jobs.daangn.com/",
    "x-graphql-client-name": "jobs-website",
}

SALARY_KO = {"HOURLY": "시급", "DAILY": "일급", "MONTHLY": "월급", "YEARLY": "연봉", "PER_CASE": "건당"}
EMPLOY_KO = {"PART_TIME_JOB": "알바", "STAFF": "정직원"}
PERIOD_KO = {"LESS_THAN_A_MONTH": "단기(1개월 미만)", "MORE_THAN_A_MONTH": "1개월 이상"}
JOB_TASK_KO = {
    "BAKING": "베이킹", "BEAUTY_CARE": "미용/뷰티", "BEVERAGE_MAKING": "음료 제조", "CAFE_BAKERY": "카페/베이커리",
    "CHILD_CARE": "아이돌봄", "CLEANING": "업체청소", "CONSTRUCTION_FIELD": "건설/현장", "CONVENIENCE_STORE": "편의점",
    "ETC": "기타", "HOUSEWORK": "가사/청소/정리", "INTERIOR": "인테리어", "KIDS_PICK_UP": "등하원도우미",
    "KITCHEN_ASSISTANCE": "주방보조/설거지", "KITCHEN_COOK": "주방장/조리사", "LEAFLET_DISTRIBUTION": "전단지",
    "LIGHT_WORK": "심부름/소일거리", "LOGISTICS_PACKAGING": "물류/포장", "MANUFACTURING": "생산/제조",
    "MOVING_ASSISTANCE": "짐 옮기기", "NURSING": "돌봄/시팅", "OFFICE_ASSISTANCE": "사무보조", "PET_CARE": "반려동물 돌봄",
    "REPAIR_INSTALLATION": "수리/설치", "SENIOR_CARE": "어르신 돌봄", "SERVING": "서빙", "SHOP_MANAGEMENT": "매장관리/판매",
    "TUTORING": "학원/과외/레슨",
}
DAY_KO = {"MON": "월", "TUE": "화", "WED": "수", "THU": "목", "FRI": "금", "SAT": "토", "SUN": "일"}

# 사이트가 안 될 때 쓰는 시도 목록 (2026-10-12)
BUILTIN_SIDOS: List[Dict[str, Any]] = [
    {"_id": 1, "name": "서울특별시"}, {"_id": 1256, "name": "경기도"}, {"_id": 825, "name": "인천광역시"},
    {"_id": 451, "name": "부산광역시"}, {"_id": 675, "name": "대구광역시"}, {"_id": 1094, "name": "대전광역시"},
    {"_id": 1179, "name": "울산광역시"}, {"_id": 1241, "name": "세종특별자치시"}, {"_id": 13371, "name": "전남광주통합특별시"},
    {"_id": 1873, "name": "강원특별자치도"}, {"_id": 2092, "name": "충청북도"}, {"_id": 2261, "name": "충청남도"},
    {"_id": 2488, "name": "전북특별자치도"}, {"_id": 3093, "name": "경상북도"}, {"_id": 3464, "name": "경상남도"},
    {"_id": 3811, "name": "제주특별자치도"},
]

EXCEL_COLUMNS: List[str] = [
    "번호", "제목", "회사명", "지역", "주소", "급여", "고용형태", "근무기간", "업무", "근무요일/날짜", "근무시간",
    "내용", "전화연락", "조회수", "관심", "지원자", "등록일시", "마감", "검색어", "당근링크",
]


def to_kst(iso: Optional[str]) -> Optional[datetime]:
    if not iso:
        return None
    try:
        return datetime.strptime(str(iso)[:19], "%Y-%m-%dT%H:%M:%S") + timedelta(hours=9)
    except Exception:
        return None


def salary_text(jp: Dict[str, Any]) -> str:
    st = jp.get("salaryType") or ""
    s = jp.get("salary")
    lab = SALARY_KO.get(st, st)
    if s is None:
        return lab
    try:
        n = int(s)
    except Exception:
        return f"{lab} {s}"
    if st in ("MONTHLY", "YEARLY"):
        return f"{lab} {n // 10000:,}만원"
    txt = f"{lab} {n:,}원"
    if jp.get("salaryPayMethod") == "WORK_DAY_PAYMENT":
        txt += " (당일지급)"
    return txt


def workdays_text(jp: Dict[str, Any]) -> str:
    days = [DAY_KO.get(d, d) for d in (jp.get("workDays") or [])]
    dates = jp.get("workDates") or []
    parts = []
    if days:
        parts.append(",".join(days))
    if dates:
        ds = sorted(dates)
        parts.append(ds[0] if len(ds) == 1 else f"{ds[0]}~{ds[-1]} ({len(ds)}일)")
    if jp.get("isWorkDaysNegotiable"):
        parts.append("요일협의")
    return " ".join(parts)


def worktime_text(jp: Dict[str, Any]) -> str:
    a, b = jp.get("workTimeStart"), jp.get("workTimeEnd")
    t = f"{a}~{b}" if a and b else (a or b or "")
    if jp.get("isWorkTimeNegotiable"):
        t = (t + " 시간협의").strip()
    return t


def normalize(jp: Dict[str, Any], keyword: str = "", detail: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    d = detail or {}
    pid = ((jp.get("daangnPermalink") or {}).get("publicId")) or ((d.get("daangnPermalink") or {}).get("publicId")) or ""
    region = ((jp.get("workplaceRegion") or {}).get("name3Region") or {}).get("name") or (jp.get("workplaceRegion") or {}).get("name") or ""
    pub = to_kst(jp.get("publishedAt") or d.get("publishedAt"))
    closed = bool(jp.get("closed") or d.get("closed"))
    tasks = ", ".join(JOB_TASK_KO.get(t, t) for t in (d.get("jobTasks") or jp.get("jobTasks") or []) if t != "ETC")
    addr = d.get("workplaceRoadAddress") or d.get("workplaceAddress") or ""
    if d.get("workplaceAddress") and d.get("workplaceRoadAddress") and d["workplaceAddress"] != d["workplaceRoadAddress"]:
        addr = f"{d['workplaceRoadAddress']} ({d['workplaceAddress']})"
    app = d.get("applicationCountInfo") or {}
    return {
        "번호": pid,
        "제목": (jp.get("title") or d.get("title") or "").strip(),
        "회사명": jp.get("companyName") or d.get("companyName") or "",
        "지역": region,
        "주소": addr,
        "급여": salary_text(jp if jp.get("salaryType") else d),
        "고용형태": EMPLOY_KO.get(jp.get("employmentType") or d.get("employmentType") or "", jp.get("employmentType") or ""),
        "근무기간": PERIOD_KO.get(d.get("workPeriod") or jp.get("workPeriod") or "", ""),
        "업무": tasks,
        "근무요일/날짜": workdays_text(jp),
        "근무시간": worktime_text(jp),
        "내용": (d.get("content") or "").strip(),
        "전화연락": "가능" if d.get("isPhoneContactable") else ("" if not d else "채팅만"),
        "조회수": d.get("viewCount") if d else "",
        "관심": d.get("watchCount") if d else "",
        "지원자": app.get("totalCount") if d else "",
        "등록일시": pub.strftime("%Y-%m-%d %H:%M") if pub else "",
        "마감": "마감" if closed else "",
        "검색어": keyword,
        "당근링크": POST_URL.format(pid=pid) if pid else "",
        "_created": pub,
        "_id": jp.get("_id") or d.get("_id"),
    }


class DaangnJobsClient:
    def __init__(self, log: Optional[Callable[[str], None]] = None, delay: Tuple[float, float] = (0.3, 0.8)):
        self.log = log or (lambda s: None)
        self.delay = delay
        self.s = requests.Session()
        self.s.headers.update(HEADERS)
        self._n = 0

    def _sleep(self) -> None:
        if self._n and self.delay[1] > 0:
            time.sleep(random.uniform(*self.delay))
        self._n += 1

    def gql(self, qid: str, variables: Dict[str, Any], tries: int = 3) -> Dict[str, Any]:
        last: Any = None
        for i in range(tries):
            try:
                self._sleep()
                r = self.s.post(GQL, data=json.dumps({"id": qid, "query": "", "variables": variables}), timeout=30)
                if r.status_code == 429 or r.status_code >= 500:
                    raise RuntimeError(f"HTTP {r.status_code}")
                j = r.json()
                if j.get("errors") and not j.get("data"):
                    raise RuntimeError("당근알바 응답 오류: " + str(j["errors"][0].get("message", ""))[:200])
                return j.get("data") or {}
            except Exception as e:  # noqa: BLE001
                last = e
                if i < tries - 1:
                    wait = 3 * (i + 1)
                    self.log(f"  재시도 {i + 1}/{tries - 1} ({e}) {wait}초 대기")
                    time.sleep(wait)
        raise RuntimeError(f"당근알바 접속 실패: {last}")

    # ---- 지역 ----
    def region_children(self, parent_id: Optional[int]) -> List[Dict[str, Any]]:
        d = self.gql(Q_REGION_CHILDREN, {"parentRegionId": parent_id})
        return [{"_id": r["_id"], "name": r.get("name") or ""} for r in (d.get("regionsByParentRegionId") or [])]

    def sidos(self) -> List[Dict[str, Any]]:
        try:
            out = self.region_children(None)
            return out or list(BUILTIN_SIDOS)
        except Exception:
            return list(BUILTIN_SIDOS)

    def search_regions(self, query: str) -> List[Dict[str, Any]]:
        d = self.gql(Q_REGION_SEARCH, {"query": query, "first": 20})
        out = []
        for e in ((d.get("searchRegions") or {}).get("edges") or []):
            n = e.get("node") or {}
            out.append({"_id": n.get("_id"), "name": n.get("name"), "name1": n.get("name1"), "name2": n.get("name2"), "name3": n.get("name3")})
        return out

    # ---- 검색 ----
    def search(self, region_id: int, keyword: str = "", short_term: bool = False, after: Optional[str] = None,
               first: int = 50) -> Tuple[List[Dict[str, Any]], Optional[str], bool]:
        where = {"searchKeyword": keyword or "", "region": int(region_id), "regionRange": "RANGE_4"}
        flt: Dict[str, Any] = {}
        if short_term:
            flt["workPeriod"] = "LESS_THAN_A_MONTH"
        if after:
            d = self.gql(Q_PAGE, {"where": where, "first": first, "filter": flt, "after": after})
        else:
            d = self.gql(Q_SEARCH, {"where": where, "first": first, "filter": flt, "isStaffCuration": False,
                                     "after": None, "othersFilter": flt, "priorityFilter": flt})
        feed = d.get("searchedFeed") or {}
        posts = []
        for e in feed.get("edges") or []:
            jp = (e.get("node") or {}).get("jobPost")
            if jp:
                posts.append(jp)
        pi = feed.get("pageInfo") or {}
        return posts, pi.get("endCursor"), bool(pi.get("hasNextPage"))

    def detail(self, public_id: str) -> Dict[str, Any]:
        d = self.gql(Q_DETAIL, {"publicId": public_id})
        pair = d.get("permalinkPairByPublicId") or {}
        model = (pair.get("daangnPermalink") or {}).get("model") or (pair.get("permalink") or {}).get("model") or {}
        if model.get("__typename") not in (None, "JobPost"):
            return {}
        return model


def _contains_any(text: str, words: List[str]) -> bool:
    t = (text or "").lower()
    return any(w.lower() in t for w in words if w)


def collect(
    client: DaangnJobsClient,
    region_ids: List[int],
    keywords: List[str],
    start: date,
    end: date,
    max_count: int = 500,
    short_term: bool = False,
    with_detail: bool = True,
    include_words: Optional[List[str]] = None,
    exclude_words: Optional[List[str]] = None,
    skip_closed: bool = True,
    seen_ids: Optional[Set[str]] = None,
    stop: Optional[Callable[[], bool]] = None,
    log: Optional[Callable[[str], None]] = None,
    progress: Optional[Callable[[int, int], None]] = None,
    region_names: Optional[Dict[int, str]] = None,
    max_pages: int = 10,
) -> List[Dict[str, Any]]:
    """동 id 목록 × 검색어 별로 당근알바를 검색해 중복 없이 모은다(등록일 기간, 최대 건수)."""
    log = log or (lambda s: None)
    stop = stop or (lambda: False)
    include_words = [w for w in (include_words or []) if w]
    exclude_words = [w for w in (exclude_words or []) if w]
    seen_ids = seen_ids or set()
    kws: List[str] = [k for k in (keywords or []) if k] or [""]
    names = region_names or {}

    got: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    kw_of: Dict[str, List[str]] = {}
    for rid in region_ids:
        if stop():
            break
        for kw in kws:
            if stop():
                break
            after = None
            pages = 0
            older_streak = 0
            label = f"{names.get(rid, rid)}" + (f" '{kw}'" if kw else "")
            n_before = len(order)
            while not stop():
                try:
                    posts, after, more = client.search(rid, kw, short_term, after)
                except Exception as e:  # noqa: BLE001
                    log(f"  [{label}] 검색 실패: {e}")
                    break
                pages += 1
                for jp in posts:
                    pub = to_kst(jp.get("publishedAt"))
                    d = pub.date() if pub else None
                    if d and d < start:
                        older_streak += 1
                        continue
                    if d and d > end:
                        continue
                    older_streak = 0
                    pid = jp.get("_id") or ""
                    if not pid:
                        continue
                    if pid in got:
                        if kw and kw not in kw_of[pid]:
                            kw_of[pid].append(kw)
                        continue
                    if pid in seen_ids:
                        continue
                    if skip_closed and jp.get("closed"):
                        continue
                    n = normalize(jp, kw)
                    hay = n["제목"] + " " + n["회사명"]
                    if exclude_words and _contains_any(hay, exclude_words):
                        continue
                    got[pid] = n
                    kw_of[pid] = [kw] if kw else []
                    order.append(pid)
                    if max_count and len(order) >= max_count:
                        break
                if progress:
                    progress(len(order), max_count or 0)
                if (max_count and len(order) >= max_count) or not more or not after or pages >= max_pages or older_streak >= 20:
                    break
            log(f"  [{label}] +{len(order) - n_before}건 (누적 {len(order)})")
            if max_count and len(order) >= max_count:
                break
        if max_count and len(order) >= max_count:
            log(f"최대 건수 {max_count}건에 도달해 멈춥니다.")
            break

    rows = [got[p] for p in order]
    if with_detail and rows:
        log(f"상세(내용·주소·조회수) 가져오는 중... {len(rows)}건")
        for i, r in enumerate(rows, 1):
            if stop():
                break
            try:
                dt = client.detail(r["번호"]) if r.get("번호") else {}
            except Exception as e:  # noqa: BLE001
                log(f"  상세 실패 {r.get('번호')}: {e}")
                dt = {}
            if dt:
                jp_stub = {k: r.get(k) for k in ()}  # noqa: F841
                merged = normalize({**dt, "daangnPermalink": {"publicId": r["번호"]}, "workplaceRegion": {"name": r["지역"]}}, r["검색어"], dt)
                merged["근무요일/날짜"] = r["근무요일/날짜"] or merged["근무요일/날짜"]
                merged["근무시간"] = r["근무시간"] or merged["근무시간"]
                merged["급여"] = r["급여"] or merged["급여"]
                r.update(merged)
            if progress and i % 5 == 0:
                progress(i, len(rows))
    for r in rows:
        r["검색어"] = ", ".join(kw_of.get(r.get("_id"), [])) or r.get("검색어", "")
    if include_words:
        rows = [r for r in rows if _contains_any(r["제목"] + " " + r.get("내용", "") + " " + r["회사명"], include_words)]
    if exclude_words:
        rows = [r for r in rows if not _contains_any(r["제목"] + " " + r.get("내용", "") + " " + r["회사명"], exclude_words)]
    rows.sort(key=lambda x: x.get("_created") or datetime.min, reverse=True)
    return rows


def save_excel(rows: List[Dict[str, Any]], path: str) -> str:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    widths = {"번호": 14, "제목": 44, "회사명": 18, "지역": 10, "주소": 30, "급여": 16, "고용형태": 8, "근무기간": 14,
              "업무": 16, "근무요일/날짜": 22, "근무시간": 14, "내용": 60, "전화연락": 8, "조회수": 7, "관심": 6,
              "지원자": 6, "등록일시": 16, "마감": 6, "검색어": 12, "당근링크": 40}
    wb = Workbook()
    ws = wb.active
    ws.title = "당근알바"
    ws.append(EXCEL_COLUMNS)
    for c in ws[1]:
        c.fill = PatternFill("solid", fgColor="FFE8D6")
        c.font = Font(bold=True, color="1F2937")
        c.alignment = Alignment(horizontal="center", vertical="center")
    link_font = Font(color="1D4ED8", underline="single")
    wrap = Alignment(wrap_text=True, vertical="top")
    top = Alignment(vertical="top")
    for r in rows:
        ws.append([r.get(k, "") for k in EXCEL_COLUMNS])
        i = ws.max_row
        for j, k in enumerate(EXCEL_COLUMNS, 1):
            cell = ws.cell(row=i, column=j)
            if k == "당근링크" and cell.value:
                cell.hyperlink = str(cell.value)
                cell.font = link_font
            cell.alignment = wrap if k in ("내용", "제목", "주소", "근무요일/날짜") else top
        if len(r.get("내용") or "") > 200:
            ws.row_dimensions[i].height = 90
    for j, k in enumerate(EXCEL_COLUMNS, 1):
        ws.column_dimensions[get_column_letter(j)].width = widths.get(k, 12)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    wb.save(path)
    return path
