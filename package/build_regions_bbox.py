"""
regions.json에서 지역 목록을 읽어 Nominatim API로 각 지역의 좌표 범위(bbox)를 조회 후
regions_bbox.json에 저장합니다.

주의: Nominatim은 1초에 1요청 제한이 있으므로 전체 regions(2700+) 처리 시 약 45분 이상 소요됩니다.
"""
import json
import os
import re
import time
from typing import Optional

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REGIONS_PATH = os.path.join(BASE_DIR, "regions.json")
OUTPUT_PATH = os.path.join(BASE_DIR, "regions_bbox.json")
OUTPUT_BROADER_PATH = os.path.join(BASE_DIR, "regions_bbox.broader.json")
OUTPUT_BROADER_V2_PATH = os.path.join(BASE_DIR, "regions_bbox.broader.v2.json")
PROXY_LIST_PATH = os.path.join(BASE_DIR, "proxy.txt")
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


def region_name_to_gu_level(region_name: str) -> str:
    """지역명에서 '동'을 제거하고 '구'(또는 '시'/'군')까지만 반환.
    예: '서울특별시 종로구 부암동' → '서울특별시 종로구'
        '경기도 성남시 분당구 정자동' → '경기도 성남시 분당구'
        '경기도 의정부시 의정부동' → '경기도 의정부시'
    """
    parts = region_name.split()
    kept = []
    for p in parts:
        if p.endswith("동"):
            break
        kept.append(p)
    return " ".join(kept) if kept else region_name


def normalize_dong_number(part: str) -> str:
    """숫자+동 → 동 변환 (가좌1동, 수내2동 → 가좌동, 수내동)"""
    return re.sub(r"\d+(?=동)", "", part)


def normalize_query(region_name: str) -> str:
    """제n동 → 동 변환 (창제1동, 창제2동 → 창제동)"""
    return re.sub(r"제\d+동", "동", region_name)


def _load_proxy_list() -> list[str]:
    """proxy_list.txt 또는 proxy.txt에서 프록시 목록 로드 (IP:PORT 형식)"""
    for path in [PROXY_LIST_PATH, os.path.join(BASE_DIR, "proxy.txt")]:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return [p.strip() for p in f if p.strip()]
    return []


def get_bbox(query: str, proxy_list: list[str] | None = None) -> dict | None:
    """지역명으로 bbox(좌표 범위) 조회. 429 시 proxy_list.txt 프록시 순회."""
    params = {
        "q": query,
        "format": "json",
        "limit": 1,
        "countrycodes": "kr",
    }
    headers = {"User-Agent": "PeterpanCrawler/1.0 (realty research)"}
    proxies_to_try = proxy_list if proxy_list is not None else _load_proxy_list()
    last_error = None

    def _request(proxies: dict | None = None) -> dict | None:
        r = requests.get(NOMINATIM_URL, headers=headers, params=params, timeout=10, proxies=proxies)
        r.raise_for_status()
        data = r.json()
        if not data:
            return None
        bb = data[0].get("boundingbox")
        if not bb or len(bb) < 4:
            return None
        print({
            "lat_min": float(bb[0]),
            "lat_max": float(bb[1]),
            "lon_min": float(bb[2]),
            "lon_max": float(bb[3]),
        })
        return {
            "lat_min": float(bb[0]),
            "lat_max": float(bb[1]),
            "lon_min": float(bb[2]),
            "lon_max": float(bb[3]),
        }

    # 프록시 없이 시도
    try:
        return _request(proxies=None)
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 429:
            last_error = e
        else:
            print(f"  실패: {query} - {e}")
            return None
    except Exception as e:
        print(f"  실패: {query} - {e}")
        return None

    # 429 → 프록시 순회
    if proxies_to_try:
        print(f"  429 발생, 프록시 {len(proxies_to_try)}개 순회")
    for proxy in proxies_to_try:
        try:
            proxy_url = f"http://{proxy}" if "://" not in proxy else proxy
            return _request(proxies={"http": proxy_url, "https": proxy_url})
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 429:
                continue
            last_error = e
        except Exception as e:
            last_error = e
    print(f"  실패: {query} - {last_error}")
    return None


