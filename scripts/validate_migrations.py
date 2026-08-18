"""Validate the monotonically numbered SQL migration set without a database."""

from pathlib import Path
import re
import sys


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    paths = sorted((root / "apps" / "api" / "migrations").glob("*.sql"))
    numbers: list[int] = []
    for path in paths:
        match = re.fullmatch(r"(\d{3})_[a-z0-9_]+\.sql", path.name)
        if match is None:
            print(f"invalid migration filename: {path.name}", file=sys.stderr)
            return 1
        numbers.append(int(match.group(1)))
    expected = list(range(1, len(paths) + 1))
    if numbers != expected:
        print(f"migration numbers must be contiguous: found {numbers}, expected {expected}", file=sys.stderr)
        return 1
    print(f"validated {len(paths)} migrations: {paths[-1].name if paths else 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
