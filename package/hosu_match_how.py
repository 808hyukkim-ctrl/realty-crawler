"""
건축물대장 전유공용면적 API 조회 스크립트
- API: 건축HUB 건축물대장정보 서비스 (getBrExposPubuseAreaInfo)
- 출처: https://www.data.go.kr/data/15134735/openapi.do
"""

import requests
import xml.etree.ElementTree as ET

# ============================================================
# 설정
# ============================================================
SERVICE_KEY = "318b0d0ce6832f4758bf8ed593807ba7c1c7f220ae46a757b06c3b5a66c079a0"
BASE_URL = "https://apis.data.go.kr/1613000/BldRgstHubService"


def get_building_area(sigungu_cd, bjdong_cd, bun, ji, dong_nm=None, ho_nm=None, page=1, rows=100):
    """
    건축물대장 전유공용면적 조회

    Parameters:
        sigungu_cd (str): 시군구코드 5자리 (예: "11500" = 서울 강서구)
        bjdong_cd  (str): 법정동코드 5자리 (예: "10500" = 마곡동)
        bun        (str): 본번 4자리 (예: "0750")
        ji         (str): 부번 4자리 (예: "0000")
        dong_nm    (str): 동명칭 필터 (예: "1403동"), None이면 전체
        ho_nm      (str): 호명칭 필터 (예: "601"), None이면 전체
        page       (int): 페이지 번호
        rows       (int): 페이지당 결과 수 (최대 100)

    Returns:
        list[dict]: 면적 데이터 리스트
    """
    params = {
        "serviceKey": SERVICE_KEY,
        "sigunguCd": sigungu_cd,
        "bjdongCd": bjdong_cd,
        "platGbCd": "0",       # 0=대지, 1=산
        "bun": bun,
        "ji": ji,
        "numOfRows": rows,
        "pageNo": page,
        # "_type": "json"
    }

    if dong_nm:
        params["dongNm"] = dong_nm
    if ho_nm:
        params["hoNm"] = ho_nm

    resp = requests.get(f"{BASE_URL}/getBrExposPubuseAreaInfo", params=params)
    resp.raise_for_status()
    print(resp.text)

    root = ET.fromstring(resp.text)

    result_code = root.findtext(".//resultCode", "")
    if result_code not in ("00", "000"):
        result_msg = root.findtext(".//resultMsg", "")
        raise Exception(f"API 오류: {result_code} - {result_msg}")

    with open("root.xml", "w", encoding="utf-8") as f:
        f.write(resp.text)

    total = int(root.findtext(".//totalCount", "0"))
    items = []

    for item in root.findall(".//item"):
        items.append({
            "dongNm": (item.findtext("dongNm") or "").strip(),
            "hoNm": (item.findtext("hoNm") or "").strip(),
            "flrNo": (item.findtext("flrNo") or "").strip(),
            "flrNoNm": (item.findtext("flrNoNm") or "").strip(),
            "exposPubuseGbCdNm": (item.findtext("exposPubuseGbCdNm") or "").strip(),
            "mainAtchGbCdNm": (item.findtext("mainAtchGbCdNm") or "").strip(),
            "strctCdNm": (item.findtext("strctCdNm") or "").strip(),
            "mainPurpsCdNm": (item.findtext("mainPurpsCdNm") or "").strip(),
            "etcPurps": (item.findtext("etcPurps") or "").strip(),
            "area": float(item.findtext("area") or "0"),
            "bldNm": (item.findtext("bldNm") or "").strip(),
            "platPlc": (item.findtext("platPlc") or "").strip(),
            "newPlatPlc": (item.findtext("newPlatPlc") or "").strip(),
            "bun": (item.findtext("bun") or "").strip(),
            "ji": (item.findtext("ji") or "").strip(),
            "mgmBldrgstPk": (item.findtext("mgmBldrgstPk") or "").strip(),
            "crtnDay": (item.findtext("crtnDay") or "").strip(),
            # 추가
            "sigunguCd": (item.findtext("sigunguCd") or "").strip(),
            "bjdongCd": (item.findtext("bjdongCd") or "").strip(),
            "platGbCd": (item.findtext("platGbCd") or "").strip(),
            "regstrGbCd": (item.findtext("regstrGbCd") or "").strip(),
            "regstrGbCdNm": (item.findtext("regstrGbCdNm") or "").strip(),
            "regstrKindCd": (item.findtext("regstrKindCd") or "").strip(),
            "regstrKindCdNm": (item.findtext("regstrKindCdNm") or "").strip(),
            "naRoadCd": (item.findtext("naRoadCd") or "").strip(),
            "naBjdongCd": (item.findtext("naBjdongCd") or "").strip(),
            "naUgrndCd": (item.findtext("naUgrndCd") or "").strip(),
            "naMainBun": (item.findtext("naMainBun") or "").strip(),
            "naSubBun": (item.findtext("naSubBun") or "").strip(),
            "flrGbCd": (item.findtext("flrGbCd") or "").strip(),
            "flrGbCdNm": (item.findtext("flrGbCdNm") or "").strip(),
            "exposPubuseGbCd": (item.findtext("exposPubuseGbCd") or "").strip(),
            "mainAtchGbCd": (item.findtext("mainAtchGbCd") or "").strip(),
            "strctCd": (item.findtext("strctCd") or "").strip(),
            "etcStrct": (item.findtext("etcStrct") or "").strip(),
            "mainPurpsCd": (item.findtext("mainPurpsCd") or "").strip(),
        })

    return items, total


