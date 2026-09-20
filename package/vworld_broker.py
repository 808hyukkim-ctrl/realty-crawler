# -*- coding: utf-8 -*-
"""
브이월드(vworld.kr) 국가중점데이터 '부동산중개업' 수집기 - 데이터 계층.

- 로그인: POST /v4po_usrlogin_a004.do  (usrIdeE/usrPwdE = base64, 응답 JSON resultMap.result)
- 파일목록: /dtmk/dtmk_ntads_s002.do?dsId=11&svcCde=NA 의 표에서 dsFileId + dsFileSq 를 읽는다
- 다운로드: /dtmk/downloadDtnaResourceFile.do?ds_file_sq=<dsFileId><dsFileSq>  (로그인 세션 필요)
- 파일: AL_D171(사무소, CSV) / AL_D172(중개업자, CSV) / AL_D170(공간정보, SHP)  ※ 인코딩 cp949

사무소 CSV 컬럼:
  법정동코드, 법정동명, 등록번호, 사업자상호, 중개업자명, 상태구분코드, 상태구분명,
  등록일자, 전화번호, 보증설정시작일, 보증설정종료일, 데이터기준일자,
  지번주소, 도로명주소, 도로명주소코드
  ※ 전화번호 칸은 공개 파일에서 비어 있다(실측 10만 건 전부 공란).
"""
from __future__ import annotations

import base64
import csv
import io
import json
import os
import re
import zipfile
from datetime import date, datetime
from typing import Callable, Dict, List, Optional, Tuple

import requests

BASE = "https://www.vworld.kr"
PAGE_URL = BASE + "/dtmk/dtmk_ntads_s002.do?dsId=11&svcCde=NA"
LOGIN_URL = BASE + "/v4po_usrlogin_a004.do"
DOWN_URL = BASE + "/dtmk/downloadDtnaResourceFile.do"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

OFFICE_PREFIX = "AL_D171"
AGENT_PREFIX = "AL_D172"

SIDO_LIST = [
    "서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시", "대전광역시", "울산광역시",
    "세종특별자치시", "경기도", "강원특별자치도", "충청북도", "충청남도", "전북특별자치도",
    "전라남도", "경상북도", "경상남도", "제주특별자치도",
]

EXCEL_COLUMNS = [
    "개업일", "시도", "시군구", "사업자상호", "중개업자명", "등록번호", "상태구분명",
    "전화번호", "도로명주소", "지번주소", "법정동코드", "데이터기준일자",
]


def _log(cb: Optional[Callable[[str], None]], msg: str) -> None:
    if cb:
        cb(msg)


# ────────────────────────────────── 브이월드 접속 ──────────────────────────────────
class VworldClient:
    def __init__(self, log: Optional[Callable[[str], None]] = None):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Referer": PAGE_URL})
        self.log = log

    def login(self, uid: str, pwd: str) -> Tuple[bool, str]:
        if not uid or not pwd:
            return False, "브이월드 아이디와 비밀번호를 입력하세요."
        try:
            self.s.get(PAGE_URL, timeout=30)
            r = self.s.post(
                LOGIN_URL,
                data={
                    "usrIdeE": base64.b64encode(uid.encode("utf-8")).decode(),
                    "usrPwdE": base64.b64encode(pwd.encode("utf-8")).decode(),
                    "nextUrl": "",
                },
                headers={"X-Requested-With": "XMLHttpRequest"},
                timeout=60,
            )
            try:
                d = r.json().get("resultMap", {})
            except Exception:
                return False, f"로그인 응답을 해석하지 못했습니다 (HTTP {r.status_code})."
            if d.get("result") == "success":
                return True, "브이월드 로그인 성공"
            return False, "로그인 실패: " + str(d.get("msg") or "아이디/비밀번호를 확인하세요.")
        except Exception as e:
            return False, f"로그인 중 오류: {e}"

    def file_list(self) -> List[Dict[str, str]]:
        """다운로드 가능한 파일 목록. [{key, label, kind, size}]"""
        r = self.s.get(PAGE_URL, timeout=60)
        html = r.text
        out: List[Dict[str, str]] = []
        for m in re.finditer(r'name="dsFileId"\s+value="([^"]+)"', html):
            fid = m.group(1)
            around = html[max(0, m.start() - 2000): m.start() + 2000]
            sq = re.search(r'name="dsFileSq"\s+value="([^"]+)"', around)
            label = ""
            for cand in re.findall(r">([^<>]{4,40})<", around):
                if "중개업" in cand:
                    label = cand.strip()
                    break
            kind = "office" if "사무소" in label else ("agent" if "중개업자" in label else "etc")
            out.append({"key": fid + (sq.group(1) if sq else ""), "label": label or fid, "kind": kind})
        return out

    def download(self, key: str, dest_dir: str, log: Optional[Callable[[str], None]] = None) -> str:
        """ds_file_sq 로 내려받아 저장한 파일 경로를 돌려준다."""
        os.makedirs(dest_dir, exist_ok=True)
        with self.s.get(DOWN_URL, params={"ds_file_sq": key}, stream=True, timeout=600) as r:
            if r.status_code != 200:
                raise RuntimeError(f"다운로드 실패 (HTTP {r.status_code}) — 브이월드 로그인이 필요합니다.")
            if "text/html" in (r.headers.get("Content-Type") or ""):
                raise RuntimeError("파일 대신 웹페이지가 왔습니다 — 브이월드 로그인이 풀렸습니다. 아이디/비밀번호를 확인하세요.")
            cd = r.headers.get("Content-Disposition", "")
            name = ""
            m = re.search(r'filename="?([^";]+)"?', cd)
            if m:
                name = os.path.basename(m.group(1))
            if not name:
                name = f"vworld_{key}.zip"
            path = os.path.join(dest_dir, name)
            total = 0
            with open(path, "wb") as f:
                for chunk in r.iter_content(1024 * 256):
                    if not chunk:
                        continue
                    f.write(chunk)
                    total += len(chunk)
                    if total % (1024 * 1024 * 5) < 1024 * 256:
                        _log(log, f"  받는 중... {total // 1048576}MB")
        if total < 10240:
            os.remove(path)
            raise RuntimeError("받은 파일이 너무 작습니다 — 브이월드 로그인이 필요한 파일입니다.")
        _log(log, f"  저장: {os.path.basename(path)} ({total // 1048576}MB)")
        return path


