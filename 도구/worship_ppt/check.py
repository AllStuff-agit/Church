"""만든 예배 PPT 확인: txt 원본과 글자 대조(verify), 그림 미리보기(render)."""
import re
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw
from pptx import Presentation

import slides
from fill import split_tail, split_verse
from sources import display_reference, load_gyodokmun, load_verses, parse_reference
from theme import find_shape

LO_PROFILE = "file:///" + str(Path.home() / "AppData/Local/Temp/worship_ppt_lo").replace("\\", "/")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _kind_indices(prs, kind: str) -> list:
    return [i for name, idx in slides.sections(prs) if name == kind or name.startswith(kind + " ") for i in idx]


def verify(pptx: Path, content: dict) -> list:
    prs = Presentation(str(pptx))
    problems = []

    if "교독문" in content and _kind_indices(prs, "교독문"):
        g = load_gyodokmun(int(content["교독문"]))
        expected = []
        for role, line in g.lines:
            text, tail = split_tail(line)
            if role == "다같이":
                expected.append("(다같이)")
            expected.append(f"{text} {tail}" if tail else text)
        got = []
        for i in _kind_indices(prs, "교독문"):
            body = find_shape(prs.slides[i], "교독문본문")
            if body is not None:
                got += [p.text for p in body.text_frame.paragraphs]
        for k in range(max(len(expected), len(got))):
            a = _norm(got[k]) if k < len(got) else "(없음)"
            b = _norm(expected[k]) if k < len(expected) else "(없음)"
            if a != b:
                problems.append(f"교독문 {g.number} {k + 1}번째 줄: 슬라이드 '{a}' / 원본 '{b}'")

    if "본문" in content:
        passages = parse_reference(content["본문"])
        expected = []
        for p in passages:
            unit = "편" if p.book == "시편" else "장"
            for n, text in load_verses(p):
                for piece in split_verse(n, text):
                    expected.append((f"{p.book} {p.chapter}{unit} {n}절", piece))
        got = [find_shape(prs.slides[i], "구절본문").text_frame.text for i in _kind_indices(prs, "말씀구절")]
        if got or _kind_indices(prs, "말씀구절"):
            for k in range(max(len(expected), len(got))):
                label = expected[k][0] if k < len(expected) else f"{k + 1}번째 장"
                a = _norm(got[k]) if k < len(got) else "(없음)"
                b = _norm(expected[k][1]) if k < len(expected) else "(없음)"
                if a != b:
                    problems.append(f"{label}: 슬라이드 '{a}' / 원본 '{b}'")
        boxes = [find_shape(prs.slides[i], "구절장") for i in _kind_indices(prs, "말씀구절")]
        labels = [e[0].rsplit(" ", 1)[0] for e in expected]
        for k, (box, want) in enumerate(zip(boxes, labels)):
            if _norm(box.text_frame.text) != want:
                problems.append(f"{k + 1}번째 말씀구절 장 구절장: 슬라이드 '{_norm(box.text_frame.text)}' / 원본 '{want}'")
        problems += _coverage(passages, got)
        ref = display_reference(passages)
        for i in _kind_indices(prs, "본문표지"):
            box = find_shape(prs.slides[i], "성경구절")
            if box is not None and _norm(box.text_frame.text) != ref:
                problems.append(f"본문표지 성경구절: 슬라이드 '{_norm(box.text_frame.text)}' / 원본 '{ref}'")
    if content.get("설교제목"):
        want = re.sub(r"[\s()\[\]]", "", content["설교제목"])
        for i in _kind_indices(prs, "본문표지"):
            box = find_shape(prs.slides[i], "설교제목")
            if box is not None:
                got_title = re.sub(r"[\s()\[\]]", "", box.text_frame.text)
            else:
                group = find_shape(prs.slides[i], "본문 타이틀")
                if group is None:
                    continue
                got_title = "".join(sh.text_frame.text for sh in group.shapes if sh.name.startswith("설교제목글자"))
            if got_title != want:
                problems.append(f"본문표지 설교제목: 슬라이드 '{got_title}' / 원본 '{want}'")
    return problems


def _coverage(passages, slide_texts) -> list:
    """원본 장 파일을 직접 읽어(채우기 코드와 별개) 요청한 절이 모두 슬라이드에 있는지 확인한다.
    묶음 절(예: 18-19)은 첫 절 번호로 시작하는 장이 있으면 함께 있는 것으로 본다."""
    from sources import _books

    heads = {int(m.group(1)) for t in slide_texts if (m := re.match(r"(\d+) ", _norm(t)))}
    out = []
    for p in passages:
        unit = "편" if p.book == "시편" else "장"
        f = next(f for f in _books()[p.book].glob("*.txt") if int(re.search(r"(\d+)[장편]$", f.stem).group(1)) == p.chapter)
        ranges = [(int(m.group(1)), int(m.group(2) or m.group(1)))
                  for line in f.read_text(encoding="utf-8").splitlines()
                  if (m := re.match(r"\D+?\d+:(\d+)(?:-(\d+))?\s", line))]
        for v in range(p.start, p.end + 1):
            head = next((a for a, b in ranges if a <= v <= b), None)
            if head is None or head not in heads:
                out.append(f"{p.book} {p.chapter}{unit} {v}절이 슬라이드에 없습니다")
    return out


def render(pptx: Path, out_dir: Path, dpi: int = 40) -> Path:
    """장별 PNG와 장 번호를 붙인 모아보기 sheet.png를 만들고 그 경로를 돌려준다."""
    from insert import soffice

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run([soffice(), f"-env:UserInstallation={LO_PROFILE}", "--headless",
                    "--convert-to", "pdf", "--outdir", str(out_dir), str(pptx)], capture_output=True)
    pdf = out_dir / (Path(pptx).stem + ".pdf")
    if not pdf.exists():
        raise RuntimeError(f"PDF 변환 실패: {pptx}")
    subprocess.run([shutil.which("pdftoppm"), "-r", str(dpi), "-png", str(pdf), str(out_dir / "p")], check=True)
    pngs = sorted(out_dir.glob("p-*.png"))
    ims = [Image.open(p) for p in pngs]
    w, h = ims[0].size
    cols = 4
    sheet = Image.new("RGB", (w * cols, h * ((len(ims) + cols - 1) // cols)), "white")
    for i, im in enumerate(ims):
        x, y = (i % cols) * w, (i // cols) * h
        sheet.paste(im, (x, y))
        ImageDraw.Draw(sheet).text((x + 4, y + 2), str(i + 1), fill="red")
    path = out_dir / "sheet.png"
    sheet.save(path)
    return path
