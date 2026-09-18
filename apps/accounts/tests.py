from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import CustomUser
from videoprompt.models import VideoPrompt


class CustomUserManagerTests(TestCase):
    """
    Unit tests for CustomUserManager (user and superuser creation).
    """

    def test_create_user_successful(self):
        user = CustomUser.objects.create_user(
            username="normaluser",
            password="testpassword123"
        )
        self.assertEqual(user.username, "normaluser")
        self.assertTrue(user.check_password("testpassword123"))
        self.assertEqual(user.role, "user")
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_create_user_no_username_raises_error(self):
        with self.assertRaises(ValueError):
            CustomUser.objects.create_user(username="", password="testpassword123")

    def test_create_superuser_successful(self):
        admin = CustomUser.objects.create_superuser(
            username="adminuser",
            password="adminpassword123"
        )
        self.assertEqual(admin.username, "adminuser")
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_superuser)
        self.assertTrue(admin.is_active)
        self.assertEqual(admin.role, "superadmin")

    def test_create_superuser_missing_is_staff_raises_error(self):
        with self.assertRaises(ValueError):
            CustomUser.objects.create_superuser(
                username="adminuser2",
                password="adminpassword123",
                is_staff=False
            )

    def test_create_superuser_missing_is_superuser_raises_error(self):
        with self.assertRaises(ValueError):
            CustomUser.objects.create_superuser(
                username="adminuser3",
                password="adminpassword123",
                is_superuser=False
            )


class UserPromptQuotaTests(TestCase):
    """
    Unit tests for prompt quota tracking and limits per user role.
    """

    def setUp(self):
        self.regular_user = CustomUser.objects.create_user(
            username="quota_user",
            password="password123",
            daily_prompt_limit=2
        )
        self.unlimited_user = CustomUser.objects.create_user(
            username="unlimited_user",
            password="password123",
            is_unlimited_prompts=True
        )
        self.superadmin = CustomUser.objects.create_superuser(
            username="superadmin_user",
            password="password123"
        )

    def test_regular_user_prompt_quota_lifecycle(self):
        self.assertEqual(self.regular_user.get_prompts_remaining_today(), 2)
        self.assertTrue(self.regular_user.can_generate_prompt())

        # Create first prompt
        VideoPrompt.objects.create(
            user=self.regular_user,
            video_url="https://example.com/video1.mp4"
        )
        self.assertEqual(self.regular_user.get_prompts_remaining_today(), 1)
        self.assertTrue(self.regular_user.can_generate_prompt())

        # Create second prompt to reach limit
        VideoPrompt.objects.create(
            user=self.regular_user,
            video_url="https://example.com/video2.mp4"
        )
        self.assertEqual(self.regular_user.get_prompts_remaining_today(), 0)
        self.assertFalse(self.regular_user.can_generate_prompt())

    def test_unlimited_prompts_user_always_allowed(self):
        self.assertEqual(self.unlimited_user.get_prompts_remaining_today(), 999999)
        self.assertTrue(self.unlimited_user.can_generate_prompt())

        for i in range(5):
            VideoPrompt.objects.create(
                user=self.unlimited_user,
                video_url=f"https://example.com/video{i}.mp4"
            )

        self.assertEqual(self.unlimited_user.get_prompts_remaining_today(), 999999)
        self.assertTrue(self.unlimited_user.can_generate_prompt())

    def test_superadmin_user_always_allowed(self):
        self.assertEqual(self.superadmin.get_prompts_remaining_today(), 999999)
        self.assertTrue(self.superadmin.can_generate_prompt())


class AccountsAuthViewsTests(TestCase):
    """
    Unit tests for authentication and session views in accounts app.
    """

    def setUp(self):
        self.client = Client()
        self.user = CustomUser.objects.create_user(
            username="testuser",
            password="password123"
        )

    def test_auth_status_unauthenticated(self):
        response = self.client.get(reverse("auth_status_api"))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["authenticated"])
        self.assertIsNone(data["username"])

    def test_auth_status_authenticated(self):
        self.client.login(username="testuser", password="password123")
        response = self.client.get(reverse("auth_status_api"))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["authenticated"])
        self.assertEqual(data["username"], "testuser")

    def test_security_sessions_page_requires_login(self):
        response = self.client.get(reverse("security_sessions"))
        self.assertEqual(response.status_code, 302)

    def test_security_sessions_page_authenticated(self):
        self.client.login(username="testuser", password="password123")
        response = self.client.get(reverse("security_sessions"))
        self.assertEqual(response.status_code, 200)
