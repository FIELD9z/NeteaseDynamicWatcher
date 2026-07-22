from __future__ import annotations

import unittest

from tools.archive_media import host_is_allowed, validate_url_syntax


class MediaArchiverTests(unittest.TestCase):
    def test_allowed_media_host(self):
        self.assertTrue(host_is_allowed("img.music.126.net", ("music.126.net",)))

    def test_reject_unknown_host(self):
        with self.assertRaises(ValueError):
            validate_url_syntax(
                "https://example.com/a.jpg",
                ("music.126.net",),
            )

    def test_reject_non_http_scheme(self):
        with self.assertRaises(ValueError):
            validate_url_syntax(
                "file:///tmp/a.jpg",
                ("music.126.net",),
            )


if __name__ == "__main__":
    unittest.main()
