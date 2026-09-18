import os
import tempfile
from unittest.mock import patch

from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from accounts.models import CustomUser
from panel_admin.views import (
    format_compact_number,
    parse_cookie_file,
    get_cookie_file_path,
)


class PanelAdminHelpersTests(TestCase):
    """
    Unit tests for panel_admin formatting and parsing utilities.
    """

    def test_format_compact_number(self):
        self.assertEqual(format_compact_number(500), "500")
        self.assertEqual(format_compact_number(1500), "1.5K")
        self.assertEqual(format_compact_number(2000), "2K")
        self.assertEqual(format_compact_number(1_500_000), "1.5M")
        self.assertEqual(format_compact_number(2_000_000_000), "2B")
        self.assertEqual(format_compact_number("invalid"), "0")
        self.assertEqual(format_compact_number(None), "0")

    def test_parse_cookie_file_non_existent(self):
        non_existent = "non_existent_cookies_9999.txt"
        info = parse_cookie_file(non_existent)
        self.assertFalse(info["exists"])
        self.assertEqual(info["total_cookies"], 0)
        self.assertFalse(info["instagram"]["active"])
        self.assertFalse(info["facebook"]["active"])

    def test_parse_cookie_file_valid_netscape(self):
        cookie_data = (
            "# Netscape HTTP Cookie File\n"
            "# Ignored comment line\n\n"
            ".instagram.com\tTRUE\t/\tTRUE\t1767225600\tsessionid\tig_session_abc123\n"
            ".instagram.com\tTRUE\t/\tTRUE\t1767225600\tds_user_id\t55443322\n"
            ".facebook.com\tTRUE\t/\tTRUE\t1767225600\tc_user\t99887766\n"
            ".facebook.com\tTRUE\t/\tTRUE\t1767225600\txs\tfb_xs_token\n"
            ".google.com\tTRUE\t/\tTRUE\t1767225600\tNID\tsome_nid\n"
        )
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w", encoding="utf-8") as f:
            f.write(cookie_data)
            temp_path = f.name

        try:
            info = parse_cookie_file(temp_path)
            self.assertTrue(info["exists"])
            self.assertEqual(info["total_cookies"], 5)
            self.assertTrue(info["instagram"]["active"])
            self.assertEqual(info["instagram"]["user_id"], "55443322")
            self.assertTrue(info["instagram"]["has_session"])
            self.assertTrue(info["facebook"]["active"])
            self.assertEqual(info["facebook"]["user_id"], "99887766")
            self.assertTrue(info["facebook"]["has_session"])
            self.assertIn("google.com", info["other_domains"])
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


