from unittest.mock import patch, MagicMock
import json
from django.core.files.uploadedfile import SimpleUploadedFile

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
        self.assertContains(response, 'id="videoUrlsInput"')
        self.assertContains(response, 'id="videoDropzone"')
        self.assertContains(response, 'id="processingBanner"')
        self.assertContains(response, 'id="myPromptsContainer"')
        self.assertContains(response, 'id="promptModal"')
        self.assertContains(response, 'id="btnGenerateWpPost"')
        self.assertContains(response, 'Generate Post WP')
        self.assertContains(response, 'triggerGenerateWpPost')
        self.assertContains(response, 'updateWpModalSection')

    @patch("videoprompt.views.dispatch_videoprompt_task")
    def test_generate_prompt_ajax_exceeds_quota(self, mock_dispatch):
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
        mock_dispatch.assert_not_called()

    @patch("videoprompt.views.dispatch_videoprompt_task")
    def test_generate_prompt_ajax_missing_url(self, mock_dispatch):
        self.client.login(username="studiouser", password="password123")
        response = self.client.post(
            reverse("videoprompt:generate_prompt_ajax"),
            {"input_type": "link", "video_url": ""}
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertEqual(data["status"], "error")
        self.assertIn("enlace de video", data["message"])
        mock_dispatch.assert_not_called()

    @patch("videoprompt.views.dispatch_videoprompt_task")
    def test_generate_prompt_ajax_success(self, mock_dispatch):
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
        mock_dispatch.assert_called_once_with(created_prompt.id)

    @patch("videoprompt.views.dispatch_videoprompt_task")
    def test_generate_prompt_ajax_batch_urls_success(self, mock_dispatch):
        self.user.daily_prompt_limit = 5
        self.user.save()
        self.client.login(username="studiouser", password="password123")

        urls_text = "https://example.com/v1.mp4\nhttps://example.com/v2.mp4, https://example.com/v3.mp4"
        response = self.client.post(
            reverse("videoprompt:generate_prompt_ajax"),
            {
                "input_type": "link",
                "video_urls": urls_text,
                "prompt_language": "en"
            }
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["count"], 3)
        self.assertEqual(len(data["prompt_ids"]), 3)
        self.assertEqual(mock_dispatch.call_count, 3)

    @patch("videoprompt.views.dispatch_videoprompt_task")
    def test_generate_prompt_ajax_batch_urls_exceeds_quota(self, mock_dispatch):
        self.user.daily_prompt_limit = 2
        self.user.save()
        self.client.login(username="studiouser", password="password123")

        urls_text = "https://example.com/v1.mp4\nhttps://example.com/v2.mp4\nhttps://example.com/v3.mp4"
        response = self.client.post(
            reverse("videoprompt:generate_prompt_ajax"),
            {
                "input_type": "link",
                "video_urls": urls_text
            }
        )
        self.assertEqual(response.status_code, 429)
        data = response.json()
        self.assertEqual(data["status"], "error")
        self.assertIn("solo te quedan 2 prompts", data["message"])
        mock_dispatch.assert_not_called()

    @patch("videoprompt.views.dispatch_videoprompt_task")
    def test_generate_prompt_ajax_batch_files_success(self, mock_dispatch):
        self.user.daily_prompt_limit = 5
        self.user.save()
        self.client.login(username="studiouser", password="password123")

        f1 = SimpleUploadedFile("v1.mp4", b"dummy_video_bytes_1", content_type="video/mp4")
        f2 = SimpleUploadedFile("v2.mp4", b"dummy_video_bytes_2", content_type="video/mp4")

        response = self.client.post(
            reverse("videoprompt:generate_prompt_ajax"),
            {
                "input_type": "file",
                "video_files": [f1, f2],
                "prompt_language": "es"
            }
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["count"], 2)
        self.assertEqual(len(data["prompt_ids"]), 2)
        self.assertEqual(mock_dispatch.call_count, 2)


class CeleryTaskVideoPromptTests(TestCase):
    """
    Tests for process_video_task in Celery worker.
    """

    def setUp(self):
        self.user = CustomUser.objects.create_user(username="celeryuser", password="password123")

    def test_process_video_task_nonexistent_record(self):
        from videoprompt.tasks import process_video_task
        result = process_video_task(999999)
        self.assertEqual(result["status"], "error")

    @patch("videoprompt.tasks.upload_and_analyze_video")
    @patch("videoprompt.tasks.extract_video_thumbnail", return_value=False)
    @patch("videoprompt.tasks.download_video_from_url")
    def test_process_video_task_url_success(self, mock_download, mock_thumb, mock_analyze):
        from videoprompt.tasks import process_video_task

        prompt = VideoPrompt.objects.create(
            user=self.user,
            video_url="https://example.com/test.mp4",
            status="pending"
        )

        mock_download.return_value = ("/fake/path.mp4", {"views": 100, "likes": 10, "comments": 2, "uploader": "test_chan", "duration": 15.0})
        mock_analyze.return_value = json.dumps({
            "style": {"visual_texture": "film"},
            "cinematography": {"camera": "static"},
            "scenes": [],
            "full_prompt_markdown": "### Style\n* **Visual Texture:** film"
        })

        res = process_video_task(prompt.id)
        self.assertEqual(res["status"], "completed")

        prompt.refresh_from_db()
        self.assertEqual(prompt.status, "completed")
        self.assertEqual(prompt.views_count, 100)
        self.assertIn("film", prompt.generated_prompt)


class BatchStatusAjaxTests(TestCase):
    """
    Tests for batch_status_ajax polling endpoint.
    """

    def setUp(self):
        self.client = Client()
        self.user = CustomUser.objects.create_user(username="batchuser", password="password123")
        self.other_user = CustomUser.objects.create_user(username="otheruser", password="password123")

    def test_batch_status_empty_ids(self):
        self.client.login(username="batchuser", password="password123")
        response = self.client.get(reverse("videoprompt:batch_status_ajax"))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["items"], [])

    def test_batch_status_returns_user_items_only(self):
        self.client.login(username="batchuser", password="password123")
        p1 = VideoPrompt.objects.create(user=self.user, video_url="https://example.com/1.mp4", status="completed")
        p2 = VideoPrompt.objects.create(user=self.user, video_url="https://example.com/2.mp4", status="processing")
        p_other = VideoPrompt.objects.create(user=self.other_user, video_url="https://example.com/3.mp4", status="completed")

        response = self.client.get(
            reverse("videoprompt:batch_status_ajax"),
            {"ids": f"{p1.id},{p2.id},{p_other.id}"}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        ids_returned = [item["id"] for item in data["items"]]
        self.assertIn(p1.id, ids_returned)
        self.assertIn(p2.id, ids_returned)
        self.assertNotIn(p_other.id, ids_returned)
        self.assertEqual(len(data["items"]), 2)


class WPArticleServiceTests(TestCase):
    """
    Unit tests for generate_and_publish_wp_article service in videoprompt.
    """

    def setUp(self):
        from wordpress_manager.models import WordPressSite
        self.user = CustomUser.objects.create_user(username="wpauthor", password="password123")
        self.wp_site = WordPressSite.objects.create(
            name="Mi Blog de Cine",
            site_url="https://blog.example.com",
            username="admin",
            application_password="app-password-123",
            is_active=True
        )
        self.prompt = VideoPrompt.objects.create(
            user=self.user,
            video_url="https://example.com/video.mp4",
            status="completed",
            generated_prompt=json.dumps({
                "style": {"visual_texture": "Cinemático", "lighting_quality": "Neón"},
                "cinematography": {"camera": "Paneo", "lens": "50mm"},
                "scenes": [
                    {"start_time": "00:00", "end_time": "00:05", "action_description": "Intro dramática"}
                ],
                "full_prompt_markdown": "Análisis del video..."
            })
        )

    @patch("videoprompt.services.wp_article_service.publish_article_to_wordpress")
    @patch("videoprompt.services.wp_article_service.get_cli_proxy_client")
    @patch("videoprompt.services.wp_article_service.get_cli_proxy_model", return_value="gemini-3.7-flash-high")
    def test_generate_and_publish_wp_article_success(self, mock_model, mock_client_factory, mock_publish):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "title": "Historia Oculta del Video de Prueba",
            "category": "Dramas",
            "article_content": "<p>Contenido completo y detallado del artículo SEO.</p>"
        })
        mock_client.models.generate_content.return_value = mock_response
        mock_client_factory.return_value = mock_client

        mock_publish.return_value = {
            "success": True,
            "post_id": 99,
            "post_url": "https://blog.example.com/historia-oculta/",
            "site_id": self.wp_site.id,
            "site_name": self.wp_site.name,
        }

        from videoprompt.services.wp_article_service import generate_and_publish_wp_article
        result = generate_and_publish_wp_article(self.prompt)

        self.assertTrue(result["success"])
        self.assertFalse(result["from_cache"])
        self.assertEqual(result["post_url"], "https://blog.example.com/historia-oculta/")
        self.assertEqual(result["article_title"], "Historia Oculta del Video de Prueba")
        self.assertEqual(result["category"], "Dramas")

        self.prompt.refresh_from_db()
        self.assertEqual(self.prompt.wp_post_url, "https://blog.example.com/historia-oculta/")
        self.assertEqual(self.prompt.wp_post_id, 99)
        self.assertEqual(self.prompt.wp_article_title, "Historia Oculta del Video de Prueba")
        self.assertEqual(self.prompt.wp_category, "Dramas")
        self.assertIsNotNone(self.prompt.wp_published_at)

    def test_generate_and_publish_wp_article_returns_cache(self):
        self.prompt.wp_post_url = "https://blog.example.com/ya-publicado/"
        self.prompt.wp_article_title = "Título Existente"
        self.prompt.wp_category = "Comedia"
        self.prompt.save()

        from videoprompt.services.wp_article_service import generate_and_publish_wp_article
        result = generate_and_publish_wp_article(self.prompt, force_regenerate=False)

        self.assertTrue(result["success"])
        self.assertTrue(result["from_cache"])
        self.assertEqual(result["post_url"], "https://blog.example.com/ya-publicado/")


