"""
bunji_data/*.txt를 읽어 건축물대장 API(_type=json) 호출 후
응답 item 리스트를 SQLite에 1행씩 적재한다.
"""

import argparse
import json
import os
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import requests


API_URL = "https://apis.data.go.kr/1613000/BldRgstHubService/getBrExposPubuseAreaInfo"
ENCODINGS = ("utf-8-sig", "utf-8", "cp949", "euc-kr")
REGION_PRIORITY = [
    "seoul",
    "busan",
    "incheon",
    "daegu",
    "daejeon",
    "gwangju",
    "ulsan",
    "sejong",
    "gyeonggi",
    "gangwon",
    "chungbuk",
    "chungnam",
    "jeonbuk",
    "jeonnam",
    "gyeongbuk",
    "gyeongnam",
    "jeju",
]

# hosu_match_how.py 기반 item 필드
ITEM_FIELDS = [
    "dongNm",
    "hoNm",
    "flrNo",
    "flrNoNm",
    "exposPubuseGbCdNm",
    "mainAtchGbCdNm",
    "strctCdNm",
    "mainPurpsCdNm",
    "etcPurps",
    "area",
    "bldNm",
    "platPlc",
    "newPlatPlc",
    "bun",
    "ji",
    "mgmBldrgstPk",
    "crtnDay",
    "sigunguCd",
    "bjdongCd",
    "platGbCd",
    "regstrGbCd",
    "regstrGbCdNm",
    "regstrKindCd",
    "regstrKindCdNm",
    "naRoadCd",
    "naBjdongCd",
    "naUgrndCd",
    "naMainBun",
    "naSubBun",
    "flrGbCd",
    "flrGbCdNm",
    "exposPubuseGbCd",
    "mainAtchGbCd",
    "strctCd",
    "etcStrct",
    "mainPurpsCd",
]


SQLITE_INT_MAX = 2**63 - 1
SQLITE_INT_MIN = -(2**63)


def detect_encoding(path: Path) -> str:
    for enc in ENCODINGS:
        try:
            with path.open("r", encoding=enc) as f:
                f.readline()
            return enc
        except UnicodeDecodeError:
            continue
    return "cp949"


def file_order_key(path: Path) -> Tuple[int, str]:
    name = path.stem.lower()
    for idx, region in enumerate(REGION_PRIORITY):
        if name.endswith(f"_{region}") or f"_{region}_" in name or region in name:
            return (idx, name)
    return (len(REGION_PRIORITY), name)


def read_resume_point_from_log(log_path: Path) -> Tuple[Optional[str], Optional[int]]:
    if not log_path.exists():
        return None, None
    # 예: [체크포인트] 파일=jibun_rnaddrkor_seoul.txt 라인=12345 검색파라미터=11680-10300-0-1172-0003
    pattern = re.compile(r"\[체크포인트\]\s*파일=(\S+)\s+라인=(\d+)\s+검색파라미터=(\S+)")
    last_file = None
    last_line = None
    try:
        with log_path.open("r", encoding="utf-8") as f:
            for line in f:
                m = pattern.search(line)
                if not m:
                    continue
                last_file = m.group(1)
                last_line = int(m.group(2))
    except Exception:
        return None, None
    return last_file, last_line