def main(limit: Optional[int] = None):
    with open(REGIONS_PATH, "r", encoding="utf-8") as f:
        regions = json.load(f)
    proxy_list = _load_proxy_list()
    if proxy_list:
        print(f"프록시 {len(proxy_list)}개 로드 (429 시 사용)")

    if limit:
        regions = dict(list(regions.items())[:limit])
        print(f"(테스트: 상위 {limit}개만 처리)")

    result = {}
    total = len(regions)
    for idx, (region_name, region_id) in enumerate(regions.items(), 1):
        query = normalize_query(region_name)
        if query != region_name:
            print(f"[{idx}/{total}] {region_name} → {query}")
        else:
            print(f"[{idx}/{total}] {region_name}")
        bbox = get_bbox(query, proxy_list=proxy_list)
        if bbox:
            print(bbox)
            result[region_name] = bbox
        # time.sleep(1.1)  # Nominatim 1req/sec 제한

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n완료: {OUTPUT_PATH} ({len(result)}개 지역)")


def _is_broader_group_target(region_name: str) -> bool:
    """숫자+동, 숫자.숫자+동, 파트 4개인 경우만 True"""
    parts = region_name.split()
    if len(parts) == 4:
        return True
    if len(parts) == 3:
        last = parts[-1]
        if re.search(r"\d+동$", last):  # 가좌1동, 수내2동
            return True
        if re.search(r"\d+\.\d+", last) and last.endswith("동"):  # 종로1.2.3.4가동
            return True
        if re.search(r"제\d+동", last):  # 창신제1동
            return True
    return False


def build_broader_v2():
    """regions_bbox.json에서 숫자+동, 숫자.숫자+동, 파트 4개인 것들을 구(3파트) 수준으로 그룹핑,
    각 그룹 내 bbox의 min(lat_min), min(lon_min), max(lat_max), max(lon_max)로 범위 최대화 후
    regions_bbox.broader.v2.json에 저장. (API 호출 없음)
    """
    with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
        bbox_data = json.load(f)

    groups: dict[str, list[dict]] = {}
    for region_name, bbox in bbox_data.items():
        if not _is_broader_group_target(region_name):
            continue
        group_key = region_name_to_gu_level(region_name)
        if group_key not in groups:
            groups[group_key] = []
        groups[group_key].append(bbox)

    result = {}
    for group_key, bboxes in groups.items():
        if not bboxes:
            continue
        result[group_key] = {
            "lat_min": min(b["lat_min"] for b in bboxes),
            "lat_max": max(b["lat_max"] for b in bboxes),
            "lon_min": min(b["lon_min"] for b in bboxes),
            "lon_max": max(b["lon_max"] for b in bboxes),
        }

    with open(OUTPUT_BROADER_V2_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"완료: {OUTPUT_BROADER_V2_PATH} ({len(result)}개 그룹)")


def _merge_group_key(region_name: str) -> Optional[str]:
    """대체 대상 그룹 키 반환. None이면 대체 대상 아님.
    - 파트 4개: 구(3단계) 수준
    - 파트 3개 + 마지막이 숫자동(가좌1동 등): 숫자 제거한 형태(가좌동)
    """
    parts = region_name.split()
    if len(parts) == 4:
        return region_name_to_gu_level(region_name)
    if len(parts) == 3 and re.search(r"\d+동$", parts[-1]):
        # 인천광역시 서구 가좌1동 → 인천광역시 서구 가좌동
        prefix = " ".join(parts[:-1])
        dong_norm = normalize_dong_number(parts[-1])
        return f"{prefix} {dong_norm}"
    return None


