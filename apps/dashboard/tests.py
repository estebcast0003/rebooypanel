from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import CustomUser
from extractor.models import FacebookPage
from videoprompt.models import VideoPrompt
from fanpages.models import FanpageProfile
from dashboard.views import format_compact_number


class DashboardHelpersTests(TestCase):
    """
    Unit tests for dashboard formatting utilities.
    """

    def test_format_compact_number(self):
        self.assertEqual(format_compact_number(850), "850")
        self.assertEqual(format_compact_number(5420), "5.4K")
        self.assertEqual(format_compact_number(121_232_240), "121.2M")
        self.assertEqual(format_compact_number(2_000_000_000), "2B")
        self.assertEqual(format_compact_number("invalid"), "0")
        self.assertEqual(format_compact_number(None), "0")


class DashboardViewTests(TestCase):
    """
    Unit tests for personal dashboard view and data isolation.
    """

    def setUp(self):
        self.client = Client()
        self.user_a = CustomUser.objects.create_user(
            username="user_a", password="password123"
        )
        self.user_b = CustomUser.objects.create_user(
            username="user_b", password="password123"
        )

        # Create data for user_a
        FacebookPage.objects.create(
            user=self.user_a,
            url="https://facebook.com/page_a",
            name="Page A",
            followers=1500
        )
        VideoPrompt.objects.create(
            user=self.user_a,
            video_url="https://example.com/video_a.mp4"
        )
        FanpageProfile.objects.create(
            user=self.user_a,
            nombre="Fanpage A"
        )

        # Create data for user_b
        FacebookPage.objects.create(
            user=self.user_b,
            url="https://facebook.com/page_b",
            name="Page B",
            followers=9000
        )

    def test_dashboard_unauthenticated_redirects(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 302)

    def test_dashboard_authenticated_user_a_data_isolation(self):
        self.client.login(username="user_a", password="password123")
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "dashboard/index.html")

        # user_a should only see their own metrics
        self.assertEqual(response.context["total_pages"], 1)
        self.assertEqual(response.context["total_followers"], 1500)
        self.assertEqual(response.context["formatted_total_followers"], "1.5K")
        self.assertEqual(response.context["total_prompts"], 1)
        self.assertEqual(response.context["total_fanpages"], 1)

    def test_dashboard_authenticated_user_b_data_isolation(self):
        self.client.login(username="user_b", password="password123")
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)

        # user_b should only see their own metrics
        self.assertEqual(response.context["total_pages"], 1)
        self.assertEqual(response.context["total_followers"], 9000)
        self.assertEqual(response.context["formatted_total_followers"], "9K")
        self.assertEqual(response.context["total_prompts"], 0)
        self.assertEqual(response.context["total_fanpages"], 0)
