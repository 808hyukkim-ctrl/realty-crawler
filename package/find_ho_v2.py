"""
네이버 부동산 → 호수 특정 v2
- requests 사용 (curl 제거)
- 건축물대장 병렬 조회 + 3회 재시도
- 국토부 주소 검색 병렬화
- 데이터 무결성 검증
"""

import requests
import xml.etree.ElementTree as ET
import urllib.parse
import re
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from collections import defaultdict

SERVICE_KEY = "318b0d0ce6832f4758bf8ed593807ba7c1c7f220ae46a757b06c3b5a66c079a0"
ENCODED_KEY = urllib.parse.quote(SERVICE_KEY, safe="")
NAVER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
    "Referer": "https://m.land.naver.com/",
}
SEOUL_SGG = [
    "11110","11140","11170","11200","11215","11230","11260","11290","11305","11320",
    "11350","11380","11410","11440","11470","11500","11530","11545","11560","11590",
    "11620","11650","11680","11710","11740",
]


def _normalize(s):
    return re.sub(r'[\s\(\)（）]', '', s).replace('벨리','밸리').lower()


def _xml_get(url, retries=3):
    """XML API 호출 (재시도 포함)"""
    for i in range(retries):
        try:
            resp = requests.get(url, timeout=15)
            if resp.status_code == 200 and len(resp.text) > 100:
                return ET.fromstring(resp.text)
        except Exception:
            pass
        if i < retries - 1:
            time.sleep(1)
    return None


# ── 네이버 ──

def naver_get_listings(complex_id, trade_type="A1"):
    items = []
    for page in range(1, 10):
        url = (f"https://m.land.naver.com/complex/getComplexArticleList"
               f"?hscpNo={complex_id}&tradTpCd={trade_type}&order=point_&showR0=N&page={page}")
        try:
            data = requests.get(url, headers=NAVER_HEADERS, timeout=10).json()
            if not isinstance(data, dict): break
            lst = data.get("result", {}).get("list", [])
            if not lst: break
            items.extend(lst)
            time.sleep(0.3)
        except Exception:
            break
    return [{"atclNo": i.get("atclNo",""), "aptNm": i.get("atclNm",""),
             "dongNm": i.get("bildNm",""), "flrInfo": i.get("flrInfo",""),
             "spc2": i.get("spc2",""), "prcInfo": i.get("prcInfo",""),
             "direction": i.get("direction",""), "desc": i.get("atclFetrDesc","")}
            for i in items]


def naver_get_complex_info(complex_id):
    """네이버 API에서 단지 주소 정보 조회 (세션 + 브라우저 헤더)"""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9",
    })
    try:
        # 페이지 방문으로 쿠키 획득
        session.get(f"https://new.land.naver.com/complexes/{complex_id}?ms=37.5,127.0,16&a=APT&b=A1", timeout=5)
        time.sleep(0.5)
        # API 호출 (브라우저 동작 모방)
        resp = session.get(f"https://new.land.naver.com/api/complexes/{complex_id}", headers={
            "Accept": "application/json",
            "Referer": f"https://new.land.naver.com/complexes/{complex_id}?ms=37.5,127.0,16&a=APT&b=A1",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }, timeout=10)
        data = resp.json()
        if data.get("success") is False: return None
        d = data.get("complexDetail", {})
        address, cortarNo = d.get("address",""), d.get("cortarNo","")
        bun, ji = "", "0000"
        for part in address.split():
            if part.replace("-","").isdigit():
                if "-" in part:
                    b, j = part.split("-",1); bun, ji = b.zfill(4), j.zfill(4)
                else:
                    bun, ji = part.zfill(4), "0000"
                break
        return {"name": d.get("complexName",""), "address": address,
                "sigunguCd": cortarNo[:5], "bjdongCd": cortarNo[5:10], "bun": bun, "ji": ji}
    except Exception:
        return None


# ── 국토부 (병렬 주소 검색) ──

