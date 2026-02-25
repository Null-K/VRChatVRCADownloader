import os
import tempfile
import unittest
from http.cookies import SimpleCookie
from unittest.mock import patch

import vrchat_vrca_downloader as app


class CookieObject:
    def __init__(self, name, value):
        self.name = name
        self.value = value


class DownloadUtilsTests(unittest.TestCase):
    def test_build_avatar_cache_filename(self):
        name = app.build_avatar_cache_filename("file_abc", "https://x/y.png")
        self.assertTrue(name.startswith("file_abc_"))
        self.assertTrue(name.endswith(".img"))

    def test_build_avatar_image_map(self):
        avatars = [
            {
                "imageUrl": "https://img.example.com/a.png",
                "unityPackages": [{"assetUrl": "https://api.vrchat.cloud/api/1/file/file_123/1/file"}],
            }
        ]
        mapping = app.build_avatar_image_map(avatars)
        self.assertEqual(mapping.get("file_123"), "https://img.example.com/a.png")

    def test_build_cookie_header_from_webview_cookies_dict(self):
        value = app.build_cookie_header_from_webview_cookies(
            [{"name": "auth", "value": "abc"}, {"name": "twoFactorAuth", "value": "xyz"}]
        )
        self.assertEqual(value, "auth=abc; twoFactorAuth=xyz;")

    def test_build_cookie_header_from_webview_cookies_str(self):
        value = app.build_cookie_header_from_webview_cookies(["auth=abc", "foo=bar"])
        self.assertEqual(value, "auth=abc; foo=bar;")

    def test_build_cookie_helper_command_frozen(self):
        cmd = app.build_cookie_helper_command(True, "app.exe", "main.py", "out.json")
        self.assertEqual(cmd, ["app.exe", "--cookie-helper", "out.json"])

    def test_build_cookie_helper_command_source(self):
        cmd = app.build_cookie_helper_command(False, "python.exe", "main.py", "out.json")
        self.assertEqual(cmd, ["python.exe", "main.py", "--cookie-helper", "out.json"])

    def test_build_custom_filename_default(self):
        avatar = {"name": "Avatar - 黑巧 - Asset bundle - x", "version": 2, "file_id": "file_1", "created_at": "2026-02-25T01:02:03Z"}
        self.assertEqual(app.build_custom_filename("", avatar), "黑巧.vrca")

    def test_build_custom_filename_template(self):
        avatar = {"name": "N", "version": 3, "file_id": "file_1", "created_at": "2026-02-25T01:02:03Z"}
        value = app.build_custom_filename("{name}_{version}_{id}_{date}", avatar)
        self.assertEqual(value, "N_3_file_1_2026-02-25.vrca")

    def test_build_custom_filename_unknown_placeholder(self):
        avatar = {"name": "N", "version": 3, "file_id": "file_1"}
        value = app.build_custom_filename("{unknown}", avatar)
        self.assertTrue(value.endswith(".vrca"))

    def test_build_proxy_dict_empty(self):
        self.assertIsNone(app.build_proxy_dict(""))

    def test_build_proxy_dict_invalid(self):
        with self.assertRaises(ValueError):
            app.build_proxy_dict("127.0.0.1:7890")

    def test_build_proxy_dict_valid(self):
        value = app.build_proxy_dict("http://127.0.0.1:7890")
        self.assertEqual(value, {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"})

    def test_compute_aggregate_progress(self):
        percent, downloaded, total = app.compute_aggregate_progress(
            [{"downloaded": 50, "total": 100}, {"downloaded": 25, "total": 100}, {"downloaded": 1, "total": 0}]
        )
        self.assertEqual((percent, downloaded, total), (37.5, 75, 200))

    def test_extract_auth_from_webview_cookies_dict(self):
        self.assertEqual(app.extract_auth_from_webview_cookies([{"name": "auth", "value": "abc"}]), "abc")

    def test_extract_auth_from_webview_cookies_object(self):
        self.assertEqual(app.extract_auth_from_webview_cookies([CookieObject("auth", "abc")]), "abc")

    def test_extract_auth_from_webview_cookies_simple_cookie(self):
        c = SimpleCookie()
        c["auth"] = "abc"
        self.assertEqual(app.extract_auth_from_webview_cookies([c]), "abc")

    def test_extract_auth_from_webview_cookies_str(self):
        self.assertEqual(app.extract_auth_from_webview_cookies(["auth=abc"]), "abc")

    def test_extract_avatar_image_url_direct(self):
        file_item = {"imageUrl": "https://x/a.png"}
        self.assertEqual(app.extract_avatar_image_url(file_item, {}), "https://x/a.png")

    def test_extract_avatar_image_url_nested(self):
        file_item = {"foo": {"bar": ["https://x/a.webp"]}}
        self.assertEqual(app.extract_avatar_image_url(file_item, {}), "https://x/a.webp")

    def test_extract_avatar_image_url_none(self):
        self.assertIsNone(app.extract_avatar_image_url({}, {}))

    def test_extract_cookie_tokens(self):
        value = app.extract_cookie_tokens("auth=abc; twoFactorAuth=xyz;")
        self.assertEqual(value, {"auth": "abc", "twoFactorAuth": "xyz"})

    def test_extract_cookie_tokens_auth_only(self):
        value = app.extract_cookie_tokens("auth=abc;")
        self.assertEqual(value, {"auth": "abc", "twoFactorAuth": None})

    def test_extract_file_id_from_url(self):
        self.assertEqual(
            app.extract_file_id_from_url("https://api.vrchat.cloud/api/1/file/file_123/1/file"),
            "file_123",
        )

    def test_extract_short_avatar_name(self):
        self.assertEqual(app.extract_short_avatar_name("Avatar - 黑巧 - Asset bundle - xx"), "黑巧")

    def test_format_bytes(self):
        self.assertEqual(app.format_bytes(0), "0 B")
        self.assertEqual(app.format_bytes(1024), "1.0 KB")

    def test_is_auth_user_response_valid(self):
        self.assertTrue(app.is_auth_user_response_valid(200, {"id": "usr_x"}))
        self.assertFalse(app.is_auth_user_response_valid(200, {"requiresTwoFactorAuth": True}))

    def test_is_stalled(self):
        self.assertTrue(app.is_stalled(100.0, 130.0, 25))
        self.assertFalse(app.is_stalled(100.0, 120.0, 25))

    def test_resolve_conflict_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "a.vrca")
            with open(src, "w", encoding="utf-8") as f:
                f.write("x")
            resolved = app.resolve_conflict_path(src)
            self.assertNotEqual(resolved, src)
            self.assertTrue(resolved.endswith(".vrca"))

    def test_should_finalize_auth_capture(self):
        self.assertTrue(app.should_finalize_auth_capture("abc", True))
        self.assertFalse(app.should_finalize_auth_capture("", True))


if __name__ == "__main__":
    unittest.main()
