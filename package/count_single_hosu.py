import re
import sys
from pathlib import Path

import pandas as pd


def pick_target_file() -> Path:
    if len(sys.argv) >= 2:
        return Path(sys.argv[1]).expanduser().resolve()

    raw = input("분석할 엑셀 파일명(또는 경로)을 입력하세요: ").strip().strip('"').strip("'")
    if not raw:
        raise ValueError("파일명을 입력해야 합니다.")

    user_path = Path(raw).expanduser()
    if user_path.is_absolute():
        return user_path.resolve()

    cwd_path = (Path.cwd() / user_path).resolve()
    if cwd_path.exists():
        return cwd_path

    data_path = (Path(__file__).resolve().parent / "data" / user_path).resolve()
    return data_path


def is_single_hosu(value: object) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    if not text:
        return False

    # 후보가 여러 개면 보통 콤마로 저장됨
    tokens = [t.strip() for t in text.split(",") if t.strip()]
    if len(tokens) != 1:
        return False

    token = tokens[0]
    # 대표 패턴: 302호, 302, B102호, B102
    return bool(re.fullmatch(r"[A-Za-z]?\d+호?", token))


def main() -> None:
    target = pick_target_file()
    if not target.exists():
        raise FileNotFoundError(f"파일이 없습니다: {target}")

    df = pd.read_excel(target)
    if "호수" not in df.columns:
        raise KeyError(f"'호수' 칼럼이 없습니다: {target.name}")

    total_rows = len(df)
    hosu_series = df["호수"]
    filled_rows = int(hosu_series.notna().sum())
    single_rows = int(hosu_series.apply(is_single_hosu).sum())

    ratio_total = (single_rows / total_rows * 100) if total_rows else 0.0
    ratio_filled = (single_rows / filled_rows * 100) if filled_rows else 0.0

    print(f"[파일] {target}")
    print(f"[전체 행 기준] 단일 호수: {single_rows} / {total_rows} ({ratio_total:.2f}%)")
    print(f"[호수 값 존재 행 기준] 단일 호수: {single_rows} / {filled_rows} ({ratio_filled:.2f}%)")


if __name__ == "__main__":
    main()
