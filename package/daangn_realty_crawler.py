from typing import Optional, Dict, Any, List, Callable, Iterable, Tuple
from curl_cffi import requests as curl_req
from curl_cffi.requests import AsyncSession
from bs4 import BeautifulSoup as bs
import re
import time
import random
import csv
import json
import asyncio
import urllib.parse
from datetime import datetime as dt, date


class DaangnNotFound(RuntimeError):
    """realty.daangn.com 지도 페이지가 404 (해당 지역/유형 경로 없음)."""


class DaangnRealtyCrawler():
    """당근 부동산 매물 유형: API값 ↔ 한글 라벨 매핑"""
    # 2026-09 realty.daangn.com 기준 매물유형. 새 사이트에 "기타"는 없고(404) 주택/사무실/건물/토지가 추가됨.
    SALES_TYPE_MAP = {
        "one_room": "원룸",
        "two_room": "빌라(투룸)",
        "officetel": "오피스텔",
        "apart": "아파트",
        "house": "주택",
        "store": "상가",
        "office": "사무실",
        "building": "건물",
        "land": "토지",
    }
    SALES_TYPE_LABEL_TO_API = {v: k for k, v in SALES_TYPE_MAP.items()}

    TRADE_TYPE_MAP = {"month": "월세", "borrow": "전세", "buy": "매매", "short": "단기"}
    TRADE_TYPE_LABEL_TO_API = {v: k for k, v in TRADE_TYPE_MAP.items()}

    # realty.daangn.com/map/{시도}/{시군구}/{동}/{매물유형}/{거래유형} 경로 세그먼트 라벨
    NEW_SALES_URL_LABEL = {
        "one_room": "원룸",
        "two_room": "빌라",
        "officetel": "오피스텔",
        "apart": "아파트",
        "house": "주택",
        "store": "상가",
        "office": "사무실",
        "building": "건물",
        "land": "토지",
    }
    NEW_TRADE_URL_LABEL = {"month": "월세", "borrow": "전세", "buy": "매매", "short": "단기"}

    # 작성자 유형 (목록 Article.writerTypeV2) → 직거래/중개 구분
    WRITER_TYPE_KO = {"BROKER": "공인중개사", "DIRECT_USER": "직거래"}
    SUB_WRITER_TYPE_KO = {"LESSOR": "집주인", "TENANT": "세입자"}

    # 상세 Article.buildingOrientation enum → 한글
    ORIENTATION_KO = {
        "NORTH_FACING": "북향", "SOUTH_FACING": "남향", "EAST_FACING": "동향", "WEST_FACING": "서향",
        "NORTH_EAST_FACING": "북동향", "NORTH_WEST_FACING": "북서향",
        "SOUTH_EAST_FACING": "남동향", "SOUTH_WEST_FACING": "남서향",
    }

    # 상세 Article.buildingUsage enum → 한글 (사이트 JS의 표시 라벨과 동일)
    BUILDING_USAGE_KO = {
        "SINGLE_FAMILY_HOUSING": "단독주택",
        "PUBLIC_HOUSING": "공동주택",
        "TYPE_1_NEIGHBORHOOD_LIVING_FACILITY": "제1종 근린생활시설",
        "TYPE_2_NEIGHBORHOOD_LIVING_FACILITY": "제2종 근린생활시설",
        "CULTURAL_AND_ASSEMBLY_FACILITIES": "문화 및 집회시설",
        "RELIGIOUS_FACILITY": "종교시설",
        "SALE_FACILITY": "판매시설",
        "TRANSPORTATION_FACILITY": "운수시설",
        "MEDICAL_FACILITY": "의료시설",
        "EDUCATION_AND_RESEARCH_FACILITY": "교육연구시설",
        "ELDERLY_FACILITY": "노유자시설",
        "STUDY_FACILITY": "수련시설",
        "EXERCISE_FACILITY": "운동시설",
        "OFFICE_FACILITY": "업무시설",
        "ACCOMMODATION_FACILITY": "숙박시설",
        "RECREATION_FACILITY": "위락시설",
        "FACTORY": "공장",
        "WAREHOUSE_FACILITY": "창고시설",
        "HAZARDOUS_MATERIAL_FACILITY": "위험물 저장 및 처리 시설",
        "DOOR_AND_PLANT_RELATED_FACILITY": "동물 및 식물 관련 시설",
        "SEWAGE_AND_WASTE_PROCESSING_FACILITY": "자원순환 관련 시설",
        "CORRECTION_AND_MILITARY_FACILITY": "교정시설",
        "BROADCASTING_AND_COMMUNICATION_FACILITY": "방송통신시설",
        "POWER_GENERATION_FACILITY": "발전시설",
        "CEMETERY_RELATED_FACILITY": "묘지 관련 시설",
        "TOURISM_AND_RECREATION_FACILITY": "관광 휴게시설",
        "FUNERAL_HOME": "장례식장",
        "CAR_RELATED_FACILITY": "자동차 관련 시설",
        "TEMPORARY_BUILDING": "야영장시설",
    }

    MAX_RETRIES = 3
    RETRY_DELAY_MIN = 2
    RETRY_DELAY_MAX = 6
    
    def __init__(self):
        super().__init__()
        self.host = "https://www.daangn.com"
        self.search_url = f"{self.host}/kr/realty/s"
        self.realty_host = "https://realty.daangn.com"
        self.timeout_sec = 20
        
        self.headers = {
            "accept": "*/*",
            "accept-encoding": "gzip, deflate, br, zstd",
            "accept-language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "baggage": "sentry-environment=prod-kr,sentry-release=40c9c07,sentry-public_key=6516b498149442e094c9fff2b63a8ec5,sentry-trace_id=16a016447568478587a7f735b4209664,sentry-sample_rate=0,sentry-transaction=routes%2Fkr.realty.s,sentry-sampled=false",
            "priority": "u=1, i",
            "referer": "https://www.daangn.com/kr/realty/s/?areaViewType=p&in=%EC%97%AD%EC%82%BC%EB%8F%99-6035&salesType=two_room&tradeType=month",
            "sec-ch-ua": '"Not(A:Brand";v="8", "Chromium";v="144", "Google Chrome";v="144"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "sentry-trace": "16a016447568478587a7f735b4209664-8f63e0085e6fb540-0",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"
        }

    def _backoff_delay(self, attempt: int, is_cancelled: Optional[Callable[[], bool]] = None):
        """재요청 전 지수 백오프 (GUI 로그 없음)"""
        delay = min(self.RETRY_DELAY_MIN * (2 ** attempt), 60)
        delay *= 0.5 + random.random()  # 50%~150% 지터
        if not is_cancelled:
            time.sleep(delay)
            return
        end_at = time.time() + delay
        while time.time() < end_at:
            if is_cancelled():
                return
            time.sleep(0.05)

    def _get_posts(self, params: Dict) -> List[Dict]:
        for attempt in range(self.MAX_RETRIES):
            try:
                r = curl_req.get(
                    self.search_url,
                    params=params,
                    headers=self.headers,
                    impersonate="chrome",
                    timeout=self.timeout_sec,
                )
                if r.status_code != 200:
                    raise RuntimeError(f"HTTP {r.status_code}")
                data = r.json()
                posts = data.get("realtyPosts", {}).get("realtyPosts", [])
                if not isinstance(posts, list):
                    raise ValueError("응답 형식 비정상")
                return posts
            except Exception:
                if attempt < self.MAX_RETRIES - 1:
                    self._backoff_delay(attempt)
                else:
                    raise
        return []

    def _parse_created_at(self, s: str) -> Optional[date]:
        """createdAt ISO 문자열을 date로 파싱 (2026-01-12T11:07:04.487Z)"""
        if not s:
            return None
        try:
            s = str(s).strip()
            part = s.split("T")[0] if "T" in s else s[:10]
            part = part.replace("-", "")[:8]
            if len(part) == 8 and part.isdigit():
                return dt.strptime(part, "%Y%m%d").date()
            return None
        except (ValueError, TypeError):
            return None

    def _filter_posts_by_date(
        self,
        posts: List[Dict],
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
    ) -> List[Dict]:
        """createdAt 기준으로 날짜 범위 필터"""
        if not date_start and not date_end:
            return posts
        try:
            start = None
            if date_start:
                s = str(date_start).strip().replace("-", "")[:8]
                if len(s) == 8:
                    start = dt.strptime(s, "%Y%m%d").date()
            end = None
            if date_end:
                s = str(date_end).strip().replace("-", "")[:8]
                if len(s) == 8:
                    end = dt.strptime(s, "%Y%m%d").date()
        except ValueError:
            return posts
        filtered = []
        for p in posts:
            created = self._parse_created_at(p.get("createdAt", ""))
            if created is None:
                if not start and not end:
                    filtered.append(p)
                continue
            if start and created < start:
                continue
            if end and created > end:
                continue
            filtered.append(p)
        return filtered
    
    def extract_realty_detail_from_html(
        self,
        html: str,
        list_post: Optional[Dict[str, Any]] = None,
        post_img_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        당근 부동산 상세 페이지 HTML에서 모든 데이터를 추출합니다.
        
        Args:
            html: 상세 페이지 HTML 문자열
            list_post: 목록 API에서 받은 매물 데이터 (보증금, 월세, 판매여부 등 병합용)
        
        Returns:
            추출된 모든 데이터를 담은 딕셔너리
        """
        soup = bs(html, "html.parser")
        result: Dict[str, Any] = {}
        
        # 1. 목록 API 데이터 병합 (보증금, 월세, 판매여부 등)
        if list_post:
            result["판매여부"] = "거래중"  # 목록에 있으면 거래중
            result["매물_URL"] = f"{self.host}{list_post.get('id', '')}"
            result['이미지_URL'] = post_img_url
            if "createdAt" in list_post:
                result["등록일시"] = list_post["createdAt"]
            if "deposit" in list_post:
                result["보증금"] = list_post["deposit"]
            if "monthPrice" in list_post or "monthlyPay" in list_post:
                result["월세"] = list_post.get("monthPrice") or list_post.get("monthlyPay")
            if "tradeType" in list_post:
                result["거래유형"] = list_post["tradeType"]  # month, jeon, sale 등
            if "salesType" in list_post:
                result["매물유형"] = list_post["salesType"]  # one_room, two_room 등
            if "title" in list_post:
                result["제목"] = list_post["title"]
        
        # 2. 페이지 내 가격 정보 (보증금/월세) - 상단 영역에서 추출
        price_section = soup.find(string=re.compile(r"보증금|월세|전세금|매매가"))
        if price_section:
            parent = price_section.parent
            if parent:
                price_text = parent.get_text(strip=True) if hasattr(parent, 'get_text') else str(parent)
                if "보증금" not in result:
                    dep_match = re.search(r"보증금\s*([\d,]+)\s*(만|억)?원?", price_text)
                    if dep_match:
                        result["보증금_텍스트"] = dep_match.group(0).strip()
                if "월세" not in result:
                    mon_match = re.search(r"월세\s*([\d,]+)\s*(만|억)?원?", price_text)
                    if mon_match:
                        result["월세_텍스트"] = mon_match.group(0).strip()
                # "1,000만원 · 50만원" 형식 (보증금 · 월세)
                # if "보증금" not in result and "월세" not in result and re.search(r"[\d,]+만원|[\d,]+억", price_text):
                #     result["가격_텍스트"] = price_text
        
        # 3. 상세 정보 (dl > dt/dd)
        detail_dl = soup.find("dl", class_=re.compile(r"cdm7k00|_1sr322h0"))
        if not detail_dl:
            detail_dl = soup.find("h2", string="상세 정보")
            if detail_dl:
                detail_dl = detail_dl.find_next("dl")
        
        if detail_dl:
            for div in detail_dl.find_all("div", recursive=False):
                dt_elem = div.find("dt")
                dd_elem = div.find("dd")
                if dt_elem and dd_elem:
                    label = dt_elem.get_text(strip=True)
                    # dd 내부에 div/button이 있으면 첫 번째 텍스트 노드 추출
                    dd_text = dd_elem.get_text(separator=" ", strip=True)
                    # 관리비 등 버튼이 있는 경우: div._1c6hyct0 또는 첫 텍스트
                    inner_div = dd_elem.find("div", class_=re.compile("_1c6hyct0"))
                    if inner_div:
                        dd_text = inner_div.get_text(strip=True)
                    result[label] = dd_text
        
        # 4. 상세 내용 (설명 텍스트)
        detail_h3 = soup.find("h3", string="상세 내용")
        if detail_h3:
            content_span = detail_h3.find_next_sibling("span", class_=re.compile("_1sr322h8"))
            if not content_span:
                content_span = detail_h3.find_next("span")
            if content_span:
                result["상세_내용"] = content_span.get_text(strip=True)
        
        # 5. 해시태그
        hashtag_links = soup.find_all("a", href=re.compile(r"/kr/realty/s/\?"), string=re.compile(r"^#"))
        if hashtag_links:
            result["해시태그"] = [a.get_text(strip=True) for a in hashtag_links]
        
        # 6. 관심/조회/채팅
        stats_span = soup.find("span", class_=re.compile("_1pwsqmm0"))
        if stats_span:
            stats_text = stats_span.get_text()
            for part in stats_text.split("·"):
                part = part.strip()
                m = re.search(r"(\d+)", part)
                if m:
                    num = int(m.group(1))
                    if "관심" in part:
                        result["관심_수"] = num
                    elif "조회" in part:
                        result["조회_수"] = num
                    elif "채팅" in part:
                        result["채팅_수"] = num
        
        # 7. 주소
        map_section = soup.find("div", class_=re.compile("_1sr322h9"))
        if map_section:
            addr_span = map_section.find_next("div").find("span") if map_section.find_next("div") else None
            if addr_span:
                result["주소"] = addr_span.get_text(strip=True)
        # 주소 대체: "주소 복사하기" 버튼 이전 span
        if "주소" not in result:
            copy_btn = soup.find("button", attrs={"aria-label": "주소 복사하기"})
            if copy_btn:
                prev_span = copy_btn.find_previous("span")
                if prev_span:
                    result["주소"] = prev_span.get_text(strip=True)
        
        # 8. 거래완료 등 판매여부 (페이지 내 - 배지/버튼 등 전용 요소만, 상세설명 내 문구 제외)
        sold_badge = soup.find(string=re.compile(r"^거래\s*완료$|^거래완료$"))
        if sold_badge:
            result["판매여부"] = "거래완료"
        
        return result
    
    def _get_post_detail(
        self,
        post_id: str,
        list_post: Optional[Dict[str, Any]] = None,
        post_img_url: Optional[str] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
    ) -> Optional[Dict[str, Any]]:
        """매물 상세 페이지를 가져와 extract_realty_detail_from_html로 파싱합니다. 비정상 시 최대 3회 재요청."""
        for attempt in range(self.MAX_RETRIES):
            if is_cancelled and is_cancelled():
                return None
            try:
                r = curl_req.get(
                    f"{self.host}{post_id}",
                    headers=self.headers,
                    impersonate="chrome",
                    timeout=self.timeout_sec,
                )
                if r.status_code != 200:
                    raise RuntimeError(f"HTTP {r.status_code}")
                result = self.extract_realty_detail_from_html(r.text, list_post=list_post, post_img_url=post_img_url)
                if not result:
                    raise ValueError("추출 데이터 없음")
                return result
            except Exception:
                if attempt < self.MAX_RETRIES - 1:
                    self._backoff_delay(attempt, is_cancelled=is_cancelled)
                else:
                    return None
        return None

    def _save_to_excel(self, rows: List[Dict[str, Any]], filepath: Optional[str] = None) -> str:
        """추출 데이터를 엑셀 파일로 저장합니다."""
        try:
            import openpyxl
        except ImportError:
            raise ImportError("엑셀 저장을 위해 openpyxl 설치 필요: pip install openpyxl")

        if not rows:
            raise ValueError("저장할 데이터가 없습니다.")
        path = filepath or f"daangn_realty_{dt.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "매물목록"
        all_keys = []
        seen = set()
        for row in rows:
            for k in row.keys():
                if k not in seen:
                    seen.add(k)
                    all_keys.append(k)

        # 값이 하나도 없는 컬럼은 제거 (엑셀에서 빈 여백칸 방지)
        def _blank(v: Any) -> bool:
            if v is None:
                return True
            if isinstance(v, str) and not v.strip():
                return True
            if isinstance(v, (list, tuple)) and not v:
                return True
            return False

        all_keys = [k for k in all_keys if any(not _blank(r.get(k)) for r in rows)]
        ws.append([self._sanitize_excel_str(str(k)) for k in all_keys])
        for row in rows:
            ws.append([self._cell_value(row.get(k)) for k in all_keys])
        self._apply_hyperlinks(ws, all_keys)
        wb.save(path)
        return path

    def _cell_value(self, v: Any) -> Any:
        """엑셀 셀에 쓸 수 있도록 값 정제 (IllegalCharacterError 방지)"""
        if v is None:
            return ""
        if isinstance(v, list):
            return self._sanitize_excel_str(", ".join(str(x) for x in v))
        if isinstance(v, str):
            return self._sanitize_excel_str(v)
        return v

    def _sanitize_excel_str(self, s: str) -> str:
        """엑셀에서 허용하지 않는 제어문자 제거 (IllegalCharacterError 방지)"""
        if not s:
            return ""
        # openpyxl: 0x00-0x1F(탭/줄바꿈/CR 제외), 0x7F, 0x80-0x9F 제거
        result = []
        for c in s:
            o = ord(c)
            if o in (0x09, 0x0A, 0x0D) or (0x20 <= o <= 0x7E) or o >= 0xA0:
                result.append(c)
            else:
                result.append(" ")
        return "".join(result)

    def _apply_hyperlinks(self, ws, all_keys: List[str]) -> None:
        """URL/링크 컬럼을 엑셀 하이퍼링크 셀로 저장"""
        try:
            from openpyxl.styles import Font
        except Exception:
            return
        url_col_indices = []
        for i, key in enumerate(all_keys, 1):
            k = str(key).strip().lower()
            if ("url" in k) or ("link" in k) or ("링크" in str(key)):
                url_col_indices.append(i)
        if not url_col_indices:
            return
        link_font = Font(color="0563C1", underline="single")
        for row_idx in range(2, ws.max_row + 1):
            for col_idx in url_col_indices:
                cell = ws.cell(row=row_idx, column=col_idx)
                value = str(cell.value or "").strip()
                if value.lower().startswith(("http://", "https://")):
                    cell.hyperlink = value
                    cell.font = link_font
        
    def _append_row_to_csv(self, row: Dict[str, Any], csv_file, csv_writer, all_keys: List[str]) -> None:
        """한 줄을 CSV에 실시간 추가"""
        values = [self._cell_value(row.get(k)) for k in all_keys]
        csv_writer.writerow(values)
        csv_file.flush()

    def _range_param(self, min_val: Optional[int], max_val: Optional[int]) -> Optional[str]:
        """min__max 형식 문자열 생성. 둘 중 하나만 있으면 min__ 또는 __max"""
        if min_val is not None and max_val is not None:
            return f"{min_val}__{max_val}"
        if min_val is not None:
            return f"{min_val}__"
        if max_val is not None:
            return f"__{max_val}"
        return None

    def _fetch_ssr_store(self, si: str, gun: str, dong: str, sales_label: str, trade_label: str) -> Optional[Dict[str, Any]]:
        """realty.daangn.com의 SSR 지도 페이지에서 window.RELAY_STORE를 파싱해 반환.

        2026년 사이트 개편 이후 매물 목록 API가 사라지고, 대신 지도 페이지 HTML에
        Relay 캐시가 JS 문자열로 이중 인코딩되어 그대로 내려온다. 정규식으로 추출 후
        JSON을 두 번 파싱하면 화면에 뿌려지는 것과 동일한 매물 데이터를 얻을 수 있다.

        경로: /map/{시도}/{시군구}/{동}/{유형}/{거래}. 시군구는 "성남시 분당구"처럼 한 세그먼트.
        dong이 비어 있으면 구 단위 페이지(/map/{시도}/{시군구}/{유형}/{거래})를 요청한다.
        웹 SSR은 최신순 첫 20건만 내려주며(다음 페이지는 앱 토큰 필요), 전체 건수는 last_total_count에 남긴다.
        """
        segs = [si, gun] + ([dong] if dong else []) + [sales_label, trade_label]
        path = "/map/" + "/".join(urllib.parse.quote(x, safe="") for x in segs)
        url = f"{self.realty_host}{path}"
        self.last_total_count: Optional[int] = None
        for attempt in range(self.MAX_RETRIES):
            try:
                r = curl_req.get(url, headers=self.headers, impersonate="chrome", timeout=self.timeout_sec)
                if r.status_code == 404:
                    raise DaangnNotFound(url)
                if r.status_code != 200:
                    raise RuntimeError(f"HTTP {r.status_code}")
                m = re.search(r'window\.RELAY_STORE\s*=\s*"(.*?)";</script>', r.text, re.S)
                if not m:
                    return None
                js_str = json.loads('"' + m.group(1) + '"')
                store = json.loads(js_str)
                # client:root 의 articlesCount(...) 에 해당 조건의 전체 매물 수가 들어있다
                root = store.get("client:root") or {}
                for k, v in root.items():
                    if isinstance(k, str) and k.startswith("articlesCount(") and isinstance(v, int):
                        self.last_total_count = v
                        break
                return store
            except DaangnNotFound:
                raise
            except Exception:
                if attempt < self.MAX_RETRIES - 1:
                    self._backoff_delay(attempt)
                else:
                    raise
        return None

    def _writer_info(self, store: Dict[str, Any], node: Dict[str, Any]) -> Tuple[str, str, str]:
        """(writerTypeV2 원값, 거래주체 한글, 직거래 구분 한글)."""
        wt = str(node.get("writerTypeV2") or "")
        sub = ""
        sref = node.get("subWriterType")
        if isinstance(sref, dict) and sref.get("__ref"):
            snode = store.get(sref["__ref"]) or {}
            sub = self.SUB_WRITER_TYPE_KO.get(str(snode.get("type") or ""), str(snode.get("type") or ""))
        elif isinstance(sref, str):
            sub = self.SUB_WRITER_TYPE_KO.get(sref, sref)
        return wt, self.WRITER_TYPE_KO.get(wt, wt), sub

    def _parse_ssr_articles(
        self,
        store: Dict[str, Any],
        region_label: str,
        sales_type_api: str,
        trade_type_api: str,
        writer_types: Optional[Iterable[str]] = None,
    ) -> List[Dict[str, Any]]:
        """RELAY_STORE dict에서 Article 노드들을 뽑아 매물 dict 리스트로 변환.

        writer_types: {"BROKER", "DIRECT_USER"} 부분집합. 지정하면 해당 작성자 유형만 남긴다
        (상세 요청 전에 걸러서 불필요한 요청을 줄인다).
        """
        allowed = {str(w).upper() for w in writer_types} if writer_types else None
        rows: List[Dict[str, Any]] = []
        for node in store.values():
            if not isinstance(node, dict) or node.get("__typename") != "Article":
                continue
            article_id = node.get("originalId") or node.get("id")
            area = node.get("area")
            wt_raw, wt_ko, sub_ko = self._writer_info(store, node)
            if allowed is not None and wt_raw.upper() not in allowed:
                continue
            trades_ref = node.get("trades") or {}
            trade_refs = trades_ref.get("__refs", []) if isinstance(trades_ref, dict) else []
            for tref in trade_refs:
                trade_node = store.get(tref) or {}
                t_type = str(trade_node.get("type") or "").upper()
                if t_type != trade_type_api.upper():
                    continue
                row: Dict[str, Any] = {
                    "매물번호": article_id,
                    "매물_URL": f"{self.realty_host}/articles/{article_id}",
                    "매물지역": region_label,
                    "매물유형": self.SALES_TYPE_MAP.get(sales_type_api.lower(), sales_type_api),
                    "거래유형": self.TRADE_TYPE_MAP.get(trade_type_api.lower(), trade_type_api),
                    "거래주체": wt_ko,
                    "직거래구분": sub_ko,
                    "면적": area,
                }
                if t_type in ("MONTH", "SHORT"):
                    row["보증금"] = trade_node.get("deposit")
                    row["월세"] = trade_node.get("monthlyPay")
                elif t_type == "BORROW":
                    row["전세금"] = trade_node.get("deposit")
                elif t_type == "BUY":
                    row["매매가"] = trade_node.get("price")
                rows.append(row)
                break  # 요청한 거래유형과 일치하는 첫 trade만 사용
        return rows

    def _fetch_article_detail(
        self, original_id: str, is_cancelled: Optional[Callable[[], bool]] = None
    ) -> Optional[Dict[str, Any]]:
        """매물 상세 페이지(SSR)에서 설명/주소/중개사무소 정보를 파싱해 반환.

        realty.daangn.com/articles/{id} 도 지도 페이지와 동일하게 window.RELAY_STORE에
        Article + BizProfile(중개사무소) 노드가 그대로 SSR로 내려온다.
        """
        url = f"{self.realty_host}/articles/{original_id}"
        for attempt in range(self.MAX_RETRIES):
            if is_cancelled and is_cancelled():
                return None
            try:
                r = curl_req.get(url, headers=self.headers, impersonate="chrome", timeout=self.timeout_sec)
                if r.status_code != 200:
                    raise RuntimeError(f"HTTP {r.status_code}")
                m = re.search(r'window\.RELAY_STORE\s*=\s*"(.*?)";</script>', r.text, re.S)
                if not m:
                    return None
                js_str = json.loads('"' + m.group(1) + '"')
                store = json.loads(js_str)
                article = None
                for node in store.values():
                    if (
                        isinstance(node, dict)
                        and node.get("__typename") == "Article"
                        and str(node.get("originalId")) == str(original_id)
                    ):
                        article = node
                        break
                if not article:
                    return None
                biz = None
                biz_ref = article.get("bizProfile")
                if isinstance(biz_ref, dict) and biz_ref.get("__ref"):
                    biz = store.get(biz_ref["__ref"])
                usage_raw = str(article.get("buildingUsage") or "")
                wt_raw, wt_ko, sub_ko = self._writer_info(store, article)
                result: Dict[str, Any] = {
                    "제목": article.get("addressInfo") or "",
                    "상세_내용": article.get("content") or "",
                    "주소": article.get("publicAddress") or article.get("address") or "",
                    "지번주소": article.get("publicJibunAddress") or "",
                    "방수": article.get("roomCnt"),
                    "욕실수": article.get("bathroomCnt"),
                    "층수": article.get("floor") or "",
                    "최고층수": article.get("topFloor") or "",
                    "사용승인일": article.get("buildingApprovalDate") or "",
                    "건축물용도": self.BUILDING_USAGE_KO.get(usage_raw, usage_raw),
                    "방향": self.ORIENTATION_KO.get(str(article.get("buildingOrientation") or ""), article.get("buildingOrientation") or ""),
                    "입주가능일": ("협의" if article.get("moveInDateNegotiable") else "") or article.get("moveInDate") or "",
                    "관리비": article.get("totalManageCost") or "",
                    "권리금": article.get("premiumMoney") or "",
                    "등록일시": article.get("publishedAt") or "",
                }
                if wt_ko:
                    result["거래주체"] = wt_ko
                    result["직거래구분"] = sub_ko
                if isinstance(biz, dict):
                    result["중개사무소"] = biz.get("businessCompanyName") or biz.get("name") or ""
                    result["중개사"] = biz.get("licenseOwnerName") or ""
                    result["중개사무소_연락처"] = biz.get("licenseOwnerContact") or ""
                    result["중개사무소_주소"] = biz.get("roadAddress") or biz.get("jibunAddress") or ""
                    result["중개등록번호"] = biz.get("licenseRegistrationNumber") or ""
                return result
            except Exception:
                if attempt < self.MAX_RETRIES - 1:
                    self._backoff_delay(attempt, is_cancelled=is_cancelled)
                else:
                    return None
        return None

    def _price_in_range(self, value: Any, lo: Optional[int], hi: Optional[int]) -> bool:
        if value is None:
            return True
        try:
            v = float(value)
        except (TypeError, ValueError):
            return True
        if lo is not None and v < lo:
            return False
        if hi is not None and v > hi:
            return False
        return True

    def _crawl_realty_ssr(
        self,
        region_name: str,
        sales_type: Optional[str],
        trade_type: Optional[str],
        area_min: Optional[int],
        area_max: Optional[int],
        monthly_pay_min: Optional[int],
        monthly_pay_max: Optional[int],
        month_price_min: Optional[int],
        month_price_max: Optional[int],
        borrow_price_min: Optional[int],
        borrow_price_max: Optional[int],
        buy_price_min: Optional[int],
        buy_price_max: Optional[int],
        short_monthly_pay_min: Optional[int],
        short_monthly_pay_max: Optional[int],
        short_price_min: Optional[int],
        short_price_max: Optional[int],
        on_item: Optional[Callable[[Dict[str, Any]], None]],
        is_cancelled: Optional[Callable[[], bool]],
        writer_types: Optional[Iterable[str]] = None,
    ) -> List[Dict[str, Any]]:
        """realty.daangn.com 신규 SSR 지도 페이지 기반 크롤링 (2026년 사이트 개편 대응).

        지역명 해석:
          "서울특별시 강남구 역삼동"        → 시도/시군구/동
          "경기도 수원시 영통구 영통동"     → 시도/"수원시 영통구"/동  (시+구는 한 세그먼트)
          "경기도 성남시 분당구"            → 동 페이지가 404면 시도/"성남시 분당구" 구 단위 페이지로 재시도
        """
        parts = region_name.split()
        si = parts[0] if parts else region_name
        if len(parts) >= 4:
            gun, dong = " ".join(parts[1:-1]), parts[-1]
        elif len(parts) == 3:
            gun, dong = parts[1], parts[2]
        elif len(parts) == 2:
            gun, dong = parts[1], ""
        else:
            gun, dong = "전체", region_name

        # UI는 "평수"(0~200) 단위 슬라이더를 쓰지만 새 사이트 데이터는 m^2 단위이므로 환산
        PYEONG_TO_M2 = 3.305785
        area_min_m2 = area_min * PYEONG_TO_M2 if area_min is not None else None
        area_max_m2 = area_max * PYEONG_TO_M2 if area_max is not None else None

        sales_list = [s for s in (sales_type or "").split(",") if s]
        trade_list = [t for t in (trade_type or "").split(",") if t]

        results: List[Dict[str, Any]] = []
        seen_keys = set()
        for sales_api in sales_list:
            if is_cancelled and is_cancelled():
                break
            sales_label = self.NEW_SALES_URL_LABEL.get(sales_api, sales_api)
            for trade_api in trade_list:
                if is_cancelled and is_cancelled():
                    break
                trade_label = self.NEW_TRADE_URL_LABEL.get(trade_api, trade_api)
                store = None
                try:
                    store = self._fetch_ssr_store(si, gun, dong, sales_label, trade_label)
                except DaangnNotFound:
                    # "경기도 성남시 분당구"처럼 마지막 토큰이 동이 아니라 구인 경우 → 시군구 세그먼트로 합쳐 재시도
                    if dong:
                        try:
                            store = self._fetch_ssr_store(si, f"{gun} {dong}", "", sales_label, trade_label)
                        except DaangnNotFound:
                            print(f"[당근-SSR] {region_name} {sales_label}/{trade_label}: 해당 지역 페이지 없음(404)")
                            continue
                        except Exception as e:
                            print(f"[당근-SSR] {region_name} {sales_label}/{trade_label} 실패: {e}")
                            continue
                    else:
                        print(f"[당근-SSR] {region_name} {sales_label}/{trade_label}: 해당 지역 페이지 없음(404)")
                        continue
                except Exception as e:
                    print(f"[당근-SSR] {region_name} {sales_label}/{trade_label} 실패: {e}")
                    continue
                if not store:
                    continue
                rows = self._parse_ssr_articles(
                    store, region_label=region_name,
                    sales_type_api=sales_api, trade_type_api=trade_api,
                    writer_types=writer_types,
                )
                total = self.last_total_count
                if total is not None and total > len(rows):
                    print(f"[당근-SSR] {region_name} {sales_label}/{trade_label}: 전체 {total}건 중 최신 {len(rows)}건 제공(웹 첫 페이지 한도)")
                # 유형 조합 사이 짧은 대기 (연속 요청 완화)
                time.sleep(random.uniform(0.4, 1.0))
                for row in rows:
                    if not self._price_in_range(row.get("면적"), area_min_m2, area_max_m2):
                        continue
                    t_upper = trade_api.upper()
                    if t_upper in ("MONTH", "SHORT"):
                        pay_lo, pay_hi = (short_monthly_pay_min, short_monthly_pay_max) if t_upper == "SHORT" else (monthly_pay_min, monthly_pay_max)
                        dep_lo, dep_hi = (short_price_min, short_price_max) if t_upper == "SHORT" else (month_price_min, month_price_max)
                        if not self._price_in_range(row.get("월세"), pay_lo, pay_hi):
                            continue
                        if not self._price_in_range(row.get("보증금"), dep_lo, dep_hi):
                            continue
                    elif t_upper == "BORROW":
                        if not self._price_in_range(row.get("전세금"), borrow_price_min, borrow_price_max):
                            continue
                    elif t_upper == "BUY":
                        if not self._price_in_range(row.get("매매가"), buy_price_min, buy_price_max):
                            continue
                    key = (row.get("매물번호"), row.get("거래유형"))
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    if is_cancelled and is_cancelled():
                        break
                    detail = self._fetch_article_detail(row.get("매물번호"), is_cancelled=is_cancelled)
                    if detail:
                        row.update(detail)
                    results.append(row)
                    if on_item:
                        try:
                            on_item(row)
                        except Exception:
                            pass
        print(f"{region_name}에서 {len(results)}개 매물 (신규 SSR)")
        return results

    def crawl_realty(
        self,
        in_: str,
        monthly_pay_min: Optional[int] = None,
        monthly_pay_max: Optional[int] = None,
        month_price_min: Optional[int] = None,
        month_price_max: Optional[int] = None,
        borrow_price_min: Optional[int] = None,
        borrow_price_max: Optional[int] = None,
        buy_price_min: Optional[int] = None,
        buy_price_max: Optional[int] = None,
        short_monthly_pay_min: Optional[int] = None,
        short_monthly_pay_max: Optional[int] = None,
        short_price_min: Optional[int] = None,
        short_price_max: Optional[int] = None,
        area_min: Optional[int] = None,
        area_max: Optional[int] = None,
        sales_type: Optional[str] = None,
        trade_type: Optional[str] = None,
        output_path: Optional[str] = None,
        csv_path: Optional[str] = None,
        return_results_only: bool = False,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
        on_item: Optional[Callable[[Dict[str, Any]], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
        region_name: Optional[str] = None,
        writer_types: Optional[Iterable[str]] = None,
    ) -> str | List[Dict[str, Any]]:
        """
        부동산 매물을 크롤링하고 엑셀 파일로 저장합니다.
        region_name: "서울특별시 강남구 역삼동"처럼 전체 지역명을 넘기면 2026년 개편된
            realty.daangn.com SSR 지도 페이지 기반으로 크롤링한다 (신규 방식, 권장).
            생략하면 예전 www.daangn.com API로 시도하는데, 해당 API는 사이트 개편으로
            더 이상 매물을 반환하지 않는다(항상 0건).
        date_start, date_end: 등록일(createdAt) 범위 필터. 신규 SSR 방식에는 등록일 정보가
            없어 현재는 적용되지 않는다 (구 API 폴백 경로에서만 동작).
        csv_path 지정 시 매물 추출 시마다 실시간으로 CSV에 한 줄씩 추가합니다.
        return_results_only=True면 저장 없이 결과 리스트만 반환.

        Returns:
            저장된 엑셀 파일 경로 (또는 results when return_results_only)
        """
        if region_name:
            results = self._crawl_realty_ssr(
                region_name=region_name,
                sales_type=sales_type,
                trade_type=trade_type,
                area_min=area_min,
                area_max=area_max,
                monthly_pay_min=monthly_pay_min,
                monthly_pay_max=monthly_pay_max,
                month_price_min=month_price_min,
                month_price_max=month_price_max,
                borrow_price_min=borrow_price_min,
                borrow_price_max=borrow_price_max,
                buy_price_min=buy_price_min,
                buy_price_max=buy_price_max,
                short_monthly_pay_min=short_monthly_pay_min,
                short_monthly_pay_max=short_monthly_pay_max,
                short_price_min=short_price_min,
                short_price_max=short_price_max,
                on_item=on_item,
                is_cancelled=is_cancelled,
                writer_types=writer_types,
            )
            if return_results_only:
                return results
            if not results:
                print("저장할 데이터가 없습니다.")
                return ""
            saved_path = self._save_to_excel(results, filepath=output_path)
            print(f"엑셀 저장 완료: {saved_path}")
            return saved_path

        # ---- 구 API 폴백 (2026년 사이트 개편 이후 서비스 종료, 항상 0건 반환됨) ----
        params = {
            "areaViewType": "p",
            "in": in_,
            "salesType": sales_type,
            "tradeType": trade_type,
            "_data": "routes/kr.realty.s"
        }
        trade_set = set((trade_type or "").split(",")) if trade_type else set()
        if "month" in trade_set:
            v = self._range_param(monthly_pay_min, monthly_pay_max)
            if v: params["monthMonthlyPay"] = v
            v = self._range_param(month_price_min, month_price_max)
            if v: params["monthPrice"] = v
        if "borrow" in trade_set:
            v = self._range_param(borrow_price_min, borrow_price_max)
            if v: params["borrowPrice"] = v
        if "buy" in trade_set:
            v = self._range_param(buy_price_min, buy_price_max)
            if v: params["buyPrice"] = v
        if "short" in trade_set:
            v = self._range_param(short_monthly_pay_min, short_monthly_pay_max)
            if v: params["shortMonthlyPay"] = v
            v = self._range_param(short_price_min, short_price_max)
            if v: params["shortPrice"] = v
        v = self._range_param(area_min, area_max)
        if v: params["area"] = v

        posts = self._get_posts(params)
        total = len(posts)
        posts = self._filter_posts_by_date(posts, date_start, date_end)
        if date_start or date_end:
            print(f"{in_} {total}개 조회 → 등록일 필터 후 {len(posts)}개")
        else:
            print(f"{in_}에서 {len(posts)}개 매물")
        
        results: List[Dict[str, Any]] = []
        csv_file = None
        csv_writer = None
        csv_keys: List[str] = []
        if not return_results_only and csv_path is None:
            csv_path = f"{str(output_path).rsplit('.', 1)[0]}.csv" if (output_path and "." in str(output_path)) else f"daangn_realty_{dt.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        for i, post in enumerate(posts):
            if is_cancelled and is_cancelled():
                print(f"[중단됨] 상세 조회 중단 ({i}/{len(posts)})")
                break
            post_id = post['id']
            post_imgs = post.get('images', [])
            post_img_url = post_imgs[0] if post_imgs else None
            post_detail = self._get_post_detail(post_id, list_post=post, post_img_url=post_img_url, is_cancelled=is_cancelled)
            if post_detail:
                results.append(post_detail)
                if on_item:
                    try:
                        on_item(post_detail)
                    except Exception:
                        pass
                print(f"[{i+1}/{len(posts)}] 추출 완료: {post_detail.get('매물번호', post_id)}")
                if not return_results_only:
                    if not csv_keys:
                        csv_keys = list(post_detail.keys())
                        csv_file = open(csv_path, "w", newline="", encoding="utf-8-sig")
                        csv_writer = csv.writer(csv_file)
                        csv_writer.writerow([self._sanitize_excel_str(str(k)) for k in csv_keys])
                    self._append_row_to_csv(post_detail, csv_file, csv_writer, csv_keys)
        
        if csv_file:
            csv_file.close()
            print(f"CSV 저장 완료: {csv_path}")
        
        if return_results_only:
            return results
        if not results:
            print("저장할 데이터가 없습니다.")
            return ""
        saved_path = self._save_to_excel(results, filepath=output_path)
        print(f"엑셀 저장 완료: {saved_path}")
        return saved_path

    async def _fetch_post_detail_async(
        self,
        session: AsyncSession,
        post_id: str,
        list_post: Dict[str, Any],
        semaphore: asyncio.Semaphore,
    ) -> Optional[Dict[str, Any]]:
        """비동기로 단일 매물 상세 조회 (동시성 제한)"""
        async with semaphore:
            for attempt in range(self.MAX_RETRIES):
                try:
                    r = await session.get(
                        f"{self.host}{post_id}",
                        impersonate="chrome",
                        timeout=self.timeout_sec,
                    )
                    if r.status_code != 200:
                        raise RuntimeError(f"HTTP {r.status_code}")
                    result = self.extract_realty_detail_from_html(r.text, list_post=list_post)
                    if not result:
                        raise ValueError("추출 데이터 없음")
                    return result
                except Exception:
                    if attempt < self.MAX_RETRIES - 1:
                        delay = min(self.RETRY_DELAY_MIN * (2 ** attempt), 60)
                        delay *= 0.5 + random.random()
                        await asyncio.sleep(delay)
                    else:
                        return None
        return None

    def crawl_realty_async(
        self,
        in_: str,
        monthly_pay_min: Optional[int] = None,
        monthly_pay_max: Optional[int] = None,
        month_price_min: Optional[int] = None,
        month_price_max: Optional[int] = None,
        borrow_price_min: Optional[int] = None,
        borrow_price_max: Optional[int] = None,
        buy_price_min: Optional[int] = None,
        buy_price_max: Optional[int] = None,
        short_monthly_pay_min: Optional[int] = None,
        short_monthly_pay_max: Optional[int] = None,
        short_price_min: Optional[int] = None,
        short_price_max: Optional[int] = None,
        area_min: Optional[int] = None,
        area_max: Optional[int] = None,
        sales_type: Optional[str] = None,
        trade_type: Optional[str] = None,
        output_path: Optional[str] = None,
        csv_path: Optional[str] = None,
        max_concurrent: int = 15,
        return_results_only: bool = False,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
    ) -> str | List[Dict[str, Any]]:
        """
        asyncio 기반 비동기 크롤링 - 동시다발적으로 상세 페이지 요청하여 속도 향상.
        date_start, date_end: 등록일(createdAt) 범위 필터
        monthMonthlyPay, monthPrice: min__max 형식 지원 (예: 30__150, 500__25000)
        
        Args:
            max_concurrent: 동시 요청 최대 개수 (기본 15)
            return_results_only: True면 저장 없이 결과 리스트만 반환
        
        Returns:
            저장된 엑셀 파일 경로 (또는 results when return_results_only)
        """
        params = {
            "areaViewType": "p",
            "in": in_,
            "salesType": sales_type,
            "tradeType": trade_type,
            "_data": "routes/kr.realty.s",
        }
        trade_set = set((trade_type or "").split(",")) if trade_type else set()
        if "month" in trade_set:
            for key, mn, mx in [("monthMonthlyPay", monthly_pay_min, monthly_pay_max), ("monthPrice", month_price_min, month_price_max)]:
                v = self._range_param(mn, mx)
                if v: params[key] = v
        if "borrow" in trade_set:
            v = self._range_param(borrow_price_min, borrow_price_max)
            if v: params["borrowPrice"] = v
        if "buy" in trade_set:
            v = self._range_param(buy_price_min, buy_price_max)
            if v: params["buyPrice"] = v
        if "short" in trade_set:
            for key, mn, mx in [("shortMonthlyPay", short_monthly_pay_min, short_monthly_pay_max), ("shortPrice", short_price_min, short_price_max)]:
                v = self._range_param(mn, mx)
                if v: params[key] = v
        v = self._range_param(area_min, area_max)
        if v: params["area"] = v
        posts = self._get_posts(params)
        total = len(posts)
        posts = self._filter_posts_by_date(posts, date_start, date_end)
        if date_start or date_end:
            print(f"{in_} {total}개 조회 → 등록일 필터 후 {len(posts)}개 (비동기 {max_concurrent})")
        else:
            print(f"{in_}에서 {len(posts)}개 매물 (비동기 {max_concurrent})")

        if not return_results_only and csv_path is None:
            csv_path = (
                f"{str(output_path).rsplit('.', 1)[0]}.csv"
                if (output_path and "." in str(output_path))
                else f"daangn_realty_{dt.now().strftime('%Y%m%d_%H%M%S')}.csv"
            )

        results: List[Dict[str, Any]] = []
        csv_keys: List[str] = []
        csv_lock = asyncio.Lock()

        async def run():
            nonlocal csv_keys
            semaphore = asyncio.Semaphore(max_concurrent)
            done_count = 0
            csv_file = None
            csv_writer = None

            async with AsyncSession(headers=self.headers, impersonate="chrome") as session:
                tasks = [
                    self._fetch_post_detail_async(session, p["id"], p, semaphore)
                    for p in posts
                ]
                for coro in asyncio.as_completed(tasks):
                    detail = await coro
                    if detail:
                        done_count += 1
                        print(f"[{done_count}/{len(posts)}] 추출 완료: {detail.get('매물번호', '')}")
                        results.append(detail)
                        if not return_results_only:
                            async with csv_lock:
                                if not csv_keys:
                                    csv_keys = list(detail.keys())
                                    csv_file = open(csv_path, "w", newline="", encoding="utf-8-sig")
                                    csv_writer = csv.writer(csv_file)
                                    csv_writer.writerow([self._sanitize_excel_str(str(k)) for k in csv_keys])
                                self._append_row_to_csv(detail, csv_file, csv_writer, csv_keys)

            if csv_file:
                csv_file.close()

        asyncio.run(run())

        if return_results_only:
            return results
        if csv_path:
            print(f"CSV 저장 완료: {csv_path}")
        if not results:
            print("저장할 데이터가 없습니다.")
            return ""
        saved_path = self._save_to_excel(results, filepath=output_path)
        print(f"엑셀 저장 완료: {saved_path}")
        return saved_path
        

if __name__ == "__main__":
    import json
    import os

    base_dir = os.path.dirname(os.path.abspath(__file__))
    regions_path = os.path.join(base_dir, "regions.seoul.json")
    with open(regions_path, "r", encoding="utf-8") as f:
        regions = json.load(f)

    crawler = DaangnRealtyCrawler()
    use_async = False
    total = len(regions)
    all_results: List[Dict[str, Any]] = []
    output_base = "daangn_seoul_all"

    for idx, (region_name, region_id) in enumerate(regions.items(), 1):
        dong = region_name.split()[-1]
        in_ = f"{dong}-{region_id}"
        print(f"\n[{idx}/{total}] {region_name} (in_={in_})")
        try:
            if use_async:
                rows = crawler.crawl_realty_async(
                    in_=in_,
                    monthly_pay_min=300,
                    month_price_min=20000,
                    sales_type="two_room",
                    trade_type="month",
                    max_concurrent=15,
                    return_results_only=True,
                )
            else:
                rows = crawler.crawl_realty(
                    in_=in_,
                    monthly_pay_min=300,
                    month_price_min=20000,
                    sales_type="two_room",
                    trade_type="month",
                    return_results_only=True,
                )
            if isinstance(rows, list):
                all_results.extend(rows)
        except Exception as e:
            print(f"  실패: {e}")

    if all_results:
        print(f"\n총 {len(all_results)}건 수집 완료. 저장 중...")
        crawler._save_to_excel(all_results, filepath=f"{output_base}.xlsx")
        with open(f"{output_base}.csv", "w", newline="", encoding="utf-8-sig") as f:
            keys = []
            seen = set()
            for r in all_results:
                for k in r.keys():
                    if k not in seen:
                        seen.add(k)
                        keys.append(k)
            w = csv.writer(f)
            w.writerow([crawler._sanitize_excel_str(str(k)) for k in keys])
            for r in all_results:
                w.writerow([crawler._cell_value(r.get(k)) for k in keys])
        print(f"엑셀: {output_base}.xlsx")
        print(f"CSV: {output_base}.csv")
    
    
    