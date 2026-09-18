from unittest.mock import patch, MagicMock

from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import CustomUser
from videoprompt.models import VideoPrompt
from videoprompt.services.gemini_client import upload_and_analyze_video


class GeminiClientServiceTests(TestCase):
    """
    Unit tests for videoprompt gemini_client service and CLI proxy integration.
    """

    def test_upload_and_analyze_video_missing_file_raises_error(self):
        with self.assertRaises(FileNotFoundError):
            upload_and_analyze_video("non_existent_file_xyz.mp4")

    @patch("videoprompt.services.gemini_client.os.path.exists", return_value=True)
    @patch("videoprompt.services.gemini_client.create_video_part_from_file")
    @patch("videoprompt.services.gemini_client.get_cli_proxy_model", return_value="gemini-3.7-flash-high")
    @patch("videoprompt.services.gemini_client.get_cli_proxy_client")
    def test_upload_and_analyze_video_success(
        self, mock_get_client, mock_get_model, mock_create_part, mock_exists
    ):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = '{"style": {"visual_texture": "cinematic", "lighting_quality": "soft", "color_palette": "warm", "atmosphere": "tense"}, "cinematography": {"camera": "Arri", "lens": "35mm", "lighting": "low-key", "mood": "dark"}, "scenes": [], "full_prompt_markdown": "# Detailed Cinematic Analysis\\nTest markdown"}'
        mock_client.models.generate_content.return_value = mock_response
        mock_get_client.return_value = mock_client

        result = upload_and_analyze_video("mock_video.mp4", additional_context="Action scene", language="es")
        self.assertIn("# Detailed Cinematic Analysis", result)
        mock_client.models.generate_content.assert_called_once()


class VideoStudioViewsTests(TestCase):
    """
    Unit tests for Video to Prompt Studio views and AJAX endpoints.
    """

    def setUp(self):
        self.client = Client()
        self.user = CustomUser.objects.create_user(
            username="studiouser",
            password="password123",
            daily_prompt_limit=1
        )

    def test_studio_view_unauthenticated_redirects(self):
        response = self.client.get(reverse("videoprompt:studio"))
        self.assertEqual(response.status_code, 302)

    def test_studio_view_authenticated(self):
        self.client.login(username="studiouser", password="password123")
        response = self.client.get(reverse("videoprompt:studio"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("quota", response.context)
        self.assertEqual(response.context["quota"]["limit"], 1)

    @patch("videoprompt.views.threading.Thread")
    def test_generate_prompt_ajax_exceeds_quota(self, mock_thread):
        self.client.login(username="studiouser", password="password123")
        # Consume the 1 allowed prompt
        VideoPrompt.objects.create(user=self.user, video_url="https://example.com/video1.mp4")

        response = self.client.post(
            reverse("videoprompt:generate_prompt_ajax"),
            {"input_type": "link", "video_url": "https://example.com/video2.mp4"}
        )
        self.assertEqual(response.status_code, 429)
        data = response.json()
        self.assertEqual(data["status"], "error")
        self.assertIn("Has alcanzado tu límite diario", data["message"])
        mock_thread.assert_not_called()

    @patch("videoprompt.views.threading.Thread")
    def test_generate_prompt_ajax_missing_url(self, mock_thread):
        self.client.login(username="studiouser", password="password123")
        response = self.client.post(
            reverse("videoprompt:generate_prompt_ajax"),
            {"input_type": "link", "video_url": ""}
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertEqual(data["status"], "error")
        self.assertIn("ingresa un enlace de video válido", data["message"])
        mock_thread.assert_not_called()

    @patch("videoprompt.views.threading.Thread")
    def test_generate_prompt_ajax_success(self, mock_thread):
        self.client.login(username="studiouser", password="password123")
        response = self.client.post(
            reverse("videoprompt:generate_prompt_ajax"),
            {
                "input_type": "link",
                "video_url": "https://example.com/valid_video.mp4",
                "additional_context": "test context",
                "prompt_language": "es"
            }
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("prompt_id", data)

        created_prompt = VideoPrompt.objects.get(pk=data["prompt_id"])
        self.assertEqual(created_prompt.user, self.user)
        self.assertEqual(created_prompt.video_url, "https://example.com/valid_video.mp4")
        self.assertEqual(created_prompt.status, "pending")
        mock_thread.assert_called_once()
