"""
모든 동 단위 지역(naver_rls.json)을 순회하면서 네이버 매물 검색 결과를 수집하고,
각 결과의 지번/동 기준으로 건축물대장 전유공용면적 API 응답을 JSONL로 누적 저장한다.

출력(JSONL) 1줄 = 매물 1건 처리 결과
"""

import argparse
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, TextIO, Tuple

import requests

from naver_crawler import NaverCrawler, _load_rls_file, find_key_in_nested_dict


ALL_REALESTATE_TYPES = (
    "JGC:IA01:IA02:IC01:IC02:IA04:IC03:"
    "OBYG:APT:ABYG:JGB:OPST:VL:DDDGG:JWJT:SGJT:HOJT:OR:SG:SMS:GJCG:APTHGJ:GM:TJ"
)
ALL_TRADE_TYPES = "A1:B1:B2"
BLDRGST_URL = "https://apis.data.go.kr/1613000/BldRgstHubService/getBrExposPubuseAreaInfo"


def iter_rls_dong_units(rls: Dict[str, Any]) -> Iterable[Tuple[str, str, str, str]]:
    for si, gu_map in (rls or {}).items():
        if not isinstance(gu_map, dict):
            continue
        for gu, dong_map in gu_map.items():
            if not isinstance(dong_map, dict):
                continue
            for dong, cortar_no in dong_map.items():
                cortar = str(cortar_no or "").strip()
                if cortar and cortar.isdigit() and len(cortar) >= 10:
                    yield si, gu, dong, cortar


def parse_bun_ji_from_jibun(text: Any) -> Optional[Tuple[str, str]]:
    raw = str(text or "").strip()
    if not raw:
        return None
    matches = re.findall(r"(\d+)(?:-(\d+))?", raw)
    if not matches:
        return None
    bun_raw, ji_raw = matches[-1]
    return bun_raw.zfill(4), (ji_raw or "0").zfill(4)


def normalize_dong_name(dong: Any) -> Optional[str]:
    txt = str(dong or "").strip()
    if not txt:
        return None
    m = re.search(r"(\d+)\s*동", txt)
    if m:
        return f"{m.group(1)}동"
    m = re.search(r"(\d+)", txt)
    if m:
        return f"{m.group(1)}동"
    return txt if txt.endswith("동") else None


def parse_cortar_no(cortar_no: Any) -> Optional[Tuple[str, str]]:
    cortar = str(cortar_no or "").strip()
    if not (cortar.isdigit() and len(cortar) >= 10):
        return None
    return cortar[:5], cortar[5:10]


def parse_items_from_xml(xml_text: str) -> Tuple[List[Dict[str, Any]], int, str, str]:
    root = ET.fromstring(xml_text)
    result_code = root.findtext(".//resultCode", "") or ""
    result_msg = root.findtext(".//resultMsg", "") or ""
    total = int(root.findtext(".//totalCount", "0") or 0)
    items: List[Dict[str, Any]] = []
    for item in root.findall(".//item"):
        items.append({
            "dongNm": (item.findtext("dongNm") or "").strip(),
            "hoNm": (item.findtext("hoNm") or "").strip(),
            "flrNo": (item.findtext("flrNo") or "").strip(),
            "flrNoNm": (item.findtext("flrNoNm") or "").strip(),
            "exposPubuseGbCdNm": (item.findtext("exposPubuseGbCdNm") or "").strip(),
            "area": float(item.findtext("area") or "0"),
            "bldNm": (item.findtext("bldNm") or "").strip(),
            "platPlc": (item.findtext("platPlc") or "").strip(),
            "newPlatPlc": (item.findtext("newPlatPlc") or "").strip(),
            "bun": (item.findtext("bun") or "").strip(),
            "ji": (item.findtext("ji") or "").strip(),
            "naRoadCd": (item.findtext("naRoadCd") or "").strip(),
            "naBjdongCd": (item.findtext("naBjdongCd") or "").strip()
        })
    return items, total, result_code.strip(), result_msg.strip()


