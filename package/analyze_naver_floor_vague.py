"""
data/ 폴더의 네이버 수집 엑셀(.xlsx)을 모두 읽어,
'해당층'이 저/중/고 등 막연한 표기인 비율을 지역(시/구)·매물종류별로 집계한다.

사용:
  python analyze_naver_floor_vague.py
  python analyze_naver_floor_vague.py --data-dir data --min-rows 5
  python analyze_naver_floor_vague.py -o data/naver_floor_vague_report.txt
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any, Iterable, List, Tuple

import pandas as pd


def _is_blank(val: Any) -> bool:
    if val is None:
        return True
    try:
        if pd.isna(val):
            return True
    except Exception:
        pass
    s = str(val).strip()
    return not s or s.lower() in ("nan", "none", "-")


def is_numeric_floor(s: str) -> bool:
    """숫자 층(5, 5층, -1층, 지하1층, B1 등)이면 True (막연 표기 아님)."""
    t = s.strip()
    if re.fullmatch(r"-?\d+(\s*층)?", t):
        return True
    if re.fullmatch(r"지하\s*-?\d+(\s*층)?", t):
        return True
    if re.fullmatch(r"[Bb]\s*-?\d+(\s*층)?", t):
        return True
    if re.fullmatch(r"지하\s*[Bb]\s*-?\d+", t):
        return True
    return False


def is_vague_floor_band(val: Any) -> bool:
    """
    저/중/고 등 구간 표기로 보이면 True.
    해당층 컬럼 값만 대상으로 한다는 전제(중개/고층 혼동 최소화).
    """
    if _is_blank(val):
        return False
    s = str(val).strip()
    if is_numeric_floor(s):
        return False

    if any(k in s for k in ("저층", "중층", "고층", "저/중/고", "저중고", "저·중·고")):
        return True
    if s in ("저", "중", "고"):
        return True
    # '저 층' 처럼 띄어쓰기
    if re.fullmatch(r"[저중고]\s*층", s):
        return True
    return False


REQUIRED_COL = "해당층"
COL_SI = "시"
COL_GU = "구"
COL_KIND = "종류"
COL_ARTICLE = "매물번호"


def iter_naver_xlsx(data_dir: Path) -> List[Path]:
    out: List[Path] = []
    for p in sorted(data_dir.glob("*.xlsx")):
        if p.name.startswith("네이버"):
            out.append(p)
    return out


def load_frames(paths: Iterable[Path]) -> Tuple[pd.DataFrame, List[str]]:
    frames: List[pd.DataFrame] = []
    errors: List[str] = []
    for p in paths:
        try:
            df = pd.read_excel(p, engine="openpyxl")
            df["_source_file"] = p.name
            frames.append(df)
        except Exception as e:
            errors.append(f"{p.name}: {e}")
    if not frames:
        return pd.DataFrame(), errors
    return pd.concat(frames, ignore_index=True), errors


def normalize_key(s: Any) -> str:
    if _is_blank(s):
        return "(빈값)"
    return str(s).strip()


def main() -> int:
    ap = argparse.ArgumentParser(description="네이버 엑셀 해당층 저/중/고 막연 표기 분석")
    ap.add_argument(
        "--data-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "data",
        help="엑셀 폴더 (기본: 프로젝트 data/)",
    )
    ap.add_argument(
        "--min-rows",
        type=int,
        default=10,
        help="비율 랭킹에 넣을 그룹의 최소 행 수",
    )
    ap.add_argument(
        "--dedupe",
        action="store_true",
        help="같은 매물번호는 한 번만 집계 (첫 행 유지)",
    )
    ap.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="리포트를 UTF-8 텍스트로 저장 (콘솔과 동일 내용)",
    )
    args = ap.parse_args()
    data_dir = args.data_dir
    if not data_dir.is_dir():
        print(f"폴더 없음: {data_dir}", file=sys.stderr)
        return 1

    paths = iter_naver_xlsx(data_dir)
    if not paths:
        print(f'"{data_dir}" 에서 네이버*.xlsx 파일을 찾지 못했습니다.', file=sys.stderr)
        return 1

    df, errs = load_frames(paths)
    if errs:
        print("--- 읽기 실패 ---", file=sys.stderr)
        for e in errs:
            print(e, file=sys.stderr)

    if df.empty:
        print("읽은 데이터가 없습니다.", file=sys.stderr)
        return 1

    if REQUIRED_COL not in df.columns:
        print(f"컬럼 '{REQUIRED_COL}' 없음. 실제 컬럼: {list(df.columns)[:20]}...", file=sys.stderr)
        return 1

    if args.dedupe and COL_ARTICLE in df.columns:
        before = len(df)
        df = df.drop_duplicates(subset=[COL_ARTICLE], keep="first")
        print(f"매물번호 기준 중복 제거: {before} -> {len(df)} 행\n", file=sys.stderr)

    vague_mask = df[REQUIRED_COL].map(is_vague_floor_band)
    df["_vague"] = vague_mask

    n = len(df)
    n_vague = int(vague_mask.sum())
    out_lines: List[str] = []

    def ln(s: str = "") -> None:
        out_lines.append(s)

    ln("=== 전체 요약 (네이버 엑셀 전부 합산) ===")
    ln(f"  파일 수: {len(paths)}")
    ln(f"  행 수:   {n}")
    ln(f"  해당층 막연(저/중/고 등): {n_vague} ({100.0 * n_vague / n:.2f}%)")
    ln(f"  해당층 숫자/지하 등 명시: {n - n_vague}")
    ln()

    def rate(v: int, t: int) -> float:
        return 100.0 * v / t if t else 0.0

    # --- 시 ---
    if COL_SI in df.columns:
        g = df.groupby(df[COL_SI].map(normalize_key), dropna=False).agg(
            vague=("_vague", "sum"),
            total=("_vague", "count"),
        )
        g = g[g["total"] >= 1].sort_values(["vague", "total"], ascending=[False, False])
        ln("=== 시별 / 막연 건수 상위 (건수 내림차순) ===")
        for k, row in g.head(25).iterrows():
            ln(
                f"  {k!s:<20}  막연 {int(row['vague']):5d} / 전체 {int(row['total']):5d}  "
                f"({rate(int(row['vague']), int(row['total'])):5.1f}%)"
            )
        ln()

        g2 = g[g["total"] >= args.min_rows].copy()
        g2["pct"] = g2.apply(lambda r: rate(int(r["vague"]), int(r["total"])), axis=1)
        g2 = g2.sort_values("pct", ascending=False)
        ln(f"=== 시별 / 막연 비율 상위 (행 >= {args.min_rows}) ===")
        for k, row in g2.head(20).iterrows():
            ln(
                f"  {k!s:<20}  {row['pct']:5.1f}%  "
                f"(막연 {int(row['vague'])}, 전체 {int(row['total'])})"
            )
        ln()

    # --- 시+구 ---
    if COL_SI in df.columns and COL_GU in df.columns:
        df["_sigu"] = df[COL_SI].map(normalize_key) + " " + df[COL_GU].map(normalize_key)
        g = df.groupby("_sigu", dropna=False).agg(
            vague=("_vague", "sum"),
            total=("_vague", "count"),
        )
        g = g[g["total"] >= 1].sort_values(["vague", "total"], ascending=[False, False])
        ln("=== 시+구별 / 막연 건수 상위 (상위 30) ===")
        for k, row in g.head(30).iterrows():
            ln(
                f"  {k!s:<36}  막연 {int(row['vague']):5d} / {int(row['total']):5d}  "
                f"({rate(int(row['vague']), int(row['total'])):5.1f}%)"
            )
        ln()

        g2 = g[g["total"] >= args.min_rows].copy()
        g2["pct"] = g2.apply(lambda r: rate(int(r["vague"]), int(r["total"])), axis=1)
        g2 = g2.sort_values("pct", ascending=False)
        ln(f"=== 시+구별 / 막연 비율 상위 (행 >= {args.min_rows}, 상위 25) ===")
        for k, row in g2.head(25).iterrows():
            ln(
                f"  {k!s:<36}  {row['pct']:5.1f}%  "
                f"(막연 {int(row['vague'])}, 전체 {int(row['total'])})"
            )
        ln()

    # --- 종류(매물유형) ---
    if COL_KIND in df.columns:
        g = df.groupby(df[COL_KIND].map(normalize_key), dropna=False).agg(
            vague=("_vague", "sum"),
            total=("_vague", "count"),
        )
        g = g.sort_values(["vague", "total"], ascending=[False, False])
        ln("=== 부동산 종류별 / 막연 건수 ===")
        for k, row in g.iterrows():
            ln(
                f"  {k!s:<24}  막연 {int(row['vague']):5d} / {int(row['total']):5d}  "
                f"({rate(int(row['vague']), int(row['total'])):5.1f}%)"
            )
        ln()

        g2 = g[g["total"] >= args.min_rows].copy()
        g2["pct"] = g2.apply(lambda r: rate(int(r["vague"]), int(r["total"])), axis=1)
        g2 = g2.sort_values("pct", ascending=False)
        ln(f"=== 부동산 종류별 / 막연 비율 상위 (행 >= {args.min_rows}) ===")
        for k, row in g2.head(15).iterrows():
            ln(
                f"  {k!s:<24}  {row['pct']:5.1f}%  "
                f"(막연 {int(row['vague'])}, 전체 {int(row['total'])})"
            )
        ln()

    # --- 시 x 종류 (막연 건수 많은 조합) ---
    if COL_SI in df.columns and COL_KIND in df.columns:
        df["_si_n"] = df[COL_SI].map(normalize_key)
        df["_kind_n"] = df[COL_KIND].map(normalize_key)
        g = df.groupby(["_si_n", "_kind_n"], dropna=False).agg(
            vague=("_vague", "sum"),
            total=("_vague", "count"),
        )
        g = g[g["vague"] >= 1].sort_values(["vague", "total"], ascending=[False, False])
        ln("=== 시 x 종류 / 막연 표기가 한 건이라도 있는 조합 (상위 40) ===")
        for (si, kd), row in g.head(40).iterrows():
            label = f"{si} / {kd}"
            ln(
                f"  {label[:56]:<56}  막연 {int(row['vague']):4d} / {int(row['total']):4d}  "
                f"({rate(int(row['vague']), int(row['total'])):5.1f}%)"
            )
        ln()

    # --- 막연 표기 실제 값 분포 ---
    vague_vals = df.loc[vague_mask, REQUIRED_COL].astype(str).str.strip()
    if len(vague_vals):
        vc = vague_vals.value_counts()
        ln("=== 막연으로 분류된 '해당층' 원문 값 (건수 상위 30) ===")
        for val, cnt in vc.head(30).items():
            ln(f"  {cnt:5d}  {val!r}")
        ln()

    ln("(막연 판정: 저층/중층/고층, 저/중/고 단독, 저/중/고 등. 숫자/지하/B층은 제외)")

    report = "\n".join(out_lines) + "\n"
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:
        pass
    print(report, end="")
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
        print(f"저장: {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
