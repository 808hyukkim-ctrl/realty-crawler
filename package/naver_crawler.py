# import requests as req
# from tls_client import Session
from curl_cffi import requests as curl_req 
import json
import math
import os
import sys
import random
import re
import xml.etree.ElementTree as ET
from datetime import datetime as dt, timedelta as td
from typing import Optional, Callable, List, Dict, Any, Generator
from bs4 import BeautifulSoup as bs
import time
from urllib.parse import urlencode
import requests


USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:148.0) Gecko/20100101 Firefox/148.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
]


# --- 유틸리티 함수 (모듈 레벨, 하위 호환) ---


def convert_price(price):
    if not price or price == 0:
        return None 
    
    if isinstance(price, str) and "억" in price:
        price = price.replace("억", "").replace(" ","").replace(",","")
        price = int(price)

    return "{:,}".format(int(int(price) * 10000))

def convert_date(date):

    if not date:
        return date 
    
    if len(date) == 6:
        new_date = date[:4] + "-" + date[4:]
    elif len(date) == 8:
        new_date = date[:4] + "-" + date[4:6] + "-" + date[6:]
    else:
        return date 

    return new_date 
    
def get_gongsi(landprice_res):
    landprice_total = landprice_res.json().get("landPriceTotal","")
    if landprice_total:
        landprice_floors = landprice_total.get("landPriceFloors","")
        if landprice_floors and isinstance(landprice_floors, list) and len(landprice_floors) > 0:
            for landprice_floor in landprice_floors:
                landprices = landprice_floor.get("landPrices", "")
                if landprices and isinstance(landprices, list) and len(landprices) > 0:
                    for landprice in landprices:
                        if landprice.get("stdYmd"):
                            gongsi_std_ymd = convert_date(str(landprice.get("stdYmd")))
                            return gongsi_std_ymd
                        
    return None 

def find_key_in_nested_dict(d, target_key):

    if isinstance(d, dict): 
        for key, value in d.items():
            if key == target_key:
                return value
            if isinstance(value, dict):
                result = find_key_in_nested_dict(value, target_key)
                if result is not None: 
                    return result
            elif isinstance(value, list): 
                for item in value:
                    if isinstance(item, dict): 
                        result = find_key_in_nested_dict(item, target_key)
                        if result is not None:
                            return result
    return None 


def find_keys_with_value(data, target_value):
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, dict):
                result = find_keys_with_value(value, target_value)
                if result:
                    return result
            else:
                if value == target_value:
                    return key
    return None


def prepare_params(params):
    prepared = {}
    for key, value in params.items():
        if value is None:
            prepared[key] = ''
        elif isinstance(value, bool):
            prepared[key] = 'true' if value else 'false'
        elif isinstance(value, (int, float)):
            prepared[key] = str(value)
        else:
            prepared[key] = str(value)
    return prepared


def _load_rls_file(file_path: str = "naver_rls.json") -> dict:
    """naver_rls.json 로드. PyInstaller 빌드 시 _MEIPASS 지원."""
    if getattr(sys, "frozen", False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base_path, file_path) if not os.path.isabs(file_path) else file_path
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError as e:
        raise FileNotFoundError(f"naver_rls.json 파일이 발견되지 않았습니다: {e}") from e


def _load_dotenv_local(base_dir: str) -> None:
    """프로젝트 폴더의 .env 를 os.environ에 반영(이미 설정된 키는 덮어쓰지 않음)."""
    path = os.path.join(base_dir, ".env")
    if not os.path.isfile(path):
        return
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip()
                if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                    val = val[1:-1]
                if key and key not in os.environ:
                    os.environ[key] = val
    except OSError:
        pass


# --- NaverCrawler 클래스 (GUI 통합용) ---

URL_REALESTATE_TYPE_DICT = {
    "APT": "complexes", "JGC": "complexes", "PRE": "complexes", "OBYG": "complexes",
    "ABYG": "complexes", "JGB": "complexes", "OPST": "complexes", "VL": "houses",
    "DDDGG": "houses", "JWJT": "houses", "SGJT": "houses", "HOJT": "houses",
    "OR": "rooms", "SG": "offices", "SMS": "offices", "APTHGJ": "offices",
    "GM": "offices", "TJ": "offices", "GJCG": "offices"
}
DIRECTION_DICT = {
    "EE": "동향", "WW": "서향", "SS": "남향", "NN": "북향",
    "EN": "북동향", "ES": "남동향", "WN": "북서향", "WS": "남서향"
}
BIZ_STEP_TYPES = {
    "01": "기본계획수립", "02": "안전진단", "03": "구역지정", "04": "추진위승인",
    "05": "조합설립인가", "06": "사업시행인가", "07": "관리처분인가", "08": "이주 및 철거",
    "09": "착공 및 분양", 10: "준공", 11: "이전고지"
}