def request_bldrgst_all_pages(
    service_key: str,
    sigungu_cd: str,
    bjdong_cd: str,
    bun: str,
    ji: str,
    dong_nm: Optional[str],
    timeout: int = 20,
    max_attempts: int = 3,
) -> Dict[str, Any]:
    all_items: List[Dict[str, Any]] = []
    page = 1
    total = None
    while True:
        params = {
            "serviceKey": service_key,
            "sigunguCd": sigungu_cd,
            "bjdongCd": bjdong_cd,
            "platGbCd": "0",
            "bun": bun,
            "ji": ji,
            "numOfRows": 100,
            "pageNo": page,
            "_type": "json"
        }
        if dong_nm:
            params["dongNm"] = dong_nm

        last_error = None
        xml_text = None
        for attempt in range(1, max_attempts + 1):
            try:
                resp = requests.get(BLDRGST_URL, params=params, timeout=timeout)
                if resp.status_code == 200 and (resp.text or "").strip():
                    xml_text = resp.text
                    break
                last_error = f"HTTP {resp.status_code}"
            except Exception as e:  # noqa: BLE001
                last_error = str(e)
            time.sleep(0.8 * (2 ** (attempt - 1)))

        if not xml_text:
            return {
                "ok": False,
                "error": f"건축물대장 API 요청 실패(page={page}): {last_error}",
                "total": total or 0,
                "items": all_items,
                "pages": page - 1,
            }

        try:
            page_items, page_total, result_code, result_msg = parse_items_from_xml(xml_text)
        except Exception as e:  # noqa: BLE001
            return {
                "ok": False,
                "error": f"XML 파싱 실패(page={page}): {e}",
                "total": total or 0,
                "items": all_items,
                "pages": page - 1,
            }

        if result_code and result_code not in ("00", "000"):
            return {
                "ok": False,
                "error": f"API 오류(page={page}): {result_code} - {result_msg}",
                "total": total or 0,
                "items": all_items,
                "pages": page - 1,
            }

        if total is None:
            total = page_total
        if not page_items:
            break

        all_items.extend(page_items)
        if total is not None and page * 100 >= total:
            break
        page += 1

    return {
        "ok": True,
        "error": None,
        "total": total or 0,
        "items": all_items,
        "pages": page,
    }


def load_seen_article_numbers(out_path: str) -> Set[str]:
    seen: Set[str] = set()
    for path in list_output_shard_paths(out_path):
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                article_no = str(obj.get("articleNo") or "").strip()
                if article_no:
                    seen.add(article_no)
    return seen


def list_output_shard_paths(base_path: str) -> List[str]:
    directory = os.path.dirname(base_path) or "."
    base_name = os.path.basename(base_path)
    stem, ext = os.path.splitext(base_name)
    pattern = re.compile(rf"^{re.escape(stem)}_(\d{{4}}){re.escape(ext)}$")
    paths = []
    base_abs = os.path.abspath(base_path)
    if os.path.exists(base_abs):
        paths.append(base_abs)
    try:
        names = os.listdir(directory)
    except Exception:
        names = []
    indexed = []
    for name in names:
        m = pattern.match(name)
        if not m:
            continue
        idx = int(m.group(1))
        indexed.append((idx, os.path.abspath(os.path.join(directory, name))))
    indexed.sort(key=lambda x: x[0])
    paths.extend([p for _, p in indexed])
    return paths


def next_shard_path(base_path: str) -> str:
    directory = os.path.dirname(base_path) or "."
    base_name = os.path.basename(base_path)
    stem, ext = os.path.splitext(base_name)
    pattern = re.compile(rf"^{re.escape(stem)}_(\d{{4}}){re.escape(ext)}$")
    max_idx = 0
    try:
        names = os.listdir(directory)
    except Exception:
        names = []
    for name in names:
        m = pattern.match(name)
        if not m:
            continue
        max_idx = max(max_idx, int(m.group(1)))
    if os.path.exists(base_path):
        max_idx = max(max_idx, 0)
    next_idx = max_idx + 1
    return os.path.abspath(os.path.join(directory, f"{stem}_{next_idx:04d}{ext}"))


def rotate_if_needed(
    out_f: TextIO,
    current_path: str,
    base_out_path: str,
    incoming_line: str,
    max_file_bytes: int,
    log: Optional[Callable[[str], None]] = None,
) -> Tuple[TextIO, str]:
    if max_file_bytes <= 0:
        return out_f, current_path
    incoming_size = len(incoming_line.encode("utf-8"))
    current_size = os.path.getsize(current_path) if os.path.exists(current_path) else 0
    if current_size + incoming_size <= max_file_bytes:
        return out_f, current_path
    out_f.close()
    rotated_path = next_shard_path(base_out_path)
    new_f = open(rotated_path, "a", encoding="utf-8")
    msg = f"[ROTATE] {current_path} -> {rotated_path}"
    if log:
        log(msg)
    else:
        print(msg)
    return new_f, rotated_path


