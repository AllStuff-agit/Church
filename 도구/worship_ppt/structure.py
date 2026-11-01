"""구조 템플릿(예배 순서 txt) 읽기."""
from dataclasses import dataclass
from pathlib import Path

THEME_KINDS = ("대기", "사도신경", "교독문", "참회기도", "본문표지", "말씀구절", "소식", "축도", "엔딩")
INSERT_KINDS = ("준비찬양", "찬송")


class StructureError(Exception):
    pass


@dataclass
class Item:
    kind: str
    arg: str | None


def parse_structure(path: Path) -> list:
    items = []
    for no, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        parts = line.split()
        if not parts:
            continue
        kind, arg = parts[0], (" ".join(parts[1:]) or None)
        if kind not in THEME_KINDS + INSERT_KINDS:
            raise StructureError(f"{no}번째 줄: 알 수 없는 항목 '{kind}'")
        items.append(Item(kind, arg))
    return items
