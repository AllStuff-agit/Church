"""예배 PPT 조립: 구조 템플릿 × 테마 템플릿 × 그 주 내용(json).

사용법 (저장소 루트에서):
  python -X utf8 도구/worship_ppt/assemble.py build --구조 2_템플릿/구조/구조-주일기본.txt \
      --테마 2_템플릿/테마/테마-초록잎들꽃.pptx --내용 내용.json [--출력 경로]
"""
import argparse
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
        except KeyError:
            problems.append("내용에 '교독문' 번호가 없습니다")
        except ValueError:
            problems.append(f"내용 '교독문'은 숫자만 적어야 합니다: '{content['교독문']}'")
        except SourceError as e:
            problems.append(f"교독문: {e}")
    if kinds["말씀구절"] or kinds["본문표지"]:
        try:
            for p in parse_reference(content["본문"]):
                load_verses(p)
        except KeyError:
            problems.append("내용에 '본문'이 없습니다")
        except SourceError as e:
            problems.append(f"본문: {e}")
    if kinds["본문표지"] and not str(content.get("설교제목", "")).strip():
        problems.append("내용에 '설교제목'이 없습니다")
    for it in items:
        if it.kind == "찬송" and it.arg and not it.arg.isdigit():
            problems.append(f"구조의 '찬송 {it.arg}': 번호는 숫자만 적어야 합니다(예: 찬송 635)")
    if any(problems[-1:]) and "번호는 숫자만" in problems[-1]:
        return problems
    for n in content.get("찬송", []):
        if not str(n).isdigit():
            problems.append(f"내용 '찬송'은 숫자만 적어야 합니다: '{n}'")
            return problems
    free = sum(1 for it in items if it.kind == "찬송" and not it.arg)
    if len(content.get("찬송", [])) != free:
        problems.append(f"구조에 번호 없는 찬송이 {free}곡인데 내용 '찬송'은 {len(content.get('찬송', []))}곡입니다")
    for n in _hymn_numbers(items, content):
        if n is not None and hymn_path(n, hymn_dir) is None:
            problems.append(f"찬송 {n}장 파일이 없습니다: {Path(hymn_dir) / f'새찬송가_{int(n):03d}장.ppt'}")
    if kinds["준비찬양"] and not content.get("준비찬양"):
        problems.append("내용에 '준비찬양'이 없습니다")
    if kinds["준비찬양"]:
        with tempfile.TemporaryDirectory() as tmp:
            for path, chorus in song_entries(content):
                if not path.exists():
                    problems.append(f"준비찬양 파일이 없습니다: {path}")
                elif chorus:
                    import insert
                    n = len(Presentation(insert.convert_to_pptx(str(path), tmp)).slides)
                    for k in chorus:
                        if not 1 <= k <= n:
                            problems.append(f"{path.name}: 후렴 장 번호 {k}이(가) 범위(1~{n}) 밖입니다")
    return problems


def song_entries(content: dict) -> list:
    """준비찬양 항목 → [(파일 경로, 후렴 장 번호 목록 또는 None)]. 항목은 경로 문자열 또는 {"파일":…, "후렴":[…]}."""
    out = []
    for e in content.get("준비찬양", []):
        f, chorus = (e["파일"], e.get("후렴")) if isinstance(e, dict) else (e, None)
        out.append((REPO / f if (REPO / f).exists() else Path(f), chorus))
    return out


def extract_slides(src: Path, numbers: list, out: Path) -> Path:
    """src(pptx)에서 numbers(1부터) 장만 그 순서로 남긴 사본을 out에 만든다."""
    prs = Presentation(str(src))
    lst = prs.slides._sldIdLst
    elems = list(lst)
    keep = [n - 1 for n in numbers]
    for el in elems:
        lst.remove(el)
    for i in keep + [i for i in range(len(elems)) if i not in keep]:
        lst.append(elems[i])
    slides.delete_slides(prs, list(range(len(keep), len(elems))))
    prs.save(str(out))
    return out


