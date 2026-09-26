import importlib.util
import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).parents[1] / "scripts" / "ppt_section_replacer.py"
SPEC = importlib.util.spec_from_file_location("ppt_section_replacer", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


BASE = "https://cwy0675.tistory.com"


class TistorySearchTests(unittest.TestCase):
    def test_builds_internal_tistory_search_url(self):
        url = MODULE.build_site_search_url("찬송을 부르세요", BASE)

        self.assertEqual(
            url,
            "https://cwy0675.tistory.com/search/%EC%B0%AC%EC%86%A1%EC%9D%84%20%EB%B6%80%EB%A5%B4%EC%84%B8%EC%9A%94",
        )
        self.assertNotIn("google.com", url)
        self.assertNotIn("keyword=", url)

    def test_prefers_direct_song_post_over_child_song_result(self):
        html = """
        <a href="/entry/어린이-찬송가-412장-찬송을-부르세요-찬송을-부르세요-NWC-PPT-악보-가사">
          어린이 찬송가 412장 찬송을 부르세요 찬송을 부르세요 NWC PPT 악보 가사
        </a>
        <a href="/entry/찬송을-부르세요-NWC-PPT악보">
          찬송을 부르세요 찬송을 부르세요 놀라운 일이 생깁니다 NWC PPT 악보 가사
        </a>
        """

        candidates = MODULE.extract_site_search_candidates(html, BASE)
        chosen = MODULE.choose_site_search_result("찬송을 부르세요", candidates)

        self.assertEqual(chosen, f"{BASE}/entry/찬송을-부르세요-NWC-PPT악보")

    def test_selects_general_ppt_and_skips_nwc_and_wide(self):
        attachments = [
            {"url": "https://cdn.example/song.nwc", "label": "song.nwc"},
            {"url": "https://cdn.example/song.PPT", "label": "song.PPT"},
            {"url": "https://cdn.example/song_Wide.PPT", "label": "song_Wide.PPT"},
        ]

        chosen = MODULE.select_ppt_attachment(attachments)

        self.assertEqual(chosen, "https://cdn.example/song.PPT")

    def test_returns_no_attachment_when_post_has_no_general_ppt(self):
        attachments = [
            {"url": "https://cdn.example/song.nwc", "label": "song.nwc"},
            {"url": "https://cdn.example/song_Wide.PPT", "label": "song_Wide.PPT"},
        ]

        self.assertIsNone(MODULE.select_ppt_attachment(attachments))

    def test_does_not_treat_comment_password_field_as_protected_post(self):
        html = """
        <div class="entry"><a href="https://cdn.example/song.PPT">song.PPT</a></div>
        <form action="/comment/add/5527">
          <input type="password" name="password" id="password_5527" />
          <textarea name="comment"></textarea>
        </form>
        """

        self.assertFalse(MODULE.is_password_protected_post(html))

    def test_detects_tistory_protected_post_marker(self):
        html = """
        <div class="entryProtected">
          보호되어 있는 글입니다. 내용을 보시려면 비밀번호를 입력하세요.
          <form action="/entry/password" method="post">
            <input type="password" name="password" />
          </form>
        </div>
        """

        self.assertTrue(MODULE.is_password_protected_post(html))

    def test_download_reports_the_file_it_just_saved(self):
        args = type(
            "Args",
            (),
            {
                "title": "찬송을 부르세요",
                "folder": "/tmp/praise",
            },
        )()
        output = io.StringIO()

        with patch.object(
            MODULE,
            "tistory_download",
            return_value="/tmp/praise/new-song.PPT",
        ), patch.object(
            MODULE,
            "search_file",
            return_value=[{"file": Path("/tmp/praise/old-song.pptx")}],
        ), redirect_stdout(output):
            MODULE.cmd_download(args)

        self.assertIn("BEST_MATCH: /tmp/praise/new-song.PPT", output.getvalue())


if __name__ == "__main__":
    unittest.main()
