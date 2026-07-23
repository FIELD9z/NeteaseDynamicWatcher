from __future__ import annotations

import unittest

from tools.archive_media import host_is_allowed, validate_url_syntax
from netease_dynamic_watcher.media_archive import is_proxy_fake_ip
import ipaddress


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

    def test_proxy_fake_ip_range_is_explicit(self):
        self.assertTrue(is_proxy_fake_ip(ipaddress.ip_address("198.18.0.1")))
        self.assertFalse(is_proxy_fake_ip(ipaddress.ip_address("192.168.1.1")))


if __name__ == "__main__":
    unittest.main()