class CookiesManagementSecurityTests(TestCase):
    """
    Tests ensuring strict RBAC for cookies management views.
    Only superadmins should have access.
    """

    def setUp(self):
        self.client = Client()
        self.regular_user = CustomUser.objects.create_user(
            username="regular", password="password123", role="user"
        )
        self.admin_user = CustomUser.objects.create_user(
            username="admin", password="password123", role="admin"
        )
        self.superadmin_user = CustomUser.objects.create_user(
            username="superadmin", password="password123", role="superadmin"
        )

    def test_cookies_view_unauthenticated_redirects(self):
        response = self.client.get(reverse("cookies_management"))
        self.assertEqual(response.status_code, 302)

    def test_cookies_view_regular_user_denied(self):
        self.client.login(username="regular", password="password123")
        response = self.client.get(reverse("cookies_management"))
        self.assertEqual(response.status_code, 302)

    def test_cookies_view_admin_user_denied(self):
        self.client.login(username="admin", password="password123")
        response = self.client.get(reverse("cookies_management"))
        self.assertEqual(response.status_code, 302)

    def test_cookies_view_superadmin_allowed(self):
        self.client.login(username="superadmin", password="password123")
        response = self.client.get(reverse("cookies_management"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "panel_admin/cookies_management.html")


class CookiesManagementActionTests(TestCase):
    """
    Tests CRUD operations on the cookie file via cookies_management_view.
    """

    def setUp(self):
        self.client = Client()
        self.superadmin = CustomUser.objects.create_user(
            username="superadmin", password="password123", role="superadmin"
        )
        self.client.login(username="superadmin", password="password123")

        self.temp_file = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
        self.temp_cookie_path = self.temp_file.name
        self.temp_file.close()

    def tearDown(self):
        if os.path.exists(self.temp_cookie_path):
            os.remove(self.temp_cookie_path)

    def test_save_raw_cookies_action(self):
        with override_settings(INSTAGRAM_COOKIE_FILE=self.temp_cookie_path):
            raw_content = "# Netscape\n.instagram.com\tTRUE\t/\tTRUE\t1767225600\tsessionid\t12345"
            response = self.client.post(
                reverse("cookies_management"),
                {"action": "save_raw", "raw_cookies": raw_content},
            )
            self.assertEqual(response.status_code, 302)
            with open(self.temp_cookie_path, "r", encoding="utf-8") as f:
                saved = f.read()
            self.assertEqual(saved, raw_content)

    def test_upload_cookie_file_action(self):
        with override_settings(INSTAGRAM_COOKIE_FILE=self.temp_cookie_path):
            uploaded_file = SimpleUploadedFile(
                "cookies.txt",
                b"# Netscape\n.instagram.com\tTRUE\t/\tTRUE\t1767225600\tds_user_id\t9999",
                content_type="text/plain",
            )
            response = self.client.post(
                reverse("cookies_management"),
                {"action": "upload_file", "cookie_file": uploaded_file},
            )
            self.assertEqual(response.status_code, 302)
            with open(self.temp_cookie_path, "rb") as f:
                saved = f.read()
            self.assertIn(b"ds_user_id\t9999", saved)

    def test_delete_cookie_file_action(self):
        with override_settings(INSTAGRAM_COOKIE_FILE=self.temp_cookie_path):
            self.assertTrue(os.path.exists(self.temp_cookie_path))
            response = self.client.post(
                reverse("cookies_management"),
                {"action": "delete_file"},
            )
            self.assertEqual(response.status_code, 302)
            self.assertFalse(os.path.exists(self.temp_cookie_path))


class TestCookiesAjaxEndpointTests(TestCase):
    """
    Tests for the AJAX endpoint used to live-test Instagram cookies.
    """

    def setUp(self):
        self.client = Client()
        self.superadmin = CustomUser.objects.create_user(
            username="superadmin", password="password123", role="superadmin"
        )
        self.client.login(username="superadmin", password="password123")

        self.temp_file = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
        self.temp_file.write(b"# Netscape dummy cookies")
        self.temp_cookie_path = self.temp_file.name
        self.temp_file.close()

    def tearDown(self):
        if os.path.exists(self.temp_cookie_path):
            os.remove(self.temp_cookie_path)

    def test_ajax_returns_400_when_cookie_file_missing(self):
        with override_settings(INSTAGRAM_COOKIE_FILE="non_existent_path_8888.txt"):
            response = self.client.post(reverse("test_cookies_ajax"))
            self.assertEqual(response.status_code, 400)
            data = response.json()
            self.assertFalse(data["success"])
            self.assertIn("No existe el archivo cookies.txt", data["message"])

    @patch("igdownloader.services.instagram_service.extract_instagram_data")
    def test_ajax_returns_200_when_extraction_succeeds(self, mock_extract):
        mock_extract.return_value = {
            "title": "Mocked Reel Title",
            "uploader": "test_creator",
            "like_count": 1200,
            "comment_count": 45,
        }
        with override_settings(INSTAGRAM_COOKIE_FILE=self.temp_cookie_path):
            response = self.client.post(
                reverse("test_cookies_ajax"),
                {"test_url": "https://www.instagram.com/reel/C8qL_yGsq6n/"},
            )
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertTrue(data["success"])
            self.assertEqual(data["title"], "Mocked Reel Title")
            self.assertEqual(data["uploader"], "test_creator")
            self.assertEqual(data["like_count"], 1200)
            mock_extract.assert_called_once()

    @patch("igdownloader.services.instagram_service.extract_instagram_data")
    def test_ajax_returns_400_when_extraction_fails(self, mock_extract):
        mock_extract.side_effect = RuntimeError("Instagram login required")
        with override_settings(INSTAGRAM_COOKIE_FILE=self.temp_cookie_path):
            response = self.client.post(
                reverse("test_cookies_ajax"),
                {"test_url": "https://www.instagram.com/reel/C8qL_yGsq6n/"},
            )
            self.assertEqual(response.status_code, 400)
            data = response.json()
            self.assertFalse(data["success"])
            self.assertIn("Instagram login required", data["message"])