def _sections(items, content) -> list:
    """구조 항목 → [(항목, 섹션 이름, 준비찬양 곡 또는 None)]. 준비찬양은 곡마다 '준비찬양 N' 섹션 하나."""
    total = Counter(it.kind for it in items)
    seen = Counter()
    out = []
    for it in items:
        if it.kind == "준비찬양":
            for k, song in enumerate(song_entries(content), 1):
                out.append((it, f"준비찬양 {k}", song))
            continue
        seen[it.kind] += 1
        out.append((it, f"{it.kind} {seen[it.kind]}" if total[it.kind] > 1 else it.kind, None))
    return out


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
    plan = _sections(items, content)

    groups = []
    for it, _, _ in plan:
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
    slides.set_sections(prs, [(name, len(g)) for (_, name, _), g in zip(plan, groups)])
    size = (prs.slide_width, prs.slide_height)
    prs.save(str(out_path))

    # 찬송·준비찬양 끼우기
    import insert as rep
    hymns = iter(_hymn_numbers(items, content))
    with tempfile.TemporaryDirectory() as tmp:
        for k, (it, name, song) in enumerate(plan):
            if it.kind == "찬송":
                srcs = [str(hymn_path(next(hymns), hymn_dir))]
            elif it.kind == "준비찬양":
                path, chorus = song
                full = rep.convert_to_pptx(str(path), tmp)
                srcs = [full]
                if chorus:  # 후렴부터: 후렴 장 → 곡 전체
                    srcs.insert(0, str(extract_slides(Path(full), chorus, Path(tmp) / f"후렴_{k}.pptx")))
            else:
                continue
            pptxs = []
            for j, s in enumerate(srcs):
                f = Path(rep.convert_to_pptx(s, tmp))
                if Path(tmp) not in f.parents:  # .pptx 원본은 그대로 돌아오므로 사본을 고친다
                    f = Path(shutil.copy(f, Path(tmp) / f"사본_{k}_{j}.pptx"))
                rep.fit_slide_size(str(f), *size)  # 곡 파일은 대개 25.4cm 폭이라 테마 크기로 키운다
                pptxs.append(str(f))
            rep.replace_section_zip(str(out_path), name, pptxs, tmp)
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
    s = sub.add_parser("search", help="1_자료/찬양곡에서 곡 찾기(없으면 종료 코드 2)")
    s.add_argument("제목")
    d = sub.add_parser("download", help="티스토리에서 16:9(_Wide) 곡 내려받기(없으면 종료 코드 2)")
    d.add_argument("제목")
    f = sub.add_parser("fix-background", help="흰 바탕 악보 섹션에 다른 섹션 배경 넣기")
    f.add_argument("파일")
    f.add_argument("--섹션", required=True, action="append")
    f.add_argument("--배경", required=True)
    args = ap.parse_args(argv)
    import check
    import songs

    if args.cmd == "search":
        found = songs.search_file(songs.SONG_DIR, args.제목)
        if not found:
            print(f"NOT_FOUND: '{args.제목}' (폴더: {songs.SONG_DIR})")
            sys.exit(2)
        for i, r in enumerate(found, 1):
            print(f"  {'★' if r['score'] == 2 else '○'} [{i}] {r['file'].name}")
        print(f"BEST_MATCH: {found[0]['file']}")
        return
    if args.cmd == "download":
        got = songs.tistory_download(args.제목, str(songs.SONG_DIR))
        if not got:
            print(f"NOT_FOUND: 티스토리에 '{args.제목}' 16:9(_Wide) 파일이 없습니다. 직접 {songs.SONG_DIR}에 넣어 주세요.")
            sys.exit(2)
        print(f"DOWNLOADED: {got}\nBEST_MATCH: {got}")
        return
    if args.cmd == "fix-background":
        from background import fix_section_background
        for sec in args.섹션:
            print(f"  [{sec}] 배경 보완 {fix_section_background(args.파일, sec, args.배경)}장 (배경: {args.배경})")
        return
    render, verify = check.render, check.verify

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
    if problems:
        sys.exit(1)


if __name__ == "__main__":
    main()