def _search_sgg(sgg, apt_name, months):
    n = _normalize(apt_name)
    for ym in months:
        root = _xml_get(f"https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev"
                        f"/getRTMSDataSvcAptTradeDev?serviceKey={ENCODED_KEY}"
                        f"&LAWD_CD={sgg}&DEAL_YMD={ym}&pageNo=1&numOfRows=500", retries=1)
        if root is None: continue
        for item in root.findall(".//item"):
            apt = (item.findtext("aptNm") or "").strip()
            na = _normalize(apt)
            if n and (na in n or n in na):
                return {"aptNm": apt,
                    "sigunguCd": (item.findtext("sggCd") or "").strip(),
                    "bjdongCd": (item.findtext("umdCd") or "").strip(),
                    "bun": (item.findtext("bonbun") or "").strip(),
                    "ji": (item.findtext("bubun") or "").strip(),
                    "umdNm": (item.findtext("umdNm") or "").strip(),
                    "jibun": (item.findtext("jibun") or "").strip()}
    return None


def molit_find_address(apt_name):
    months = [(datetime.now() - timedelta(days=30*i)).strftime("%Y%m") for i in range(4)]
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(_search_sgg, sgg, apt_name, months): sgg for sgg in SEOUL_SGG}
        for f in as_completed(futures):
            r = f.result()
            if r:
                for remaining in futures: remaining.cancel()
                return r
    return None


def molit_get_trades(sigungu_cd, apt_filter, months=None):
    if months is None:
        months = [(datetime.now() - timedelta(days=30*i)).strftime("%Y%m") for i in range(12)]
    nf = _normalize(apt_filter) if apt_filter else None
    trades = []
    for ym in months:
        page = 1
        while True:
            root = _xml_get(f"https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev"
                           f"/getRTMSDataSvcAptTradeDev?serviceKey={ENCODED_KEY}"
                           f"&LAWD_CD={sigungu_cd}&DEAL_YMD={ym}&pageNo={page}&numOfRows=500")
            if root is None: break
            items = root.findall(".//item")
            if not items: break
            total = int(root.findtext(".//totalCount","0"))
            for item in items:
                apt = (item.findtext("aptNm") or "").strip()
                if nf and nf not in _normalize(apt) and _normalize(apt) not in nf: continue
                if (item.findtext("cdealType") or "").strip() == "O": continue
                dong = (item.findtext("aptDong") or "").strip()
                if not dong: continue
                trades.append({"aptNm": apt, "dong": dong,
                    "floor": (item.findtext("floor") or "").strip(),
                    "area": (item.findtext("excluUseAr") or "").strip(),
                    "price": (item.findtext("dealAmount") or "").strip(),
                    "year": (item.findtext("dealYear") or "").strip(),
                    "month": (item.findtext("dealMonth") or "").strip(),
                    "day": (item.findtext("dealDay") or "").strip()})
            if page * 500 >= total: break
            page += 1
        time.sleep(0.2)
    return trades


# ── 건축물대장 (병렬 + 재시도 + 검증) ──

def _fetch_area_page(sigungu_cd, bjdong_cd, bun, ji, page):
    """1페이지 조회 (3회 재시도)"""
    url = (f"https://apis.data.go.kr/1613000/BldRgstHubService/getBrExposPubuseAreaInfo"
           f"?serviceKey={SERVICE_KEY}&sigunguCd={sigungu_cd}&bjdongCd={bjdong_cd}"
           f"&platGbCd=0&bun={bun}&ji={ji}&numOfRows=100&pageNo={page}")
    return _xml_get(url, retries=3)


