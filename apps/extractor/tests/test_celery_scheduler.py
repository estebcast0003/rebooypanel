from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from extractor.models import ExtractionJob, FacebookPage, UserExtractorPreference
from extractor.services.scheduler import scheduler
from extractor.tasks import dispatch_scheduled_fanpage_updates, update_user_fanpages_task

User = get_user_model()


class UserExtractorPreferenceTests(TestCase):
    def setUp(self):
        self.user1 = User.objects.create_user(username="celery_user1", password="password123")
        self.user2 = User.objects.create_user(username="celery_user2", password="password123")

    def test_default_preference_created(self):
        pref = UserExtractorPreference.get_or_create_for_user(self.user1)
        self.assertTrue(pref.auto_refresh_enabled)
        self.assertEqual(pref.refresh_interval_hours, 24)
        self.assertIsNone(pref.last_refresh_at)
        self.assertIsNone(pref.next_refresh_at)

    def test_user_preferences_isolated(self):
        scheduler.save_settings(enabled=False, interval_minutes=1440, user=self.user1)
        scheduler.save_settings(enabled=True, interval_minutes=360, user=self.user2)

        status1 = scheduler.load_settings(user=self.user1)
        status2 = scheduler.load_settings(user=self.user2)

        self.assertFalse(status1["enabled"])
        self.assertTrue(status2["enabled"])
        self.assertEqual(status2["interval_hours"], 6)


class ExtractorSchedulerAPITests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="apiuser", password="password123", role="user")
        self.client.login(username="apiuser", password="password123")

    def test_get_scheduler_status(self):
        response = self.client.get("/extractor/api/scheduler/status/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertTrue(data["scheduler"]["enabled"])
        self.assertEqual(data["scheduler"]["interval_hours"], 24)

    @patch("extractor.services.scheduler.scheduler.trigger_now")
    def test_get_scheduler_status_auto_triggers_when_due(self, mock_trigger):
        mock_trigger.return_value = "dummy-job-id"
        pref = UserExtractorPreference.get_or_create_for_user(self.user)
        pref.auto_refresh_enabled = True
        pref.next_refresh_at = timezone.now() - timedelta(seconds=10)
        pref.save()

        response = self.client.get("/extractor/api/scheduler/status/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["triggered"])
        self.assertEqual(data["job_id"], "dummy-job-id")
        mock_trigger.assert_called_once_with(user=self.user)

    def test_update_scheduler_status(self):
        response = self.client.post(
            "/extractor/api/scheduler/update/",
            data={"enabled": False, "interval_minutes": 720},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertFalse(data["scheduler"]["enabled"])
        self.assertEqual(data["scheduler"]["interval_hours"], 12)

        pref = UserExtractorPreference.objects.get(user=self.user)
        self.assertFalse(pref.auto_refresh_enabled)
        self.assertEqual(pref.refresh_interval_hours, 12)


class CelerySchedulerTaskTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="celeryworkeruser", password="password123")
        self.pref = UserExtractorPreference.get_or_create_for_user(self.user)
        self.pref.auto_refresh_enabled = True
        self.pref.next_refresh_at = timezone.now() - timedelta(minutes=5)
        self.pref.save()

        self.page = FacebookPage.objects.create(
            user=self.user,
            url="https://www.facebook.com/celerytestpage",
            name="Celery Test Page",
            followers=5000,
        )

    @patch("extractor.tasks.update_user_fanpages_task.delay")
    def test_dispatch_scheduled_fanpage_updates(self, mock_delay):
        result = dispatch_scheduled_fanpage_updates()
        self.assertEqual(result["dispatched_users_count"], 1)
        self.assertIn("celeryworkeruser", result["users"])
        mock_delay.assert_called_once_with(self.user.id)

        self.pref.refresh_from_db()
        self.assertIsNotNone(self.pref.last_refresh_at)
        self.assertGreater(self.pref.next_refresh_at, timezone.now())

    @patch("extractor.services.runner._run_extraction_worker")
    def test_update_user_fanpages_task(self, mock_worker):
        res = update_user_fanpages_task(self.user.id)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["username"], "celeryworkeruser")
        self.assertEqual(res["total_urls"], 1)

        job = ExtractionJob.objects.filter(user=self.user).first()
        self.assertIsNotNone(job)
        self.assertEqual(job.total_urls, 1)
        mock_worker.assert_called_once_with(str(job.id), [self.page.url])
