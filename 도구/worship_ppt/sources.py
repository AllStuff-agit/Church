"""1_자료의 txt 원본 읽기: 교독문, 개역개정 성경 구절, 본문 표기 해석."""
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GYODOKMUN_DIR = REPO / "1_자료" / "교독문"
BIBLE_DIR = REPO / "1_자료" / "개역개정성경"

ABBR = ("창 출 레 민 신 수 삿 룻 삼상 삼하 왕상 왕하 대상 대하 스 느 에 욥 시 잠 전 아 사 렘 애 겔 단 호 욜 암 옵 욘 미 나 합 습 학 슥 말 "
        "마 막 눅 요 행 롬 고전 고후 갈 엡 빌 골 살전 살후 딤전 딤후 딛 몬 히 약 벧전 벧후 요일 요이 요삼 유 계").split()
EXTRA_ALIAS = {"마태": "마태복음", "마가": "마가복음", "누가": "누가복음", "요한": "요한복음",
               "요한1서": "요한일서", "요한2서": "요한이서", "요한3서": "요한삼서", "요1": "요한일서", "요2": "요한이서", "요3": "요한삼서"}


class SourceError(Exception):
    pass


@dataclass
class Gyodokmun:
    number: int
    title: str
    lines: list  # [(역할, 본문)] 역할: 인도|회중|다같이


@dataclass
class Passage:
    book: str
    chapter: int
    start: int
    end: int


def load_gyodokmun(n: int) -> Gyodokmun:
    f = GYODOKMUN_DIR / f"교독문_{n}.txt"
    if not f.exists():
        raise SourceError(f"교독문 {n}번 파일이 없습니다: {f.relative_to(REPO)}")
    rows = f.read_text(encoding="utf-8").splitlines()
    title = re.sub(r"^교독문\s*\d+\.\s*", "", rows[0]).strip()
    lines = []
    for row in rows[2:]:
        if row.strip():
            role, text = row.split(":", 1)
            lines.append((role.strip(), text.strip()))
    return Gyodokmun(n, title, lines)


@lru_cache(maxsize=None)
def _books() -> dict:
    """정식 책 이름 → 책 폴더. 폴더 번호 순서(01~66)가 ABBR 순서와 같다."""
    folders = sorted((d for d in BIBLE_DIR.glob("*/*") if d.is_dir()), key=lambda d: int(d.name.split("_")[0]))
    return {d.name.split("_", 1)[1]: d for d in folders}


@lru_cache(maxsize=None)
def _aliases() -> dict:
    names = list(_books())
    alias = {n: n for n in names}
    alias.update(dict(zip(ABBR, names)))
    alias.update(EXTRA_ALIAS)
    return alias


def _book(token: str) -> str:
    token = token.strip()
    if token in _aliases():
        return _aliases()[token]
    raise SourceError(f"알 수 없는 성경 책 이름: '{token}'")


@lru_cache(maxsize=None)
def _chapter(book: str, chapter: int) -> dict:
    """장 파일 → {절: 본문}. 소제목 <…> 제거, 절 번호 없는 줄은 앞 절에 이어 붙임, 묶음 절(18-19)은 첫 절에."""
    folder = _books()[book]
    unit = "편" if book == "시편" else "장"
    files = [f for f in folder.glob("*.txt") if int(re.search(r"(\d+)[장편]$", f.stem).group(1)) == chapter]
    if not files:
        raise SourceError(f"{book} {chapter}{unit} 파일이 없습니다")
    verses, last = {}, None
    for line in files[0].read_text(encoding="utf-8").splitlines():
        m = re.match(r"\D+?\d+:(\d+)(?:-(\d+))?\s+(.*)$", line)
        if m:
            last = int(m.group(1))
            verses[last] = m.group(3)
            for k in range(last + 1, int(m.group(2) or last) + 1):
                verses[k] = ""
        else:
            rest = line.split(":", 1)[1] if ":" in line else line
            if last is not None and not re.fullmatch(r"\s*제.권\s*", rest):
                verses[last] += " " + rest
    return {v: re.sub(r"\s+", " ", re.sub(r"<[^>]*>", "", t)).strip() for v, t in verses.items()}


def parse_reference(text: str) -> list:
    """'삼하 21:1-14', '마태 4:8-10, 요한 12:12-15', '사무엘하 21:1-22:3', '5:1-3,7' 형식."""
    out, book, chapter = [], None, None
    for part in re.split(r"[,，]", text):
        part = part.strip().replace("~", "-")
        if not part:
            continue
        m = re.match(r"^(.*?)\s*(\d+:)?(\d+)(?:-(\d+:)?(\d+))?$", part)  # 책 이름에 숫자 가능(요한1서)
        if not m:
            raise SourceError(f"본문 표기를 읽을 수 없습니다: '{part}'")
        if m.group(1):
            book = _book(m.group(1))
        if book is None:
            raise SourceError(f"책 이름이 없습니다: '{part}'")
        if m.group(2):
            chapter = int(m.group(2)[:-1])
        if chapter is None:
            raise SourceError(f"장이 없습니다: '{part}'")
        start = int(m.group(3))
        end_ch = int(m.group(4)[:-1]) if m.group(4) else chapter
        end = int(m.group(5)) if m.group(5) else start
        for ch in range(chapter, end_ch + 1):
            s = start if ch == chapter else 1
            e = end if ch == end_ch else max(_chapter(book, ch))
            out.append(Passage(book, ch, s, e))
        chapter = end_ch
    return out


def load_verses(p: Passage) -> list:
    """[(절, 본문)]. 앞 절에 묶인 빈 절은 건너뜀."""
    verses = _chapter(p.book, p.chapter)
    unit = "편" if p.book == "시편" else "장"
    if p.start > p.end:
        raise SourceError(f"{p.book} {p.chapter}{unit} {p.start}-{p.end}절: 끝 절이 시작 절보다 앞입니다")
    start = p.start
    while start > 1 and verses.get(start) == "":  # 묶음 절(예: 18-19) 중간에서 시작하면 묶음 첫 절부터
        start -= 1
    out = []
    for v in range(start, p.end + 1):
        if v not in verses:
            raise SourceError(f"{p.book} {p.chapter}{unit} {v}절이 없습니다")
        if verses[v]:
            out.append((v, verses[v]))
    return out


def display_reference(ps: list) -> str:
    parts = []
    for p in ps:
        unit = "편" if p.book == "시편" else "장"
        verses = f"{p.start}-{p.end}" if p.start != p.end else f"{p.start}"
        parts.append(f"{p.book} {p.chapter}{unit} {verses}절")
    return ", ".join(parts)