def building_get_unit_areas(sigungu_cd, bjdong_cd, bun, ji):
    """건축물대장 전유면적 조회 (병렬 + 무결성 검증)"""
    # 1) 첫 페이지로 전체 건수 확인
    root = _fetch_area_page(sigungu_cd, bjdong_cd, bun, ji, 1)
    if root is None: return {}
    total = int(root.findtext(".//totalCount", "0"))
    total_pages = (total + 99) // 100

    # 2) 첫 페이지 파싱
    all_items_by_page = {1: root.findall(".//item")}

    # 3) 나머지 페이지 병렬 조회
    if total_pages > 1:
        with ThreadPoolExecutor(max_workers=10) as ex:
            futures = {ex.submit(_fetch_area_page, sigungu_cd, bjdong_cd, bun, ji, p): p
                       for p in range(2, total_pages + 1)}
            for f in as_completed(futures):
                p = futures[f]
                r = f.result()
                if r is not None:
                    all_items_by_page[p] = r.findall(".//item")

    # 4) 누락 페이지 재시도
    for p in range(1, total_pages + 1):
        if p not in all_items_by_page:
            print(f"    ⚠️ page {p} 재시도...")
            r = _fetch_area_page(sigungu_cd, bjdong_cd, bun, ji, p)
            if r is not None:
                all_items_by_page[p] = r.findall(".//item")

    # 5) 전유면적만 추출
    unit_map = {}
    total_parsed = 0
    for p in sorted(all_items_by_page):
        for item in all_items_by_page[p]:
            total_parsed += 1
            if (item.findtext("exposPubuseGbCdNm") or "").strip() == "전유":
                dong = (item.findtext("dongNm") or "").strip()
                ho = (item.findtext("hoNm") or "").strip()
                area = float(item.findtext("area") or "0")
                if dong and ho:
                    unit_map[(dong, ho)] = area

    # 6) 무결성 검증
    fetched_pages = len(all_items_by_page)
    if fetched_pages < total_pages:
        print(f"    ⚠️ {total_pages}페이지 중 {fetched_pages}페이지만 수집 ({total_pages - fetched_pages}페이지 누락)")

    return unit_map


# ── 매칭 ──

def match_to_unit(dong, floor, area, unit_map):
    dong_key = dong if "동" in dong else dong + "동"
    try: floor_int = int(floor)
    except (ValueError, TypeError): return None, []
    try: area_float = float(area)
    except (ValueError, TypeError): return None, []
    candidates = []
    for (d, ho), a in unit_map.items():
        if d != dong_key or abs(a - area_float) > 0.01: continue
        try: ho_floor = int(ho) // 100 if int(ho) >= 100 else 1
        except ValueError: continue
        if ho_floor == floor_int: candidates.append((ho, a))
    if len(candidates) == 1: return candidates[0][0], candidates
    return None, candidates


def parse_naver_floor(flr_info):
    if "/" in flr_info:
        f = flr_info.split("/")[0]
        if f.isdigit(): return int(f)
    if flr_info.isdigit(): return int(flr_info)
    return None


def format_price(price_str):
    try:
        p = int(price_str.replace(",",""))
        if p >= 10000:
            r = p % 10000
            return f"{p//10000}억{f' {r:,}' if r else ''}"
        return f"{p:,}"
    except (ValueError, AttributeError):
        return price_str


# ── 메인 ──

