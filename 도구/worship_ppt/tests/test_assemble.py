import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from pptx import Presentation
from pptx.util import Emu

import slides
from assemble import assemble, check_inputs
from fill import chars_per_line, paginate_gyodokmun, split_verse
from fixtures import make_mini_theme
from sources import REPO, load_gyodokmun, load_verses, parse_reference
from structure import parse_structure
from theme import find_shape, kind_slides

STRUCTURE = REPO / "2_템플릿/구조/구조-주일기본.txt"


def _hymn(path: Path, n_slides: int) -> Path:
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(12192000), Emu(6858000)
    for i in range(n_slides):
        s = prs.slides.add_slide(prs.slide_layouts[6])
        s.shapes.add_textbox(0, 0, Emu(1000000), Emu(500000)).text_frame.text = f"{path.stem} {i + 1}"
    prs.save(path)
    return path


class AssembleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.theme = make_mini_theme(self.dir / "theme.pptx")
        self.hymns = self.dir / "hymns"
        self.hymns.mkdir()
        for n in (337, 300, 635):
            _hymn(self.hymns / f"새찬송가_{n:03d}장.pptx", 2)
        self.prep = _hymn(self.dir / "준비곡.pptx", 3)
        self.content = {"date": "261101", "교독문": 49, "본문": "사무엘하 21:1-3",
                        "설교제목": "공동체를 회복시키시는 하나님", "찬송": [337, 300],
                        "준비찬양": [str(self.prep)]}

    def tearDown(self):
        self.tmp.cleanup()

    def test_check_ok(self):
        self.assertEqual(check_inputs(parse_structure(STRUCTURE), self.theme, self.content, self.hymns), [])

    def test_check_missing_hymn(self):
        bad = dict(self.content, 찬송=[999, 300])
        probs = check_inputs(parse_structure(STRUCTURE), self.theme, bad, self.hymns)
        self.assertTrue(any("찬송 999장" in p for p in probs), probs)

    def test_check_hymn_count(self):
        bad = dict(self.content, 찬송=[337])
        probs = check_inputs(parse_structure(STRUCTURE), self.theme, bad, self.hymns)
        self.assertTrue(any("찬송" in p and "2곡" in p for p in probs), probs)

    def test_check_missing_prep(self):
        bad = dict(self.content, 준비찬양=["없는곡.pptx"])
        probs = check_inputs(parse_structure(STRUCTURE), self.theme, bad, self.hymns)
        self.assertTrue(any("없는곡.pptx" in p for p in probs), probs)

    def test_check_no_prep_list(self):
        bad = {k: v for k, v in self.content.items() if k != "준비찬양"}
        probs = check_inputs(parse_structure(STRUCTURE), self.theme, bad, self.hymns)
        self.assertIn("내용에 '준비찬양'이 없습니다", probs)

    def test_check_bad_number(self):
        bad = dict(self.content, 교독문="49번")
        probs = check_inputs(parse_structure(STRUCTURE), self.theme, bad, self.hymns)
        self.assertTrue(any("교독문" in p and "49번" in p for p in probs), probs)

    def test_structure_bad_hymn_number(self):
        f = self.dir / "s.txt"
        f.write_text("찬송 635장\n", encoding="utf-8")
        probs = check_inputs(parse_structure(f), self.theme, {"찬송": []}, self.hymns)
        self.assertTrue(any("635장" in p for p in probs), probs)

    def test_chorus_first(self):
        content = dict(self.content, 준비찬양=[{"파일": str(self.prep), "후렴": [2, 3]}])
        out = assemble(STRUCTURE, self.theme, content, self.dir / "c.pptx", self.hymns)
        prs = Presentation(str(out))
        idx = dict(slides.sections(prs))["준비찬양 1"]
        texts = [prs.slides[i].shapes[0].text_frame.text for i in idx]
        self.assertEqual(texts, ["준비곡 2", "준비곡 3", "준비곡 1", "준비곡 2", "준비곡 3"])

    def test_one_section_per_song(self):
        second = _hymn(self.dir / "둘째곡.pptx", 2)
        content = dict(self.content, 준비찬양=[str(self.prep), {"파일": str(second), "후렴": [2]}])
        out = assemble(STRUCTURE, self.theme, content, self.dir / "m.pptx", self.hymns)
        secs = slides.sections(Presentation(str(out)))
        names = [n for n, _ in secs]
        self.assertEqual(names[:4], ["대기 1", "준비찬양 1", "준비찬양 2", "대기 2"])
        count = {n: len(i) for n, i in secs}
        self.assertEqual(count["준비찬양 1"], 3)
        self.assertEqual(count["준비찬양 2"], 3)  # 후렴 1장 + 전체 2장

    def test_chorus_out_of_range(self):
        content = dict(self.content, 준비찬양=[{"파일": str(self.prep), "후렴": [9]}])
        probs = check_inputs(parse_structure(STRUCTURE), self.theme, content, self.hymns)
        self.assertTrue(any("후렴 장 번호 9" in p for p in probs), probs)

    def test_assemble(self):
        out = assemble(STRUCTURE, self.theme, self.content, self.dir / "out.pptx", self.hymns)
        prs = Presentation(str(out))
        secs = slides.sections(prs)
        names = [n for n, _ in secs]
        self.assertEqual(names, ["대기 1", "준비찬양 1", "대기 2", "사도신경", "교독문", "참회기도", "찬송 1",
                                 "본문표지 1", "말씀구절", "본문표지 2", "찬송 2", "소식", "찬송 3", "축도", "엔딩"])
        count = {n: len(i) for n, i in secs}
        tp = Presentation(str(self.theme))
        body = find_shape(tp.slides[kind_slides(tp)["교독문"][1]], "교독문본문")
        pages = paginate_gyodokmun(load_gyodokmun(49).lines, chars=chars_per_line(body))
        self.assertEqual(count["교독문"], 1 + len(pages))
        expected = sum(len(split_verse(n, v)) for p in parse_reference("사무엘하 21:1-3") for n, v in load_verses(p))
        self.assertEqual(count["말씀구절"], expected)
        self.assertEqual(count["준비찬양 1"], 3)
        self.assertEqual(count["찬송 1"], 2)
        self.assertEqual(len(prs.slides), sum(count.values()))


if __name__ == "__main__":
    unittest.main()
