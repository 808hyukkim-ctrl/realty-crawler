"""
bunji_data 하위 텍스트 파일을 UTF-8로 일괄 변환.

기본 동작:
- 재귀적으로 *.txt 파일 탐색
- 인코딩 자동 판별(utf-8-sig, utf-8, cp949, euc-kr)
- UTF-8로 덮어쓰기 변환
- 원본 백업(.bak) 생성
"""

import argparse
import shutil
from pathlib import Path
from typing import Iterable, Optional, Tuple


PREFERRED_ENCODINGS = ("utf-8-sig", "utf-8", "cp949", "euc-kr")


def read_with_detect(path: Path) -> Tuple[str, str]:
    last_exc: Optional[Exception] = None
    for enc in PREFERRED_ENCODINGS:
        try:
            text = path.read_text(encoding=enc)
            return text, enc
        except UnicodeDecodeError as e:
            last_exc = e
            continue

    # 엄격 모드에서 모두 실패하면 cp949 replace로라도 복구 시도
    try:
        text = path.read_text(encoding="cp949", errors="replace")
        return text, "cp949(replace)"
    except Exception as e:  # noqa: BLE001
        last_exc = e

    raise RuntimeError(f"디코딩 실패: {path} ({last_exc})")


def iter_target_files(root: Path, pattern: str = "*.txt") -> Iterable[Path]:
    yield from sorted(root.rglob(pattern))


def convert_file(path: Path, backup: bool = True) -> Tuple[bool, str]:
    text, src_enc = read_with_detect(path)

    if backup:
        backup_path = path.with_suffix(path.suffix + ".bak")
        if not backup_path.exists():
            shutil.copy2(path, backup_path)

    # UTF-8(BOM 없음)으로 저장
    path.write_text(text, encoding="utf-8", newline="")
    return True, src_enc


def main() -> None:
    parser = argparse.ArgumentParser(description="bunji_data 텍스트 파일 UTF-8 일괄 변환")
    parser.add_argument(
        "--root",
        default="bunji_data",
        help="대상 루트 폴더 (기본: bunji_data)",
    )
    parser.add_argument(
        "--glob",
        default="*.txt",
        help="대상 파일 glob 패턴 (기본: *.txt)",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="백업(.bak) 파일을 만들지 않음",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.exists():
        raise FileNotFoundError(f"대상 폴더가 없습니다: {root}")

    files = list(iter_target_files(root, args.glob))
    total = len(files)
    print(f"[START] root={root} files={total} backup={not args.no_backup}")

    ok_count = 0
    fail_count = 0

    for idx, path in enumerate(files, 1):
        try:
            _, src_enc = convert_file(path, backup=not args.no_backup)
            ok_count += 1
            print(f"[OK] {idx}/{total} {path} ({src_enc} -> utf-8)")
        except Exception as e:  # noqa: BLE001
            fail_count += 1
            print(f"[FAIL] {idx}/{total} {path} ({e})")

    print(f"[DONE] total={total} ok={ok_count} fail={fail_count}")


if __name__ == "__main__":
    main()