def find_ho(naver_input, trade_type="A1"):
    start = time.time()
    raw = str(naver_input).strip().strip('"').strip("'")
    m = re.search(r'articleNo=(\d+)', raw)
    complex_id = m.group(1) if m else raw
    trade_name = {"A1":"매매","B1":"전세","B2":"월세"}.get(trade_type, trade_type)

    print(f"\n{'━'*70}")
    print(f"  네이버 부동산 호수 특정 (단지 {complex_id}, {trade_name})")
    print(f"{'━'*70}")

    # 1. 매물
    t0 = time.time()
    listings = naver_get_listings(complex_id, trade_type)
    if not listings:
        print("  ❌ 매물 없음 — 단지ID를 확인해주세요."); return None
    apt_name = listings[0]["aptNm"]
    print(f"  📍 {apt_name} | {trade_name} {len(listings)}건 ({time.time()-t0:.1f}s)")

    # 2. 주소
    t0 = time.time()
    info = naver_get_complex_info(complex_id)
    if info and info.get("bun"):
        sigungu_cd, bjdong_cd, bun, ji = info["sigunguCd"], info["bjdongCd"], info["bun"], info["ji"]
        src = "네이버"
    else:
        molit = molit_find_address(apt_name)
        if not molit:
            print("  ❌ 주소를 찾을 수 없습니다."); return None
        sigungu_cd, bjdong_cd, bun, ji = molit["sigunguCd"], molit["bjdongCd"], molit["bun"], molit["ji"]
        src = "국토부"
    print(f"  📍 주소: {sigungu_cd}-{bjdong_cd} {bun}-{ji} ({src}, {time.time()-t0:.1f}s)")

    # 3. 건축물대장
    t0 = time.time()
    unit_map = building_get_unit_areas(sigungu_cd, bjdong_cd, bun, ji)
    dong_counts = defaultdict(int)
    for d, _ in unit_map: dong_counts[d] += 1
    print(f"  📍 건축물대장: {len(unit_map)}세대, {len(dong_counts)}개동 ({time.time()-t0:.1f}s)")
    if not unit_map:
        print("  ❌ 건축물대장 데이터 없음"); return None

    # 4. 매물 매칭
    print(f"\n{'━'*70}")
    print(f"  📌 현재 매물 호수 특정 ({len(listings)}건)")
    print(f"{'━'*70}")
    results = []
    s = {"confirmed":0, "narrowed":0, "unknown":0}
    for li in listings:
        floor = parse_naver_floor(li["flrInfo"])
        if floor is not None:
            ho, cands = match_to_unit(li["dongNm"], str(floor), li["spc2"], unit_map)
        else:
            ho, cands = None, []
        if ho:          mark = f"✅ {ho}호"; s["confirmed"] += 1
        elif cands:     mark = f"⚠️ {' / '.join(h+'호' for h,_ in cands)}"; s["narrowed"] += 1
        elif floor is None: mark = "🔍 층수 미상"; s["unknown"] += 1
        else:           mark = "❌ 매칭 실패"; s["unknown"] += 1
        results.append({**li, "ho": ho, "candidates": cands, "mark": mark})
        print(f"  {li['dongNm']} {li['flrInfo']}층 | {li['spc2']}㎡ | {li['prcInfo']}  →  {mark}")

    # 5. 실거래가 매칭
    t0 = time.time()
    trades = molit_get_trades(sigungu_cd, apt_name)
    tc = 0
    print(f"\n{'━'*70}")
    print(f"  📌 실거래가 호수 특정 ({len(trades)}건, 최근 1년, {time.time()-t0:.1f}s)")
    print(f"{'━'*70}")
    for t in trades:
        ho, cands = match_to_unit(t["dong"], t["floor"], t["area"], unit_map)
        price = format_price(t["price"])
        date = f"{t['year']}.{t['month'].zfill(2)}.{t['day'].zfill(2)}"
        if ho:      mark = f"✅ {ho}호"; tc += 1
        elif cands: mark = f"⚠️ {' / '.join(h+'호' for h,_ in cands)}"
        else:       mark = "❌"
        print(f"  {date} | {t['dong']}동 {t['floor']}층 | {t['area']}㎡ | {price}만원  →  {mark}")

    elapsed = time.time() - start
    print(f"\n{'━'*70}")
    print(f"  매물: ✅{s['confirmed']} ⚠️{s['narrowed']} 🔍{s['unknown']}")
    print(f"  실거래: {len(trades)}건 중 ✅{tc}건 확정")
    print(f"  소요시간: {elapsed:.1f}초")
    print(f"{'━'*70}\n")
    return results


if __name__ == "__main__":
    import sys
    # cid = sys.argv[1] if len(sys.argv) > 1 else "107504"
    cid = "https://new.land.naver.com/houses?articleNo=2614788864"
    tt = sys.argv[2] if len(sys.argv) > 2 else "A1"
    find_ho(cid, tt)
