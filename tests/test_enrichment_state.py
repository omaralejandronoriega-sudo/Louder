from __future__ import annotations

import sys
import unittest
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import enrichment_state as es
import build_artists as ba


class EnrichmentStateTests(unittest.TestCase):
    def test_complete_is_terminal(self):
        self.assertFalse(es.is_due({"profile_status": "complete"}))

    def test_legacy_checked_is_not_terminal(self):
        self.assertTrue(es.is_due({"profile_checked_at": es.iso(es.utcnow())}))

    def test_partial_respects_retry_window(self):
        now = es.utcnow()
        self.assertFalse(es.is_due({
            "profile_status": "partial",
            "next_retry_at": es.iso(now + timedelta(hours=1)),
        }, now=now))
        self.assertTrue(es.is_due({
            "profile_status": "partial",
            "next_retry_at": es.iso(now - timedelta(seconds=1)),
        }, now=now))

    def test_profile_requires_valid_image_bio_and_data(self):
        artist = {"bio": "Bio"}
        gallery = {
            "images": [{"url": "https://example.com/a.jpg", "valid": True}],
            "musicbrainz_id": "abc",
        }
        status, missing = es.profile_status(artist, gallery)
        self.assertEqual(status, "complete")
        self.assertEqual(missing, [])

    def test_track_artwork_key_uses_track_for_missing_album(self):
        self.assertEqual(
            ba.track_artwork_key("Artist", {"title": "Song", "album": ""}),
            "track|artist|song",
        )
        self.assertEqual(
            ba.track_artwork_key("Artist", {"title": "Song", "album": "Album"}),
            "artist|album",
        )

    def test_existing_artist_metadata_counts_as_profile_data(self):
        artist = {
            "bio": "Bio",
            "genres": ["indie"],
            "social": [{"name": "Instagram", "url": "https://instagram.com/example"}],
        }
        gallery = {
            "images": [{"url": "https://example.com/a.jpg", "valid": True}],
        }
        status, missing = es.profile_status(artist, gallery)
        self.assertEqual(status, "complete")
        self.assertEqual(missing, [])

    def test_remote_image_validation_requires_real_image_bytes(self):
        class Response:
            def __init__(self, payload: bytes):
                self.url = "https://example.com/image.jpg"
                self.status_code = 200
                self.headers = {"Content-Type": "image/jpeg"}
                self.payload = payload

            def iter_content(self, chunk_size: int):
                yield self.payload

        class Session:
            def __init__(self, payload: bytes):
                self.payload = payload

            def get(self, *args, **kwargs):
                return Response(self.payload)

        fake_html = b"<html>not an image</html>" + (b"x" * 300)
        ok, _, reason = es.validate_remote_image(Session(fake_html), "https://example.com/image.jpg")
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("invalid_bytes"))

        fake_jpeg = b"\xff\xd8\xff" + (b"x" * 300)
        ok, _, reason = es.validate_remote_image(Session(fake_jpeg), "https://example.com/image.jpg")
        self.assertTrue(ok)
        self.assertEqual(reason, "bytes")

    def test_unvalidated_image_is_missing(self):
        artist = {"bio": "Bio"}
        gallery = {
            "images": [{"url": "https://example.com/a.jpg"}],
            "musicbrainz_id": "abc",
        }
        status, missing = es.profile_status(artist, gallery)
        self.assertEqual(status, "partial")
        self.assertIn("image", missing)


if __name__ == "__main__":
    unittest.main()
