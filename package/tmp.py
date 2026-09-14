import json
import os
from typing import Dict, Any

import requests


# 국토교통부 건축HUB 건축물대장정보 서비스
# https://www.data.go.kr/data/15134735/openapi.do#/API%20%EB%AA%A9%EB%A1%9D/getBrTitleInfo
BASE_URL = "https://apis.data.go.kr/1613000/BldRgstHubService"
SERVICE_KEY = os.getenv(
    "BLDRGST_SERVICE_KEY",
    "318b0d0ce6832f4758bf8ed593807ba7c1c7f220ae46a757b06c3b5a66c079a0",
)

# 테스트 기본 파라미터(개포동 예시)
COMMON_PARAMS: Dict[str, Any] = {
    "serviceKey": SERVICE_KEY,
    "sigunguCd": "11680",  # 강남구
    "bjdongCd": "10300",   # 개포동
    "platGbCd": "0",       # 0=대지, 1=산
    "bun": "1172",
    "ji": "0003",
    "numOfRows": 100,
    "pageNo": 1,
    "_type": "json",
}

# 데이터포털 설명의 상세기능 기준 주요 API 목록
API_ENDPOINTS = [
    "getBrBasisOulnInfo",        # 기본개요
    "getBrRecapTitleInfo",       # 총괄표제부
    "getBrTitleInfo",            # 표제부
    "getBrFlrOulnInfo",          # 층별개요
    "getBrAtchJibunInfo",        # 부속지번
    "getBrExposPubuseAreaInfo",  # 전유공용면적
    "getBrWclfInfo",             # 오수정화시설
    "getBrHsprcInfo",            # 주택가격
    "getBrExposInfo",            # 전유부
    "getBrJijiguInfo",           # 지역지구구역
]


def call_api(endpoint: str) -> Dict[str, Any]:
    url = f"{BASE_URL}/{endpoint}"
    res = requests.get(url, params=COMMON_PARAMS, timeout=30)
    print("=" * 88)
    print(f"[{endpoint}]")
    print(f"- status_code: {res.status_code}")

    text_preview = (res.text or "")[:300].replace("\n", " ").replace("\r", " ")
    print(f"- response_preview: {text_preview}")

    try:
        data = res.json()
    except Exception:
        print("- json_parse: FAIL")
        return {"_raw_text": res.text, "_status_code": res.status_code}

    result_code = (
        data.get("response", {})
        .get("header", {})
        .get("resultCode")
    )
    result_msg = (
        data.get("response", {})
        .get("header", {})
        .get("resultMsg")
    )
    total_count = (
        data.get("response", {})
        .get("body", {})
        .get("totalCount")
    )
    print(f"- resultCode/resultMsg: {result_code} / {result_msg}")
    print(f"- totalCount: {total_count}")
    return data


def main() -> None:
    output_dir = "tmp_bldrgst_api_json"
    os.makedirs(output_dir, exist_ok=True)

    all_results: Dict[str, Any] = {}
    for endpoint in API_ENDPOINTS:
        data = call_api(endpoint)
        all_results[endpoint] = data

        path = os.path.join(output_dir, f"{endpoint}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"- saved: {path}")

    merged_path = os.path.join(output_dir, "all_endpoints.json")
    with open(merged_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print("=" * 88)
    print(f"모든 API 결과 저장 완료: {merged_path}")


if __name__ == "__main__":
    main()