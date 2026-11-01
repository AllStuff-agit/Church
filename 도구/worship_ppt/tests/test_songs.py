import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

import songs as MODULE

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

    def test_selects_only_wide(self):
        attachments = [
            {"url": "https://cdn.example/song.nwc", "label": "song.nwc"},
            {"url": "https://cdn.example/song.PPT", "label": "song.PPT"},
            {"url": "https://cdn.example/song_Wide.PPT", "label": "song_Wide.PPT"},
        ]

        self.assertEqual(MODULE.select_ppt_attachment(attachments), "https://cdn.example/song_Wide.PPT")

    def test_no_wide_returns_none(self):
        # 16:9만 쓴다: 4:3(_Wide 아님) 첨부만 있으면 받지 않는다
        attachments = [
            {"url": "https://cdn.example/song.nwc", "label": "song.nwc"},
            {"url": "https://cdn.example/song.PPT", "label": "song.PPT"},
        ]

        self.assertIsNone(MODULE.select_ppt_attachment(attachments))

    def test_search_file(self):
        found = MODULE.search_file(MODULE.SONG_DIR, "주 품에 품으소서")
        self.assertEqual(found[0]["file"].name, "주 품에 품으소서.PPT")
        self.assertEqual(MODULE.search_file(MODULE.SONG_DIR, "없는곡제목123"), [])

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


if __name__ == "__main__":
    unittest.main()
