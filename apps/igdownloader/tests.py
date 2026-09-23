import json
from unittest.mock import patch, MagicMock

from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import CustomUser
from igdownloader.models import InstagramDownload
from igdownloader.services.facebook_copy_service import analyze_video_for_facebook
from wordpress_manager.models import WordPressSite


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
        self.wp_site = WordPressSite.objects.create(
            name="Sitio Tech",
            site_url="https://tech.example.com",
            username="wp_admin",
            application_password="abcd efgh ijkl mnop",
            is_active=True
        )

    @patch("igdownloader.services.facebook_copy_service.download_temp_video", return_value="mock_temp.mp4")
    @patch("igdownloader.services.facebook_copy_service.create_video_part_from_file")
    @patch("igdownloader.services.facebook_copy_service.get_cli_proxy_model", return_value="gemini-3.7-flash-high")
    @patch("igdownloader.services.facebook_copy_service.get_cli_proxy_client")
    @patch("igdownloader.services.facebook_copy_service.publish_article_to_wordpress")
    @patch("os.path.exists", return_value=True)
    @patch("os.remove")
    def test_generate_facebook_copy_success(
        self, mock_remove, mock_exists, mock_publish_wp, mock_get_client, mock_get_model, mock_create_part, mock_download
    ):
        mock_publish_wp.return_value = {
            "success": True,
            "post_id": 42,
            "post_url": "https://tech.example.com/2026/09/mi-articulo/",
            "site_id": self.wp_site.id,
            "site_name": self.wp_site.name,
            "site_url": self.wp_site.site_url,
        }
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "title": "Aprende este tip increíble 🔥",
            "description": "Descubre cómo optimizar tu flujo de trabajo en minutos. Dale like y compartí!",
            "article_content": "<p>Contenido completo del artículo SEO sobre productividad.</p>",
            "hashtags": "#viral #reels"
        })
        mock_client.models.generate_content.return_value = mock_response
        mock_get_client.return_value = mock_client

        result = analyze_video_for_facebook(self.download)
        self.assertTrue(result["success"])
        self.assertEqual(result["wp_post_url"], "https://tech.example.com/2026/09/mi-articulo/")
        self.assertEqual(result["wp_article_title"], "Aprende este tip increíble 🔥")
        self.assertEqual(result["wp_site_name"], "Sitio Tech")

        self.download.refresh_from_db()
        self.assertEqual(self.download.fb_status, "completed")
        self.assertEqual(self.download.fb_title, "Aprende este tip increíble 🔥")
        self.assertEqual(self.download.fb_hashtags, "#viral #reels")
        self.assertIn("Descubre cómo", self.download.fb_description)
        self.assertEqual(self.download.wp_post_url, "https://tech.example.com/2026/09/mi-articulo/")
        self.assertEqual(self.download.wp_post_id, 42)
        self.assertEqual(self.download.wp_site, self.wp_site)
        self.assertEqual(self.download.wp_article_title, "Aprende este tip increíble 🔥")
        self.assertEqual(self.download.wp_article_content, "<p>Contenido completo del artículo SEO sobre productividad.</p>")

        mock_publish_wp.assert_called_once_with(
            title="Aprende este tip increíble 🔥",
            content_html="<p>Contenido completo del artículo SEO sobre productividad.</p>",
            instagram_url=self.download.instagram_url,
        )

    @patch("igdownloader.services.facebook_copy_service.download_temp_video", return_value="mock_temp.mp4")
    @patch("igdownloader.services.facebook_copy_service.create_video_part_from_file")
    @patch("igdownloader.services.facebook_copy_service.get_cli_proxy_model", return_value="gemini-3.7-flash-high")
    @patch("igdownloader.services.facebook_copy_service.get_cli_proxy_client")
    @patch("igdownloader.services.facebook_copy_service.publish_article_to_wordpress", side_effect=ValueError("No hay dominios activos"))
    @patch("os.path.exists", return_value=True)
    @patch("os.remove")
    def test_generate_facebook_copy_wp_error_still_completes(
        self, mock_remove, mock_exists, mock_publish_wp, mock_get_client, mock_get_model, mock_create_part, mock_download
    ):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "title": "Aprende este tip increíble 🔥",
            "description": "Descubre cómo optimizar tu flujo de trabajo en minutos. Dale like y compartí!",
            "article_content": "<p>Contenido del artículo</p>",
            "hashtags": "#viral #reels"
        })
        mock_client.models.generate_content.return_value = mock_response
        mock_get_client.return_value = mock_client

        result = analyze_video_for_facebook(self.download)
        self.assertTrue(result["success"])
        self.assertIsNone(result["wp_post_url"])
        self.assertEqual(result["wp_article_title"], "Aprende este tip increíble 🔥")
        self.assertIsNone(result["wp_site_name"])

        self.download.refresh_from_db()
        self.assertEqual(self.download.fb_status, "completed")
        self.assertEqual(self.download.fb_title, "Aprende este tip increíble 🔥")
        self.assertIsNone(self.download.wp_post_url)
        self.assertIsNone(self.download.wp_post_id)
        self.assertIsNone(self.download.wp_site)
        self.assertEqual(self.download.wp_article_title, "Aprende este tip increíble 🔥")
        self.assertEqual(self.download.wp_article_content, "<p>Contenido del artículo</p>")

    def test_cached_facebook_copy_with_wp_fields(self):
        self.download.fb_status = "completed"
        self.download.fb_title = "Título en caché"
        self.download.fb_description = "Descripción en caché"
        self.download.fb_hashtags = "#cache"
        self.download.wp_post_url = "https://tech.example.com/cached-article/"
        self.download.wp_article_title = "Título en caché"
        self.download.wp_site = self.wp_site
        self.download.save()

        result = analyze_video_for_facebook(self.download, force_regenerate=False)
        self.assertTrue(result["success"])
        self.assertTrue(result["from_cache"])
        self.assertEqual(result["wp_post_url"], "https://tech.example.com/cached-article/")
        self.assertEqual(result["wp_article_title"], "Título en caché")
        self.assertEqual(result["wp_site_name"], self.wp_site.name)


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
        self.wp_site = WordPressSite.objects.create(
            name="Sitio View Test",
            site_url="https://views.example.com",
            username="wp_views",
            application_password="pass",
            is_active=True
        )
        self.download = InstagramDownload.objects.create(
            user=self.user,
            instagram_url="https://www.instagram.com/reel/abc1234/",
            wp_post_url="https://views.example.com/art-1/",
            wp_post_id=99,
            wp_site=self.wp_site,
            wp_article_title="Título de Vista",
            wp_article_content="<p>Texto</p>",
            fb_title="Título FB",
            fb_description="Desc FB",
            fb_hashtags="#tag",
            fb_status="completed"
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

    def test_status_ajax_includes_wp_fields(self):
        self.client.login(username="allowed_ig_user", password="password123")
        response = self.client.get(reverse("igdownloader:status_ajax", kwargs={"pk": self.download.id}))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["wp_post_url"], "https://views.example.com/art-1/")
        self.assertEqual(data["wp_article_title"], "Título de Vista")
        self.assertEqual(data["wp_site_name"], "Sitio View Test")

    @patch("igdownloader.services.facebook_copy_service.analyze_video_for_facebook")
    def test_generate_facebook_copy_ajax_success(self, mock_analyze):
        self.client.login(username="allowed_ig_user", password="password123")
        mock_analyze.return_value = {
            "success": True,
            "title": "Nuevo Título",
            "description": "Nueva Descripción",
            "hashtags": "#nuevo",
            "hashtags_source": "ai",
            "generated_at": "23 Sep 2026, 15:30",
            "from_cache": False,
            "wp_post_url": "https://views.example.com/art-1/",
            "wp_article_title": "Nuevo Título",
            "wp_site_name": "Sitio View Test",
        }
        response = self.client.post(reverse("igdownloader:generate_facebook_copy_ajax", kwargs={"pk": self.download.id}))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["title"], "Nuevo Título")
        self.assertEqual(data["wp_post_url"], "https://views.example.com/art-1/")
        self.assertEqual(data["wp_article_title"], "Nuevo Título")
        self.assertEqual(data["wp_site_name"], "Sitio View Test")

    def test_index_template_contains_wp_article_link_block_and_buttons(self):
        self.client.login(username="allowed_ig_user", password="password123")
        response = self.client.get(reverse("igdownloader:index"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")

        # IDs y elementos del bloque WordPress
        self.assertIn('id="fbWpCard"', content)
        self.assertIn('id="fbWpVisitBtn"', content)
        self.assertIn('id="fbWpCopyBtn"', content)
        self.assertIn('id="fbWpLinkText"', content)
        self.assertIn('id="fbWpSiteBadge"', content)
        self.assertIn('id="fbWpContentBox"', content)
        self.assertIn('id="fbWpEmptyNotice"', content)

        # Botones y textos
        self.assertIn('Enlace para el 1er Comentario (Artículo WordPress)', content)
        self.assertIn('copySocialOnly(this)', content)
        self.assertIn('Copiar Copy para Red Social', content)
        self.assertIn('copyWpLinkOnly(this)', content)
        self.assertIn('Copiar Link para Comentario', content)
        self.assertIn('Copiar Todo (Copy Social + Link Comentario)', content)
        self.assertIn('Dominios WordPress', content)

    def test_index_template_contains_updated_descriptions_and_js_handlers(self):
        self.client.login(username="allowed_ig_user", password="password123")
        response = self.client.get(reverse("igdownloader:index"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")

        # Textos actualizados de Idle y Loading
        self.assertIn('redacta un artículo para WordPress con el embed de Instagram', content)
        self.assertIn('copy social', content)
        self.assertIn('primer comentario', content)

        # Funciones JS y lógica de estado WordPress
        self.assertIn('function copySocialOnly(', content)
        self.assertIn('function copyWpLinkOnly(', content)
        self.assertIn('function copyAllFbContent(', content)
        self.assertIn('wp_post_url', content)
        self.assertIn('wp_site_name', content)
        self.assertIn('Sin Dominio WP', content)
        self.assertIn('¡Copy generado y artículo publicado en WordPress!', content)

