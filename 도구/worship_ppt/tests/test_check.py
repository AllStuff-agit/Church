import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from pptx import Presentation

from assemble import assemble
from check import render, verify
from fixtures import make_mini_theme
from sources import REPO
from test_assemble import STRUCTURE, _hymn
from theme import find_shape
import slides


class CheckTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = Path(cls.tmp.name)
        hymns = d / "hymns"
        hymns.mkdir()
        for n in (337, 300, 635):
            _hymn(hymns / f"새찬송가_{n:03d}장.pptx", 1)
        cls.content = {"date": "261101", "교독문": 49, "본문": "사무엘하 21:1-3",
                       "설교제목": "공동체를 회복시키시는 하나님", "찬송": [337, 300],
                       "준비찬양": [str(_hymn(d / "준비.pptx", 1))]}
        cls.out = assemble(STRUCTURE, make_mini_theme(d / "theme.pptx"), cls.content, d / "out.pptx", hymns)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_verify_clean(self):
        self.assertEqual(verify(self.out, self.content), [])

    def test_verify_detects_change(self):
        bad = Path(self.tmp.name) / "bad.pptx"
        prs = Presentation(str(self.out))
        idx = dict(slides.sections(prs))["말씀구절"][0]
        box = find_shape(prs.slides[idx], "구절본문")
        box.text_frame.paragraphs[0].runs[0].text = "1 틀린 본문"
        prs.save(str(bad))
        problems = verify(bad, self.content)
        self.assertEqual(len(problems), 1)
        self.assertIn("1절", problems[0])

    def test_verify_detects_gyodokmun_change(self):
        bad = Path(self.tmp.name) / "bad2.pptx"
        prs = Presentation(str(self.out))
        idx = dict(slides.sections(prs))["교독문"][1]
        find_shape(prs.slides[idx], "교독문본문").text_frame.paragraphs[0].runs[0].text = "엉뚱한 줄"
        prs.save(str(bad))
        problems = verify(bad, self.content)
        self.assertTrue(any("교독문 49" in p for p in problems), problems)

    def test_verify_chapter_label(self):
        bad = Path(self.tmp.name) / "bad3.pptx"
        prs = Presentation(str(self.out))
        idx = dict(slides.sections(prs))["말씀구절"][0]
        find_shape(prs.slides[idx], "구절장").text_frame.paragraphs[0].runs[0].text = "사무엘하 22장"
        prs.save(str(bad))
        self.assertTrue(any("구절장" in p for p in verify(bad, self.content)))

    def test_verify_title(self):
        bad = Path(self.tmp.name) / "bad4.pptx"
        prs = Presentation(str(self.out))
        idx = dict(slides.sections(prs))["본문표지 1"][0]
        find_shape(prs.slides[idx], "설교제목").text_frame.paragraphs[0].runs[0].text = "다른 제목"
        prs.save(str(bad))
        self.assertTrue(any("설교제목" in p for p in verify(bad, self.content)))

    def test_verify_coverage(self):
        content = dict(self.content, 본문="신 6:19-20")
        d = Path(self.tmp.name)
        out = assemble(STRUCTURE, make_mini_theme(d / "t2.pptx"), content, d / "o2.pptx", d / "hymns")
        self.assertEqual(verify(out, content), [])
        prs = Presentation(str(out))
        idx = dict(slides.sections(prs))["말씀구절"][0]
        slides.delete_slides(prs, [idx])
        slides.set_sections(prs, [(n, len(i)) for n, i in slides.sections(prs)])  # 지운 장은 이미 빠져 있음
        prs.save(str(d / "o3.pptx"))
        self.assertTrue(any("19절" in p for p in verify(d / "o3.pptx", content)))

    def test_render(self):
        if shutil.which("pdftoppm") is None:
            self.skipTest("pdftoppm 없음")
        sheet = render(self.out, Path(self.tmp.name) / "png")
        self.assertTrue(sheet.exists())


if __name__ == "__main__":
    unittest.main()