# ────────────────────────────────── 파일 읽기 ──────────────────────────────────
def find_local_file(folder: str, prefix: str = OFFICE_PREFIX) -> Optional[str]:
    """폴더에서 가장 최신 AL_D171*.zip / *.csv 를 찾는다."""
    if not folder or not os.path.isdir(folder):
        return None
    cands = []
    for n in os.listdir(folder):
        if not n.upper().startswith(prefix):
            continue
        if n.lower().endswith((".zip", ".csv")):
            cands.append(os.path.join(folder, n))
    if not cands:
        return None
    return max(cands, key=lambda p: (os.path.getmtime(p), p))


def read_offices(path: str, log: Optional[Callable[[str], None]] = None) -> List[Dict[str, str]]:
    """AL_D171 zip 또는 csv → dict 목록."""
    if path.lower().endswith(".zip"):
        z = zipfile.ZipFile(path)
        names = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if not names:
            raise RuntimeError("압축 안에 CSV가 없습니다. 사무소정보(CSV) 파일인지 확인하세요.")
        fh = z.open(names[0])
    else:
        fh = open(path, "rb")
    rows: List[Dict[str, str]] = []
    with fh:
        txt = io.TextIOWrapper(fh, encoding="cp949", errors="replace", newline="")
        for row in csv.DictReader(txt):
            rows.append(row)
    _log(log, f"  읽음: {os.path.basename(path)} — {len(rows):,}건")
    return rows


def data_base_date(rows: List[Dict[str, str]]) -> str:
    for r in rows[:50]:
        v = (r.get("데이터기준일자") or "").strip()
        if v:
            return v
    return ""


def region_map(rows: List[Dict[str, str]]) -> Dict[str, List[str]]:
    """{시도: [시군구...]} — 법정동명 첫 두 토막으로 만든다."""
    out: Dict[str, set] = {}
    for r in rows:
        full = " ".join((r.get("법정동명") or "").split())
        if not full:
            continue
        parts = full.split(" ")
        sido = parts[0]
        gun = " ".join(parts[1:]) if len(parts) > 1 else ""
        out.setdefault(sido, set())
        if gun:
            out[sido].add(gun)
    return {k: sorted(v) for k, v in sorted(out.items())}


def split_region(name: str) -> Tuple[str, str]:
    full = " ".join((name or "").split())
    parts = full.split(" ")
    return (parts[0] if parts else "", " ".join(parts[1:]) if len(parts) > 1 else "")


