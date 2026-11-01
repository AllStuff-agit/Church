import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from pptx import Presentation

import slides
from fixtures import make_mini_theme
from structure import THEME_KINDS
from theme import find_kind_slides, find_shape, kind_slides, validate_theme


class ThemeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_valid_theme(self):
        path = make_mini_theme(self.dir / "t.pptx")
        self.assertEqual(validate_theme(path, list(THEME_KINDS)), [])

    def test_missing_section(self):
        path = make_mini_theme(self.dir / "t.pptx", skip_kind="교독문")
        self.assertEqual(validate_theme(path, list(THEME_KINDS)), ["이 테마에는 교독문 슬라이드가 없습니다"])

    def test_missing_box(self):
        path = make_mini_theme(self.dir / "t.pptx", rename=("구절장", "다른이름"))
        self.assertEqual(validate_theme(path, list(THEME_KINDS)), ["말씀구절 슬라이드에 '구절장' 상자가 없습니다"])

    def test_boxes_on_second_slide_of_section(self):
        # 교독문 섹션: 표지 장 + 본문 장. 본문 상자가 두 번째 장에 있어도 통과해야 함
        path = make_mini_theme(self.dir / "t.pptx", cover=True)
        self.assertEqual(validate_theme(path, list(THEME_KINDS)), [])
        prs = Presentation(path)
        self.assertEqual(len(kind_slides(prs)["교독문"]), 2)

    def test_find_kind_slides(self):
        prs = Presentation(make_mini_theme(self.dir / "t.pptx"))
        found = find_kind_slides(prs)
        self.assertEqual(found["대기"], 0)
        self.assertEqual(found["엔딩"], 9)
        self.assertIsNotNone(find_shape(prs.slides[found["말씀구절"]], "구절본문"))
        self.assertIsNone(find_shape(prs.slides[0], "없는상자"))


class SlideOpsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_duplicate_slide(self):
        prs = Presentation(make_mini_theme(self.dir / "t.pptx"))
        new = slides.duplicate_slide(prs, 6)
        self.assertEqual(new, 10)
        self.assertIsNotNone(find_shape(prs.slides[new], "구절본문"))  # 저장 전 메모리에서도 보여야 함
        out = self.dir / "o.pptx"
        prs.save(out)
        prs2 = Presentation(out)
        self.assertEqual(len(prs2.slides), 11)
        self.assertIsNotNone(find_shape(prs2.slides[10], "구절본문"))

    def test_delete_and_sections(self):
        prs = Presentation(make_mini_theme(self.dir / "t.pptx"))
        slides.delete_slides(prs, [1, 2, 3, 4, 5, 6, 7, 8])
        self.assertEqual(len(prs.slides), 2)
        slides.duplicate_slide(prs, 0)
        slides.set_sections(prs, [("대기", 2), ("교독문", 1)])
        out = self.dir / "o.pptx"
        prs.save(out)
        self.assertEqual(slides.section_names(Presentation(out)), ["대기", "교독문"])


if __name__ == "__main__":
    unittest.main()
