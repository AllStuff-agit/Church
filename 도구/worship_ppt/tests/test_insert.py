import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from pptx import Presentation
from pptx.util import Emu, Pt

from insert import fit_slide_size


def _small(path: Path, w=9144000, h=5143500) -> Path:
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(w), Emu(h)
    s = prs.slides.add_slide(prs.slide_layouts[6])
    tb = s.shapes.add_textbox(Emu(900000), Emu(450000), Emu(1800000), Emu(900000))
    tb.text_frame.text = "가사"
    tb.text_frame.paragraphs[0].runs[0].font.size = Pt(30)
    g = s.shapes.add_group_shape()
    g.shapes.add_textbox(Emu(600000), Emu(300000), Emu(300000), Emu(300000)).text_frame.text = "묶음"
    prs.save(path)
    return path


class FitSlideSizeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_scales_shapes_and_fonts_to_target_size(self):
        f = _small(self.dir / "a.pptx")
        fit_slide_size(str(f), 12192000, 6858000)
        prs = Presentation(str(f))
        self.assertEqual((prs.slide_width, prs.slide_height), (12192000, 6858000))
        tb = prs.slides[0].shapes[0]
        self.assertAlmostEqual(tb.left, 1200000, delta=2000)
        self.assertAlmostEqual(tb.top, 600000, delta=2000)
        self.assertAlmostEqual(tb.width, 2400000, delta=2000)
        self.assertEqual(tb.text_frame.paragraphs[0].runs[0].font.size.pt, 40)
        g = prs.slides[0].shapes[1]
        self.assertAlmostEqual(g.left, 800000, delta=2000)
        self.assertAlmostEqual(g.width, 400000, delta=2000)
        self.assertEqual(g.shapes[0].left, 600000)  # 묶음 안은 묶음 좌표 그대로

    def test_other_ratio_keeps_aspect_and_centers(self):
        f = _small(self.dir / "b.pptx", 9144000, 6858000)  # 4:3 → 16:9: 세로 맞춤, 가로 가운데
        fit_slide_size(str(f), 12192000, 6858000)
        tb = Presentation(str(f)).slides[0].shapes[0]
        self.assertEqual(tb.width, 1800000)
        self.assertEqual(tb.left, 900000 + (12192000 - 9144000) // 2)

    def test_same_size_untouched(self):
        f = _small(self.dir / "c.pptx", 12192000, 6858000)
        before = f.read_bytes()
        fit_slide_size(str(f), 12192000, 6858000)
        self.assertEqual(f.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