# ────────────────────────────────── 신규 개업 추리기 ──────────────────────────────────
def filter_new(
    rows: List[Dict[str, str]],
    sidos: Optional[List[str]] = None,
    sigungus: Optional[List[str]] = None,
    start: Optional[date] = None,
    end: Optional[date] = None,
    only_open: bool = True,
    exclude_regnos: Optional[set] = None,
) -> List[Dict[str, str]]:
    sido_set = set(sidos or [])
    gun_set = set(sigungus or [])
    ex = exclude_regnos or set()
    out: List[Dict[str, str]] = []
    for r in rows:
        if only_open and (r.get("상태구분명") or "").strip() != "영업중":
            continue
        sido, gun = split_region(r.get("법정동명"))
        if sido_set and sido not in sido_set:
            continue
        if gun_set and gun not in gun_set:
            continue
        d = (r.get("등록일자") or "").strip()
        if len(d) != 10:
            continue
        try:
            dd = date.fromisoformat(d)
        except ValueError:
            continue
        if start and dd < start:
            continue
        if end and dd > end:
            continue
        reg = (r.get("등록번호") or "").strip()
        if reg and reg in ex:
            continue
        out.append(
            {
                "개업일": d,
                "시도": sido,
                "시군구": gun,
                "사업자상호": (r.get("사업자상호") or "").strip(),
                "중개업자명": (r.get("중개업자명") or "").strip(),
                "등록번호": reg,
                "상태구분명": (r.get("상태구분명") or "").strip(),
                "전화번호": (r.get("전화번호") or "").strip(),
                "도로명주소": " ".join((r.get("도로명주소") or "").split()),
                "지번주소": " ".join((r.get("지번주소") or "").split()),
                "법정동코드": (r.get("법정동코드") or "").strip(),
                "데이터기준일자": (r.get("데이터기준일자") or "").strip(),
            }
        )
    out.sort(key=lambda x: (x["개업일"], x["시도"], x["시군구"], x["사업자상호"]), reverse=True)
    return out


def attach_agents(rows: List[Dict[str, str]], agent_path: str, log=None) -> None:
    """중개업자 파일(AL_D172)에서 대표자 종별(공인중개사/중개인 등)을 붙인다."""
    try:
        agents = read_offices(agent_path, log)
    except Exception as e:
        _log(log, f"  중개업자 파일을 읽지 못했습니다: {e}")
        return
    by_reg: Dict[str, Dict[str, str]] = {}
    for a in agents:
        reg = (a.get("등록번호") or "").strip()
        if reg and (a.get("직위구분명") or "").strip() in ("대표", ""):
            by_reg.setdefault(reg, a)
    hit = 0
    for r in rows:
        a = by_reg.get(r["등록번호"])
        if a:
            r["종별"] = (a.get("중개업자종별명") or "").strip()
            r["자격증취득일"] = (a.get("자격증취득일") or "").strip()
            hit += 1
        else:
            r.setdefault("종별", "")
            r.setdefault("자격증취득일", "")
    _log(log, f"  중개업자 정보 연결: {hit}/{len(rows)}건")


# ────────────────────────────────── 저장 ──────────────────────────────────
def save_excel(rows: List[Dict[str, str]], path: str) -> str:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    cols = list(EXCEL_COLUMNS)
    for extra in ("종별", "자격증취득일"):
        if rows and extra in rows[0] and extra not in cols:
            cols.insert(cols.index("상태구분명") + 1, extra)

    wb = Workbook()
    ws = wb.active
    ws.title = "신규 개업"
    ws.append(cols)
    head_fill = PatternFill("solid", fgColor="1E3A5F")
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = head_fill
        c.alignment = Alignment(horizontal="center", vertical="center")
    for r in rows:
        ws.append([r.get(c, "") for c in cols])
    widths = {"개업일": 12, "시도": 12, "시군구": 12, "사업자상호": 34, "중개업자명": 11,
              "등록번호": 18, "상태구분명": 10, "종별": 12, "자격증취득일": 13, "전화번호": 14,
              "도로명주소": 46, "지번주소": 40, "법정동코드": 12, "데이터기준일자": 13}
    for i, c in enumerate(cols, start=1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = widths.get(c, 14)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    os.makedirs(os.path.dirname(path), exist_ok=True)
    wb.save(path)
    return path


# ────────────────────────────────── 이미 받은 곳 기억 ──────────────────────────────────
def load_seen(path: str) -> Dict[str, str]:
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f) or {}
    except Exception:
        pass
    return {}


def save_seen(path: str, seen: Dict[str, str]) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(seen, f, ensure_ascii=False)
    except Exception:
        pass