def get_exclusive_area(sigungu_cd, bjdong_cd, bun, ji, dong_nm=None):
    """
    전유면적(전용면적)만 추출하여 동/호/면적 매핑 반환

    Returns:
        dict: {(동, 호): 전용면적} 형태
    """
    unit_map = {}
    page = 1

    while True:
        items, total = get_building_area(sigungu_cd, bjdong_cd, bun, ji, dong_nm=dong_nm, page=page)
        with open(f"hosu_match_how_{page}.json", "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=4)
        if not items:
            break

        for item in items:
            if item["exposPubuseGbCdNm"] == "전유":
                key = (item["dongNm"], item["hoNm"])
                unit_map[key] = item["area"]

        if page * 100 >= total:
            break
        page += 1

    return unit_map


# ============================================================
# 사용 예시
# ============================================================
if __name__ == "__main__":

    # ----------------------------------------------------------
    # 예시 1: 특정 세대 조회 (1403동 601호)
    # ----------------------------------------------------------
    print("=" * 70)
    print("예시 1: 전유/공용면적 상세 조회")
    print("=" * 70)

    SIGUNGU_CD = "26230"
    BJDONG_CD = "10200"
    BUN = "0908"
    JI = "0000"
    DONG_NM = "125동"

    items, total = get_building_area(
        sigungu_cd=SIGUNGU_CD,  # 서울 강서구
        bjdong_cd=BJDONG_CD,   # 마곡동
        bun=BUN,          # 본번 750
        ji=JI,           # 부번 0
        dong_nm=DONG_NM,
        # ho_nm="601",
    )

    import json
    with open("hosu_match_how.json", "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=4)

    for item in items:
        print(f"  [{item['exposPubuseGbCdNm']}] {item['flrNoNm']:>8} | "
              f"{item['etcPurps']:<30} | {item['area']:>8.2f}㎡")

    # ----------------------------------------------------------
    # 예시 2: 특정 동 전체 전용면적 조회
    # ----------------------------------------------------------
    print()
    print("=" * 70)
    print("예시 2: 전체 호별 전용면적")
    print("=" * 70)

    unit_map = get_exclusive_area(
        sigungu_cd=SIGUNGU_CD,
        bjdong_cd=BJDONG_CD,
        bun=BUN,
        ji=JI,
        dong_nm=DONG_NM,
    )
    print(unit_map)

    from collections import defaultdict
    by_floor = defaultdict(list)
    for (dong, ho), area in sorted(unit_map.items()):

        if "B" in ho:
            continue 

        ho = ho.replace("호","")
        floor = int(ho) // 100 if int(ho) >= 100 else 1
        by_floor[floor].append((ho, area))

    # for floor in sorted(by_floor.keys()):
    #     units = sorted(by_floor[floor])
    #     line = ", ".join(f"{ho}호({area}㎡)" for ho, area in units)
        # print(f"  {floor:>2}층: {line}")

    # ----------------------------------------------------------
    # 예시 3: 실거래가 매칭
    # ----------------------------------------------------------
    print()
    print("=" * 70)
    print("예시 3: 실거래가 → 호수 특정")
    print("=" * 70)

    # 실거래 데이터 (국토부 API에서 가져온 것)
    trade = {"dong": "", "floor": 3, "area": 28.56}
    print(f"  실거래: {trade['dong']}동 {trade['floor']}층 {trade['area']}㎡")

    # 해당 동+층에서 같은 면적 찾기
    candidates = [
        (ho, area) for (dong, ho), area in unit_map.items()
        if int(ho.replace("호","")) // 100 == trade["floor"]  # 같은 층
        and abs(area - trade["area"]) < 0.01  # 같은 면적
    ]

    if len(candidates) == 1:
        print(f"  → ✅ 확정: {candidates[0][0]}호")
    else:
        print(f"  → ⚠️ {len(candidates)}개 후보: {', '.join(h for h, _ in candidates)}호")
