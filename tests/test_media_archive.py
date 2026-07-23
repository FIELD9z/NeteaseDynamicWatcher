from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import ipaddress

from netease_dynamic_watcher.media_archive import (
    archive_database_media,
    is_proxy_fake_ip,
    validate_download_target,
)
from netease_dynamic_watcher.models import Event
from netease_dynamic_watcher.store import StateStore
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

    def test_proxy_fake_ip_range_is_explicit(self):
        self.assertTrue(is_proxy_fake_ip(ipaddress.ip_address("198.18.0.1")))
        self.assertTrue(is_proxy_fake_ip(ipaddress.ip_address("198.19.255.255")))
        self.assertFalse(is_proxy_fake_ip(ipaddress.ip_address("192.168.1.1")))

    def test_fake_ip_is_accepted_only_after_netease_hostname_allowlist(self):
        fake_ip = [(2, 1, 6, "", ("198.18.0.7", 443))]
        with mock.patch(
            "netease_dynamic_watcher.media_archive.socket.getaddrinfo",
            return_value=fake_ip,
        ):
            validate_download_target(
                "https://p1.music.126.net/a.jpg",
                ("music.126.net",),
            )
            with self.assertRaisesRegex(ValueError, "允许列表"):
                validate_download_target(
                    "https://attacker.example/a.jpg",
                    ("music.126.net",),
                )

    def test_private_loopback_unknown_and_dangerous_urls_are_rejected(self):
        allowed = ("music.126.net",)
        for address in ("127.0.0.1", "10.0.0.8", "172.16.0.2", "192.168.1.2"):
            with self.subTest(address=address), mock.patch(
                "netease_dynamic_watcher.media_archive.socket.getaddrinfo",
                return_value=[(2, 1, 6, "", (address, 443))],
            ):
                with self.assertRaisesRegex(ValueError, "非公网地址"):
                    validate_download_target(
                        "https://p1.music.126.net/a.jpg",
                        allowed,
                    )

        for url in (
            "https://unknown.example/a.jpg",
            "file:///etc/passwd",
            "https://user:password@p1.music.126.net/a.jpg",
            "https://p1.music.126.net:444/a.jpg",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_download_target(url, allowed)

    def test_equal_content_is_stored_as_one_physical_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "watcher.sqlite3"
            media = root / "media"
            manifest = media / "manifest.json"
            store = StateStore(str(database))
            for event_id, image_url in (
                ("one", "https://p1.music.126.net/one.jpg"),
                ("two", "https://p1.music.126.net/two.jpg"),
            ):
                store.save(
                    Event(
                        event_id=event_id,
                        user_id="u",
                        nickname="offline",
                        event_type="image",
                        summary=event_id,
                        publish_time_ms=1,
                        url="",
                        image_urls=(image_url,),
                    )
                )

            def fake_download(
                opener,
                url,
                destination_without_suffix,
                *,
                expected_kind,
                timeout,
                max_bytes,
            ):
                destination = destination_without_suffix.with_suffix(".jpg")
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"identical offline bytes")
                return destination, 23, "image/jpeg", "same-content-digest"

            with (
                mock.patch(
                    "netease_dynamic_watcher.media_archive.socket.getaddrinfo",
                    return_value=[(2, 1, 6, "", ("8.8.8.8", 443))],
                ),
                mock.patch(
                    "netease_dynamic_watcher.media_archive.download_one",
                    side_effect=fake_download,
                ),
            ):
                report = archive_database_media(
                    database,
                    output_dir=media,
                    manifest_path=manifest,
                )

            physical_files = [
                path
                for path in media.rglob("*")
                if path.is_file() and path != manifest
            ]
            items = json.loads(manifest.read_text(encoding="utf-8"))["items"]
            self.assertEqual(report["downloaded"], 1)
            self.assertEqual(report["deduplicated"], 1)
            self.assertEqual(len(physical_files), 1)
            self.assertEqual(items[0]["local_path"], items[1]["local_path"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