def merge_four_part_to_gu():
    """regions_bbox.json에서 파트 4개인 지역 + 숫자동(가좌1동 등) 지역만 구/동 수준 bbox로 대체 후 결합 저장.
    - 파트 4개(예: 경기도 성남시 분당구 정자동) → 구 수준 bbox 1회 조회
    - 파트 3개+숫자동(예: 인천광역시 서구 가좌1동, 가좌2동) → 가좌동 bbox 1회 조회로 통합
    """
    with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
        bbox_data = json.load(f)

    # 대체 대상: 파트 4개 OR 파트 3개+숫자동
    keys_to_remove = set()
    keys_to_merge = []
    for k in bbox_data.keys():
        group = _merge_group_key(k)
        if group:
            keys_to_remove.add(k)
            keys_to_merge.append((k, group))

    group_names = sorted(set(g for _, g in keys_to_merge))

    if not group_names:
        print("대체 대상 지역 없음. 종료.")
        return

    proxy_list = _load_proxy_list()
    if proxy_list:
        print(f"프록시 {len(proxy_list)}개 로드 (429 시 사용)")
    print(f"대체 대상 {len(keys_to_merge)}개 제거 → 그룹 {len(group_names)}개 키로 bbox 조회")
    gu_bbox_cache = {}
    for idx, group_name in enumerate(group_names, 1):
        query = normalize_query(group_name)
        print(f"[{idx}/{len(group_names)}] {group_name}")
        bbox = get_bbox(query, proxy_list=proxy_list)
        if bbox:
            gu_bbox_cache[group_name] = bbox
        # time.sleep(1.1)

    # 기존 대체 대상 키 제거, 변환된 키로만 추가
    for k in keys_to_remove:
        del bbox_data[k]
    for group_name, bbox in gu_bbox_cache.items():
        bbox_data[group_name] = bbox

    with open(OUTPUT_BROADER_PATH, "w", encoding="utf-8") as f:
        json.dump(bbox_data, f, ensure_ascii=False, indent=2)

    print(f"\n완료: {OUTPUT_BROADER_PATH} (제거 {len(keys_to_remove)}개, 추가 {len(gu_bbox_cache)}개)")


def main_broader(limit: Optional[int] = None):
    """regions.json에서 '구'까지(3단계) 지역명만 추출해 bbox 조회 후 regions.broader.json에 저장."""
    with open(REGIONS_PATH, "r", encoding="utf-8") as f:
        regions = json.load(f)

    # 구(3단계)까지의 지역명만 중복 제거
    gu_level_names = sorted(set(region_name_to_gu_level(name) for name in regions.keys()))

    if limit:
        gu_level_names = gu_level_names[:limit]
        print(f"(테스트: 상위 {limit}개만 처리)")

    proxy_list = _load_proxy_list()
    if proxy_list:
        print(f"프록시 {len(proxy_list)}개 로드 (429 시 사용)")
    result = {}
    total = len(gu_level_names)
    for idx, region_name in enumerate(gu_level_names, 1):
        query = normalize_query(region_name)
        print(f"[{idx}/{total}] {region_name}")
        bbox = get_bbox(query, proxy_list=proxy_list)
        if bbox:
            result[region_name] = bbox
        # time.sleep(1.1)  # Nominatim 1req/sec 제한

    with open(OUTPUT_BROADER_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n완료: {OUTPUT_BROADER_PATH} ({len(result)}개 지역)")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "broader_v2":
        build_broader_v2()
    elif len(sys.argv) > 1 and sys.argv[1] == "merge":
        merge_four_part_to_gu()
    elif len(sys.argv) > 1 and sys.argv[1] == "broader":
        limit = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else None
        main_broader(limit=limit)
    elif len(sys.argv) > 1 and "get_bbox" in sys.argv[1]:
        get_bbox(sys.argv[2])
    else:
        limit = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else None
        main(limit=limit)
