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
        ref = display_reference(passages)
        for i in _kind_indices(prs, "본문표지"):
            box = find_shape(prs.slides[i], "성경구절")
            if box is not None and _norm(box.text_frame.text) != ref:
                problems.append(f"본문표지 성경구절: 슬라이드 '{_norm(box.text_frame.text)}' / 원본 '{ref}'")
    return problems


def render(pptx: Path, out_dir: Path, dpi: int = 40) -> Path:
    """장별 PNG와 장 번호를 붙인 모아보기 sheet.png를 만들고 그 경로를 돌려준다."""
    from assemble import _replacer

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run([_replacer().soffice(), f"-env:UserInstallation={LO_PROFILE}", "--headless",
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
