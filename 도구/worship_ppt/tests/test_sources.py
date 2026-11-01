import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from sources import Passage, SourceError, display_reference, load_gyodokmun, load_verses, parse_reference


class GyodokmunTest(unittest.TestCase):
    def test_gyodokmun_9(self):
        g = load_gyodokmun(9)
        self.assertEqual(g.title, "시편 15편")
        self.assertEqual(g.lines[0], ("인도", "여호와여 주의 장막에 머무를 자 누구오며"))
        self.assertEqual(g.lines[-1][0], "회중")
        self.assertTrue(g.lines[-1][1].endswith("(1-5) (아멘)"))

    def test_missing_gyodokmun(self):
        with self.assertRaisesRegex(SourceError, "교독문 999"):
            load_gyodokmun(999)


class ReferenceTest(unittest.TestCase):
    def test_reference_variants(self):
        self.assertEqual(parse_reference("삼하 21:1-14"), [Passage("사무엘하", 21, 1, 14)])
        self.assertEqual(parse_reference("사무엘하 21:1~14"), [Passage("사무엘하", 21, 1, 14)])
        self.assertEqual(parse_reference("요한1서 4:7")[0].book, "요한일서")
        self.assertEqual(parse_reference("시 23:1-6")[0].book, "시편")

    def test_reference_multi(self):
        self.assertEqual(parse_reference("마태 4:8-10, 요한 12:12-15"),
                         [Passage("마태복음", 4, 8, 10), Passage("요한복음", 12, 12, 15)])
        self.assertEqual(parse_reference("사무엘하 21:1-22:3"),
                         [Passage("사무엘하", 21, 1, 22), Passage("사무엘하", 22, 1, 3)])

    def test_display(self):
        self.assertEqual(display_reference([Passage("민수기", 31, 1, 6)]), "민수기 31장 1-6절")
        self.assertEqual(display_reference([Passage("시편", 23, 1, 6)]), "시편 23편 1-6절")


class VerseTest(unittest.TestCase):
    def test_verses_strip_heading(self):
        vs = load_verses(Passage("창세기", 1, 1, 2))
        self.assertEqual(vs[0], (1, "태초에 하나님이 천지를 창조하시니라"))
        self.assertEqual(len(vs), 2)

    def test_missing_verse(self):
        with self.assertRaisesRegex(SourceError, "민수기 31장 60절"):
            load_verses(Passage("민수기", 31, 60, 60))


if __name__ == "__main__":
    unittest.main()