class NaverCrawler:
    """네이버 부동산 크롤러. GUI 통합을 위한 콜백(on_log, on_progress, is_cancelled) 지원."""

    def __init__(
        self,
        rls_path: str = "naver_rls.json",
        on_log: Optional[Callable[[str], None]] = None,
        on_progress: Optional[Callable[[int, int, str], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
    ):
        self.exec_ts = str(int(time.time() * 1000))
        # os.makedirs(f"c_info_{self.exec_ts}", exist_ok=True)
        self.rls = _load_rls_file(rls_path)
        self.sess = curl_req.Session()
        self.search_sess = curl_req.Session()
        self.search_sess.headers = ({
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Connection": "keep-alive",
            # "Cookie": "wcs_bt=44058a670db444:1772390292; NAC=G7vyB8A6boIA; NNB=BZW4PTREO2SGS; BUC=u6DyicNjcDYy_PVU62p7KV2wb3w0WVLJqsEuxXAyYr8=; PROP_TEST_KEY=1772385831286.d5f2beba8244c28f2f7bfaefab9263eb6de232731ebcbdfd5f613638be3661ca; PROP_TEST_ID=05a8a147ac692c8f63b85efb4c82217e74241096fff1e206ac236e06d12760a0; NACT=1; REALESTATE=1772390178121; SRT30=1772389946; SRT5=1772389946",
            "Host": "m.land.naver.com",
            "Referer": "https://m.land.naver.com/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "TE": "trailers",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:148.0) Gecko/20100101 Firefox/148.0",
            "X-Requested-With": "XMLHttpRequest",
        })
        self.timeout_sec = 20
        self._bldrgst_max_attempts = max(1, int(os.getenv("BLDRGST_RETRY_ATTEMPTS", "3")))
        self._bldrgst_retry_backoff_sec = float(os.getenv("BLDRGST_RETRY_BACKOFF_SEC", "1.2"))
        # 전용면적 API 페이지네이션 상한 (이상 응답 시 무한 루프 방지)
        self._bldrgst_excl_max_pages = max(1, int(os.getenv("BLDRGST_EXCL_MAX_PAGES", "500")))
        self.sess.headers.update({
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "ko-KR,ko;q=0.8,en-US;q=0.5,en;q=0.3",
            "Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6IlJFQUxFU1RBVEUiLCJpYXQiOjE3NTU4NjE2MDIsImV4cCI6MTc1NTg3MjQwMn0.oUESmR0PhLfqPu50Dp0Ksd8hH6CbN69Kgy1AtKAJBkA",
            "Connection": "keep-alive",
            "Cookie": "NNB=DHVGK5NIFRZGQ; BUC=dQnzU4cEAFITbLHCXucm96M1Hygq1eXI9lNBTGomvQ8=; NAC=bf7HCYhdY1viB; nstore_session=GhC7pWraNQqUi1r/3Cat+iHt; nstore_pagesession=jcNSelqqFq2n0wsMS4d-275984; ASID=d261344a00000198112a58d000000023; nhn.realestate.article.rlet_type_cd=A01; nhn.realestate.article.trade_type_cd=\"\"; nhn.realestate.article.ipaddress_city=4100000000; _fwb=2477cFBKnotdBO5kFtJXAxb.1755860647279; landHomeFlashUseYn=Y; NACT=1; SRT30=1755860649; REALESTATE=Fri%20Aug%2022%202025%2020%3A20%3A02%20GMT%2B0900%20(Korean%20Standard%20Time); PROP_TEST_KEY=1755861602330.91922a3ba1b2bed031aac365bc7783fb4ad34c557cfec7fe9de50e9bbd33395f; PROP_TEST_ID=13ef4231cf828a73659d00b359317c1ed14816b42c7301637b8f1b90db90f7df; _fwb=2477cFBKnotdBO5kFtJXAxb.1755860647279; SRT5=1755861459",
            "Host": "new.land.naver.com",
            "Referer": "https://new.land.naver.com/rooms?ms=37.362105,127.1040745,17&a=APT:OPST:ABYG:OBYG:GM:OR:DDDGG:JWJT:SGJT:HOJT:VL&e=RETAIL&aa=SMALLSPCRENT",
            "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "same-origin",
            "TE": "trailers",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:142.0) Gecko/20100101 Firefox/142.0"
        })
        self._on_log = on_log or (lambda msg: print(msg, end=""))
        self._on_progress = on_progress or (lambda c, t, m: None)
        self._is_cancelled = is_cancelled or (lambda: False)
        # self._bldrgst_service_key = os.getenv(
        #     "BLDRGST_SERVICE_KEY",
        #     "318b0d0ce6832f4758bf8ed593807ba7c1c7f220ae46a757b06c3b5a66c079a0",
        # )
        self._bldrgst_service_key = "318b0d0ce6832f4758bf8ed593807ba7c1c7f220ae46a757b06c3b5a66c079a0"
        self._exclusive_area_cache: Dict[tuple, Dict[str, Dict[str, Any]]] = {}
        _base_dir = os.path.dirname(os.path.abspath(__file__))
        _load_dotenv_local(_base_dir)
        _mode = str(os.getenv("MODE") or os.getenv("mode") or "").strip().lower()
        _hosu_opt_out = str(os.getenv("HOSU_DEBUG_LOG", "1")).lower() in ("0", "false", "off", "no")
        # 호수 추론 상세 로그(hosu_infer_debug.log): .env 의 MODE/mode 가 dev 일 때만 기록. dev 에서도 HOSU_DEBUG_LOG=0 이면 끔.
        self._hosu_debug_enabled = _mode == "dev" and not _hosu_opt_out
        self._hosu_debug_log_path = os.path.join(_base_dir, "hosu_infer_debug.log")
        self._hosu_debug_log("=== 네이버 크롤러 시작 (호수 추론 로그) ===")

        self.IMG_BASE_URL = 'https://landthumb-phinf.pstatic.net'

    def _log(self, msg: str):
        self._on_log(str(msg) + "\n" if not msg.endswith("\n") else msg)

    def _rotate_ua(self):
        ua = random.choice(USER_AGENTS)
        self.search_sess.headers["User-Agent"] = ua
        return ua

    def _parse_pnu(self, pnu: Any) -> Optional[tuple]:
        pnu_str = str(pnu or "").strip()
        if not pnu_str.isdigit() or len(pnu_str) < 19:
            return None
        return (pnu_str[:5], pnu_str[5:10], pnu_str[11:15], pnu_str[15:19])

    def _parse_cortar_no(self, cortar_no: Any) -> Optional[tuple]:
        cortar_str = str(cortar_no or "").strip()
        if not cortar_str.isdigit() or len(cortar_str) < 10:
            return None
        return (cortar_str[:5], cortar_str[5:10])

    def _reverse_geocode_jibun(self, lat: Any, lon: Any) -> Optional[str]:
        """map.naver.com 역지오코딩(키 불필요)으로 좌표 → '시도 시군구 동 지번' 주소 복원.

        상가/사무실/건물/토지 매물은 텍스트 주소가 동까지만 내려오지만
        좌표는 실제 건물 위치라서 이 방법으로 정확한 지번을 얻을 수 있다.
        """
        try:
            # self.sess에는 Host: new.land.naver.com 헤더가 고정돼 있어 map.naver.com에 쓰면
            # 421이 나므로 역지오코딩 전용 세션을 별도로 사용한다.
            if not hasattr(self, "_geo_sess"):
                self._geo_sess = curl_req.Session()
            url = f"https://map.naver.com/p/api/location/geocode?coords={lon},{lat}&orders=addr&output=json"
            res = self._geo_sess.get(
                url,
                impersonate="chrome",
                timeout=self.timeout_sec,
                headers={"Referer": "https://map.naver.com/", "Accept": "application/json"},
            )
            if res.status_code != 200:
                return None
            for item in res.json().get("results") or []:
                if item.get("name") != "addr":
                    continue
                region = item.get("region") or {}
                land = item.get("land") or {}
                names = []
                for key in ("area1", "area2", "area3", "area4"):
                    nm = str((region.get(key) or {}).get("name") or "").strip()
                    if nm:
                        names.append(nm)
                n1 = str(land.get("number1") or "").strip()
                n2 = str(land.get("number2") or "").strip()
                if not names or not n1:
                    return None
                san = "산" if str(land.get("type") or "") == "2" else ""
                jibun = f"{san}{n1}" + (f"-{n2}" if n2 else "")
                return " ".join(names + [jibun])
        except Exception:
            pass
        return None

    def _extract_bun_ji_from_detail_addr(self, detail_addr: Any) -> Optional[tuple]:
        """
        detail_addr 끝 지번에서 본번/부번 추출.
        예: "... 1281-32" -> ("1281", "0032"), "... 1281" -> ("1281", "0000")
        """
        text = str(detail_addr or "").strip()
        if not text:
            return None
        matches = re.findall(r"(\d+)(?:-(\d+))?", text)
        if not matches:
            return None
        bun_raw, ji_raw = matches[-1]
        bun = bun_raw.zfill(4)
        ji = (ji_raw or "0").zfill(4)
        return (bun, ji)

    def _normalize_dong_name(self, dong: Any) -> Optional[str]:
        text = str(dong or "").strip()
        if not text:
            return None
        m = re.search(r"(\d+)\s*동", text)
        if m:
            return f"{m.group(1)}동"
        m = re.search(r"(\d+)", text)
        if m:
            return f"{m.group(1)}동"
        return text if text.endswith("동") else None

    def _dong_nm_api_variants(self, dong_nm: Optional[str]) -> List[Optional[str]]:
        """
        건축물대장 API `dongNm` 전달 순서.
        '101동'처럼 숫자+동이면 먼저 '101동'으로 조회하고, 결과가 비면 '101'만 넣어 재시도한다.
        '1동'은 기존과 같이 API에서 필터 생략에 가깝게 단일 값만 사용한다.
        """
        if dong_nm is None:
            return [None]
        s = str(dong_nm).strip()
        if not s:
            return [None]
        if s == "1동":
            return [s]
        m = re.fullmatch(r"(\d+)동", s)
        if m:
            return [s, m.group(1)]
        return [s]

    def _to_floor_int(self, floor: Any) -> Optional[int]:
        text = str(floor or "").strip()
        m = re.search(r"-?\d+", text)
        if not m:
            return None
        try:
            return int(m.group(0))
        except Exception:
            return None

    def _to_total_floor_int(self, total_floor: Any) -> Optional[int]:
        text = str(total_floor or "").strip()
        m = re.search(r"\d+", text)
        if not m:
            return None
        try:
            val = int(m.group(0))
            return val if val > 0 else None
        except Exception:
            return None

    def _infer_floor_band_target(self, floor: Any, total_floor: Any) -> Optional[int]:
        """
        '저/중/고' 같은 표기를 총층 기준 대표층으로 변환.
        """
        floor_text = str(floor or "").strip().lower()
        tf = self._to_total_floor_int(total_floor)
        if not floor_text or not tf:
            return None
        if "저" in floor_text:
            return max(1, int(round(tf * 0.2)))
        if "중" in floor_text:
            # 홀수 총층에서는 정확한 가운데층(올림)을 사용: 5층 -> 3층
            return max(1, (tf + 1) // 2)
        if "고" in floor_text:
            return max(1, int(round(tf * 0.8)))
        return None

    def _infer_floor_band_range(self, floor: Any, total_floor: Any) -> Optional[tuple[int, int]]:
        """
        '저/중/고' 표기일 때 총층 기준 포함 층 범위 (닫힌 구간).
        총층을 3등분해 하·중·상 층대로 나눔. (대표층 1개로 좁히지 않고 구간 전체를 후보로 쓸 때 사용)
        """
        floor_text = str(floor or "").strip().lower()
        tf = self._to_total_floor_int(total_floor)
        if not floor_text or not tf:
            return None
        hi_저 = max(1, tf // 3)
        hi_중 = max(hi_저, (2 * tf) // 3)
        if "저" in floor_text:
            return (1, hi_저)
        if "중" in floor_text:
            lo = min(hi_저 + 1, tf)
            hi = max(lo, hi_중)
            return (lo, hi)
        if "고" in floor_text:
            lo = min(hi_중 + 1, tf)
            hi = tf
            if lo > hi:
                return (tf, tf)
            return (lo, hi)
        return None

    def _is_basement_expected(self, floor: Any) -> bool:
        text = str(floor or "").strip().upper()
        if not text:
            return False
        if "지하" in text:
            return True
        if re.search(r"\bB\d+\b", text):
            return True
        m = re.search(r"-\d+", text)
        return bool(m)

    def _to_exclusive_area_float(self, article_space: Any, area2: Any) -> Optional[float]:
        area = None
        if isinstance(article_space, dict):
            area = article_space.get("exclusiveSpace")
        if area in (None, ""):
            area = area2
        try:
            return float(area) if area not in (None, "") else None
        except Exception:
            return None

    def _truncate_2dp(self, value: Optional[float]) -> Optional[float]:
        if value is None:
            return None
        try:
            # 반올림이 아니라 소수 둘째 자리에서 0 방향으로 끊기. int(x*100)는 부동소수점 오차로 한 자리 밀릴 수 있음.
            v = float(value)
            if v >= 0:
                return math.floor(v * 100 + 1e-9) / 100
            return math.ceil(v * 100 - 1e-9) / 100
        except Exception:
            return None

    def _hosu_debug_log(self, message: str) -> None:
        if not self._hosu_debug_enabled:
           return
        try:
           ts = dt.now().strftime("%Y-%m-%d %H:%M:%S")
           with open(self._hosu_debug_log_path, "a", encoding="utf-8") as f:
               f.write(f"[{ts}] {message}\n")
        except Exception:
           pass
        # pass

    def _hosu_debug_block(self, title: str, payload: Dict[str, Any]) -> None:
        if not self._hosu_debug_enabled:
            return
        lines = [f"── {title} ──"]
        for k, v in payload.items():
            lines.append(f"  {k}: {v}")
        lines.append("─" * 36)
        self._hosu_debug_log("\n".join(lines))

    def _request_bldrgst_with_retry(
        self,
        url: str,
        params: Dict[str, Any],
        page: int,
    ) -> Optional[requests.Response]:
        retryable_statuses = {408, 425, 429, 500, 502, 503, 504}
        for attempt in range(1, self._bldrgst_max_attempts + 1):
            try:
                resp = requests.get(url, params=params, timeout=self.timeout_sec)
                if resp.status_code == 200:
                    return resp

                resp_text = (resp.text or "").strip()
                preview = resp_text[:300].replace("\n", " ").replace("\r", " ")
                self._hosu_debug_log(
                    f"[건축물대장] HTTP 비정상 페이지={page} 시도={attempt}/{self._bldrgst_max_attempts} "
                    f"상태코드={resp.status_code} 응답일부={preview}"
                )
                if resp.status_code not in retryable_statuses or attempt >= self._bldrgst_max_attempts:
                    return resp
            except Exception as e:
                self._hosu_debug_log(
                    f"[건축물대장] 요청 예외 페이지={page} 시도={attempt}/{self._bldrgst_max_attempts} 오류={e}"
                )
                if attempt >= self._bldrgst_max_attempts:
                    return None

            sleep_sec = self._bldrgst_retry_backoff_sec * (2 ** (attempt - 1)) + random.uniform(0, 0.25)
            self._hosu_debug_log(
                f"[건축물대장] 재시도 대기 페이지={page} 다음시도={attempt + 1} 대기초={sleep_sec:.2f}"
            )
            time.sleep(sleep_sec)
        return None

    def _fetch_exclusive_unit_map(
        self,
        sigungu_cd: str,
        bjdong_cd: str,
        bun: str,
        ji: str,
        dong_nm: Optional[str] = None,
    ) -> Dict[str, Dict[str, Any]]:
        if not self._bldrgst_service_key:
            self._hosu_debug_log("[건축물대장] 건너뜀: 공공데이터 서비스키 없음")
            return {}

        cache_key = (sigungu_cd, bjdong_cd, bun, ji, dong_nm or "")
        if cache_key in self._exclusive_area_cache:
            n = len(self._exclusive_area_cache[cache_key])
            self._hosu_debug_log(
                f"[건축물대장] 캐시 사용 시군구={sigungu_cd} 법정동={bjdong_cd} 번={bun} 지={ji} 동명={dong_nm or '(미지정)'} 호수={n}건"
            )
            return self._exclusive_area_cache[cache_key]

        self._hosu_debug_log(
            f"[건축물대장] 전용면적 조회 시작 시군구={sigungu_cd} 법정동={bjdong_cd} 번={bun} 지={ji} 동명={dong_nm or '(미지정)'}"
        )
        unit_map: Dict[str, Dict[str, Any]] = {}
        page = 1
        total = None
        had_success_response = False
        base_url = "https://apis.data.go.kr/1613000/BldRgstHubService/getBrExposPubuseAreaInfo"
        while True:
            if page > self._bldrgst_excl_max_pages:
                self._hosu_debug_log(
                    f"[건축물대장] 중단: 페이지 상한 도달 page={page} max={self._bldrgst_excl_max_pages}"
                )
                break
            params = {
                "serviceKey": self._bldrgst_service_key,
                "sigunguCd": sigungu_cd,
                "bjdongCd": bjdong_cd,
                "platGbCd": "0",
                "bun": bun,
                "ji": ji,
                "numOfRows": 100,
                "pageNo": page,
            }
            if dong_nm and dong_nm != "1동":
                params["dongNm"] = dong_nm
            try:
                # 건축물대장 API는 requests 방식으로 고정
                resp = self._request_bldrgst_with_retry(base_url, params, page)
                if resp is None:
                    self._hosu_debug_log(f"[건축물대장] 중단: 재시도 후에도 요청 실패 페이지={page}")
                    break
                self._hosu_debug_log(f"[건축물대장] 응답 페이지={page} HTTP상태={resp.status_code}")
                resp_text = (resp.text or "").strip()
                self._hosu_debug_log(f"[건축물대장] 응답 본문 길이={len(resp_text)}바이트")
                if resp.status_code != 200:
                    preview = resp_text[:300].replace("\n", " ").replace("\r", " ")
                    self._hosu_debug_log(
                        f"[건축물대장] HTTP 비정상 본문 페이지={page} 상태={resp.status_code} 일부={preview}"
                    )

                if not resp_text:
                    self._hosu_debug_log("[건축물대장] 중단: 응답 본문 없음")
                    break

                try:
                    root = ET.fromstring(resp_text)
                except Exception as pe:
                    preview = resp_text[:200].replace("\n", " ").replace("\r", " ")
                    self._hosu_debug_log(
                        f"[건축물대장] XML 파싱 실패 페이지={page} 오류={pe} 일부={preview}"
                    )
                    break
                had_success_response = True
            except Exception as e:
                self._hosu_debug_log(f"[건축물대장] 예외 페이지={page} 내용={e}")
                break

            result_code = (root.findtext(".//resultCode") or "").strip()
            result_msg = (root.findtext(".//resultMsg") or "").strip()
            if result_code and result_code not in ("00", "000"):
                self._hosu_debug_log(
                    f"[건축물대장] API 오류 코드={result_code} 메시지={result_msg}"
                )
                break

            if total is None:
                try:
                    total = int(root.findtext(".//totalCount", "0"))
                except Exception:
                    total = 0
                self._hosu_debug_log(f"[건축물대장] 응답 총건수={total}")

            items = root.findall(".//item")
            if not items:
                self._hosu_debug_log(f"[건축물대장] 중단: 해당 페이지에 item 없음 페이지={page}")
                break

            before = len(unit_map)
            for item in items:
                expos_type = (item.findtext("exposPubuseGbCdNm") or "").strip()
                if expos_type != "전유":
                    continue
                ho_nm = (item.findtext("hoNm") or "").strip()
                if not ho_nm:
                    continue
                try:
                    area = float(item.findtext("area") or "0")
                except Exception:
                    continue
                unit_map[ho_nm] = {
                    "area": area,
                    "mgmBldrgstPk": (item.findtext("mgmBldrgstPk") or "").strip(),
                }
            self._hosu_debug_log(
                f"[건축물대장] 페이지 처리 완료 페이지={page} 원본항목={len(items)} 이번에추가={len(unit_map) - before} 누적호수={len(unit_map)}"
            )

            if total is not None and page * 100 >= total:
                self._hosu_debug_log(f"[건축물대장] 전체 페이지 수집 완료 마지막페이지={page}")
                break
            page += 1

        if had_success_response and unit_map:
            self._exclusive_area_cache[cache_key] = unit_map
        elif had_success_response:
            self._hosu_debug_log(
                f"[건축물대장] 캐시 저장 안 함 (유효 전유 호수 0건, 빈 결과는 캐시하지 않음) 시군구={sigungu_cd} 법정동={bjdong_cd} 번={bun} 지={ji}"
            )
        else:
            self._hosu_debug_log(
                f"[건축물대장] 캐시 저장 안 함 (성공 응답 없음) 시군구={sigungu_cd} 법정동={bjdong_cd} 번={bun} 지={ji}"
            )
        self._hosu_debug_log(
            f"[건축물대장] 조회 종료 시군구={sigungu_cd} 법정동={bjdong_cd} 번={bun} 지={ji} 동명={dong_nm or '(미지정)'} 최종호수={len(unit_map)}건"
        )
        return unit_map

    def _infer_hosu(
        self,
        c_info: Dict[str, Any],
        dong: Any,
        floor: Any,
        total_floor: Any,
        article_space: Any,
        area2: Any,
        detail_addr: Any,
        sojaeji: Any = None,
    ) -> Optional[str]:
        article_no = find_key_in_nested_dict(c_info, "articleNo")
        realestate_type_code = str(find_key_in_nested_dict(c_info, "realestateTypeCode") or "")
        article_url = (
            f"https://new.land.naver.com/{URL_REALESTATE_TYPE_DICT.get(realestate_type_code, 'complexes')}?articleNo={article_no}"
            if article_no else None
        )
        dong_nm = self._normalize_dong_name(dong)
        floor_no = self._to_floor_int(floor)
        band_target_floor = self._infer_floor_band_target(floor, total_floor)
        band_floor_range = self._infer_floor_band_range(floor, total_floor)
        basement_expected = self._is_basement_expected(floor)
        target_area = self._to_exclusive_area_float(article_space, area2)
        target_area_trunc = self._truncate_2dp(target_area)
        self._hosu_debug_block("호수 추론 입력", {
            "매물번호": article_no,
            "매물 URL": article_url,
            "부동산 유형 코드": realestate_type_code,
            "법정동 코드(네이버)": find_key_in_nested_dict(c_info, "cortarNo"),
            "단지번호": find_key_in_nested_dict(c_info, "hscpNo"),
            "건물번호": find_key_in_nested_dict(c_info, "buildNo"),
            "관리 건축물대장 PK": find_key_in_nested_dict(c_info, "mgmBldrgstPk"),
            "동(원문)": dong,
            "층(원문)": floor,
            "전체 층(원문)": total_floor,
            "동명(정규화)": dong_nm,
            "층 숫자(정규화)": floor_no,
            "저·중·고 대표층": band_target_floor,
            "저·중·고 층 범위(포함)": band_floor_range,
            "지하 매물 추정": basement_expected,
            "전용면적 보조값": area2,
            "목표 전용면적": target_area,
            "목표 전용면적(소수 둘째자리 절사)": target_area_trunc,
            "상세 주소": detail_addr,
            "소재지": sojaeji,
        })
        if not dong_nm:
            self._hosu_debug_log(f"[호수 추론] 안내 매물번호={article_no} 동명 없음 → 동 조건 없이 진행")
        if floor_no is None:
            if band_floor_range is not None:
                lo_r, hi_r = band_floor_range
                self._hosu_debug_log(
                    f"[호수 추론] 안내 매물번호={article_no} 저·중·고 구간 → 호수층 {lo_r}~{hi_r}층 구간에 해당하는 호 전부 유지 (대표층 최소거리 필터 없음)"
                )
            elif band_target_floor is not None:
                self._hosu_debug_log(
                    f"[호수 추론] 안내 매물번호={article_no} 저·중·고 대표층={band_target_floor} (층 범위 미산출)"
                )
            else:
                self._hosu_debug_log(f"[호수 추론] 안내 매물번호={article_no} 층 숫자 없음 → 층 조건 없이 진행")
        if target_area is None:
            self._hosu_debug_log(f"[호수 추론] 안내 매물번호={article_no} 전용면적 없음 → 면적 조건 없이 진행")

        cortar_no = find_key_in_nested_dict(c_info, "cortarNo")
        parsed_cortar = self._parse_cortar_no(cortar_no)
        if not parsed_cortar:
            self._hosu_debug_log(
                f"[호수 추론] 실패 매물번호={article_no} 사유=법정동코드(네이버) 파싱 실패 값={cortar_no}"
            )
            return None

        bun_ji = self._extract_bun_ji_from_detail_addr(detail_addr)
        bunji_source = "detail_addr"
        if not bun_ji:
            bun_ji = self._extract_bun_ji_from_detail_addr(sojaeji)
            bunji_source = "sojaeji"
        if not bun_ji:
            self._hosu_debug_log(
                f"[호수 추론] 실패 매물번호={article_no} 사유=지번 추출 실패 상세주소={detail_addr!r} 소재지={sojaeji!r}"
            )
            return None

        sigungu_cd, bjdong_cd = parsed_cortar
        bun, ji = bun_ji
        dong_nm_variants = self._dong_nm_api_variants(dong_nm)
        bunji_src_ko = "상세 주소" if bunji_source == "detail_addr" else "소재지"
        self._hosu_debug_block("호수 추론 · 지번·행정코드", {
            "매물번호": article_no,
            "지번 출처": bunji_src_ko,
            "법정동 코드(원문)": cortar_no,
            "시군구 코드": sigungu_cd,
            "법정동 코드(파싱)": bjdong_cd,
            "번": bun,
            "지": ji,
            "동명(정규화)": dong_nm,
            "대장 API 동명 후보(순서대로)": dong_nm_variants,
        })

        unit_map: Dict[str, Dict[str, Any]] = {}
        last_try: Optional[str] = None
        for try_dong in dong_nm_variants:
            last_try = try_dong
            unit_map = self._fetch_exclusive_unit_map(sigungu_cd, bjdong_cd, bun, ji, try_dong)
            if unit_map:
                if len(dong_nm_variants) > 1 and try_dong != dong_nm_variants[0]:
                    self._hosu_debug_log(
                        f"[호수 추론] 동명 재시도 성공 매물번호={article_no} 사용동명={try_dong!r} 앞선시도(0건)={dong_nm_variants[0]!r}"
                    )
                break
            if len(dong_nm_variants) > 1 and try_dong == dong_nm_variants[0]:
                self._hosu_debug_log(
                    f"[호수 추론] 동명 재시도 매물번호={article_no} 동명={try_dong!r} 결과=0건 다음={dong_nm_variants[1:]!r}"
                )
        if not unit_map:
            self._hosu_debug_log(
                f"[호수 추론] 실패 매물번호={article_no} 사유=건축물대장 전용면적 호 목록 없음 동명(정규화)={dong_nm} 시도한동명={dong_nm_variants} 마지막시도={last_try!r}"
            )
            return None

        # 1차 mgmBldrgstPk 매핑 시도 로직 임시 비활성화
        # target_mgm_pk = str(find_key_in_nested_dict(c_info, "mgmBldrgstPk") or "").strip()
        # if target_mgm_pk:
        #     mgm_candidate = None
        #     for ho_nm, unit in unit_map.items():
        #         unit_mgm = str((unit or {}).get("mgmBldrgstPk") or "").strip()
        #         if unit_mgm != target_mgm_pk:
        #             continue
        #         if (not basement_expected) and re.search(r"[bB]", str(ho_nm or "")):
        #             continue
        #         mgm_candidate = ho_nm if ho_nm.endswith("호") else f"{ho_nm}호"
        #         break
        #     if mgm_candidate:
        #         self._hosu_debug_log(
        #             f"infer mgm success: articleNo={article_no}, mgmBldrgstPk={target_mgm_pk}, result={mgm_candidate}"
        #         )
        #         return mgm_candidate
        #     self._hosu_debug_log(
        #         f"infer mgm no-match: articleNo={article_no}, mgmBldrgstPk={target_mgm_pk} -> 일반 필터 진행"
        #     )

        candidates = []
        total_checked = 0
        for ho_nm, unit in unit_map.items():
            total_checked += 1
            if (not basement_expected) and re.search(r"[bB]", str(ho_nm or "")):
                continue
            area = unit.get("area")
            digits = re.sub(r"[^\d]", "", ho_nm)
            if not digits:
                continue
            try:
                ho_int = int(digits)
            except Exception:
                continue
            ho_floor = ho_int // 100 if ho_int >= 100 else 1
            if floor_no is not None and ho_floor != floor_no:
                continue
            if target_area is not None:
                area_trunc = self._truncate_2dp(area)
                if area_trunc != target_area_trunc:
                    continue
            candidates.append(ho_nm if ho_nm.endswith("호") else f"{ho_nm}호")

        # floor가 '저/중/고'처럼 모호한 경우: 총층 기준 저·중·고 층대(구간)에 속하는 호만 남김. 구간 안에서는 전부 유지(대표층과의 최소거리로 1개로 줄이지 않음).
        if floor_no is None and band_floor_range is not None and candidates:
            def _ho_floor_from_name(ho: str) -> Optional[int]:
                d = re.sub(r"[^\d]", "", ho or "")
                if not d:
                    return None
                try:
                    v = int(d)
                except Exception:
                    return None
                return v // 100 if v >= 100 else 1

            lo, hi = band_floor_range
            with_floor = []
            for c in candidates:
                cf = _ho_floor_from_name(c)
                if cf is not None:
                    with_floor.append((c, cf))
            if with_floor:
                candidates = [c for c, cf in with_floor if lo <= cf <= hi]
            else:
                # 호명에서 층을 추출 못 하면 구간 필터를 적용할 수 없음 → 임의로 전 면적매칭 후보만 남기지 않음
                self._hosu_debug_log(
                    f"[호수 추론] 안내 매물번호={article_no} 저·중·고 구간 필터인데 호명에서 층 추출 불가 → 후보 제거"
                )
                candidates = []

        if not candidates:
            self._hosu_debug_log(
                f"[호수 추론] 실패 매물번호={article_no} 사유=층·면적 조건 후 호수 후보 없음 대장에서검사={total_checked}건 "
                f"층숫자={floor_no} 저중고층범위={band_floor_range} 저중고대표층={band_target_floor} 목표면적={target_area}"
            )
            return None
        if len(candidates) == 1:
            result = candidates[0]
            self._hosu_debug_block("호수 추론 결과", {
                "매물번호": article_no,
                "추정 호수": result,
                "후보 개수": 1,
                "대장에서 검사한 호수": total_checked,
            })
            self._hosu_debug_log(f"[호수 추론] 성공 매물번호={article_no} 호수={result}")
            return result
        result = ",".join(sorted(set(candidates)))
        self._hosu_debug_block("호수 추론 결과", {
            "매물번호": article_no,
            "추정 호수(복수, 쉼표 구분)": result,
            "후보 개수": len(sorted(set(candidates))),
            "대장에서 검사한 호수": total_checked,
        })
        self._hosu_debug_log(f"[호수 추론] 복수 후보 매물번호={article_no} 호수={result}")
        return result

    def get_r(self, si: str, gu: str, dong: str) -> List:
        """시/구/동 선택에 따른 지역 코드 반환 [si, gu, dong, r_no]"""
        if gu == "구 선택":
            first_gu_key = list(self.rls[si].keys())[0]
            first_dong_key = list(self.rls[si][first_gu_key].keys())[0]
            r_no = self.rls[si][first_gu_key][first_dong_key][:2].ljust(10, "0")
            return [si, None, None, r_no]
        elif dong == "동 선택":
            first_dong_key = list(self.rls[si][gu].keys())[0]
            return [si, gu, None, self.rls[si][gu][first_dong_key][:5].ljust(10, "0")]
        return [si, gu, dong, self.rls[si][gu][dong]]
    
    # bbox 정식 명칭 → naver_rls 약칭 매핑
    _FULL_TO_SHORT_SI = {
        "서울특별시": "서울시", "인천광역시": "인천시", "부산광역시": "부산시",
        "대전광역시": "대전시", "대구광역시": "대구시", "울산광역시": "울산시",
        "광주광역시": "광주시", "세종특별자치시": "세종시",
        "강원특별자치도": "강원도", "전라북도": "전북도", "제주특별자치도": "제주도",
    }

    def _resolve_rls_keys(self, region_name: str) -> Optional[tuple]:
        """지역명 문자열 → (시도키, 시군구키, 동키) 매핑.
        '서울특별시 강남구 개포동', '서울시 강남구 개포동', '경기도 고양시 덕양구 강매동' 등 지원.
        구 키에 공백이 있는 경우(고양시 덕양구, 안양시 만안구)는 첫 토큰이 시도, 마지막 토큰이 동, 중간이 시군구."""
        parts = region_name.split()
        if len(parts) < 2:
            return None
        si_full = parts[0]
        si = self._FULL_TO_SHORT_SI.get(si_full, si_full)
        if si not in self.rls:
            return None
        if len(parts) == 2:
            gu = parts[1]
            dong = None
        else:
            dong = parts[-1]
            gu = " ".join(parts[1:-1])
        if gu not in self.rls[si]:
            return None
        if dong and dong not in self.rls[si][gu]:
            return None
        return (si, gu, dong or "동 선택")

    def crawl_complexes_v2(
        self,
        realestate_type: str,
        trade_type: str,
        regions_bbox: Dict[str, Dict[str, float]],
        region_names: List[str],
        min_date: Optional[dt] = None,
        wprc_min: Optional[int] = None,
        wprc_max: Optional[int] = None,
        rprc_min: Optional[int] = None,
        rprc_max: Optional[int] = None,
        dprc_min: Optional[int] = None,
        dprc_max: Optional[int] = None,
        spc_min: Optional[int] = None,
        spc_max: Optional[int] = None,
    ) -> Generator[list, None, None]:
        """regions_bbox 기반으로 동을 순회하며 articleList API를 페이지네이션하고,
        수집된 atclNo마다 extract_detail_v2를 호출하여 상세 데이터를 yield한다."""
        url = "https://m.land.naver.com/cluster/ajax/articleList"
        seen_atcl: set[str] = set()
        total_yielded = 0

        for region_idx, region_name in enumerate(region_names, 1):
            if self._is_cancelled():
                self._log(f"중단 요청됨 (동 순회 {region_idx}/{len(region_names)})")
                break

            bbox = regions_bbox.get(region_name)
            if not bbox:
                self._log(f"bbox 없음 (건너뜀): {region_name}")
                continue

            lat = (bbox["lat_min"] + bbox["lat_max"]) / 2
            lon = (bbox["lon_min"] + bbox["lon_max"]) / 2

            params: Dict[str, Any] = {
                "itemId": "", "mapKey": "", "lgeo": "", "showR0": "", "z": "12",
                "rletTpCd": realestate_type,
                "tradTpCd": trade_type,
                "lat": lat, "lon": lon,
                "btm": bbox["lat_min"] - 0.02, "lft": bbox["lon_min"] - 0.025,
                "top": bbox["lat_max"] + 0.02, "rgt": bbox["lon_max"] + 0.025,
                "sort": "dates", "page": 0,
            }
            if wprc_min: params["wprcMin"] = wprc_min
            if wprc_max: params["wprcMax"] = wprc_max
            if rprc_min: params["rprcMin"] = rprc_min
            if rprc_max: params["rprcMax"] = rprc_max
            if dprc_min: params["dprcMin"] = dprc_min
            if dprc_max: params["dprcMax"] = dprc_max
            if spc_min: params["spcMin"] = spc_min
            if spc_max: params["spcMax"] = spc_max

            page = 1
            date_break = False
            older_day_count = 0

            while True:
                if self._is_cancelled():
                    break
                if older_day_count >= 5:
                    print(f"[{region_idx}/{len(region_names)}] {region_name}: 5회 이상 연속 날짜 필터보다 이전 매물 출현 -> 건너뜀")
                    older_day_count = 0
                    break

                self._rotate_ua()
                params["page"] = page
                print(f"[{region_idx}/{len(region_names)}] {region_name} (p{page})")

                data = None 
                for _ in range(3):
                    try:
                        time.sleep(random.uniform(2, 3))
                        res = self.search_sess.get(url, params=params, impersonate='chrome', timeout=self.timeout_sec)
                        print(url + "?" + urlencode(params))
                        print(res.text, res)
                        data = res.json()
                        break
                    except Exception as e:
                        self._log(f"articleList 요청 실패 ({region_name}, p{page}): {e}")
                        print(f"[{region_idx}/{len(region_names)}] {region_name}: articleList 요청 실패 (p{page}): {e}")
                        continue

                if not data:
                    break

                body = data.get("body", [])
                more = data.get("more", False)

                if not body:
                    break

                self._log(f"[{region_idx}/{len(region_names)}] {region_name}: {page}페이지, {len(body)}건")
                print(f"[{region_idx}/{len(region_names)}] {region_name}: {page}페이지, {len(body)}건")

                for item in body:
                    if self._is_cancelled():
                        break

                    atcl_cfm_ymd = item.get("atclCfmYmd", "")
                    print(f"[{region_idx}/{len(region_names)}] {region_name}: atcl_cfm_ymd={atcl_cfm_ymd}")
                    if atcl_cfm_ymd and min_date:
                        try:
                            item_date = dt.strptime(atcl_cfm_ymd.rstrip("."), "%y.%m.%d")
                            # print(f"[{region_idx}/{len(region_names)}] {region_name}: 날짜 필터 적용 (atcl_cfm_ymd={atcl_cfm_ymd}, item_date={item_date}, min_date={min_date})")
                            if item_date < min_date:
                                # print(f"[{region_idx}/{len(region_names)}] {region_name}: 날짜 필터 적용 (atcl_cfm_ymd={atcl_cfm_ymd}, item_date={item_date}, min_date={min_date})")
                                # date_break = True
                                # break
                                older_day_count += 1
                                continue 
                        except ValueError:
                            pass

                    atcl_no = str(item.get("atclNo", ""))
                    print(f"[{region_idx}/{len(region_names)}] {region_name}: atcl_no={atcl_no}")
                    if not atcl_no or atcl_no in seen_atcl:
                        print(f"[{region_idx}/{len(region_names)}] {region_name}: 중복 매물 건너뜀 (atcl={atcl_no})")
                        continue
                    seen_atcl.add(atcl_no)

                    try:
                        detail = self.extract_detail_v2(atcl_no)
                        if detail:
                            total_yielded += 1
                            self._on_progress(region_idx, len(region_names), f"누적 {total_yielded}건")
                            yield detail
                    except Exception as e:
                        self._log(f"상세 추출 실패 (atcl={atcl_no}): {e}")
                        print(f"[{region_idx}/{len(region_names)}] {region_name}: 상세 추출 실패 (atcl={atcl_no}): {e}")

                if date_break or not more:
                    print(f"[{region_idx}/{len(region_names)}] {region_name}: 날짜 필터 또는 더 이상 데이터 없음")
                    break
                page += 1

        self._log(f"완료: 총 {total_yielded}건")
        print(f"완료: 총 {total_yielded}건")

    def crawl_complexes_v1(
        self,
        realestate_type: str,
        trade_type: str,
        region_names: List[str],
        min_date: Optional[dt] = None,
        min_deal_price: Optional[int] = None,
        max_deal_price: Optional[int] = None,
        min_warranty_price: Optional[int] = None,
        max_warranty_price: Optional[int] = None,
        min_rent_price: Optional[int] = None,
        max_rent_price: Optional[int] = None,
        min_area: Optional[int] = None,
        max_area: Optional[int] = None,
        is_hosu_needed: bool = True,
        max_pages: Optional[int] = None
    ) -> Generator[list, None, None]:
        """new.land.naver.com/api/articles 기반으로 동을 순회하며 articleList를 페이지네이션하고,
        수집된 articleNo마다 extract_detail_v2를 호출하여 상세 데이터를 yield한다.

        max_pages: 동 하나당 최대로 넘길 페이지 수. None이면 매물이 더 없을 때까지 모두 순회.
        """
        url = "https://new.land.naver.com/api/articles"
        seen_atcl: set[str] = set()
        total_yielded = 0

        for region_idx, region_name in enumerate(region_names, 1):
            if self._is_cancelled():
                self._log(f"중단 요청됨 (동 순회 {region_idx}/{len(region_names)})")
                break

            resolved = self._resolve_rls_keys(region_name)
            if not resolved:
                self._log(f"지역 매핑 실패 (건너뜀): {region_name}")
                continue

            si, gu, dong = resolved
            r = self.get_r(si, gu, dong)
            r_no = r[3]

            # 가격 범위 계산
            if trade_type and "A1" in trade_type and ("B1" in trade_type or "B2" in trade_type):
                min_price = min(min_deal_price if min_deal_price else 0, min_warranty_price if min_warranty_price else 0)
                max_price = max(max_deal_price if max_deal_price else 900000000, max_warranty_price if max_warranty_price else 900000000)
            elif trade_type and "A1" in trade_type:
                min_price = min_deal_price if min_deal_price else 0
                max_price = max_deal_price if max_deal_price else 900000000
            elif trade_type and ("B1" in trade_type or "B2" in trade_type):
                min_price = min_warranty_price if min_warranty_price else 0
                max_price = max_warranty_price if max_warranty_price else 900000000
            else:
                min_price = 0
                max_price = 900000000

            params = {
                "cortarNo": r_no,
                "order": "rank",
                "realEstateType": realestate_type,
                "tradeType": trade_type,
                "tag": "::::::::",
                "rentPriceMin": min_rent_price if min_rent_price else 0,
                "rentPriceMax": max_rent_price if max_rent_price else 900000000,
                "priceMin": min_price,
                "priceMax": max_price,
                "areaMin": min_area if min_area else 0,
                "areaMax": max_area if max_area else 900000000,
                "oldBuildYears": "",
                "recentlyBuildYears": "",
                "minHouseHoldCount": "",
                "maxHouseHoldCount": "",
                "showArticle": False,
                "sameAddressGroup": False,
                "minMaintenanceCost": "",
                "maxMaintenanceCost": "",
                "priceType": "RETAIL",
                "directions": "",
                "page": 1,
                "articleState": "",
            }

            page = 1
            is_more_data = True
            now = dt.now()

            while is_more_data:
                if self._is_cancelled():
                    break

                params["page"] = page
                # self._log(f"[{region_idx}/{len(region_names)}] {region_name}: articleList 요청 중 (p{page})")
                print(f"[{region_idx}/{len(region_names)}] {region_name}: articleList 요청 중 (p{page})")

                article_list = None
                for _ in range(3):
                    try:
                        time.sleep(random.uniform(1.5, 2.5))
                        res = self.sess.get(url, params=params, impersonate='chrome', timeout=self.timeout_sec)
                        res_json = res.json()
                        is_more_data = res_json.get("isMoreData", False)
                        article_list = res_json.get("articleList", [])
                        break
                    except Exception as e:
                        self._log(f"articleList 요청 실패 ({region_name}, p{page}): {e}")
                        print(f"[{region_idx}/{len(region_names)}] {region_name}: articleList 요청 실패 (p{page}): {e}")
                        continue
                    
                if not article_list:
                    break

                self._log(f"[{region_idx}/{len(region_names)}] {region_name}: {page}페이지, {len(article_list)}건")
                print(f"[{region_idx}/{len(region_names)}] {region_name}: {page}페이지, {len(article_list)}건")

                for article in article_list:
                    if self._is_cancelled():
                        break

                    article_no = str(article.get("articleNo", ""))
                    if not article_no or article_no in seen_atcl:
                        continue
                    seen_atcl.add(article_no)

                    # 날짜 필터
                    article_confirm_date = article.get("articleConfirmYmd", "")
                    if article_confirm_date and min_date:
                        try:
                            article_confirm_dt = dt.strptime(article_confirm_date, "%Y%m%d")
                            if article_confirm_dt < min_date:
                                continue
                        except ValueError:
                            pass

                    try:
                        detail = self.extract_detail_v2(article_no, is_hosu_needed=is_hosu_needed)
                        if detail:
                            total_yielded += 1
                            self._on_progress(region_idx, len(region_names), f"누적 {total_yielded}건")
                            yield detail
                    except Exception as e:
                        self._log(f"상세 추출 실패 (atcl={article_no}): {e}")
                        print(f"[{region_idx}/{len(region_names)}] {region_name}: 상세 추출 실패 (atcl={article_no}): {e}")

                if max_pages and page >= max_pages:
                    self._log(f"[{region_idx}/{len(region_names)}] {region_name}: 최대 {max_pages}페이지까지만 수집합니다.")
                    print(f"[{region_idx}/{len(region_names)}] {region_name}: 최대 {max_pages}페이지 도달, 다음 지역으로 넘어갑니다.")
                    break

                page += 1

        self._log(f"완료: 총 {total_yielded}건")
        print(f"완료: 총 {total_yielded}건")

    def search_articles_v1(
        self,
        realestate_type: str,
        trade_type: str,
        region_names: List[str],
        min_date: Optional[dt] = None,
        min_deal_price: Optional[int] = None,
        max_deal_price: Optional[int] = None,
        min_warranty_price: Optional[int] = None,
        max_warranty_price: Optional[int] = None,
        min_rent_price: Optional[int] = None,
        max_rent_price: Optional[int] = None,
        min_area: Optional[int] = None,
        max_area: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """new.land.naver.com/api/articles 기반으로 목록만 조회하여 검색 결과를 반환한다."""
        url = "https://new.land.naver.com/api/articles"
        seen_atcl: set[str] = set()
        results: List[Dict[str, Any]] = []

        for region_idx, region_name in enumerate(region_names, 1):
            if self._is_cancelled():
                self._log(f"중단 요청됨 (목록 검색 {region_idx}/{len(region_names)})")
                break

            resolved = self._resolve_rls_keys(region_name)
            if not resolved:
                self._log(f"지역 매핑 실패 (건너뜀): {region_name}")
                continue

            si, gu, dong = resolved
            r = self.get_r(si, gu, dong)
            r_no = r[3]

            if trade_type and "A1" in trade_type and ("B1" in trade_type or "B2" in trade_type):
                min_price = min(min_deal_price if min_deal_price else 0, min_warranty_price if min_warranty_price else 0)
                max_price = max(max_deal_price if max_deal_price else 900000000, max_warranty_price if max_warranty_price else 900000000)
            elif trade_type and "A1" in trade_type:
                min_price = min_deal_price if min_deal_price else 0
                max_price = max_deal_price if max_deal_price else 900000000
            elif trade_type and ("B1" in trade_type or "B2" in trade_type):
                min_price = min_warranty_price if min_warranty_price else 0
                max_price = max_warranty_price if max_warranty_price else 900000000
            else:
                min_price = 0
                max_price = 900000000

            params = {
                "cortarNo": r_no,
                "order": "rank",
                "realEstateType": realestate_type,
                "tradeType": trade_type,
                "tag": "::::::::",
                "rentPriceMin": min_rent_price if min_rent_price else 0,
                "rentPriceMax": max_rent_price if max_rent_price else 900000000,
                "priceMin": min_price,
                "priceMax": max_price,
                "areaMin": min_area if min_area else 0,
                "areaMax": max_area if max_area else 900000000,
                "oldBuildYears": "",
                "recentlyBuildYears": "",
                "minHouseHoldCount": "",
                "maxHouseHoldCount": "",
                "showArticle": False,
                "sameAddressGroup": False,
                "minMaintenanceCost": "",
                "maxMaintenanceCost": "",
                "priceType": "RETAIL",
                "directions": "",
                "page": 1,
                "articleState": "",
            }

            page = 1
            is_more_data = True

            while is_more_data:
                if self._is_cancelled():
                    break

                params["page"] = page
                print(f"[{region_idx}/{len(region_names)}] {region_name}: 검색결과 조회 중 (p{page})")
                article_list = None
                for _ in range(3):
                    try:
                        time.sleep(random.uniform(1.0, 1.8))
                        res = self.sess.get(url, params=params, impersonate='chrome', timeout=self.timeout_sec)
                        res_json = res.json()
                        is_more_data = res_json.get("isMoreData", False)
                        article_list = res_json.get("articleList", [])
                        break
                    except Exception as e:
                        self._log(f"검색결과 조회 실패 ({region_name}, p{page}): {e}")
                        print(f"[{region_idx}/{len(region_names)}] {region_name}: 검색결과 조회 실패 (p{page}): {e}")
                        continue

                if not article_list:
                    break

                self._log(f"[{region_idx}/{len(region_names)}] {region_name}: 검색 {page}페이지, {len(article_list)}건")
                for article in article_list:

                    if self._is_cancelled():
                        break

                    article_no = str(article.get("articleNo", "")).strip()
                    if not article_no or article_no in seen_atcl:
                        continue
                    seen_atcl.add(article_no)

                    article_confirm_date = str(article.get("articleConfirmYmd", "") or "")
                    if article_confirm_date and min_date:
                        try:
                            article_confirm_dt = dt.strptime(article_confirm_date, "%Y%m%d")
                            if article_confirm_dt < min_date:
                                continue
                        except ValueError:
                            pass
                        
                    article_name = str(article.get("articleName", "") or "").strip()
                    building_name = str(article.get("buildingName", "") or "").strip()
                    floor_info = str(article.get("floorInfo", "") or "").strip()
                    area_name = str(article.get("areaName", "") or "").strip()
                    feature_desc = str(
                        article.get("articleFeatureDesc", "")
                        or article.get("articleFeatureDescription", "")
                        or ""
                    ).strip()
                    realestate_type_name = str(article.get("realEstateTypeName", "") or "").strip()
                    trade_type_name = str(article.get("tradeTypeName", "") or "").strip()
                    represent_price = str(article.get("dealOrWarrantPrc", "") or article.get("price", "") or "").strip()
                    rent_price = str(article.get("rentPrc", "") or "").strip()
                    price_text = represent_price
                    if rent_price:
                        price_text = f"{represent_price}/{rent_price}" if represent_price else rent_price
                    full_parts = [p for p in (building_name, area_name, floor_info, feature_desc) if p]
                    article_full_name = article_name
                    if full_parts:
                        article_full_name = f"{article_name} | {' / '.join(full_parts)}" if article_name else " / ".join(full_parts)
                    if building_name.endswith("동"):
                        article_name = f"{article_name} {building_name}"

                    results.append(
                        {
                            "article_no": article_no,
                            "region_name": region_name,
                            "article_name": article_name,
                            "article_full_name": article_full_name,
                            "realestate_type_name": realestate_type_name,
                            "trade_type_name": trade_type_name,
                            "price_text": price_text,
                            "confirm_date": article_confirm_date,
                        }
                    )

                self._on_progress(region_idx, len(region_names), f"검색결과 누적 {len(results)}건")
                page += 1

        self._log(f"검색 완료: 총 {len(results)}건")
        return results

    def search_complexes(
        self,
        si: str, gu: str, dong: str,
        realestate_type: str = "APT:ABYG:JGC:PRE",
        tag: str = "::::::::",
        trade_type: Optional[str] = None,
        min_deal_price: Optional[int] = None, max_deal_price: Optional[int] = None,
        min_warranty_price: Optional[int] = None, max_warranty_price: Optional[int] = None,
        min_rent_price: Optional[int] = None, max_rent_price: Optional[int] = None,
        min_area: Optional[int] = None, max_area: Optional[int] = None,
        max_days_from_now: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """지역·필터 조건으로 단지 목록 검색. GUI에서 호출."""
        r = self.get_r(si, gu, dong)
        return self.get_cls(
            *r, realestate_type=realestate_type, tag=tag, trade_type=trade_type,
            min_deal_price=min_deal_price, max_deal_price=max_deal_price,
            min_warranty_price=min_warranty_price, max_warranty_price=max_warranty_price,
            min_rent_price=min_rent_price, max_rent_price=max_rent_price,
            min_area=min_area, max_area=max_area, max_days_from_now=max_days_from_now,
        )

    def extract_details(
        self,
        complexes: List[Dict],
        realestate_type: str = "APT:ABYG:JGC:PRE",
        tag: str = "::::::::",
        trade_type: Optional[str] = None,
        min_deal_price: Optional[int] = None, max_deal_price: Optional[int] = None,
        min_warranty_price: Optional[int] = None, max_warranty_price: Optional[int] = None,
        min_rent_price: Optional[int] = None, max_rent_price: Optional[int] = None,
        min_area: Optional[int] = None, max_area: Optional[int] = None,
        on_item: Optional[Callable[[List[Any]], None]] = None,
    ) -> List[List]:
        """선택된 단지들의 상세 정보 추출. GUI에서 호출."""
        data = []
        total = len(complexes)
        for i, c in enumerate(complexes, 1):
            if self._is_cancelled():
                self._log("[중단됨]")
                break
            self._on_progress(i, total, c.get("complex_name", ""))
            rows = self.get_complex_info(
                c, realestate_type=realestate_type, tag=tag, trade_type=trade_type,
                min_deal_price=min_deal_price, max_deal_price=max_deal_price,
                min_warranty_price=min_warranty_price, max_warranty_price=max_warranty_price,
                min_rent_price=min_rent_price, max_rent_price=max_rent_price,
                min_area=min_area, max_area=max_area,
            )
            for row in rows:
                data.append(row)
                if on_item:
                    on_item(row)
        return data

    def get_cls(self, *r, realestate_type="APT:ABYG:JGC:PRE", tag="::::::::", trade_type=None, min_deal_price=None, max_deal_price=None,
            min_warranty_price=None, max_warranty_price=None, min_rent_price=None, max_rent_price=None,
            min_area=None, max_area=None, max_days_from_now=None):
        si, gu, dong, r_no = r
        cls = []
        if "IA01:IA02:IC01:IC02:IA04:IC03" != realestate_type:
            cls_url = "https://new.land.naver.com/api/articles"

            if "A1" in trade_type and ("B1" in trade_type or "B2" in trade_type):
                min_price = min(min_deal_price if min_deal_price else 0, min_warranty_price if min_warranty_price else 0)
                max_price = max(max_deal_price if max_deal_price else 900000000, max_warranty_price if max_warranty_price else 900000000)
            elif "A1" in trade_type:
                min_price = min_deal_price if min_deal_price else 0
                max_price = max_deal_price if max_deal_price else 900000000
            elif "B1" in trade_type or "B2" in trade_type:
                min_price = min_warranty_price if min_warranty_price else 0
                max_price = max_warranty_price if max_warranty_price else 900000000
            else:
                min_price = 0
                max_price = 900000000

            cls_params = {
                "cortarNo": r_no,
                "order": "rank",
                "realEstateType": realestate_type,
                "tradeType": trade_type,
                "tag": tag,
                "rentPriceMin": min_rent_price if min_rent_price else 0,
                "rentPriceMax": max_rent_price if max_rent_price else 900000000,
                "priceMin": min_price,
                "priceMax": max_price,
                "areaMin": min_area if min_area else 0,
                "areaMax": max_area if max_area else 900000000,
                "oldBuildYears": "",
                "recentlyBuildYears": "",
                "minHouseHoldCount": "",
                "maxHouseHoldCount": "",
                "showArticle": False,
                "sameAddressGroup": False,
                "minMaintenanceCost": "",
                "maxMaintenanceCost": "",
                "priceType": "RETAIL",
                "directions": "",
                "page": 1,
                "articleState": ""
            }

            is_more_data = True 
            page = 1
            article_no_list = []
            
            now = dt.now()

            while is_more_data:
                if self._is_cancelled():
                    self._log(f"네이버: 단지 검색 중단 요청됨 ({page}페이지 진입 전, 누적 {len(cls)}개)")
                    break
                self._log(f"네이버: 단지 검색중... ({page}페이지, 누적 {len(cls)}개)")

                cls_params["page"] = page
                # print(cls_params)
                cls_res = self.sess.get(cls_url, params=cls_params, impersonate='chrome', timeout=self.timeout_sec)
                is_more_data = cls_res.json().get("isMoreData")

                article_list = cls_res.json().get("articleList")

                for article in article_list:
    
                    article_no = article.get("articleNo")

                    article_confirm_date = article.get("articleConfirmYmd", "")
                    if max_days_from_now and article_confirm_date:
                        article_confirm_dt = dt.strptime(article_confirm_date, "%Y%m%d")
                        if article_confirm_dt < now - td(days=max_days_from_now):
                            print((now - td(days=max_days_from_now)).strftime("%Y%m%d"), article_confirm_date)
                            continue 

                    if article_no and article_no not in article_no_list:
                        cls.append({
                            "si" : si, 
                            "gu" : gu, 
                            "dong" : dong, 
                            "complex_name" : article.get("articleName"),
                            "complex_no" : article_no,
                            "realestate_type_name" : article.get("realEstateTypeName"),
                            "realestate_type" : article.get("realEstateTypeCode", "")  
                        })

                    article_no_list.append(article_no)

                page += 1

        if "IA01:IA02:IC01:IC02:IA04:IC03" in realestate_type:

            pre_url = "https://isale.land.naver.com/iSale/AjaxContent/"
            pre_data = {
                "sy_ajax_content": "SYAreaComplexList",
                "sy_sido": si,
                "sy_gugun": gu, 
                "sy_dong": dong,
                "bclass": "IA01:IA02:IC01:IC02:IA04:IC03",
                "sy_sort": 0
            }
            pre_res = self.sess.post(pre_url, data=pre_data, impersonate='chrome', timeout=self.timeout_sec)
            soup = bs(pre_res.text, "lxml-xml")
            try:
                complex_data = soup.select_one("sycomplexdata")
                if complex_data:
                    ext_data = complex_data.text.split("CDATA[", 1)[1].split("]]>", 1)[0]
                    ext_data = json.loads(ext_data)
                    ext_data = ext_data.get("Data")
                else:
                    complex_data = soup.select_one("SYComplexData")
                    ext_data = json.loads(complex_data.text).get("Data")
                
                build_dtl_cd_list = [[e.get("build_dtl_cd"), e.get("supp_cd")] for e in ext_data]

                import xmltodict 

                for build_dtl_cd in build_dtl_cd_list:

                    det_data = {
                        "sy_ajax_content": "SYComplexInfo",
                        "build_dtl_cd": build_dtl_cd[0],
                        "supp_cd": build_dtl_cd[1],
                        "SYMap": None,
                        "a": "IA01:IA02:IC01:IC02:IA04:IC03"
                    }

                    try:
                        det_res = self.sess.post(pre_url, data=det_data, impersonate='chrome', timeout=self.timeout_sec)
                        xml_dict = xmltodict.parse(det_res.text)
                        # print(xml_dict)
                        view_content = xml_dict["channel"]["SYViewContent"]
                        view_content_soup = bs(view_content, "html.parser")

                        complex_content = xml_dict["channel"]["SYComplexContent"]
                        complex_content_soup = bs(complex_content, "html.parser")
                        info_table = complex_content_soup.select_one("table.InfoTableWrap tbody")

                        try:
                            name = view_content_soup.select_one("h3.Title").text
                        except: name = None  

                        try: 
                            total_floor = view_content_soup.find(string=lambda text: "층" in text).text.replace("층","")
                        except: total_floor = None  

                        try:
                            deal_price = ((convert_price(view_content_soup.select_one("dd.Data").text.split("~")[0].strip())) + " ~ " + 
                                            (convert_price(view_content_soup.select_one("dd.Data").text.split("~")[1].strip())))
                        except: deal_price = None  

                        try:
                            nanbang = complex_content_soup.find("th", string="난방방식").find_parent().select_one("td").text
                        except: nanbang = None 

                        try: 
                            movein_possible_ymd = convert_date(view_content_soup.select_one("dd.Date").text.split("입주")[1].replace(".","").strip())
                        except: movein_possible_ymd = None

                        try: 
                            detail_addr = " ".join(complex_content_soup.find("th", string="분양주소").find_parent().select_one("td").text.split(" ")[2:])
                        except: detail_addr = None 

                        try:
                            construction_company_name = complex_content_soup.find("th", string="건설사").find_parent().select_one("td").text
                        except : construction_company_name = None 

                        try:
                            saede_num = complex_content_soup.find("th", string="단지규모").find_parent().select_one("td").text.split("세대", 1)[0].split(" ")[-1]
                        except: saede_num = None 

                        try: 
                            dong_num = complex_content_soup.find("th", string="단지규모").find_parent().select_one("td").text.split("개동", 1)[0].split(" ", -1)[1]
                        except: dong_num = None 

                        try:
                            park_count = complex_content_soup.find("th", string="주차대수").find_parent().select_one("td").text.split("대", 1)[0]
                        except: park_count = None 

                        # print(json.dumps(xml_dict, indent=4))
                        try:
                            sy_json = json.loads(xml_dict["channel"]["SYJson"])
                        except: pass 

                        try:
                            if not deal_price:
                                deal_price = sy_json.get("price")
                                if deal_price:
                                    deal_price = ((convert_price(deal_price.replace(",","").split("~")[0].strip())) + " ~ " + 
                                                (convert_price(deal_price.replace(",","").split("~")[1].strip())))
                        except: pass 
                        try:
                            if not saede_num:
                                saede_num = sy_json.get("total_house_cnt")
                                if saede_num:
                                    saede_num = saede_num.split("총")[1].split("세대")[0].strip()
                        except: pass 
                        try: 
                            if not movein_possible_ymd:
                                movein_possible_ymd = sy_json.get("move_in_date")
                                if movein_possible_ymd:
                                    movein_possible_ymd = convert_date(movein_possible_ymd)
                        except: pass 

                        in_data = {
                                "addr_si" : si, 
                                "addr_gu" : gu,
                                "addr_dong" : dong,
                                "url_with_no" : f"https://isale.land.naver.com/iSale/Map/#SYDetail?build_dtl_cd={build_dtl_cd[0]}&supp_cd={build_dtl_cd[1]}&a=IA01:IA02:IC01:IC02:IA04:IC03",
                                "expose_start_ymd": None,
                                "verification_type_name": None,
                                "realestate_type": "분양중/예정",
                                "trade_type": None,
                                "name": name, 
                                "dong": None,
                                "hosu": None,
                                "area1": None,
                                "area2": None,
                                "arch_area": None,
                                "exclusive_rate": None,
                                "yj_rate": None,
                                "gp_rate": None,
                                "floor": None,
                                "total_floor": total_floor,
                                "direction": None,
                                "deal_price": deal_price,
                                "rent_price": None,
                                "price_by_space": None,
                                "gongsi_std_ymd": None,
                                "gongsi_min_price": None,
                                "gongsi_max_price": None,
                                "right_price": None,
                                "finance_price": None,
                                "all_warrant_price": None,
                                "all_rent_price": None,
                                "premium_price": None,
                                "biz_step": None,
                                "usage_district": None,
                                "management_cost": None,
                                "room_count": None,
                                "bathroom_count": None,
                                "nanbang": nanbang if nanbang != "-" else nanbang,
                                "current_usage": None,
                                "recommend_usage": None,
                                "building_usage": None,
                                "jisang_jiha_floor": None,
                                "movein_possible_ymd": movein_possible_ymd,
                                "simple_description": None,
                                "detail_description": None,
                                "sojaeji": f"{si} {gu}",
                                "addr": None,
                                "detail_addr": detail_addr,
                                "lat_long": None,
                                "construction_company_name": construction_company_name,
                                "apt_use_approve_ymd" : None,
                                "saede_num": saede_num,
                                "dong_num": dong_num,
                                "park_count": park_count,
                                "agent_num": None,
                                "agent_name": None,
                                "agent_man_name": None,
                                "agent_addr": None,
                                "agent_no": None,
                                "agent_tel": None,
                                "agent_phone": None
                            }
                    
                        cls.append({
                            "si" : si, 
                            "gu" : gu, 
                            "dong" : dong, 
                            "complex_name" : name,
                            "complex_no" : None,
                            "realestate_type_name" : "분양중/예정",
                            "realestate_type" : "IA01:IA02:IC01:IC02:IA04:IC03",
                            "in_data" : in_data 
                        })
                    except Exception as e:
                        print(f"520: Error: {e}") 
                        continue 
            except Exception as e:
                print(f"523: Error: {e}") 
                pass 

        return cls

    def get_complex_info(self, c, realestate_type="APT:ABYG:JGC:PRE", tag="::::::::", trade_type=None, min_deal_price=None, max_deal_price=None,
                min_warranty_price=None, max_warranty_price=None, min_rent_price=None, max_rent_price=None,
                min_area=None, max_area=None):
        c_no = c["complex_no"]
        realestate_type = c["realestate_type"]


        c_list_url = f"https://new.land.naver.com/api/articles/complex/{c_no}"
    
        page = 1
    
        c_list_params = {
            "realEstateType": realestate_type,
            "tradeType": trade_type,
            "tag": tag,
            "rentPriceMin": min_rent_price if min_rent_price else 0,
            "rentPriceMax": max_rent_price if max_rent_price else 900000000,
            "priceMin": min_deal_price if min_deal_price else 0,
            "priceMax": max_deal_price if max_deal_price else 900000000,
            "areaMin": min_area if min_area else 0,
            "areaMax": max_area if max_area else 900000000,
            "oldBuildYears": "",
            "recentlyBuildYears": "",
            "minHouseHoldCount": "",
            "maxHouseHoldCount": "",
            "showArticle": False,
            "sameAddressGroup": False,
            "minMaintenanceCost": "",
            "maxMaintenanceCost": "",
            "priceType": "RETAIL",
            "directions": "",
            # "page": page,
            "complexNo": c_no,
            "buildingNos": "",
            "areaNos": "",
            "type": "list",
            "order": "rank"
        }
    
        is_more_data = True 
    
        data = []
    
        if c_no:
    
            new_c_no_list = [c_no]
    
            try:
                while is_more_data:
                    c_list_params["page"] = page
                    c_list_res = self.sess.get(c_list_url, params=c_list_params, impersonate='chrome', timeout=self.timeout_sec)
                    is_more_data = c_list_res.json().get("isMoreData")
                    c_list = c_list_res.json().get("articleList")
                    article_no_list = [c.get("articleNo") for c in c_list if c.get("articleNo")]
                    new_c_no_list.extend(article_no_list)
                    page += 1
            except:
                pass 
    
            for new_c_no in new_c_no_list:
    
                c_info_url = f"https://new.land.naver.com/api/articles/{new_c_no}?complexNo="
                
                try:
                    c_info_res = self.sess.get(c_info_url, impersonate='chrome', timeout=self.timeout_sec)
                    c_info = c_info_res.json()
    
                    # article_no = None 
                    addr_si = None 
                    addr_gu = None
                    addr_dong = None
                    expose_start_ymd = None 
                    verification_type_name = None 
                    realestate_type = None 
                    trade_type = None 
                    name = c["complex_name"] 
                    dong = None 
                    area1 = None 
                    area2 = None 
                    arch_area = None 
                    exclusive_rate = None 
                    yj_rate = None 
                    gp_rate = None 
                    direction = None 
                    floor = None 
                    total_floor = None 
                    hosu = None
                    deal_price = None 
                    rent_price = None 
                    price_by_space = None 
                    gongsi_std_ymd = None  #
                    gongsi_min_price = None # 
                    gongsi_max_price = None #
                    right_price = None 
                    finance_price = None 
                    all_warrant_price = None 
                    all_rent_price = None 
                    premium_price = None 
                    biz_step = None 
                    usage_district = None # 용도지역 
                    management_cost = None 
                    room_count = None 
                    bathroom_count = None 
                    nanbang = None
                    current_usage = None
                    recommend_usage = None
                    building_usage = None # 건축물용도 
                    jisang_jiha_floor = None 
                    movein_possible_ymd = None
                    simple_description = None 
                    detail_description = None
                    sojaeji = None 
                    addr = None 
                    detail_addr = None 
                    lat_long = None 
                    construction_company_name = None
                    saede_num = None
                    dong_num = None
                    park_count = None
                    agent_num = None  # 중개사수
                    agent_name = None 
                    agent_man_name = None 
                    agent_addr = None 
                    agent_no = None 
                    agent_tel = None # 중개사 전화 
                    agent_phone = None # 중개사 휴대폰
    
                    article_detail = c_info.get("articleDetail")
                    # article_no = article_detail.get("articleNo", "") # 
    
                    if not article_detail: 
                        print("article_detail is None")
                        continue 
    
                    hscp_no = article_detail.get("hscpNo", "")
                    dong_no = article_detail.get("buildNo", "")
    
                    detail_addr_url = f"https://new.land.naver.com/api/complexes/{hscp_no}?sameAddressGroup=false"
                    try:
                        detail_addr_res = self.sess.get(detail_addr_url, impersonate='chrome', timeout=self.timeout_sec)
                        if detail_addr_res.status_code != 200:
                            raise Exception
                        c_detail = detail_addr_res.json().get("complexDetail", "")
                        if c_detail:
                            detail_addr = f'{c_detail.get("address").split(" ")[-1]} {c_detail.get("detailAddress")}'
                            yj_rate = c_detail.get("batlRatio", "")
                            gp_rate = c_detail.get("btlRatio", "")
                    except: pass 
    
                    landprice_url = f"https://new.land.naver.com/api/complexes/{hscp_no}/buildings/landprice"
                    landprice_params = {
                        "dongNo" : dong_no, 
                        "complexNo" : hscp_no 
                    }
                    try:
                        landprice_res = self.sess.get(landprice_url, params=landprice_params, impersonate='chrome', timeout=self.timeout_sec)
                        if landprice_res.status_code != 200:
                            print("landprice_res is not 200")
                            raise Exception
                        gongsi_std_ymd = get_gongsi(landprice_res)
                        landprice_color_summary = landprice_res.json().get("landPriceColorSummary", "")
                        if landprice_color_summary:
                            gongsi_min_price = landprice_color_summary.get("minLandPrice", "")
                            gongsi_min_price = "{:,}".format(gongsi_min_price)
                            gongsi_max_price = landprice_color_summary.get("maxLandPrice", "")
                            gongsi_max_price = "{:,}".format(gongsi_max_price)
                    except: 
                        pass 
    
                    addr_si = article_detail.get("cityName", "")
                    addr_gu = article_detail.get("divisionName", "")
                    addr_dong = article_detail.get("sectionName", "")
                    sojaeji = article_detail.get("exposureAddress", "")
                    if not sojaeji:
                        sojaeji = f"{addr_si} {addr_gu}".strip()
                    expose_start_ymd = article_detail.get("exposeStartYMD", "")
                    expose_start_ymd = convert_date(expose_start_ymd)
    
                    verification_type_name = article_detail.get("verificationTypeName", "")
                    realestate_type = article_detail.get("realestateTypeName", "")
                    realestate_type_code = article_detail.get("realestateTypeCode", "")
                    # building_type = building_types[building_type_code]
                    trade_type_code = article_detail.get("tradeTypeCode", "")
                    if trade_type and trade_type_code and trade_type_code not in trade_type:
                        print("trade_type and trade_type_code and trade_type_code not in trade_type")
                        continue 
                    trade_type = article_detail.get("tradeTypeName", "")
                    # name = article_detail.get("aptName", "")
                    dong = article_detail.get("buildingName", "")
                    article_addition = c_info.get("articleAddition")
                    area1 = article_addition.get("area1", "") # 공급,계약,대지 
                    area2 = article_addition.get("area2", "") # 전용,연
                    if area1 and (min_area and area1 < min_area) or (max_area and area1 > max_area):
                        print("area1 and (min_area and area1 < min_area) or (max_area and area1 > max_area)")
                        continue 
                    article_space = c_info.get("articleSpace", "")
                    arch_area = article_space.get("buildingSpace", "") if article_space else None 
                    arch_area = int(float(arch_area)) if arch_area else arch_area # 건면적 
                    exclusive_rate = article_space.get("exclusiveRate", "") if article_space else None # 전용률
                    # if area1 and area2:
                    #     yj_rate = int(area2 / area1) # 용적률
                    article_redevelop = c_info.get("articleRedevelop", "")
                    if not yj_rate:
                        yj_rate = find_key_in_nested_dict(c_info, "floorAreaRatio")
                    if not yj_rate or yj_rate == "-" or realestate_type == "전원주택":
                        yj_rate = find_key_in_nested_dict(c_info, "vlRat")
                    if not gp_rate: 
                        gp_rate = find_key_in_nested_dict(c_info, "buildingCoverageRatio")
                    if not gp_rate or gp_rate == "-" or realestate_type == "전원주택":
                        gp_rate = find_key_in_nested_dict(c_info, "bcRat")
                    # yj_rate = article_redevelop.get("floorAreaRatio", "") if article_redevelop else None # 용적률
                    # gp_rate = article_redevelop.get("buildingCoverageRatio", "") if article_redevelop else None # 건폐율 
    
                    direction = article_addition.get("direction", "")
                    floor_info = article_addition.get("floorInfo", "")
                    if floor_info:
                        floor = floor_info.split("/")[0].strip()
                        total_floor = floor_info.split("/")[1].strip()
    
                    article_price = c_info.get("articlePrice")
                    if trade_type_code == "A1":
                        deal_price = article_price.get('dealPrice', "")
                        if (deal_price and (min_deal_price and deal_price < min_deal_price)
                        or (max_deal_price and deal_price > max_deal_price)):
                            print("deal_price and (min_deal_price and deal_price < min_deal_price) or (max_deal_price and deal_price > max_deal_price)")
                            continue 
    
                    elif trade_type_code == "B1" or trade_type_code == "B2" or trade_type_code == "B3":
                        deal_price = article_price.get("warrantPrice", "")
                        if (deal_price and (min_warranty_price and deal_price < min_warranty_price)
                        or (max_warranty_price and deal_price > max_warranty_price)):
                            print("deal_price and (min_warranty_price and deal_price < min_warranty_price) or (max_warranty_price and deal_price > max_warranty_price)")
                            continue 
                    deal_price = convert_price(deal_price)
                    price_by_space = c_info.get("priceBySpace", "")
                    price_by_space = convert_price(price_by_space)
    
                    rent_price = article_price.get("rentPrice", "")
                    if (rent_price and (min_rent_price and rent_price < min_rent_price)
                            or (max_rent_price and rent_price > max_rent_price)):
                        print("rent_price and (min_rent_price and rent_price < min_rent_price) or (max_rent_price and rent_price > max_rent_price)")
                        continue 
                    rent_price = convert_price(rent_price)
                    right_price = article_price.get("rightPrice") # 권리금 
                    right_price = convert_price(right_price)
                    finance_price = article_price.get("financePrice", "") # 융자금
                    finance_price = convert_price(finance_price)
                    # all_warrant_price = article_price.get("allWarrantPrice", "") # 기보증금 
                    # if (all_warrant_price and (min_warranty_price and all_warrant_price < min_warranty_price)
                    #         or (max_warranty_price and all_warrant_price > max_warranty_price)):
                    #     continue 
                    # all_warrant_price = convert_price(all_warrant_price)
                    # all_rent_price = article_price.get("allRentPrice", "") # 기월세 
                    # all_rent_price = convert_price(all_rent_price)
                    premium_price = article_price.get("premiumPrice", "") 
                    premium_price = convert_price(premium_price)
                    biz_step = find_key_in_nested_dict(c_info, "bizStepDescription") # 사업시행단계
    
                    article_facility = c_info.get("articleFacility", "")
    
                    management_cost = article_detail.get("monthlyManagementCost", "") # 관리비 
    
                    admin_cost_info = c_info.get("administrationCostInfo", "")
                    if not management_cost and admin_cost_info:
                        etc_fee_details = admin_cost_info.get("etcFeeDetails", "")
                        if etc_fee_details:
                            management_cost = etc_fee_details.get("etcFeeAmount", "") if admin_cost_info else None 
                    if not management_cost and admin_cost_info:
                        fixed_fee_details = admin_cost_info.get("fixedFeeDetails", "")
                        if fixed_fee_details:
                            management_cost = sum([f.get("amount") for f in fixed_fee_details if f.get("amount")])
    
                    if management_cost:
                        management_cost = "{:,}".format(management_cost)
    
                    room_count = article_detail.get("roomCount", "") 
                    bathroom_count = article_detail.get("bathroomCount", "")
                    nanbang = (f'{article_facility.get("heatMethodTypeName", "")}/{article_facility.get("heatFuelTypeName", "")}'
                            if article_facility and article_facility.get("heatMethodTypeName", "") else None)
                    if nanbang is None:
                        nanbang = (f'{article_detail.get("aptHeatMethodTypeName", "")}/{article_detail.get("aptHeatFuelTypeName", "")}'
                            if article_detail and article_detail.get("aptHeatMethodTypeName", "") else None)
                    current_usage = article_detail.get("currentUsage", "") # 현재업종 
                    recommend_usage = article_detail.get("recommendUsage", "") # 추천업종 
    
                    article_br = c_info.get("articleBuildingRegister", "")
    
                    article_floor = c_info.get("articleFloor", "")
                    jisang_floor = article_floor.get("uppergroundFloorCount", "") if article_floor else None 
                    jiha_floor = article_floor.get("undergroundFloorCount", "") if article_floor else None 
                    if jisang_floor and jiha_floor and not (jisang_floor == "-" and jiha_floor == "-") :
                        jisang_jiha_floor = f"{jisang_floor}/{jiha_floor}"
    
                    movein_possible_ymd = article_detail.get("moveInPossibleYmd", "") # 입주가능일
                    if not movein_possible_ymd:
                        movein_possible_ymd = find_key_in_nested_dict(c_info, "moveInTypeName")
                    try:
                        movein_possible_ymd = convert_date(movein_possible_ymd)
                    except: pass 
                    simple_description = article_detail.get("articleFeatureDescription", "") # 간략설명
                    detail_description = article_detail.get("detailDescription", "") # 설명 
                    # sojaeji = f"{article_detail.get("cityName", "")} {article_detail.get("divisionName", "")}".strip() # 소재지
                    # sojaeji = f"{c["si"]} {c["gu"]}"
                    lat_long = f'{article_detail.get("latitude", "")},{article_detail.get("longitude", "")}'
                    construction_company_name = find_key_in_nested_dict(c_info, "aptConstructionCompanyName")
                    if not construction_company_name:
                        construction_company_name = find_key_in_nested_dict(c_info, "constructorName")
                    apt_use_approve_ymd = article_detail.get("aptUseApproveYmd", "") # 사용승인일
                    if not apt_use_approve_ymd:
                        apt_use_approve_ymd = article_facility.get("buildingUseAprvYmd", "") if article_facility else None 
                    apt_use_approve_ymd = convert_date(apt_use_approve_ymd)
                    saede_num = article_detail.get("aptHouseholdCount", "")
                    if not saede_num:
                        saede_num = find_key_in_nested_dict(c_info, "householdCount")
                    if not saede_num:
                        saede_num = find_key_in_nested_dict(c_info, "allHoCnt")
                    dong_num = article_detail.get("totalDongCount", "")
                    # is_parking_possible = find_key_in_nested_dict("parkingPossibleYN", "")
                    park_count = article_br.get("totalParkingCnt", "") if article_br else article_detail.get("aptParkingCount", "")
    
                    pbs_url = f"https://fin.land.naver.com/articles/{new_c_no}"
                    try:
                        pbs_res = self.sess.get(pbs_url, impersonate='chrome', timeout=self.timeout_sec)
                        if pbs_res.status_code != 200:
                            raise Exception
    
                        pbs_soup = bs(pbs_res.text, "html.parser")
    
                        if not price_by_space:
                            try:
                                price_by_space = pbs_soup.select_one("span.ArticleSummary_info-size___Ut9Q")
                                if price_by_space:
                                    price_by_space = price_by_space.text.split("만원")[0].replace("억 ", "")
                            except: 
                                pass 
    
                        try:
                            scripts = pbs_soup.select("script")
                            target_script = None 
                            for script in scripts:
                                if script.get("id") == "__NEXT_DATA__":
                                    target_script = script
                                    break 
    
                            info_json = json.loads(target_script.string)
    
                            if not yj_rate or yj_rate == "-" or realestate_type == "재개발":
                                try:
                                    yj_rate = find_key_in_nested_dict(info_json, "floorAreaRatio")
                                    if "재개발" == realestate_type or not yj_rate:
                                        building_ratio_info = find_key_in_nested_dict(info_json, "buildingRatioInfo")
                                        if building_ratio_info:
                                            yj_rate = building_ratio_info.get("floorAreaRatio", "")
                                    if yj_rate: yj_rate = int(yj_rate)
                                except: pass 
                            if not gp_rate or gp_rate == "-" or realestate_type == "재개발":
                                try:
                                    gp_rate = find_key_in_nested_dict(info_json, "buildingCoverageRatio")
                                    if "재개발" == realestate_type or not gp_rate:
                                        building_ratio_info = find_key_in_nested_dict(info_json, "buildingRatioInfo")
                                        if building_ratio_info:
                                            gp_rate = building_ratio_info.get("buildingCoverageRatio", "")
                                    if gp_rate: gp_rate = int(gp_rate)
                                except: pass 
                            if not rent_price:
                                try:
                                    rent_price = find_key_in_nested_dict(info_json, "rentAmount")
                                    if rent_price: rent_price = "{:,}".format(rent_price)
                                except: pass 
                            if not deal_price and trade_type_code == "B1":
                                try:
                                    deal_price = find_key_in_nested_dict(info_json, "warrantyAmount")
                                    if deal_price: deal_price = "{:,}".format(deal_price)
                                except: pass 
                            if not all_warrant_price:
                                try:
                                    all_warrant_price = find_key_in_nested_dict(info_json, "previousDeposit")
                                    if all_warrant_price: all_warrant_price = "{:,}".format(all_warrant_price)
                                except: pass 
                            if not all_rent_price:
                                try:
                                    all_rent_price = find_key_in_nested_dict(info_json, "previousMonthlyRent")
                                    if all_rent_price: all_rent_price = "{:,}".format(all_rent_price)
                                except: pass 
                            if not direction:
                                try:
                                    direction = find_key_in_nested_dict(info_json, "direction")
                                    if direction: direction = DIRECTION_DICT.get(direction, direction)
                                except: pass 
                            if not building_usage:
                                try:
                                    building_usage = find_key_in_nested_dict(info_json, "buildingUse")
                                    if not building_usage:
                                        building_usage = find_key_in_nested_dict(info_json, "buildingPrincipalUse")
                                except: pass 
                            if not usage_district:
                                try:
                                    usage_district = find_key_in_nested_dict(info_json, "areaUsage")
                                except: pass
                            if not usage_district or not saede_num: 
                                if not usage_district:
                                    pnu = find_key_in_nested_dict(info_json, "pnu")
                                    if pnu:
                                        pnu_res = self.sess.get(f"https://fin.land.naver.com/front-api/v1/complex/buildingRegistration?pnu={pnu}", impersonate='chrome', timeout=self.timeout_sec)
                                        if pnu_res.status_code != 200: raise Exception
                                        if not usage_district:
                                            try:
                                                special_purpose_info = find_key_in_nested_dict(pnu_res.json(), "specialPurposeInfo")
                                                if special_purpose_info:
                                                        usage_district = special_purpose_info.get("area").get("purpose")
                                            except: pass 
                                        if not saede_num:
                                            try:
                                                saede_num = find_key_in_nested_dict(pnu_res.json(), "hoNumber")
                                            except: pass 
                                            if not saede_num:
                                                try: 
                                                    saede_num = find_key_in_nested_dict(pnu_res.json(), "familyNumber")
                                                except: pass 
                            if not park_count:
                                try: 
                                    park_count = find_key_in_nested_dict(info_json, "totalParkingCount") 
                                except: pass 
                            if not detail_addr:
                                try: 
                                    dong_eup_myeon_code = find_key_in_nested_dict(info_json, "legalDivisionNumber")
                                    jibun = find_key_in_nested_dict(info_json, "jibun")
                                    dong_eup_myeon = find_keys_with_value(self.rls, dong_eup_myeon_code)
                                    detail_addr = f'{dong_eup_myeon if dong_eup_myeon else ""} {jibun if jibun else ""}'.strip()
                                except: pass 
                        except: pass 
                    except:
                        pass 
    
                    agents_url = f"https://new.land.naver.com/api/articles?representativeArticleNo={new_c_no}"
    
                    try:
                        agents_res = self.sess.get(agents_url, impersonate='chrome', timeout=self.timeout_sec)
                        if agents_res.status_code != 200:
                            raise Exception
                        agent_num = len(agents_res.json()) 
                    except: pass 
    
                    article_realtor = c_info.get("articleRealtor", "")
                    agent_name = article_realtor.get("realtorName", "") if article_realtor else None 
                    agent_man_name = article_realtor.get("representativeName", "") if article_realtor else None 
                    agent_addr = article_realtor.get("address", "") if article_realtor else None 
                    agent_no = article_realtor.get("establishRegistrationNo", "") if article_realtor else None 
                    agent_tel = article_realtor.get("representativeTelNo", "") if article_realtor else None # 중개사 전화 
                    agent_phone = article_realtor.get("cellPhoneNo", "") if article_realtor else None # 중개사 휴대폰
    
                    if not biz_step or not construction_company_name:
                        biz_url = f"https://fin.land.naver.com/front-api/v1/complex/reconstruction?complexNumber={c_no}"
                        try:
                            biz_res = self.sess.get(biz_url, impersonate='chrome', timeout=self.timeout_sec)
                            if biz_res.status_code != 200: raise Exception
                            if not construction_company_name:
                                try:
                                    construction_company_name = biz_res.json().get("result").get('constructionCompany')
                                except: pass 
                            if not biz_step:
                                try: 
                                    biz_step_code = biz_res.json().get("result").get("currentBusinessStep").get("stepType")
                                    if biz_step_code:
                                        biz_step = BIZ_STEP_TYPES.get(biz_step_code, biz_step_code)
                                except: pass 
                        except: pass 
    
                    if all_warrant_price != None and all_warrant_price != "":
                        all_warrant_price = all_warrant_price if int(all_warrant_price.replace(",","") if isinstance(all_warrant_price, str) else all_warrant_price) != 0 else None 
                    if all_rent_price != None and all_rent_price != "":
                        all_rent_price = all_rent_price if int(all_rent_price.replace(",","") if isinstance(all_rent_price, str) else all_rent_price) != 0 else None 
                    if dong_num != None and dong_num != "":
                        dong_num = None if int(dong_num) == 0 else dong_num 
                    if park_count != None and dong_num != "":
                        park_count = None if int(park_count) == 0 else park_count
                    if yj_rate:
                        if yj_rate == "-":
                            yj_rate = None
                        else: 
                            yj_rate = int(float(yj_rate))
                    if gp_rate:
                        if gp_rate == "-":
                            gp_rate = None 
                        else:
                            gp_rate = int(float(gp_rate))
                    if management_cost == 0:
                        management_cost = None 
               
                    hosu = self._infer_hosu(
                        c_info,
                        dong=dong,
                        floor=floor,
                        total_floor=total_floor,
                        article_space=article_space,
                        area2=area2,
                        detail_addr=detail_addr,
                        sojaeji=sojaeji,
                    )

                    temp_data = [
                        addr_si,
                        addr_gu,
                        addr_dong,
                        f"https://new.land.naver.com/{URL_REALESTATE_TYPE_DICT.get(realestate_type_code, 'complexes')}?articleNo={new_c_no}",
                        expose_start_ymd,
                        verification_type_name,
                        realestate_type,
                        trade_type,
                        name,
                        dong,
                        hosu,
                        area1,
                        area2,
                        arch_area,
                        exclusive_rate,
                        yj_rate,
                        gp_rate,
                        floor,
                        total_floor,
                        direction,
                        deal_price,
                        rent_price,
                        price_by_space,
                        gongsi_std_ymd,
                        gongsi_min_price,
                        gongsi_max_price,
                        right_price,
                        finance_price,
                        all_warrant_price,
                        all_rent_price,
                        premium_price,
                        biz_step,
                        usage_district,
                        management_cost,
                        room_count,
                        bathroom_count,
                        nanbang,
                        current_usage,
                        recommend_usage,
                        building_usage,
                        jisang_jiha_floor,
                        movein_possible_ymd,
                        simple_description, 
                        detail_description,
                        sojaeji,
                        addr,
                        detail_addr,
                        lat_long,
                        construction_company_name,
                        apt_use_approve_ymd,
                        saede_num,
                        dong_num,
                        park_count, 
                        agent_num, 
                        agent_name,
                        agent_man_name,
                        agent_addr,
                        agent_no,
                        agent_tel,
                        agent_phone,
                    ]
    
                    data.append(temp_data)
                    
                except Exception as e: 
                    self._log(str(e))
    
        else:
            data.append(list(c["in_data"].values()))
    
        return data

    def extract_detail_v2(self, atcl_no: str, is_hosu_needed: bool = True) -> Optional[list]:
        """개별 매물 상세 API를 호출하고, 기존 extract_details와 동일한 필드 리스트를 반환한다."""
        c_info_url = f"https://new.land.naver.com/api/articles/{atcl_no}?complexNo="
        try:
            c_info_res = self.sess.get(c_info_url, impersonate='chrome', timeout=self.timeout_sec)
            c_info = c_info_res.json()
            # with open(f"c_info_{self.exec_ts}/{atcl_no}.json", "w", encoding="utf-8") as f:
            #    json.dump(c_info, f, ensure_ascii=False, indent=4)
        except Exception as e:
            self._log(f"extract_detail_v2 article 요청 실패 (atcl={atcl_no}): {e}")
            return None

        article_detail = c_info.get("articleDetail")
        if not article_detail:
            self._log(f"extract_detail_v2 articleDetail 없음 (atcl={atcl_no})")
            return None

        addr_si = article_detail.get("cityName", "")
        addr_gu = article_detail.get("divisionName", "")
        addr_dong = article_detail.get("sectionName", "")
        sojaeji = article_detail.get("exposureAddress", "")
        if not sojaeji:
            sojaeji = f"{addr_si} {addr_gu}".strip()
        expose_start_ymd = convert_date(article_detail.get("exposeStartYMD", ""))
        verification_type_name = article_detail.get("verificationTypeName", "")
        realestate_type = article_detail.get("realestateTypeName", "")
        realestate_type_code = article_detail.get("realestateTypeCode", "")
        trade_type_code = article_detail.get("tradeTypeCode", "")
        trade_type = article_detail.get("tradeTypeName", "")
        name = article_detail.get("articleName", "") or article_detail.get("complexName", "") or article_detail.get("aptName", "")
        dong = article_detail.get("buildingName", "")

        hscp_no = article_detail.get("hscpNo", "")
        dong_no = article_detail.get("buildNo", "")

        yj_rate = None
        gp_rate = None
        detail_addr = None

        try:
            detail_addr_url = f"https://new.land.naver.com/api/complexes/{hscp_no}?sameAddressGroup=false"
            detail_addr_res = self.sess.get(detail_addr_url, impersonate='chrome', timeout=self.timeout_sec)
            if detail_addr_res.status_code == 200:
                c_detail = detail_addr_res.json().get("complexDetail", "")
                if c_detail:
                    detail_addr = f'{c_detail.get("address", "").split(" ")[-1]} {c_detail.get("detailAddress", "")}'.strip()
                    yj_rate = c_detail.get("batlRatio", "")
                    gp_rate = c_detail.get("btlRatio", "")
        except Exception:
            pass

        gongsi_std_ymd = None
        gongsi_min_price = None
        gongsi_max_price = None
        try:
            landprice_url = f"https://new.land.naver.com/api/complexes/{hscp_no}/buildings/landprice"
            landprice_params = {"dongNo": dong_no, "complexNo": hscp_no}
            landprice_res = self.sess.get(landprice_url, params=landprice_params, impersonate='chrome', timeout=self.timeout_sec)
            if landprice_res.status_code == 200:
                gongsi_std_ymd = get_gongsi(landprice_res)
                landprice_color_summary = landprice_res.json().get("landPriceColorSummary", "")
                if landprice_color_summary:
                    gp_min = landprice_color_summary.get("minLandPrice", "")
                    gongsi_min_price = "{:,}".format(gp_min) if gp_min else None
                    gp_max = landprice_color_summary.get("maxLandPrice", "")
                    gongsi_max_price = "{:,}".format(gp_max) if gp_max else None
        except Exception:
            pass

        article_addition = c_info.get("articleAddition") or {}
        area1 = article_addition.get("area1", "")
        area2 = article_addition.get("area2", "")
        article_space = c_info.get("articleSpace", "")
        arch_area = article_space.get("buildingSpace", "") if article_space else None
        arch_area = int(float(arch_area)) if arch_area else arch_area
        exclusive_rate = article_space.get("exclusiveRate", "") if article_space else None
        rep_img_url = article_addition.get("representativeImgUrl", "")

        if not yj_rate:
            yj_rate = find_key_in_nested_dict(c_info, "floorAreaRatio")
        if not yj_rate or yj_rate == "-" or realestate_type == "전원주택":
            yj_rate = find_key_in_nested_dict(c_info, "vlRat")
        if not gp_rate:
            gp_rate = find_key_in_nested_dict(c_info, "buildingCoverageRatio")
        if not gp_rate or gp_rate == "-" or realestate_type == "전원주택":
            gp_rate = find_key_in_nested_dict(c_info, "bcRat")

        direction = article_addition.get("direction", "")
        floor_info = article_addition.get("floorInfo", "")
        floor = None
        total_floor = None
        if floor_info:
            parts = floor_info.split("/")
            floor = parts[0].strip()
            total_floor = parts[1].strip() if len(parts) > 1 else None

        article_price = c_info.get("articlePrice") or {}
        deal_price = None
        rent_price = None
        if trade_type_code == "A1":
            deal_price = article_price.get("dealPrice", "")
        elif trade_type_code in ("B1", "B2", "B3"):
            deal_price = article_price.get("warrantPrice", "")
        deal_price = convert_price(deal_price)
        price_by_space = convert_price(c_info.get("priceBySpace", ""))

        rent_price = convert_price(article_price.get("rentPrice", ""))
        right_price = convert_price(article_price.get("rightPrice"))
        finance_price = convert_price(article_price.get("financePrice", ""))
        premium_price = convert_price(article_price.get("premiumPrice", ""))
        biz_step = find_key_in_nested_dict(c_info, "bizStepDescription")

        usage_district = None
        management_cost = article_detail.get("monthlyManagementCost", "")
        admin_cost_info = c_info.get("administrationCostInfo", "")
        if not management_cost and admin_cost_info:
            etc_fee_details = admin_cost_info.get("etcFeeDetails", "")
            if etc_fee_details:
                management_cost = etc_fee_details.get("etcFeeAmount", "")
        if not management_cost and admin_cost_info:
            fixed_fee_details = admin_cost_info.get("fixedFeeDetails", "")
            if fixed_fee_details:
                management_cost = sum([f.get("amount") for f in fixed_fee_details if f.get("amount")])
        if management_cost:
            management_cost = "{:,}".format(management_cost) if isinstance(management_cost, (int, float)) else management_cost

        room_count = article_detail.get("roomCount", "")
        bathroom_count = article_detail.get("bathroomCount", "")
        article_facility = c_info.get("articleFacility", "")
        nanbang = (f'{article_facility.get("heatMethodTypeName", "")}/{article_facility.get("heatFuelTypeName", "")}'
                   if article_facility and article_facility.get("heatMethodTypeName", "") else None)
        if nanbang is None:
            nanbang = (f'{article_detail.get("aptHeatMethodTypeName", "")}/{article_detail.get("aptHeatFuelTypeName", "")}'
                       if article_detail.get("aptHeatMethodTypeName", "") else None)
        current_usage = article_detail.get("currentUsage", "")
        recommend_usage = article_detail.get("recommendUsage", "")
        building_usage = None

        article_floor = c_info.get("articleFloor", "")
        jisang_floor = article_floor.get("uppergroundFloorCount", "") if article_floor else None
        jiha_floor = article_floor.get("undergroundFloorCount", "") if article_floor else None
        jisang_jiha_floor = None
        if jisang_floor and jiha_floor and not (jisang_floor == "-" and jiha_floor == "-"):
            jisang_jiha_floor = f"{jisang_floor}/{jiha_floor}"

        movein_possible_ymd = article_detail.get("moveInPossibleYmd", "")
        if not movein_possible_ymd:
            movein_possible_ymd = find_key_in_nested_dict(c_info, "moveInTypeName")
        try:
            movein_possible_ymd = convert_date(movein_possible_ymd)
        except Exception:
            pass
        simple_description = article_detail.get("articleFeatureDescription", "")
        detail_description = article_detail.get("detailDescription", "")
        addr = None
        lat_long = f'{article_detail.get("latitude", "")},{article_detail.get("longitude", "")}'
        construction_company_name = find_key_in_nested_dict(c_info, "aptConstructionCompanyName")
        if not construction_company_name:
            construction_company_name = find_key_in_nested_dict(c_info, "constructorName")
        apt_use_approve_ymd = article_detail.get("aptUseApproveYmd", "")
        if not apt_use_approve_ymd:
            apt_use_approve_ymd = article_facility.get("buildingUseAprvYmd", "") if article_facility else None
        apt_use_approve_ymd = convert_date(apt_use_approve_ymd)
        saede_num = article_detail.get("aptHouseholdCount", "")
        if not saede_num:
            saede_num = find_key_in_nested_dict(c_info, "householdCount")
        if not saede_num:
            saede_num = find_key_in_nested_dict(c_info, "allHoCnt")
        dong_num = article_detail.get("totalDongCount", "")
        article_br = c_info.get("articleBuildingRegister", "")
        park_count = article_br.get("totalParkingCnt", "") if article_br else article_detail.get("aptParkingCount", "")

        all_warrant_price = None
        all_rent_price = None

        # fin.land.naver.com 상세 페이지에서 추가 정보 추출
        try:
            pbs_url = f"https://fin.land.naver.com/articles/{atcl_no}"
            pbs_res = self.sess.get(pbs_url, impersonate='chrome', timeout=self.timeout_sec)
            if pbs_res.status_code == 200:
                pbs_soup = bs(pbs_res.text, "html.parser")
                if not price_by_space:
                    try:
                        pbs_el = pbs_soup.select_one("span.ArticleSummary_info-size___Ut9Q")
                        if pbs_el:
                            price_by_space = pbs_el.text.split("만원")[0].replace("억 ", "")
                    except Exception:
                        pass
                try:
                    scripts = pbs_soup.select("script")
                    target_script = None
                    for script in scripts:
                        if script.get("id") == "__NEXT_DATA__":
                            target_script = script
                            break
                    if target_script:
                        info_json = json.loads(target_script.string)
                        if not yj_rate or yj_rate == "-" or realestate_type == "재개발":
                            try:
                                yj_rate = find_key_in_nested_dict(info_json, "floorAreaRatio")
                                if realestate_type == "재개발" or not yj_rate:
                                    bri = find_key_in_nested_dict(info_json, "buildingRatioInfo")
                                    if bri:
                                        yj_rate = bri.get("floorAreaRatio", "")
                                if yj_rate:
                                    yj_rate = int(yj_rate)
                            except Exception:
                                pass
                        if not gp_rate or gp_rate == "-" or realestate_type == "재개발":
                            try:
                                gp_rate = find_key_in_nested_dict(info_json, "buildingCoverageRatio")
                                if realestate_type == "재개발" or not gp_rate:
                                    bri = find_key_in_nested_dict(info_json, "buildingRatioInfo")
                                    if bri:
                                        gp_rate = bri.get("buildingCoverageRatio", "")
                                if gp_rate:
                                    gp_rate = int(gp_rate)
                            except Exception:
                                pass
                        if not rent_price:
                            try:
                                rp = find_key_in_nested_dict(info_json, "rentAmount")
                                if rp:
                                    rent_price = "{:,}".format(rp)
                            except Exception:
                                pass
                        if not deal_price and trade_type_code == "B1":
                            try:
                                dp = find_key_in_nested_dict(info_json, "warrantyAmount")
                                if dp:
                                    deal_price = "{:,}".format(dp)
                            except Exception:
                                pass
                        if not all_warrant_price:
                            try:
                                awp = find_key_in_nested_dict(info_json, "previousDeposit")
                                if awp:
                                    all_warrant_price = "{:,}".format(awp)
                            except Exception:
                                pass
                        if not all_rent_price:
                            try:
                                arp = find_key_in_nested_dict(info_json, "previousMonthlyRent")
                                if arp:
                                    all_rent_price = "{:,}".format(arp)
                            except Exception:
                                pass
                        if not direction:
                            try:
                                d = find_key_in_nested_dict(info_json, "direction")
                                if d:
                                    direction = DIRECTION_DICT.get(d, d)
                            except Exception:
                                pass
                        if not building_usage:
                            try:
                                building_usage = find_key_in_nested_dict(info_json, "buildingUse")
                                if not building_usage:
                                    building_usage = find_key_in_nested_dict(info_json, "buildingPrincipalUse")
                            except Exception:
                                pass
                        if not usage_district:
                            try:
                                usage_district = find_key_in_nested_dict(info_json, "areaUsage")
                            except Exception:
                                pass
                        if not usage_district or not saede_num:
                            if not usage_district:
                                pnu = find_key_in_nested_dict(info_json, "pnu")
                                if pnu:
                                    try:
                                        pnu_res = self.sess.get(f"https://fin.land.naver.com/front-api/v1/complex/buildingRegistration?pnu={pnu}", impersonate='chrome', timeout=self.timeout_sec)
                                        if pnu_res.status_code == 200:
                                            if not usage_district:
                                                try:
                                                    spi = find_key_in_nested_dict(pnu_res.json(), "specialPurposeInfo")
                                                    if spi:
                                                        usage_district = spi.get("area", {}).get("purpose")
                                                except Exception:
                                                    pass
                                            if not saede_num:
                                                try:
                                                    saede_num = find_key_in_nested_dict(pnu_res.json(), "hoNumber")
                                                except Exception:
                                                    pass
                                                if not saede_num:
                                                    try:
                                                        saede_num = find_key_in_nested_dict(pnu_res.json(), "familyNumber")
                                                    except Exception:
                                                        pass
                                    except Exception:
                                        pass
                        if not park_count:
                            try:
                                park_count = find_key_in_nested_dict(info_json, "totalParkingCount")
                            except Exception:
                                pass
                        if not detail_addr:
                            try:
                                dong_eup_myeon_code = find_key_in_nested_dict(info_json, "legalDivisionNumber")
                                jibun = find_key_in_nested_dict(info_json, "jibun")
                                dong_eup_myeon = find_keys_with_value(self.rls, dong_eup_myeon_code)
                                detail_addr = f'{dong_eup_myeon if dong_eup_myeon else ""} {jibun if jibun else ""}'.strip()
                            except Exception:
                                pass
                except Exception:
                    pass
        except Exception:
            pass

        agent_num = None
        try:
            agents_url = f"https://new.land.naver.com/api/articles?representativeArticleNo={atcl_no}"
            agents_res = self.sess.get(agents_url, impersonate='chrome', timeout=self.timeout_sec)
            if agents_res.status_code == 200:
                agent_num = len(agents_res.json())
        except Exception:
            pass

        article_realtor = c_info.get("articleRealtor", "")
        agent_name = article_realtor.get("realtorName", "") if article_realtor else None
        agent_man_name = article_realtor.get("representativeName", "") if article_realtor else None
        agent_addr = article_realtor.get("address", "") if article_realtor else None
        agent_no = article_realtor.get("establishRegistrationNo", "") if article_realtor else None
        agent_tel = article_realtor.get("representativeTelNo", "") if article_realtor else None
        agent_phone = article_realtor.get("cellPhoneNo", "") if article_realtor else None

        if not biz_step or not construction_company_name:
            try:
                biz_url = f"https://fin.land.naver.com/front-api/v1/complex/reconstruction?complexNumber={hscp_no}"
                biz_res = self.sess.get(biz_url, impersonate='chrome', timeout=self.timeout_sec)
                if biz_res.status_code == 200:
                    if not construction_company_name:
                        try:
                            construction_company_name = biz_res.json().get("result", {}).get("constructionCompany")
                        except Exception:
                            pass
                    if not biz_step:
                        try:
                            biz_step_code = biz_res.json().get("result", {}).get("currentBusinessStep", {}).get("stepType")
                            if biz_step_code:
                                biz_step = BIZ_STEP_TYPES.get(biz_step_code, biz_step_code)
                        except Exception:
                            pass
            except Exception:
                pass

        # 후처리
        if all_warrant_price is not None and all_warrant_price != "":
            try:
                val = int(str(all_warrant_price).replace(",", ""))
                all_warrant_price = None if val == 0 else all_warrant_price
            except Exception:
                pass
        if all_rent_price is not None and all_rent_price != "":
            try:
                val = int(str(all_rent_price).replace(",", ""))
                all_rent_price = None if val == 0 else all_rent_price
            except Exception:
                pass
        if dong_num is not None and dong_num != "":
            try:
                dong_num = None if int(dong_num) == 0 else dong_num
            except Exception:
                pass
        if park_count is not None and park_count != "":
            try:
                park_count = None if int(park_count) == 0 else park_count
            except Exception:
                pass
        if yj_rate:
            yj_rate = None if yj_rate == "-" else int(float(yj_rate))
        if gp_rate:
            gp_rate = None if gp_rate == "-" else int(float(gp_rate))
        if management_cost == 0:
            management_cost = None

        # 소재지/세부주소 지번 상호 보완:
        # - 아파트/오피스텔: 소재지가 동까지만 나오고 지번은 세부주소에만 있음 → 소재지에 병합
        # - 원룸/빌라: 지번이 소재지에만 있고 세부주소가 빈칸 → 세부주소 채움
        # - 상가/사무실/건물/토지: 텍스트 주소가 아예 동까지만 옴 → 매물 좌표(실건물 위치)를
        #   역지오코딩해서 정확한 지번 주소 복원
        try:
            _jibun_re = re.compile(r"(산?\d+(?:-\d+)?)\s*$")
            _sojaeji_s = str(sojaeji or "").strip()
            _detail_s = str(detail_addr or "").strip()
            _m_detail = _jibun_re.search(_detail_s)
            _m_sojaeji = _jibun_re.search(_sojaeji_s)
            if _m_detail and not _m_sojaeji:
                if addr_dong and _detail_s.startswith(addr_dong) and addr_si:
                    sojaeji = f"{addr_si} {addr_gu} {_detail_s}".strip()
                else:
                    sojaeji = f"{_sojaeji_s} {_m_detail.group(1)}".strip()
                _m_sojaeji = _jibun_re.search(str(sojaeji))
            elif _m_sojaeji and not _m_detail:
                _jibun = _m_sojaeji.group(1)
                detail_addr = f"{addr_dong} {_jibun}".strip() if addr_dong else _jibun
            if not _m_sojaeji:
                _lat = article_detail.get("latitude")
                _lon = article_detail.get("longitude")
                _rg = self._reverse_geocode_jibun(_lat, _lon) if (_lat and _lon) else None
                if _rg:
                    sojaeji = _rg
                    _m_rg = _jibun_re.search(_rg)
                    if _m_rg and not _jibun_re.search(str(detail_addr or "")):
                        _dong_part = addr_dong or (_rg.split()[-2] if len(_rg.split()) >= 2 else "")
                        detail_addr = f"{_dong_part} {_m_rg.group(1)}".strip()
        except Exception:
            pass

        article_url = f"https://new.land.naver.com/{URL_REALESTATE_TYPE_DICT.get(realestate_type_code, 'complexes')}?articleNo={atcl_no}"

        if is_hosu_needed:
            hosu = self._infer_hosu(
                c_info,
                dong=dong,
                floor=floor,
                total_floor=total_floor,
                article_space=article_space,
                area2=area2,
                detail_addr=detail_addr,
                sojaeji=sojaeji,
            )

        article_img_url = f"{self.IMG_BASE_URL}{rep_img_url}" if rep_img_url else None

        final_data = [
            addr_si, addr_gu, addr_dong, article_url, article_img_url,
            expose_start_ymd, verification_type_name, realestate_type, trade_type,
            name, dong, area1, area2, arch_area, exclusive_rate, yj_rate, gp_rate,
            floor, total_floor, direction, deal_price, rent_price, price_by_space,
            gongsi_std_ymd, gongsi_min_price, gongsi_max_price, right_price, finance_price,
            all_warrant_price, all_rent_price, premium_price, biz_step, usage_district,
            management_cost, room_count, bathroom_count, nanbang, current_usage, recommend_usage,
            building_usage, jisang_jiha_floor, movein_possible_ymd, simple_description,
            detail_description, sojaeji, addr, detail_addr, lat_long,
            construction_company_name, apt_use_approve_ymd, saede_num, dong_num, park_count,
            agent_num, agent_name, agent_man_name, agent_addr, agent_no, agent_tel, agent_phone,
        ]
        if is_hosu_needed:
            final_data.insert(11, hosu)

        return final_data


__all__ = ['convert_price', 'convert_date', 'NaverCrawler']

if __name__ == "__main__":
    rls = _load_rls_file()
    import tkinter as tk
    from tkinter import ttk, messagebox

    class ScrollableFrame(ttk.Frame):
        def __init__(self, container, *args, **kwargs):
            super().__init__(container, *args, **kwargs)
            
            canvas = tk.Canvas(self, bg="#f0f0f0")
            scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
            self.scrollable_frame = ttk.Frame(canvas) 
    
            self.scrollable_frame.bind(
                "<Configure>",
                lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
            )
    
            canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
            canvas.configure(yscrollcommand=scrollbar.set)
    
            canvas.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")
    
            self.scrollable_frame.bind("<Enter>", lambda e: self._bind_to_mousewheel(canvas))
            self.scrollable_frame.bind("<Leave>", lambda e: self._unbind_from_mousewheel(canvas))
        
        def _bind_to_mousewheel(self, canvas):
            if canvas.tk.call('tk', 'windowingsystem') == 'aqua':
                canvas.bind_all("<MouseWheel>", lambda event: canvas.yview_scroll(int(-1*(event.delta)), "units"))
            else:
                canvas.bind_all("<MouseWheel>", lambda event: canvas.yview_scroll(int(-1*(event.delta/120)), "units"))
                canvas.bind_all("<Button-4>", lambda event: canvas.yview_scroll(-1, "units")) 
                canvas.bind_all("<Button-5>", lambda event: canvas.yview_scroll(1, "units"))  
        
        def _unbind_from_mousewheel(self, canvas):
            canvas.unbind_all("<MouseWheel>")
            canvas.unbind_all("<Button-4>")
            canvas.unbind_all("<Button-5>")
    
    root = tk.Tk()
    root.title("네이버부동산 크롤러")
    root.geometry(f"500x800") 
    root.configure(bg="#f0f0f0")
    
    style = ttk.Style(root)
    style.theme_use('default')
    style.configure("TButton", font=("Arial", 12))
    style.configure("TLabel", font=("Arial", 12))
    style.configure("Header.TLabel", font=("Arial", 14, "bold"))
    style.configure("TCheckbutton", font=("Arial", 10))
    
    main_frame = ttk.Frame(root, padding=10)
    main_frame.pack(fill="both", expand=True)
    
    scrollable_main = ScrollableFrame(main_frame)
    scrollable_main.pack(fill="both", expand=True)
    
    region_frame = ttk.LabelFrame(scrollable_main.scrollable_frame, text="지역 선택", padding=10)
    region_frame.pack(fill="x", expand=True, padx=5, pady=5, anchor="w")
    
    selected_si = tk.StringVar(value="시 선택")
    selected_gu = tk.StringVar(value="구 선택")
    selected_dong = tk.StringVar(value="동 선택")
    
    def update_gu(*args):
        sido = selected_si.get()
        if sido not in rls:
            selected_gu.set("구 선택")
            selected_dong.set("동 선택")  # 구를 선택하지 않으면 동도 초기화
            dong_menu['menu'].delete(0, 'end')
            dong_menu['menu'].add_command(label="동 선택", command=lambda: selected_dong.set("동 선택"))
            return
    
        gu_options = list(rls[sido].keys())
        selected_gu.set("구 선택")  # 구를 선택할 때마다 기본값으로 "구 선택"으로 설정
    
        gu_menu['menu'].delete(0, 'end')
        for gu in gu_options:
            gu_menu['menu'].add_command(label=gu, command=lambda value=gu: selected_gu.set(value))
    
        update_dong()  # 구가 변경되면 동도 초기화
    
    def update_dong(*args):
        si = selected_si.get()
        gu = selected_gu.get()
    
        if si not in rls or gu not in rls[si]:
            selected_dong.set("동 선택")
            dong_menu['menu'].delete(0, 'end')
            dong_menu['menu'].add_command(label="동 선택", command=lambda: selected_dong.set("동 선택"))
            return
    
        dong_options = list(rls[si][gu].keys())
        selected_dong.set("동 선택")  # 동을 선택할 때마다 기본값으로 "동 선택"으로 설정
    
        dong_menu['menu'].delete(0, 'end')
        for dong in dong_options:
            dong_menu['menu'].add_command(label=dong, command=lambda value=dong: selected_dong.set(value))
    
    
    si_menu = ttk.OptionMenu(region_frame, selected_si, "시 선택", *rls.keys())
    si_menu.grid(row=0, column=0, padx=5, pady=5, sticky="w")
    
    gu_menu = ttk.OptionMenu(region_frame, selected_gu, "구 선택")
    gu_menu.grid(row=0, column=1, padx=5, pady=5, sticky="w")
    
    dong_menu = ttk.OptionMenu(region_frame, selected_dong, "동 선택")
    dong_menu.grid(row=0, column=2, padx=5, pady=5, sticky="w")
    
    selected_si.trace_add('write', update_gu)
    selected_gu.trace_add('write', update_dong)
    
    filter_frame = ttk.LabelFrame(scrollable_main.scrollable_frame, text="필터 선택", padding=10)
    filter_frame.pack(fill="x", expand=True, padx=5, pady=5, anchor="w")
    
    def create_checkboxes(parent, options, selected_vars, title, max_per_row=4):
        frame = ttk.LabelFrame(parent, text=title, padding=10)
        frame.pack(fill="x", expand=True, padx=5, pady=5, anchor="w")
    
        for idx, option in enumerate(options):
            var = tk.BooleanVar()
            selected_vars[option] = var
            cb = ttk.Checkbutton(frame, text=option, variable=var)
            
            # Grid layout으로 줄바꿈 처리
            row = idx // max_per_row
            col = idx % max_per_row
            cb.grid(row=row, column=col, sticky="w", padx=5, pady=5)
    
    # 아파트 구분 체크박스
    apartment_options = [
        "아파트",
        "아파트분양권",
        "재건축",
        "오피스텔",
        "오피스텔분양권",
        "재개발",
        "분양중/예정",
        "빌라/연립",
        "단독/다가구",
        "전원주택",
        "상가주택",
        "한옥주택",
        "원룸",
        "투룸",
        "상가",
        "사무실",
        "공장/창고",
        "지식산업센터",
        "건물",
        "토지"
    ]
    selected_apartment_options = {}
    create_checkboxes(filter_frame, apartment_options, selected_apartment_options, "아파트 구분")
    
    # 거래유형 체크박스
    transaction_options = [
        "매매",
        "전세",
        "월세",
        "단기임대",
    ]
    selected_transaction_options = {}
    create_checkboxes(filter_frame, transaction_options, selected_transaction_options, "거래유형")
    
    def create_range_options(parent, label_text, options_dict, var_left, var_right):
        frame = ttk.LabelFrame(parent, text=label_text, padding=10)
        frame.pack(fill="x", expand=True, padx=5, pady=5, anchor="w")
    
        left_menu = ttk.OptionMenu(frame, var_left, "무관", *options_dict.keys())
        left_menu.pack(side="left", padx=5, pady=5)
    
        tilde = ttk.Label(frame, text="~")
        tilde.pack(side="left")
    
        right_menu = ttk.OptionMenu(frame, var_right, "무관", *options_dict.keys())
        right_menu.pack(side="left", padx=5, pady=5)
    
    # 매매가 옵션
    deal_price_dict = {
        "무관": None,
        "5천": 5000,
        "6천" : 6000,
        "7천" : 7000,
        "8천" : 8000,
        "9천" : 9000,
        "1억": 10000,
        "2억": 20000,
        "3억": 30000,
        "4억": 40000,
        "5억": 50000,
        "6억": 60000,
        "7억": 70000,
        "8억": 80000,
        "9억": 90000,
        "10억": 100000,
        "11억": 110000,
        "12억": 120000,
        "13억": 130000,
        "14억": 140000,
        "15억": 150000,
        "16억": 160000,
        "17억": 170000,
        "18억": 180000,
    }
    deal_price_option_L = tk.StringVar(value="무관")
    deal_price_option_R = tk.StringVar(value="무관")
    create_range_options(filter_frame, "매매가", deal_price_dict, deal_price_option_L, deal_price_option_R)
    
    # 보증금 옵션
    warranty_price_dict = {
        "무관": None,
        "1천": 1000,
        "2천": 2000,
        "3천": 3000,
        "4천": 4000,
        "5천": 5000,
        "6천": 6000,
        "7천": 7000,
        "8천": 8000,
        "9천": 9000,
        "1억": 10000,
        "2억": 20000,
        "3억": 30000,
        "4억": 40000,
        "5억": 50000
    }
    warranty_price_option_L = tk.StringVar(value="무관")
    warranty_price_option_R = tk.StringVar(value="무관")
    create_range_options(filter_frame, "보증금", warranty_price_dict, warranty_price_option_L, warranty_price_option_R)
    
    # 월세 옵션
    rent_price_dict = {
        "무관": None,
        "10" : 10,
        "20": 20,
        "30": 30,
        "40": 40,
        "50": 50,
        "60": 60,
        "70": 70,
        "80": 80,
        "90": 90,
        "1백": 100,
        "2백": 200,
    }
    rent_price_option_L = tk.StringVar(value="무관")
    rent_price_option_R = tk.StringVar(value="무관")
    create_range_options(filter_frame, "월세", rent_price_dict, rent_price_option_L, rent_price_option_R)
    
    # 면적 옵션
    area_dict = {
        "무관": None,
        "10평": 33,
        "20평": 66,
        "30평": 99,
        "40평": 132,
        "50평": 165,
        "60평": 198,
        "70평": 231
    }
    area_option_L = tk.StringVar(value="무관")
    area_option_R = tk.StringVar(value="무관")
    create_range_options(filter_frame, "면적", area_dict, area_option_L, area_option_R)
    
    from functools import partial
    
    def create_exclusive_checkboxes(parent, options, selected_vars, title):
        frame = ttk.LabelFrame(parent, text=title, padding=10)
        frame.pack(fill="x", expand=True, padx=5, pady=5, anchor="w")
        
        def on_check(var, option, *args):
            if var.get():  
                for key in selected_vars:
                    if key != option:
                        selected_vars[key].set(False)
        
        for option in options:
            var = tk.BooleanVar()
            selected_vars[option] = var
            
            if option == "전체":
                var.set(True)
            
            var.trace_add("write", partial(on_check, var, option))
            
            cb = ttk.Checkbutton(frame, text=option, variable=var)
            cb.pack(side="left", padx=5, pady=5)
    
    date_dict = {
        "전체" : None,
        "오늘" : 1,
        "어제/오늘" : 2,
        "일주일" : 7,
        "한달" : 30
    }
    date_options = list(date_dict.keys())
    selected_date_options = {} 
    create_exclusive_checkboxes(filter_frame, date_options, selected_date_options, "등록일")
    
    button_frame = ttk.Frame(scrollable_main.scrollable_frame, padding=10)
    button_frame.pack(fill="x", expand=True, padx=5, pady=5, anchor="w")
    
    def search():
    
        selected_items.clear()
    
        global cls 
        # JGC:PRE:OBYG:APT:ABYG:JGB:OPST # SG:SMS:GJCG:APTHGJ:GM:TJ
        JGC = ("JGC" if selected_apartment_options["재건축"].get() else "")
        PRE = ("IA01:IA02:IC01:IC02:IA04:IC03" if selected_apartment_options["분양중/예정"].get() else "")
        OBYG = ("OBYG" if selected_apartment_options["오피스텔분양권"].get() else "")
        APT = ("APT" if selected_apartment_options["아파트"].get() else "")
        ABYG = ("ABYG" if selected_apartment_options["아파트분양권"].get() else "")
        JGB = ("JGB" if selected_apartment_options["재개발"].get() else "")
        OPST = ("OPST" if selected_apartment_options["오피스텔"].get() else "")
        VL = ("VL" if selected_apartment_options["빌라/연립"].get() else "")
        DDDGG = ("DDDGG" if selected_apartment_options["단독/다가구"].get() else "")
        JWJT = ("JWJT" if selected_apartment_options["전원주택"].get() else "")
        SGJT = ("SGJT" if selected_apartment_options["상가주택"].get() else "")
        HOJT = ("HOJT" if selected_apartment_options["한옥주택"].get() else "")
        OR = ("OR" if selected_apartment_options["원룸"].get() or selected_apartment_options["투룸"].get() else "")
        SG = ("SG" if selected_apartment_options["상가"].get() else "")
        SMS = ("SMS" if selected_apartment_options["사무실"].get() else "")
        GJCG = ("GJCG" if selected_apartment_options["공장/창고"].get() else "")
        APTHGJ = ("APTHGJ" if selected_apartment_options["지식산업센터"].get() else "")
        GM = ("GM" if selected_apartment_options["건물"].get() else "")
        TJ = ("TJ" if selected_apartment_options["토지"].get() else "")
    
        realestate_type = ":".join([t for t in [JGC, PRE, OBYG, APT, ABYG, JGB, OPST, VL, DDDGG, JWJT, SGJT, HOJT, OR, SG, SMS, GJCG, APTHGJ, GM, TJ] if t])
    
        # if OR:
        #     if selected_apartment_options["원룸"].get() and not selected_apartment_options["투룸"].get():
        #         tag = ":::::::ONEROOM:"
        #     elif not selected_apartment_options["원룸"].get() and selected_apartment_options["투룸"].get():
        #         tag = ":::::::TWOROOM:"
        #     else:
        #         tag = ":::::::SMALLSPCRENT:"
        # else: tag = "::::::::"
        tag = "::::::::"
    
        A1 = ("A1" if selected_transaction_options["매매"].get() else "")
        B1 = ("B1" if selected_transaction_options["전세"].get() else "")
        B2 = ("B2" if selected_transaction_options["월세"].get() else "")
        B3 = ("B3" if selected_transaction_options["단기임대"].get() else "")
        trade_type = ":".join(t for t in [A1, B1, B2, B3] if t) 
        
        min_deal_price = deal_price_dict[deal_price_option_L.get()]
        max_deal_price = deal_price_dict[deal_price_option_R.get()]
    
        min_warranty_price = warranty_price_dict[warranty_price_option_L.get()]
        max_warranty_price = warranty_price_dict[warranty_price_option_R.get()]
    
        min_rent_price = rent_price_dict[rent_price_option_L.get()]
        max_rent_price = rent_price_dict[rent_price_option_R.get()]
    
        min_area = area_dict[area_option_L.get()]
        max_area = area_dict[area_option_R.get()]
    
        date_key = [key for key, value in selected_date_options.items() if value.get()]
        max_days_from_now = date_dict[date_key[0]]
    
        crawler = NaverCrawler()
        cls = crawler.search_complexes(
            selected_si.get(), selected_gu.get(), selected_dong.get(),
            realestate_type=realestate_type, tag=tag, trade_type=trade_type,
            min_deal_price=min_deal_price, max_deal_price=max_deal_price,
            min_warranty_price=min_warranty_price, max_warranty_price=max_warranty_price,
            min_rent_price=min_rent_price, max_rent_price=max_rent_price,
            min_area=min_area, max_area=max_area, max_days_from_now=max_days_from_now,
        )
        print(f"{len(cls)}개 조회됨")
        create_cls_checkboxes(checkbox_frame, cls)
    
    search_button = ttk.Button(button_frame, text="검색", command=search)
    search_button.pack(side="left", padx=10, pady=10)
    
    def exec():
        global cls 
        # print(selected_items)
        selected_cls_idx_list = [i for i, (key, value) in enumerate(selected_items.items()) if value.get()]
        # print(selected_cls_idx_list)
        filtered_cls = [cls[i] for i in selected_cls_idx_list]
    
        JGC = ("JGC" if selected_apartment_options["재건축"].get() else "")
        PRE = ("IA01:IA02:IC01:IC02:IA04:IC03" if selected_apartment_options["분양중/예정"].get() else "")
        OBYG = ("OBYG" if selected_apartment_options["오피스텔분양권"].get() else "")
        APT = ("APT" if selected_apartment_options["아파트"].get() else "")
        ABYG = ("ABYG" if selected_apartment_options["아파트분양권"].get() else "")
        JGB = ("JGB" if selected_apartment_options["재개발"].get() else "")
        OPST = ("OPST" if selected_apartment_options["오피스텔"].get() else "")
        VL = ("VL" if selected_apartment_options["빌라/연립"].get() else "")
        DDDGG = ("DDDGG" if selected_apartment_options["단독/다가구"].get() else "")
        JWJT = ("JWJT" if selected_apartment_options["전원주택"].get() else "")
        SGJT = ("SGJT" if selected_apartment_options["상가주택"].get() else "")
        HOJT = ("HOJT" if selected_apartment_options["한옥주택"].get() else "")
        OR = ("OR" if selected_apartment_options["원룸"].get() or selected_apartment_options["투룸"].get() else "")
        SG = ("SG" if selected_apartment_options["상가"].get() else "")
        SMS = ("SMS" if selected_apartment_options["사무실"].get() else "")
        GJCG = ("GJCG" if selected_apartment_options["공장/창고"].get() else "")
        APTHGJ = ("APTHGJ" if selected_apartment_options["지식산업센터"].get() else "")
        GM = ("GM" if selected_apartment_options["건물"].get() else "")
        TJ = ("TJ" if selected_apartment_options["토지"].get() else "")
    
        realestate_type = ":".join([t for t in [JGC, PRE, OBYG, APT, ABYG, JGB, OPST, VL, DDDGG, JWJT, SGJT, HOJT, OR, SG, SMS, GJCG, APTHGJ, GM, TJ] if t])
    
        # if OR:
        #     if selected_apartment_options["원룸"].get() and not selected_apartment_options["투룸"].get():
        #         tag = ":::::::ONEROOM:"
        #     elif not selected_apartment_options["원룸"].get() and selected_apartment_options["투룸"].get():
        #         tag = ":::::::TWOROOM:"
        #     else:
        #         tag = ":::::::SMALLSPCRENT:"
        # else: tag = "::::::::"
        tag = "::::::::"
    
        A1 = ("A1" if selected_transaction_options["매매"].get() else "")
        B1 = ("B1" if selected_transaction_options["전세"].get() else "")
        B2 = ("B2" if selected_transaction_options["월세"].get() else "")
        B3 = ("B3" if selected_transaction_options["단기임대"].get() else "")
        trade_type = ":".join(t for t in [A1, B1, B2, B3] if t) 
        
        min_deal_price = deal_price_dict[deal_price_option_L.get()]
        max_deal_price = deal_price_dict[deal_price_option_R.get()]
    
        min_warranty_price = warranty_price_dict[warranty_price_option_L.get()]
        max_warranty_price = warranty_price_dict[warranty_price_option_R.get()]
    
        min_rent_price = rent_price_dict[rent_price_option_L.get()]
        max_rent_price = rent_price_dict[rent_price_option_R.get()]
    
        min_area = area_dict[area_option_L.get()]
        max_area = area_dict[area_option_R.get()]
    
        messagebox.showinfo("알림", "작업을 시작합니다.")
    
        crawler = NaverCrawler()
        data = crawler.extract_details(
            filtered_cls,
            realestate_type=realestate_type, tag=tag, trade_type=trade_type,
            min_deal_price=min_deal_price, max_deal_price=max_deal_price,
            min_warranty_price=min_warranty_price, max_warranty_price=max_warranty_price,
            min_rent_price=min_rent_price, max_rent_price=max_rent_price,
            min_area=min_area, max_area=max_area,
        )
    
        if len(data) == 0:
            messagebox.showerror("알림", "저장된 데이터가 없습니다.")
            return 
        
        import pandas as pd 
        
        df = pd.DataFrame(data)
        df.columns = [
            "시",
            "구",
            "동",
            '매물번호',
            '등록/확인일',
            '집주인/확인',
            '종류',
            '거래방식',
            '매물명',
            '이미지URL',
            '아파트동',
            '호수',
            '공급/계약/대지',
            '전용/연',
            '건면적',
            '전용률',
            '용적률',
            '건폐율',
            '해당층',
            '전체층',
            '방향',
            '매매/전세금',
            '월세',
            '평단가',
            '공시기준일',
            '공시가(최저)',
            '공시가(최고)',
            '권리금',
            '융자금',
            '기보증금',
            '기월세',
            '프리미엄',
            '사업시행단계',
            '용도지역',
            '관리비',
            '방수',
            '화장실수',
            '난방',
            '현재업종',
            '추천업종',
            '건축물용도',
            '지상층/지하층',
            '입주가능일',
            '간략설명',
            '설명',
            '소재지',
            '주소',
            '세부주소',
            '위도/경도',
            '건설사',
            '사용승인일',
            '세대수',
            '동수',
            '주차가능수',
            '중개사수',
            '중개사무소명',
            '중개사명',
            '중개사주소',
            '중개사등록번호',
            '중개사전화',
            '중개사휴대폰'
        ]
        
        import time, re 
    
        from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
        df = df.map(lambda x: ILLEGAL_CHARACTERS_RE.sub(r'', x) if isinstance(x, str) else x)
        # df.fillna('', inplace=True)
        df.to_excel(f"data_{int(time.time())}.xlsx", index=False)
        
        messagebox.showinfo("알림", "작업을 완료했습니다.")
    
    exec_button = ttk.Button(button_frame, text="실행", command=exec)
    exec_button.pack(side="left", padx=10, pady=10)
    
    result_frame = ttk.LabelFrame(scrollable_main.scrollable_frame, text="검색결과", padding=10)
    result_frame.pack(fill="both", expand=True, padx=5, pady=5, anchor="w")
    
    result_scrollable = ScrollableFrame(result_frame)
    result_scrollable.pack(fill="both", expand=True)
    
    checkbox_frame = tk.Frame(result_scrollable.scrollable_frame, bg="white")
    checkbox_frame.pack(fill="both", expand=True, anchor="w")
    
    selected_items = {}
    cls = []  # 검색 결과 단지 목록 (search()에서 설정)
    
    def create_cls_checkboxes(parent, data):
        for widget in parent.winfo_children():
            widget.destroy()
    
        select_all_var = tk.BooleanVar(value=False)
    
        def toggle_all():
            for var in selected_items.values():
                var.set(select_all_var.get())
    
        select_all_checkbox = ttk.Checkbutton(
            parent,
            text="전체선택",
            variable=select_all_var,
            command=toggle_all
        )
        select_all_checkbox.pack(anchor="w", pady=5)
    
        for item in data:
            label = f'{item["complex_name"]} ({item["realestate_type_name"]}) [{item["complex_no"]}]'
            selected_items[label] = tk.BooleanVar(value=False)
            cb = ttk.Checkbutton(parent, text=label, variable=selected_items[label])
            cb.pack(anchor="w", pady=2)
    
        parent.update_idletasks()
        parent.master.update_idletasks()
    
    main_frame.rowconfigure(0, weight=1)
    main_frame.columnconfigure(0, weight=1)

    root.mainloop()