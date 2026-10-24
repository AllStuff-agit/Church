import importlib.util
import unittest
from pathlib import Path

from lxml import etree


SCRIPT = Path(__file__).parents[1] / "scripts" / "ppt_section_replacer.py"
SPEC = importlib.util.spec_from_file_location("ppt_section_replacer", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}

# 악보+흰 바탕 이미지가 <p:bg>에 들어 있는 슬라이드 (비 준비하시니 자료와 같은 구조)
SLIDE = f"""<p:sld xmlns:p="{NS['p']}" xmlns:a="{NS['a']}" xmlns:r="{NS['r']}"><p:cSld>
<p:bg><p:bgPr><a:blipFill rotWithShape="0"><a:blip r:embed="rId1"/><a:stretch/></a:blipFill></p:bgPr></p:bg>
<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>
<p:sp><p:nvSpPr><p:cNvPr id="4" name="쪽번호"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr/></p:sp>
</p:spTree></p:cSld></p:sld>""".encode()


class FixBackgroundTests(unittest.TestCase):
    def test_moves_score_to_transparent_picture_behind_shapes(self):
        tree = etree.fromstring(MODULE._move_bg_to_transparent_pic(SLIDE, 9144000, 6858000))

        bg_blip = tree.find(".//p:bg//a:blip", NS)
        self.assertEqual(bg_blip.get(f"{{{NS['r']}}}embed"), MODULE.BG_FIX_RID)

        sp_tree = tree.find(".//p:spTree", NS)
        pic = sp_tree[2]  # nvGrpSpPr, grpSpPr 다음 = 가장 뒤쪽 레이어
        self.assertEqual(etree.QName(pic).localname, "pic")
        self.assertEqual(pic.find(".//a:blip", NS).get(f"{{{NS['r']}}}embed"), "rId1")
        self.assertIsNotNone(pic.find(".//a:clrChange", NS))
        self.assertEqual(pic.find(".//p:cNvPr", NS).get("id"), "5")
        self.assertEqual(pic.find(".//a:ext", NS).get("cy"), "6858000")

    def test_skips_already_fixed_slide(self):
        once = MODULE._move_bg_to_transparent_pic(SLIDE, 9144000, 6858000)
        self.assertIsNone(MODULE._move_bg_to_transparent_pic(once, 9144000, 6858000))


if __name__ == "__main__":
    unittest.main()
