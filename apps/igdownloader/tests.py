import json
from unittest.mock import patch, MagicMock

from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import CustomUser
from igdownloader.models import InstagramDownload
from igdownloader.services.facebook_copy_service import analyze_video_for_facebook


class InstagramDownloadModelTests(TestCase):
    """
    Unit tests for InstagramDownload model methods and formatting properties.
    """

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username="iguser", password="password123"
        )

    def test_formatted_likes(self):
        download = InstagramDownload.objects.create(
            user=self.user,
            instagram_url="https://www.instagram.com/reel/abc1/",
            like_count=None
        )
        self.assertIsNone(download.formatted_likes)

        download.like_count = 850
        self.assertEqual(download.formatted_likes, "850")

        download.like_count = 1500
        self.assertEqual(download.formatted_likes, "1.5K")

        download.like_count = 2_500_000
        self.assertEqual(download.formatted_likes, "2.5M")

    def test_formatted_comments(self):
        download = InstagramDownload.objects.create(
            user=self.user,
            instagram_url="https://www.instagram.com/reel/abc2/",
            comment_count=None
        )
        self.assertIsNone(download.formatted_comments)

        download.comment_count = 72
        self.assertEqual(download.formatted_comments, "72")

        download.comment_count = 4300
        self.assertEqual(download.formatted_comments, "4.3K")


class FacebookCopyServiceTests(TestCase):
    """
    Unit tests for Facebook Copy generation via CLI Proxy API.
    """

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username="copyuser", password="password123"
        )
        self.download = InstagramDownload.objects.create(
            user=self.user,
            instagram_url="https://www.instagram.com/reel/C8qL_yGsq6n/",
            original_hashtags="#viral #reels",
            original_caption="Awesome reel video"
        )

    @patch("igdownloader.services.facebook_copy_service.download_temp_video", return_value="mock_temp.mp4")
    @patch("igdownloader.services.facebook_copy_service.create_video_part_from_file")
    @patch("igdownloader.services.facebook_copy_service.get_cli_proxy_model", return_value="gemini-3.7-flash-high")
    @patch("igdownloader.services.facebook_copy_service.get_cli_proxy_client")
    @patch("os.path.exists", return_value=True)
    @patch("os.remove")
    def test_generate_facebook_copy_success(
        self, mock_remove, mock_exists, mock_get_client, mock_get_model, mock_create_part, mock_download
    ):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "title": "Aprende este tip increíble 🔥",
            "description": "Descubre cómo optimizar tu flujo de trabajo en minutos. Dale like y compartí!",
            "hashtags": "#viral #reels"
        })
        mock_client.models.generate_content.return_value = mock_response
        mock_get_client.return_value = mock_client

        result = analyze_video_for_facebook(self.download)
        self.assertTrue(result["success"])

        self.download.refresh_from_db()
        self.assertEqual(self.download.fb_status, "completed")
        self.assertEqual(self.download.fb_title, "Aprende este tip increíble 🔥")
        self.assertEqual(self.download.fb_hashtags, "#viral #reels")
        self.assertIn("Descubre cómo", self.download.fb_description)


class InstagramDownloaderViewsTests(TestCase):
    """
    Unit tests for Instagram Downloader views and permissions.
    """

    def setUp(self):
        self.client = Client()
        self.user = CustomUser.objects.create_user(
            username="allowed_ig_user", password="password123", can_view_ig_downloader=True
        )
        self.restricted_user = CustomUser.objects.create_user(
            username="restricted_ig_user", password="password123", can_view_ig_downloader=False
        )

    def test_index_unauthenticated_redirects(self):
        response = self.client.get(reverse("igdownloader:index"))
        self.assertEqual(response.status_code, 302)

    def test_index_allowed_user(self):
        self.client.login(username="allowed_ig_user", password="password123")
        response = self.client.get(reverse("igdownloader:index"))
        self.assertEqual(response.status_code, 200)

    def test_index_restricted_user_forbidden(self):
        self.client.login(username="restricted_ig_user", password="password123")
        response = self.client.get(reverse("igdownloader:index"))
        self.assertEqual(response.status_code, 403)

    def test_process_ajax_empty_url(self):
        self.client.login(username="allowed_ig_user", password="password123")
        response = self.client.post(reverse("igdownloader:process_ajax"), {"instagram_url": ""})
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn("error", data)

    def test_status_ajax_not_found(self):
        self.client.login(username="allowed_ig_user", password="password123")
        response = self.client.get(reverse("igdownloader:status_ajax", kwargs={"pk": 99999}))
        self.assertEqual(response.status_code, 404)