class VideoPromptWPViewTests(TestCase):
    """
    Unit tests for WordPress generation AJAX view in videoprompt.
    """

    def setUp(self):
        self.client = Client()
        self.user = CustomUser.objects.create_user(username="wpuser", password="password123")
        self.other_user = CustomUser.objects.create_user(username="otherwpuser", password="password123")
        self.prompt = VideoPrompt.objects.create(
            user=self.user,
            video_url="https://example.com/reel.mp4",
            status="completed",
            generated_prompt=json.dumps({"scenes": []})
        )

    def test_generate_wp_post_ajax_unauthenticated_redirects(self):
        response = self.client.post(reverse("videoprompt:generate_wp_post_ajax", kwargs={"pk": self.prompt.id}))
        self.assertEqual(response.status_code, 302)

    def test_generate_wp_post_ajax_not_found_for_other_user(self):
        self.client.login(username="otherwpuser", password="password123")
        response = self.client.post(reverse("videoprompt:generate_wp_post_ajax", kwargs={"pk": self.prompt.id}))
        self.assertEqual(response.status_code, 404)

    def test_generate_wp_post_ajax_not_completed_fails(self):
        self.client.login(username="wpuser", password="password123")
        pending_prompt = VideoPrompt.objects.create(
            user=self.user,
            video_url="https://example.com/pending.mp4",
            status="processing"
        )
        response = self.client.post(reverse("videoprompt:generate_wp_post_ajax", kwargs={"pk": pending_prompt.id}))
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertIn("aún no ha finalizado", data["error"])

    @patch("videoprompt.services.wp_article_service.generate_and_publish_wp_article")
    def test_generate_wp_post_ajax_success(self, mock_service):
        self.client.login(username="wpuser", password="password123")
        mock_service.return_value = {
            "success": True,
            "post_url": "https://blog.example.com/mi-articulo/",
            "post_id": 101,
            "site_name": "Blog Principal",
            "article_title": "Mi Artículo de Cine",
            "category": "Entretenimiento",
            "from_cache": False,
        }

        response = self.client.post(reverse("videoprompt:generate_wp_post_ajax", kwargs={"pk": self.prompt.id}))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["wp_post_url"], "https://blog.example.com/mi-articulo/")
        self.assertEqual(data["wp_site_name"], "Blog Principal")
        self.assertEqual(data["wp_article_title"], "Mi Artículo de Cine")

    def test_check_prompt_status_ajax_includes_wp_fields(self):
        self.client.login(username="wpuser", password="password123")
        self.prompt.wp_post_url = "https://blog.example.com/articulo-test/"
        self.prompt.wp_article_title = "Título del Test"
        self.prompt.save()

        response = self.client.get(reverse("videoprompt:check_prompt_status_ajax", kwargs={"pk": self.prompt.id}))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["wp_post_url"], "https://blog.example.com/articulo-test/")
        self.assertEqual(data["wp_article_title"], "Título del Test")


