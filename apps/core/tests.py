import os
import tempfile
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings
from core.services.cli_proxy import (
    get_cli_proxy_client,
    get_cli_proxy_model,
    create_video_part_from_file,
)


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
