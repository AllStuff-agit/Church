import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from sources import REPO
from structure import Item, StructureError, THEME_KINDS, parse_structure


class StructureTest(unittest.TestCase):
    def test_default_structure(self):
        items = parse_structure(REPO / "2_템플릿/구조/구조-주일기본.txt")
        self.assertEqual(len(items), 15)
        self.assertEqual(items[0], Item("대기", None))
        self.assertEqual(items[12], Item("찬송", "635"))
        self.assertEqual(len(THEME_KINDS), 9)

    def test_blank_and_spaces(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "s.txt"
            f.write_text("  대기  \n\n찬송   635\n", encoding="utf-8")
            self.assertEqual(parse_structure(f), [Item("대기", None), Item("찬송", "635")])

    def test_unknown_kind(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "s.txt"
            f.write_text("대기\n사도신경\n없는종류\n", encoding="utf-8")
            with self.assertRaisesRegex(StructureError, "3번째 줄: 알 수 없는 항목 '없는종류'"):
                parse_structure(f)


if __name__ == "__main__":
    unittest.main()
