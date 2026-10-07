import os
import tempfile
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings, Client
from django.urls import reverse
from django.templatetags.static import static
from core.services.cli_proxy import (
    get_cli_proxy_client,
    get_cli_proxy_model,
    create_video_part_from_file,
)


class LoginViewMetadataAndAssetsTests(TestCase):
    """
    Test suite verifying that the login view properly renders comprehensive
    SEO, Open Graph, and Twitter metadata, and references essential brand assets.
    """

    def setUp(self):
        self.client = Client()
        self.login_url = reverse('login')

    def test_login_view_renders_successfully(self):
        response = self.client.get(self.login_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'core/login.html')
        self.assertTemplateUsed(response, 'base.html')

    def test_login_view_renders_system_metadata(self):
        response = self.client.get(self.login_url)
        content = response.content.decode('utf-8')

        # SEO & Browser metadata
        self.assertIn('<meta name="description"', content)
        self.assertIn('content="Acceso al sistema central y panel administrativo de Rebooy Studio."', content)
        self.assertIn('<meta name="author" content="Rebooy">', content)
        self.assertIn('<meta name="robots" content="noindex, nofollow">', content)
        self.assertIn('<meta name="theme-color" content="#0f172a">', content)
        self.assertIn('<meta name="color-scheme" content="dark">', content)

    def test_login_view_renders_open_graph_metadata(self):
        response = self.client.get(self.login_url)
        content = response.content.decode('utf-8')

        # Open Graph tags
        self.assertIn('<meta property="og:site_name" content="Rebooy Panel">', content)
        self.assertIn('<meta property="og:type" content="website">', content)
        self.assertIn('<meta property="og:title" content="Iniciar Sesión — Rebooy Panel">', content)
        self.assertIn('property="og:description"', content)
        self.assertIn('property="og:image"', content)
        self.assertTrue('id.' in content and '.jpg' in content)

    def test_login_view_renders_twitter_card_metadata(self):
        response = self.client.get(self.login_url)
        content = response.content.decode('utf-8')

        # Twitter Card tags
        self.assertIn('<meta name="twitter:card" content="summary_large_image">', content)
        self.assertIn('<meta name="twitter:title" content="Iniciar Sesión — Rebooy Panel">', content)
        self.assertIn('name="twitter:description"', content)
        self.assertIn('name="twitter:image"', content)

    def test_login_view_references_brand_and_background_images(self):
        response = self.client.get(self.login_url)
        content = response.content.decode('utf-8')

        # Favicons
        self.assertTrue('favicon.' in content and '.ico' in content)
        self.assertTrue('favicon.' in content and '.png' in content)
        self.assertIn('rel="apple-touch-icon"', content)
        self.assertIn('rel="preload" as="image"', content)

        # Background image & Creator Identity avatar
        self.assertIn('background-image: url(', content)
        self.assertIn('alt="Rebooy Creator Identity"', content)
        self.assertIn('loading="eager"', content)

    def test_static_brand_assets_resolution(self):
        id_url = static('img/id.jpg')
        favicon_ico_url = static('img/favicon.ico')
        favicon_png_url = static('img/favicon.png')

        self.assertTrue(id_url.startswith('/static/'))
        self.assertIn('id', id_url)
        self.assertTrue(favicon_ico_url.startswith('/static/'))
        self.assertTrue(favicon_png_url.startswith('/static/'))



class CLIProxyServiceTests(TestCase):
    """
    Unit tests for CLI Proxy Client service, checking initialization,
    configuration fallbacks, and in-memory binary payload creation.
    """

    @override_settings(
        CLI_SECRET_KEY="test-secret-key-123",
        CLI_PROXY_URL="https://cli.serverdok.site",
    )
    @patch("core.services.cli_proxy.genai.Client")
    def test_get_cli_proxy_client_success(self, mock_client_cls):
        mock_instance = MagicMock()
        mock_client_cls.return_value = mock_instance

        client = get_cli_proxy_client()
        self.assertEqual(client, mock_instance)
        mock_client_cls.assert_called_once()
        _, kwargs = mock_client_cls.call_args
        self.assertEqual(kwargs.get("api_key"), "test-secret-key-123")
        http_options = kwargs.get("http_options")
        self.assertIsNotNone(http_options)
        self.assertEqual(http_options.base_url, "https://cli.serverdok.site")
        self.assertEqual(http_options.api_version, "v1beta")

    @override_settings(CLI_SECRET_KEY="")
    def test_get_cli_proxy_client_missing_key_raises_error(self):
        with patch.dict(os.environ, {"CLI_SECRET_KEY": ""}):
            with self.assertRaises(ValueError) as ctx:
                get_cli_proxy_client()
            self.assertIn("CLI_SECRET_KEY no está configurada", str(ctx.exception))

    @override_settings(CLI_SECRET_KEY="your_cli_secret_key_here")
    def test_get_cli_proxy_client_placeholder_key_raises_error(self):
        with patch.dict(os.environ, {"CLI_SECRET_KEY": "your_cli_secret_key_here"}):
            with self.assertRaises(ValueError) as ctx:
                get_cli_proxy_client()
            self.assertIn("CLI_SECRET_KEY no está configurada", str(ctx.exception))

    @override_settings(CLI_PROXY_MODEL="gemini-custom-model")
    def test_get_cli_proxy_model_from_settings(self):
        self.assertEqual(get_cli_proxy_model(), "gemini-custom-model")

    def test_create_video_part_from_file_success(self):
        sample_bytes = b"\x00\x00\x00\x1cftypisom\x00\x00\x02\x00samplepayload"
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(sample_bytes)
            temp_path = f.name

        try:
            part = create_video_part_from_file(temp_path, mime_type="video/mp4")
            self.assertIsNotNone(part)
            self.assertEqual(part.inline_data.data, sample_bytes)
            self.assertEqual(part.inline_data.mime_type, "video/mp4")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_create_video_part_from_file_not_found(self):
        non_existent_path = "non_existent_video_file_9999.mp4"
        with self.assertRaises(FileNotFoundError):
            create_video_part_from_file(non_existent_path)
