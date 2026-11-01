"""예배 PPT 조립: 구조 템플릿 × 테마 템플릿 × 그 주 내용(json).

사용법 (저장소 루트에서):
  python -X utf8 도구/worship_ppt/assemble.py build --구조 2_템플릿/구조/구조-주일기본.txt \
      --테마 2_템플릿/테마/테마-초록잎들꽃.pptx --내용 내용.json [--출력 경로]
"""
import argparse
import importlib.util
import json
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from pptx import Presentation

import slides
from fill import fill_gyodokmun, fill_verses
from sources import REPO, SourceError, display_reference, load_gyodokmun, load_verses, parse_reference
from structure import INSERT_KINDS, THEME_KINDS, parse_structure
from theme import kind_slides, validate_theme
from title import fill_cover

HYMN_DIR = REPO / "1_자료" / "찬송가"
REPLACER = REPO / ".claude/skills/church-worship-ppt/scripts/ppt_section_replacer.py"


def _replacer():
    spec = importlib.util.spec_from_file_location("ppt_section_replacer", REPLACER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def hymn_path(n: int, hymn_dir: Path) -> Path | None:
    for ext in (".ppt", ".pptx", ".PPT", ".PPTX"):
        f = Path(hymn_dir) / f"새찬송가_{int(n):03d}장{ext}"
        if f.exists():
            return f
    return None


def _hymn_numbers(items, content) -> list:
    """구조 순서대로 찬송 번호: 번호가 적힌 항목은 그 번호, 아니면 content['찬송']에서 차례로."""
    free = iter(content.get("찬송", []))
    return [int(it.arg) if it.arg else next(free, None) for it in items if it.kind == "찬송"]


def check_inputs(items, theme_path, content: dict, hymn_dir: Path = HYMN_DIR) -> list:
    problems = validate_theme(Path(theme_path), [it.kind for it in items if it.kind in THEME_KINDS])
    kinds = Counter(it.kind for it in items)
    if kinds["교독문"]:
        try:
            load_gyodokmun(int(content["교독문"]))
        except (KeyError, SourceError) as e:
            problems.append(f"교독문: {e}" if not isinstance(e, KeyError) else "내용에 '교독문' 번호가 없습니다")
    if kinds["말씀구절"] or kinds["본문표지"]:
        try:
            for p in parse_reference(content["본문"]):
                load_verses(p)
        except KeyError:
            problems.append("내용에 '본문'이 없습니다")
        except SourceError as e:
            problems.append(f"본문: {e}")
    if kinds["본문표지"] and not content.get("설교제목"):
        problems.append("내용에 '설교제목'이 없습니다")
    free = sum(1 for it in items if it.kind == "찬송" and not it.arg)
    if len(content.get("찬송", [])) != free:
        problems.append(f"구조에 번호 없는 찬송이 {free}곡인데 내용 '찬송'은 {len(content.get('찬송', []))}곡입니다")
    for n in _hymn_numbers(items, content):
        if n is not None and hymn_path(n, hymn_dir) is None:
            problems.append(f"찬송 {n}장 파일이 없습니다: {Path(hymn_dir) / f'새찬송가_{int(n):03d}장.ppt'}")
    if kinds["준비찬양"]:
        for f in content.get("준비찬양", []):
            if not (REPO / f).exists() and not Path(f).exists():
                problems.append(f"준비찬양 파일이 없습니다: {f}")
    return problems


def _section_names(items) -> list:
    total = Counter(it.kind for it in items)
    seen = Counter()
    names = []
    for it in items:
        seen[it.kind] += 1
        names.append(f"{it.kind} {seen[it.kind]}" if total[it.kind] > 1 else it.kind)
    return names


def assemble(structure_path, theme_path, content: dict, out_path, hymn_dir: Path = HYMN_DIR) -> Path:
    items = parse_structure(Path(structure_path))
    problems = check_inputs(items, theme_path, content, hymn_dir)
    if problems:
        raise SystemExit("조립 전 점검 실패:\n- " + "\n- ".join(problems))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    prs = Presentation(str(theme_path))
    samples = kind_slides(prs)
    n_samples = len(prs.slides)
    passages = parse_reference(content["본문"]) if "본문" in content else []

    groups = []
    for it in items:
        if it.kind in INSERT_KINDS:
            groups.append([])
            continue
        copies = [slides.duplicate_slide(prs, i) for i in samples[it.kind]]
        if it.kind == "교독문":
            copies = fill_gyodokmun(prs, copies, load_gyodokmun(int(content["교독문"])))
        elif it.kind == "말씀구절":
            copies = fill_verses(prs, copies[0], passages)
        elif it.kind == "본문표지":
            for c in copies:
                fill_cover(prs, c, display_reference(passages), content["설교제목"])
        groups.append(copies)

    # 구조 순서로 장 재배열 후 견본 원본 삭제
    lst = prs.slides._sldIdLst
    elems = list(lst)
    order = [i for g in groups for i in g] + list(range(n_samples))
    for el in elems:
        lst.remove(el)
    for i in order:
        lst.append(elems[i])
    slides.delete_slides(prs, list(range(len(order) - n_samples, len(order))))
    names = _section_names(items)
    slides.set_sections(prs, [(name, len(g)) for name, g in zip(names, groups)])
    prs.save(str(out_path))

    # 찬송·준비찬양 끼우기
    rep = _replacer()
    hymns = iter(_hymn_numbers(items, content))
    with tempfile.TemporaryDirectory() as tmp:
        for it, name in zip(items, names):
            if it.kind == "찬송":
                srcs = [hymn_path(next(hymns), hymn_dir)]
            elif it.kind == "준비찬양":
                srcs = [REPO / f if (REPO / f).exists() else Path(f) for f in content.get("준비찬양", [])]
            else:
                continue
            if srcs:
                rep.replace_section_zip(str(out_path), name, [rep.convert_to_pptx(str(s), tmp) for s in srcs], tmp)
    return out_path


def main(argv=None):
    ap = argparse.ArgumentParser(description="예배 PPT 조립")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--구조", required=True)
    b.add_argument("--테마", required=True)
    b.add_argument("--내용", required=True)
    b.add_argument("--출력")
    r = sub.add_parser("render")
    r.add_argument("파일")
    r.add_argument("--폴더", help="PNG 저장 폴더(기본: 임시 폴더)")
    v = sub.add_parser("verify")
    v.add_argument("파일")
    v.add_argument("--내용", required=True)
    args = ap.parse_args(argv)
    from check import render, verify

    if args.cmd == "render":
        out_dir = Path(args.폴더) if args.폴더 else Path(tempfile.mkdtemp(prefix="worship_render_"))
        print(f"모아보기: {render(Path(args.파일), out_dir)}")
        return
    content = json.loads(Path(args.내용).read_text(encoding="utf-8"))
    if args.cmd == "verify":
        problems = verify(Path(args.파일), content)
        print("대조 결과: 원본과 일치" if not problems else "대조 결과: 다른 곳 있음\n- " + "\n- ".join(problems))
        sys.exit(1 if problems else 0)
    out = Path(args.출력) if args.출력 else REPO / "4_예배PPT/주일" / f"{content['date']}_주일.pptx"
    out = assemble(Path(args.구조), Path(args.테마), content, out)
    prs = Presentation(str(out))
    print(f"완료: {out.relative_to(REPO) if out.is_relative_to(REPO) else out}")
    for name, idx in slides.sections(prs):
        print(f"  {name}: {len(idx)}장")
    problems = verify(out, content)
    print("대조 결과: 원본과 일치" if not problems else "대조 결과: 다른 곳 있음\n- " + "\n- ".join(problems))


if __name__ == "__main__":
    main()
