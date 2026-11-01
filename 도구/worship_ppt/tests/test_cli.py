import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1]))

import assemble


class CliTest(unittest.TestCase):
    def test_search_found(self):
        out = io.StringIO()
        with redirect_stdout(out):
            assemble.main(["search", "주 품에 품으소서"])
        self.assertIn("BEST_MATCH:", out.getvalue())

    def test_search_missing_exits_2(self):
        with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as cm:
            assemble.main(["search", "없는곡제목123"])
        self.assertEqual(cm.exception.code, 2)

    def test_download_missing_exits_2(self):
        with patch("songs.tistory_download", return_value=None), redirect_stdout(io.StringIO()), \
                self.assertRaises(SystemExit) as cm:
            assemble.main(["download", "없는곡"])
        self.assertEqual(cm.exception.code, 2)

    def test_build_exits_1_on_verify_problems(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "c.json"
            f.write_text(json.dumps({"date": "261101"}), encoding="utf-8")
            with patch("assemble.assemble", return_value=Path(d) / "x.pptx"), \
                    patch("assemble.Presentation"), patch("slides.sections", return_value=[]), \
                    patch("check.verify", return_value=["다름"]), redirect_stdout(io.StringIO()), \
                    self.assertRaises(SystemExit) as cm:
                assemble.main(["build", "--구조", "s", "--테마", "t", "--내용", str(f), "--출력", str(Path(d) / "x.pptx")])
            self.assertEqual(cm.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
