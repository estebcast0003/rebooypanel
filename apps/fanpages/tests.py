from unittest.mock import patch, MagicMock
from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import CustomUser
from fanpages.models import FanpageProfile, OpenRouterConfig


class FanpageModelTests(TestCase):
    """
    Unit tests for FanpageProfile and OpenRouterConfig models.
    """

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username="fanpage_owner", password="password123"
        )

    def test_fanpage_profile_str(self):
        profile = FanpageProfile.objects.create(
            user=self.user,
            nombre="Ciencia Asombrosa",
            descripcion="Datos y experimentos fascinantes",
            prompt_foto_perfil="Astrophysics logo, 1:1, vibrant",
            prompt_foto_portada="Panorama of stars and galaxy, 16:5",
            estilo_visual="Fotografía cinematográfica",
            subtema="Astronomía"
        )
        self.assertIn("Ciencia Asombrosa", str(profile))
        self.assertIn("fanpage_owner", str(profile))

    def test_openrouter_config_get_active_config(self):
        self.assertIsNone(OpenRouterConfig.get_active_config())

        config = OpenRouterConfig.objects.create(
            provider="gemini",
            is_active=True,
            gemini_model="gemini-3.7-flash-high"
        )
        active = OpenRouterConfig.get_active_config()
        self.assertIsNotNone(active)
        self.assertEqual(active.id, config.id)
        self.assertEqual(active.gemini_model, "gemini-3.7-flash-high")


class FanpageStudioViewsTests(TestCase):
    """
    Unit tests for Fanpage Studio access permissions and views.
    """

    def setUp(self):
        self.client = Client()
        self.user_allowed = CustomUser.objects.create_user(
            username="allowed_fanpage_user",
            password="password123",
            can_view_fanpages=True
        )
        self.user_denied = CustomUser.objects.create_user(
            username="denied_fanpage_user",
            password="password123",
            can_view_fanpages=False
        )

    def test_studio_view_unauthenticated_redirects(self):
        response = self.client.get(reverse("fanpages:studio"))
        self.assertEqual(response.status_code, 302)

    def test_studio_view_allowed_user(self):
        self.client.login(username="allowed_fanpage_user", password="password123")
        response = self.client.get(reverse("fanpages:studio"))
        self.assertEqual(response.status_code, 200)

    def test_studio_view_denied_user_forbidden(self):
        self.client.login(username="denied_fanpage_user", password="password123")
        response = self.client.get(reverse("fanpages:studio"))
        self.assertEqual(response.status_code, 403)


class FanpagesAIServiceTests(TestCase):
    """
    Unit tests ensuring Fanpages generation uses the centralized CLI proxy.
    """

    @patch("fanpages.services.get_cli_proxy_model", return_value="gemini-3.7-flash-high")
    @patch("fanpages.services.get_cli_proxy_client")
    def test_generate_with_gemini_uses_cli_proxy(self, mock_get_client, mock_get_model):
        from fanpages.services import _generate_with_gemini

        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = (
            '{"nombre": "Cine Test", "descripcion": "Desc", '
            '"prompt_foto_perfil": "prompt 1", "prompt_foto_portada": "prompt 2", '
            '"estilo_visual": "Cyberpunk", "subtema": "SciFi"}'
        )
        mock_client.models.generate_content.return_value = mock_resp
        mock_get_client.return_value = mock_client

        data, model_str = _generate_with_gemini(None, "test prompt")
        self.assertEqual(data["nombre"], "Cine Test")
        self.assertIn("CLI Proxy", model_str)
        mock_get_client.assert_called_once()
        mock_client.models.generate_content.assert_called_once()
