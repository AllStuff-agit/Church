import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from pptx import Presentation

from fill import fill_verses, split_verse
from fixtures import make_mini_theme
from sources import parse_reference
from theme import find_shape, kind_slides


class SplitVerseTest(unittest.TestCase):
    def test_short(self):
        self.assertEqual(split_verse(1, "여호와께서 모세에게 말씀하여 이르시되", 90), ["1 여호와께서 모세에게 말씀하여 이르시되"])

    def test_long_split_on_word(self):
        text = " ".join(["가나다라마바사"] * 20)  # 159자
        parts = split_verse(7, text, 90)
        self.assertEqual(len(parts), 2)
        self.assertTrue(parts[0].startswith("7 "))
        self.assertFalse(parts[1][0].isdigit())
        self.assertEqual(" ".join([parts[0][2:], parts[1]]), text)
        for p in parts:
            self.assertLessEqual(len(p), 92)


class BalancedSplitTest(unittest.TestCase):
    def test_balanced(self):
        text = " ".join(["가나다라마바사"] * 20)  # 159자 → 두 조각이 비슷한 길이
        a, b = split_verse(7, text, 110)
        self.assertLess(abs(len(a) - len(b)), 10)


class FillVersesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.prs = Presentation(make_mini_theme(Path(self.tmp.name) / "t.pptx"))
        self.sample = kind_slides(self.prs)["말씀구절"][0]

    def tearDown(self):
        self.tmp.cleanup()

    def _text(self, i, box):
        return find_shape(self.prs.slides[i], box).text_frame.text

    def test_numbers_31(self):
        out = fill_verses(self.prs, self.sample, parse_reference("민수기 31:1-6"))
        self.assertEqual(len(out), 6)
        self.assertEqual(self._text(out[0], "구절본문"), "1 여호와께서 모세에게 말씀하여 이르시되")
        self.assertEqual(self._text(out[0], "구절장"), "민수기 31장")

    def test_multi_passage(self):
        out = fill_verses(self.prs, self.sample, parse_reference("마태 4:8-10, 요한 12:12-15"))
        self.assertEqual(len(out), 7)
        self.assertEqual(self._text(out[3], "구절장"), "요한복음 12장")
        self.assertTrue(self._text(out[3], "구절본문").startswith("12 "))

    def test_bundle_label(self):
        out = fill_verses(self.prs, self.sample, parse_reference("신 6:19-20"))
        self.assertTrue(self._text(out[0], "구절본문").startswith("18-19 여호와께서"))

    def test_psalm_unit(self):
        out = fill_verses(self.prs, self.sample, parse_reference("시 23:1"))
        self.assertEqual(self._text(out[0], "구절장"), "시편 23편")


if __name__ == "__main__":
    unittest.main()
