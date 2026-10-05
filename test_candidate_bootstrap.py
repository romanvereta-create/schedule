import tempfile
import unittest
from pathlib import Path

import candidate_bootstrap as bootstrap


class CandidateBootstrapTests(unittest.TestCase):
    def test_installs_only_release_allowlist(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)

            def download(url):
                return ("payload:" + url.rsplit("/", 1)[-1]).encode()

            result = bootstrap.install(root, downloader=download)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["files"], len(bootstrap.RELEASE_FILES))
            self.assertEqual(
                (root / "bot.py").read_bytes(),
                b"payload:bot.py",
            )
            self.assertTrue((root / "locales" / "en.js").is_file())
            self.assertFalse((root / "data").exists())

    def test_failed_download_keeps_existing_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "bot.py").write_bytes(b"old")
            calls = 0

            def download(_url):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("network")
                return b"new"

            with self.assertRaises(OSError):
                bootstrap.install(root, downloader=download)
            self.assertEqual((root / "bot.py").read_bytes(), b"old")
            self.assertFalse(any(root.rglob("*.new")))


if __name__ == "__main__":
    unittest.main()