def iter_bunji_rows(path: Path) -> Iterable[Tuple[int, Dict[str, str]]]:
    enc = detect_encoding(path)
    with path.open("r", encoding=enc, errors="replace") as f:
        for line_no, line in enumerate(f, 1):
            raw = line.strip()
            if not raw:
                continue
            cols = raw.split("|")
            # pnu|bjdong10|시도|시군구|법정동|...|산여부|본번|부번|...
            if len(cols) < 9:
                continue
            bjdong10 = (cols[1] or "").strip()
            bun_raw = (cols[7] or "").strip()
            ji_raw = (cols[8] or "").strip()
            if not (bjdong10.isdigit() and len(bjdong10) >= 10 and bun_raw.isdigit()):
                continue
            if ji_raw and (not ji_raw.isdigit()):
                continue

            sigungu_cd = bjdong10[:5]
            bjdong_cd = bjdong10[5:10]
            plat_gb_cd = "1" if (cols[6] or "").strip() == "1" else "0"
            bun = bun_raw.zfill(4)
            ji = (ji_raw or "0").zfill(4)
            search_param = f"{sigungu_cd}-{bjdong_cd}-{plat_gb_cd}-{bun}-{ji}"

            yield line_no, {
                "source_file": path.name,
                "source_line": str(line_no),
                "pnu": (cols[0] or "").strip(),
                "sido": (cols[2] or "").strip(),
                "sigungu_nm": (cols[3] or "").strip(),
                "bjdong_nm": (cols[4] or "").strip(),
                "sigungu_cd": sigungu_cd,
                "bjdong_cd": bjdong_cd,
                "plat_gb_cd": plat_gb_cd,
                "bun": bun,
                "ji": ji,
                "search_param": search_param,
            }


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bldrgst_query (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            search_param TEXT NOT NULL UNIQUE,
            source_file TEXT,
            source_line INTEGER,
            pnu TEXT,
            sido TEXT,
            sigungu_nm TEXT,
            bjdong_nm TEXT,
            sigungu_cd TEXT NOT NULL,
            bjdong_cd TEXT NOT NULL,
            plat_gb_cd TEXT NOT NULL,
            bun TEXT NOT NULL,
            ji TEXT NOT NULL,
            requested_at TEXT,
            response_ok INTEGER,
            result_code TEXT,
            result_msg TEXT,
            total_count INTEGER,
            page_count INTEGER,
            raw_json TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bldrgst_item (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            search_param TEXT NOT NULL,
            query_id INTEGER NOT NULL,
            item_index INTEGER NOT NULL,
            dongNm TEXT,
            hoNm TEXT,
            flrNo TEXT,
            flrNoNm TEXT,
            exposPubuseGbCdNm TEXT,
            mainAtchGbCdNm TEXT,
            strctCdNm TEXT,
            mainPurpsCdNm TEXT,
            etcPurps TEXT,
            area REAL,
            bldNm TEXT,
            platPlc TEXT,
            newPlatPlc TEXT,
            bun TEXT,
            ji TEXT,
            mgmBldrgstPk TEXT,
            crtnDay TEXT,
            sigunguCd TEXT,
            bjdongCd TEXT,
            platGbCd TEXT,
            regstrGbCd TEXT,
            regstrGbCdNm TEXT,
            regstrKindCd TEXT,
            regstrKindCdNm TEXT,
            naRoadCd TEXT,
            naBjdongCd TEXT,
            naUgrndCd TEXT,
            naMainBun TEXT,
            naSubBun TEXT,
            flrGbCd TEXT,
            flrGbCdNm TEXT,
            exposPubuseGbCd TEXT,
            mainAtchGbCd TEXT,
            strctCd TEXT,
            etcStrct TEXT,
            mainPurpsCd TEXT,
            FOREIGN KEY(query_id) REFERENCES bldrgst_query(id),
            UNIQUE(search_param, item_index, hoNm, mgmBldrgstPk, flrNo, area)
        )
        """
    )
    conn.commit()


def call_api_json(service_key: str, p: Dict[str, str], timeout: int, max_attempts: int, page_no: int = 1) -> Dict:
    last_error: Optional[str] = None
    for attempt in range(1, max_attempts + 1):
        try:
            params = {
                "serviceKey": service_key,
                "sigunguCd": p["sigungu_cd"],
                "bjdongCd": p["bjdong_cd"],
                "platGbCd": p["plat_gb_cd"],
                "bun": p["bun"],
                "ji": p["ji"],
                "numOfRows": 100,
                "pageNo": page_no,
                "_type": "json",
            }
            resp = requests.get(API_URL, params=params, timeout=timeout)
            if resp.status_code == 429:
                return {"_error": "HTTP 429 Too Many Requests", "_status_code": 429}
            resp.raise_for_status()
            return resp.json()
        except Exception as e:  # noqa: BLE001
            last_error = str(e)
            time.sleep(0.8 * (2 ** (attempt - 1)))
    return {"_error": last_error or "unknown"}


def parse_json_response(payload: Dict) -> Tuple[bool, str, str, int, int, List[Dict]]:
    if "_error" in payload:
        return False, "", payload["_error"], 0, 0, []
    response = payload.get("response") or {}
    header = response.get("header") or {}
    body = response.get("body") or {}
    code = str(header.get("resultCode") or "")
    msg = str(header.get("resultMsg") or "")
    total = int(body.get("totalCount") or 0)
    page_no = int(body.get("pageNo") or 1)
    items_obj = body.get("items") or {}
    item = items_obj.get("item") if isinstance(items_obj, dict) else []
    if item is None:
        rows = []
    elif isinstance(item, list):
        rows = item
    else:
        rows = [item]
    ok = code in ("00", "000")
    return ok, code, msg, total, page_no, rows


def send_telegram_alert(bot_token: str, chat_id: str, message: str) -> Tuple[bool, str]:
    if not bot_token or not chat_id:
        return False, "텔레그램 토큰/챗아이디 미설정"
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": message},
            timeout=10,
        )
        if resp.status_code == 200:
            return True, "ok"
        return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def upsert_query(conn: sqlite3.Connection, p: Dict[str, str], parsed: Tuple, payload: Dict) -> int:
    ok, code, msg, total, page_no, _ = parsed
    conn.execute(
        """
        INSERT INTO bldrgst_query (
            search_param, source_file, source_line, pnu, sido, sigungu_nm, bjdong_nm,
            sigungu_cd, bjdong_cd, plat_gb_cd, bun, ji, requested_at,
            response_ok, result_code, result_msg, total_count, page_count, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'),
                  ?, ?, ?, ?, ?, ?)
        ON CONFLICT(search_param) DO UPDATE SET
            requested_at=datetime('now'),
            response_ok=excluded.response_ok,
            result_code=excluded.result_code,
            result_msg=excluded.result_msg,
            total_count=excluded.total_count,
            page_count=excluded.page_count,
            raw_json=excluded.raw_json
        """,
        (
            p["search_param"],
            p["source_file"],
            int(p["source_line"]),
            p["pnu"],
            p["sido"],
            p["sigungu_nm"],
            p["bjdong_nm"],
            p["sigungu_cd"],
            p["bjdong_cd"],
            p["plat_gb_cd"],
            p["bun"],
            p["ji"],
            1 if ok else 0,
            code,
            msg,
            total,
            page_no,
            json.dumps(payload, ensure_ascii=False),
        ),
    )
    row = conn.execute(
        "SELECT id FROM bldrgst_query WHERE search_param = ?",
        (p["search_param"],),
    ).fetchone()
    return int(row[0])


def insert_items(
    conn: sqlite3.Connection,
    query_id: int,
    search_param: str,
    rows: List[Dict],
    start_index: int = 1,
) -> int:
    if not rows:
        # 검색결과(item)가 없더라도 매핑 행 1개를 남긴다.
        if start_index != 1:
            return 0
        exists = conn.execute(
            """
            SELECT 1
            FROM bldrgst_item
            WHERE query_id = ? AND search_param = ? AND item_index = 0
            LIMIT 1
            """,
            (query_id, search_param),
        ).fetchone()
        if exists:
            return 0
        conn.execute(
            """
            INSERT INTO bldrgst_item (
                search_param, query_id, item_index,
                dongNm, hoNm, flrNo, flrNoNm, exposPubuseGbCdNm, mainAtchGbCdNm,
                strctCdNm, mainPurpsCdNm, etcPurps, area, bldNm, platPlc, newPlatPlc,
                bun, ji, mgmBldrgstPk, crtnDay, sigunguCd, bjdongCd, platGbCd,
                regstrGbCd, regstrGbCdNm, regstrKindCd, regstrKindCdNm, naRoadCd,
                naBjdongCd, naUgrndCd, naMainBun, naSubBun, flrGbCd, flrGbCdNm,
                exposPubuseGbCd, mainAtchGbCd, strctCd, etcStrct, mainPurpsCd
            ) VALUES (
                ?, ?, 0,
                NULL, NULL, NULL, NULL, NULL, NULL,
                NULL, NULL, NULL, NULL, NULL, NULL, NULL,
                NULL, NULL, NULL, NULL, NULL, NULL, NULL,
                NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
                NULL, NULL, NULL, NULL, NULL
            )
            """,
            (search_param, query_id),
        )
        return 1

    inserted = 0
    for i, item in enumerate(rows, start_index):
        values = [item.get(k) for k in ITEM_FIELDS]
        # area는 REAL로 저장
        if values[9] not in (None, ""):
            try:
                values[9] = float(values[9])
            except Exception:
                values[9] = None
        # SQLite INTEGER 범위를 넘는 정수는 TEXT로 저장
        for idx, v in enumerate(values):
            if idx == 9:  # area
                continue
            if isinstance(v, bool):
                values[idx] = int(v)
                continue
            if isinstance(v, int):
                if v > SQLITE_INT_MAX or v < SQLITE_INT_MIN:
                    values[idx] = str(v)
            elif isinstance(v, float):
                # 실수 컬럼이 아닌데 float로 들어오면 문자열로 보존
                values[idx] = str(v)
        conn.execute(
            """
            INSERT OR IGNORE INTO bldrgst_item (
                search_param, query_id, item_index,
                dongNm, hoNm, flrNo, flrNoNm, exposPubuseGbCdNm, mainAtchGbCdNm,
                strctCdNm, mainPurpsCdNm, etcPurps, area, bldNm, platPlc, newPlatPlc,
                bun, ji, mgmBldrgstPk, crtnDay, sigunguCd, bjdongCd, platGbCd,
                regstrGbCd, regstrGbCdNm, regstrKindCd, regstrKindCdNm, naRoadCd,
                naBjdongCd, naUgrndCd, naMainBun, naSubBun, flrGbCd, flrGbCdNm,
                exposPubuseGbCd, mainAtchGbCd, strctCd, etcStrct, mainPurpsCd
            ) VALUES (
                ?, ?, ?,
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (search_param, query_id, i, *values),
        )
        if conn.total_changes > 0:
            inserted += 1
    return inserted


def main() -> None:
    parser = argparse.ArgumentParser(description="번지 텍스트 -> 건축물대장 JSON -> SQLite 적재")
    parser.add_argument("--bunji-dir", default="bunji_data", help="번지 txt 폴더")
    parser.add_argument("--db-path", default="bldrgst_local.db", help="SQLite DB 파일 경로")
    parser.add_argument("--log-file", default="load_bunji_to_sqlite.log", help="진행 로그 파일 경로")
    parser.add_argument("--service-key", default="", help="공공 API 서비스키")
    parser.add_argument("--glob", default="*.txt", help="대상 파일 패턴")
    parser.add_argument("--max-files", type=int, default=0, help="테스트용 파일 수 제한(0=전체)")
    parser.add_argument("--max-lines-per-file", type=int, default=0, help="파일당 처리 라인 제한(0=전체)")
    parser.add_argument("--timeout", type=int, default=20, help="API timeout(sec)")
    parser.add_argument("--max-attempts", type=int, default=3, help="API 재시도 횟수")
    parser.add_argument("--sleep", type=float, default=0.01, help="요청 간 대기(sec)")
    parser.add_argument("--resume", action="store_true", help="이미 처리한 search_param 스킵")
    parser.add_argument("--sample-every", type=int, default=200, help="N건마다 적재 샘플 로그 출력")
    parser.add_argument("--checkpoint-every", type=int, default=20, help="체크포인트 로그 출력 주기(요청 N건)")
    parser.add_argument("--ignore-log-resume", action="store_true", help="로그 기반 이어하기를 사용하지 않음")
    parser.add_argument("--telegram-bot-token", default=os.getenv("TELEGRAM_BOT_TOKEN", ""), help="텔레그램 봇 토큰")
    parser.add_argument("--telegram-chat-id", default=os.getenv("TELEGRAM_CHAT_ID", ""), help="텔레그램 챗 ID")
    args = parser.parse_args()

    # service_key = (args.service_key or "").strip() or "Pd8XP2zEM16EBWbwV1ZFj4CzL8kr3mroUS0WKu9l%2FEsB0frVldsvnVt1N4SwqQELHMUGtyKSv8cUtw3tlXXZxA%3D%3D"
    service_key = "Pd8XP2zEM16EBWbwV1ZFj4CzL8kr3mroUS0WKu9l/EsB0frVldsvnVt1N4SwqQELHMUGtyKSv8cUtw3tlXXZxA=="
    bunji_dir = Path(args.bunji_dir).resolve()
    log_path = Path(args.log_file).resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(msg: str) -> None:
        line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
        print(line)
        with log_path.open("a", encoding="utf-8") as lf:
            lf.write(line + "\n")

    files = sorted(bunji_dir.rglob(args.glob), key=file_order_key)
    if args.max_files > 0:
        files = files[: args.max_files]

    resume_file_from_log = None
    resume_line_from_log = None
    if not args.ignore_log_resume:
        resume_file_from_log, resume_line_from_log = read_resume_point_from_log(log_path)

    conn = sqlite3.connect(str(Path(args.db_path).resolve()))
    init_db(conn)

    seen = set()
    if args.resume:
        for row in conn.execute("SELECT search_param FROM bldrgst_query"):
            seen.add(row[0])

    total_queries = 0
    ok_queries = 0
    fail_queries = 0
    inserted_items = 0
    stopped_by_429 = False

    start_ts = time.time()
    log(
        f"[시작] 대상파일={len(files)}개, 재개스킵={len(seen)}건, "
        f"DB={Path(args.db_path).resolve()}, 번지폴더={bunji_dir}, 로그파일={log_path}"
    )
    if resume_file_from_log and resume_line_from_log:
        log(f"[로그이어하기] 파일={resume_file_from_log}, 라인={resume_line_from_log} 이후부터 재개")
    if files:
        preview = ", ".join(p.name for p in files[:8])
        log(f"[파일순서] 우선 처리 목록(앞 8개): {preview}")

    resume_file_idx = None
    if resume_file_from_log:
        for idx, p in enumerate(files):
            if p.name == resume_file_from_log:
                resume_file_idx = idx
                break

    for fidx, txt in enumerate(files, 1):
        if resume_file_idx is not None and (fidx - 1) < resume_file_idx:
            log(f"[파일건너뜀] 로그이어하기 기준으로 건너뜀: {txt.name}")
            continue
        file_start = time.time()
        file_queries = 0
        file_items = 0
        log(f"[파일시작] {fidx}/{len(files)} {txt}")
        for line_no, p in iter_bunji_rows(txt):
            if resume_file_idx is not None and (fidx - 1) == resume_file_idx and resume_line_from_log:
                if line_no <= resume_line_from_log:
                    continue
            if args.max_lines_per_file > 0 and line_no > args.max_lines_per_file:
                break
            if args.resume and p["search_param"] in seen:
                continue

            current_page = 1
            pages_fetched_this_query = 0
            rows_fetched_this_query = 0
            item_index_cursor = 1
            qid: Optional[int] = None
            first_payload: Dict = {}
            ok = True
            result_code = ""
            result_msg = ""
            total_count = 0
            inserted = 0

            while True:
                payload = call_api_json(
                    service_key,
                    p,
                    args.timeout,
                    args.max_attempts,
                    page_no=current_page,
                )
                if payload.get("_status_code") == 429:
                    stopped_by_429 = True
                    msg = (
                        f"[중단] API 429 감지: 파일={txt.name}, 라인={line_no}, "
                        f"검색파라미터={p['search_param']}, 페이지={current_page}, 오류={payload.get('_error')}"
                    )
                    log(msg)
                    ok_tg, tg_msg = send_telegram_alert(
                        args.telegram_bot_token.strip(),
                        args.telegram_chat_id.strip(),
                        f"건축물대장 수집 중단(429)\n파일: {txt.name}\n라인: {line_no}\n검색파라미터: {p['search_param']}\n페이지: {current_page}\n오류: {payload.get('_error')}",
                    )
                    if ok_tg:
                        log("[텔레그램] 429 중단 알림 전송 성공")
                    else:
                        log(f"[텔레그램] 429 중단 알림 전송 실패: {tg_msg}")
                    break

                parsed = parse_json_response(payload)
                ok, result_code, result_msg, total_count, _, rows = parsed
                pages_fetched_this_query += 1
                if current_page == 1:
                    first_payload = payload
                    qid = upsert_query(conn, p, parsed, payload)

                if not ok:
                    break
                if not rows:
                    break

                if qid is None:
                    qid = upsert_query(conn, p, parsed, payload)

                inserted += insert_items(
                    conn,
                    qid,
                    p["search_param"],
                    rows,
                    start_index=item_index_cursor,
                )
                rows_fetched_this_query += len(rows)
                item_index_cursor += len(rows)
                current_page += 1

            if stopped_by_429:
                break

            if qid is None:
                parsed_for_upsert = (
                    ok,
                    result_code,
                    result_msg,
                    total_count,
                    pages_fetched_this_query or 1,
                    [],
                )
                qid = upsert_query(conn, p, parsed_for_upsert, first_payload or {"_error": result_msg})

            if rows_fetched_this_query == 0:
                inserted += insert_items(conn, qid, p["search_param"], [], start_index=1)

            summary_payload = {
                "firstPage": first_payload,
                "pagesFetched": pages_fetched_this_query,
                "rowsFetched": rows_fetched_this_query,
            }
            conn.execute(
                """
                UPDATE bldrgst_query
                SET response_ok = ?,
                    result_code = ?,
                    result_msg = ?,
                    total_count = ?,
                    page_count = ?,
                    raw_json = ?,
                    requested_at = datetime('now')
                WHERE id = ?
                """,
                (
                    1 if ok else 0,
                    result_code,
                    result_msg,
                    total_count,
                    pages_fetched_this_query,
                    json.dumps(summary_payload, ensure_ascii=False),
                    qid,
                ),
            )
            conn.commit()

            total_queries += 1
            file_queries += 1
            inserted_items += inserted
            file_items += inserted
            if ok:
                ok_queries += 1
            else:
                fail_queries += 1

            if total_queries % 1 == 0:
                elapsed = time.time() - start_ts
                rate = total_queries / elapsed if elapsed > 0 else 0.0
                log(
                    f"[진행] 요청={total_queries}건 성공={ok_queries}건 실패={fail_queries}건 "
                    f"적재행={inserted_items}행 경과={elapsed:.1f}초 속도={rate:.2f}건/초 "
                    f"(금회결과 totalCount={total_count}, 수집페이지={pages_fetched_this_query}, "
                    f"수집item행={rows_fetched_this_query}, 삽입={inserted}, 코드={result_code}, 메시지={result_msg})"
                )
            if args.sample_every > 0 and total_queries % args.sample_every == 0:
                if rows_fetched_this_query > 0 and first_payload:
                    first_rows = parse_json_response(first_payload)[5]
                    sample = (first_rows[0] if first_rows else {}) or {}
                    log(
                        "[샘플적재] "
                        f"검색파라미터={p['search_param']} "
                        f"건물명={sample.get('bldNm')} "
                        f"동={sample.get('dongNm')} 호={sample.get('hoNm')} "
                        f"층={sample.get('flrNo')} 면적={sample.get('area')} "
                        f"관리PK={sample.get('mgmBldrgstPk')}"
                    )
                else:
                    log(f"[샘플적재] 검색파라미터={p['search_param']} 응답 item 없음")
            if args.checkpoint_every > 0 and total_queries % args.checkpoint_every == 0:
                log(
                    f"[체크포인트] 파일={txt.name} 라인={line_no} "
                    f"검색파라미터={p['search_param']}"
                )
            time.sleep(args.sleep)

        if stopped_by_429:
            break

        file_elapsed = time.time() - file_start
        log(
            f"[파일완료] {fidx}/{len(files)} {txt.name} "
            f"요청={file_queries}건 적재행={file_items}행 소요={file_elapsed:.1f}초"
        )

    total_elapsed = time.time() - start_ts
    total_rate = total_queries / total_elapsed if total_elapsed > 0 else 0.0
    log(
        f"[종료] 총요청={total_queries}건 성공={ok_queries}건 실패={fail_queries}건 "
        f"총적재행={inserted_items}행 총소요={total_elapsed:.1f}초 평균속도={total_rate:.2f}건/초"
    )
    conn.close()


if __name__ == "__main__":
    main()