def main() -> None:
    parser = argparse.ArgumentParser(description="네이버 매물 -> 건축물대장 응답 JSONL 수집기")
    parser.add_argument("--rls", default="naver_rls.json", help="동 단위 지역 코드 파일 경로")
    parser.add_argument("--out", default="bldrgst_by_article.jsonl", help="출력 JSONL 파일명")
    parser.add_argument("--out-dir", default="bldrgst_jsonl_out", help="JSONL/로그 저장 폴더")
    parser.add_argument("--service-key", default=os.getenv("BLDRGST_SERVICE_KEY", ""), help="건축물대장 API 서비스키")
    parser.add_argument("--max-regions", type=int, default=0, help="테스트용: 처리할 동 개수 제한(0=전체)")
    parser.add_argument("--sleep", type=float, default=0.05, help="상세 API 호출 간격(초)")
    parser.add_argument("--resume", action="store_true", help="기존 출력 파일이 있으면 articleNo 기준 이어서 수집")
    parser.add_argument(
        "--max-file-mb",
        type=int,
        default=200,
        help="JSONL 파일 최대 용량(MB). 초과 시 _0001, _0002... 파일로 자동 분할",
    )
    parser.add_argument(
        "--log-file",
        default="collect_bldrgst.log",
        help="텍스트 로그 파일명(출력 폴더 기준)",
    )
    args = parser.parse_args()

    service_key = (args.service_key or "").strip()
    if not service_key:
        # 기존 코드와 동일한 기본키 fallback
        service_key = "318b0d0ce6832f4758bf8ed593807ba7c1c7f220ae46a757b06c3b5a66c079a0"

    rls = _load_rls_file(args.rls)
    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)
    log_path = os.path.join(out_dir, args.log_file)

    def log(msg: str) -> None:
        line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
        print(line)
        with open(log_path, "a", encoding="utf-8") as lf:
            lf.write(line + "\n")

    dong_units = list(iter_rls_dong_units(rls))
    if args.max_regions > 0:
        dong_units = dong_units[: args.max_regions]

    base_out_path = os.path.join(out_dir, args.out)
    seen_article_nos: Set[str] = load_seen_article_numbers(base_out_path) if args.resume else set()
    request_cache: Dict[Tuple[str, str, str, str, str], Dict[str, Any]] = {}

    crawler = NaverCrawler(on_log=lambda _msg: None)

    region_count = len(dong_units)
    processed_articles = 0
    saved_lines = 0
    ok_count = 0
    fail_count = 0
    parse_fail_count = 0
    req_fail_count = 0
    article_fail_count = 0
    started_at = datetime.now().isoformat(timespec="seconds")
    start_ts = time.time()
    log(f"[START] regions={region_count}, resume_seen={len(seen_article_nos)}, started_at={started_at}, out_dir={out_dir}")
    max_file_bytes = max(0, int(args.max_file_mb)) * 1024 * 1024
    current_out_path = base_out_path

    with open(current_out_path, "a", encoding="utf-8") as out_f:
        for idx, (si, gu, dong, cortar_no) in enumerate(dong_units, 1):
            region_start = time.time()
            try:
                cls = crawler.get_cls(
                    si,
                    gu,
                    dong,
                    cortar_no,
                    realestate_type=ALL_REALESTATE_TYPES,
                    trade_type=ALL_TRADE_TYPES,
                )
            except Exception as e:  # noqa: BLE001
                log(f"[REGION FAIL] {idx}/{region_count} {si} {gu} {dong}({cortar_no}) -> {e}")
                continue

            elapsed_all = time.time() - start_ts
            elapsed_region = time.time() - region_start
            done_ratio = (idx / region_count * 100.0) if region_count else 100.0
            speed = (saved_lines / elapsed_all) if elapsed_all > 0 else 0.0
            log(
                f"[REGION] {idx}/{region_count} ({done_ratio:.1f}%) {si} {gu} {dong}({cortar_no}) "
                f"results={len(cls)} | elapsed_region={elapsed_region:.1f}s elapsed_total={elapsed_all:.1f}s "
                f"saved={saved_lines} ok={ok_count} fail={fail_count} cache={len(request_cache)} rate={speed:.2f}rows/s"
            )
            for c in cls:
                article_no = str(c.get("complex_no") or "").strip()
                if not article_no or not article_no.isdigit():
                    continue
                if article_no in seen_article_nos:
                    continue

                processed_articles += 1
                row: Dict[str, Any] = {
                    "ts": datetime.now().isoformat(timespec="seconds"),
                    "region": {"si": si, "gu": gu, "dong": dong, "cortarNo": cortar_no},
                    "articleNo": article_no,
                    "realestateTypeName": c.get("realestate_type_name"),
                    "realestateTypeCode": c.get("realestate_type"),
                }
                try:
                    c_info_url = f"https://new.land.naver.com/api/articles/{article_no}?complexNo="
                    c_info_res = crawler.sess.get(c_info_url, impersonate="chrome", timeout=crawler.timeout_sec)
                    c_info = c_info_res.json()
                    article_detail = c_info.get("articleDetail") or {}

                    detail_dong = article_detail.get("buildingName") or dong
                    sojaeji = article_detail.get("exposureAddress") or ""
                    detail_addr = ""
                    hscp_no = article_detail.get("hscpNo") or ""
                    if hscp_no:
                        try:
                            detail_addr_url = f"https://new.land.naver.com/api/complexes/{hscp_no}?sameAddressGroup=false"
                            detail_addr_res = crawler.sess.get(detail_addr_url, impersonate="chrome", timeout=crawler.timeout_sec)
                            if detail_addr_res.status_code == 200:
                                c_detail = detail_addr_res.json().get("complexDetail") or {}
                                if c_detail:
                                    detail_addr = (
                                        f'{str(c_detail.get("address", "")).split(" ")[-1]} '
                                        f'{c_detail.get("detailAddress", "")}'
                                    ).strip()
                        except Exception:
                            pass
                    cortar_detail = find_key_in_nested_dict(c_info, "cortarNo") or cortar_no
                    parsed_cortar = parse_cortar_no(cortar_detail)
                    bunji = parse_bun_ji_from_jibun(sojaeji)
                    bunji_source = "sojaeji"
                    if not bunji:
                        bunji = parse_bun_ji_from_jibun(detail_addr)
                        bunji_source = "detail_addr"
                    norm_dong = normalize_dong_name(detail_dong)

                    row["detail"] = {
                        "dong": detail_dong,
                        "sojaeji": sojaeji,
                        "detailAddr": detail_addr,
                        "cortarNo": str(cortar_detail),
                        "bunjiSource": bunji_source,
                        "dongNmForApi": norm_dong,
                    }

                    if not parsed_cortar:
                        row["ok"] = False
                        row["error"] = "cortarNo 파싱 실패"
                    elif not bunji:
                        row["ok"] = False
                        row["error"] = "지번 파싱 실패"
                    else:
                        sigungu_cd, bjdong_cd = parsed_cortar
                        bun, ji = bunji
                        cache_key = (sigungu_cd, bjdong_cd, bun, ji, norm_dong or "")
                        if cache_key in request_cache:
                            bld_result = request_cache[cache_key]
                            row["fromCache"] = True
                        else:
                            bld_result = request_bldrgst_all_pages(
                                service_key=service_key,
                                sigungu_cd=sigungu_cd,
                                bjdong_cd=bjdong_cd,
                                bun=bun,
                                ji=ji,
                                dong_nm=norm_dong,
                            )
                            request_cache[cache_key] = bld_result
                            row["fromCache"] = False

                        row["request"] = {
                            "sigunguCd": sigungu_cd,
                            "bjdongCd": bjdong_cd,
                            "bun": bun,
                            "ji": ji,
                            "dongNm": norm_dong,
                        }
                        row["bldrgst"] = bld_result
                        row["ok"] = bool(bld_result.get("ok"))
                        row["error"] = bld_result.get("error")

                except Exception as e:  # noqa: BLE001
                    row["ok"] = False
                    row["error"] = f"article 처리 실패: {e}"
                    article_fail_count += 1

                if row.get("ok"):
                    ok_count += 1
                else:
                    fail_count += 1
                    err = str(row.get("error") or "")
                    if "지번 파싱 실패" in err or "cortarNo 파싱 실패" in err:
                        parse_fail_count += 1
                    elif "API" in err or "요청 실패" in err or "XML 파싱 실패" in err:
                        req_fail_count += 1

                line = json.dumps(row, ensure_ascii=False) + "\n"
                out_f, current_out_path = rotate_if_needed(
                    out_f=out_f,
                    current_path=current_out_path,
                    base_out_path=base_out_path,
                    incoming_line=line,
                    max_file_bytes=max_file_bytes,
                    log=log,
                )
                out_f.write(line)
                out_f.flush()
                seen_article_nos.add(article_no)
                saved_lines += 1

                if processed_articles % 50 == 0:
                    elapsed = time.time() - start_ts
                    speed = (saved_lines / elapsed) if elapsed > 0 else 0.0
                    log(
                        f"[PROGRESS] processed_articles={processed_articles}, saved_lines={saved_lines}, "
                        f"ok={ok_count}, fail={fail_count}, parse_fail={parse_fail_count}, "
                        f"req_fail={req_fail_count}, article_fail={article_fail_count}, "
                        f"cache_size={len(request_cache)}, elapsed={elapsed:.1f}s, rate={speed:.2f}rows/s"
                    )
                time.sleep(args.sleep)

    ended_at = datetime.now().isoformat(timespec="seconds")
    elapsed_total = time.time() - start_ts
    log(
        f"[DONE] processed_articles={processed_articles}, saved_lines={saved_lines}, "
        f"ok={ok_count}, fail={fail_count}, parse_fail={parse_fail_count}, "
        f"req_fail={req_fail_count}, article_fail={article_fail_count}, "
        f"cache_size={len(request_cache)}, elapsed={elapsed_total:.1f}s, "
        f"ended_at={ended_at}, log_file={log_path}"
    )


if __name__ == "__main__":
    main()

