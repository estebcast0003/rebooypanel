from unittest.mock import patch
from django.test import TestCase
from extractor.models import ExtractionJob, ExtractorSetting, FacebookPage
from extractor.services.scheduler import scheduler

class SchedulerTestCase(TestCase):
    def test_scheduler_load_and_save_settings(self):
        scheduler.save_settings(enabled=True, interval_minutes=30)
        settings = scheduler.load_settings()
        self.assertTrue(settings['enabled'])
        self.assertEqual(settings['interval_minutes'], 30)
        self.assertIsNotNone(settings['next_run'])
        self.assertGreater(settings['remaining_seconds'], 0)

        scheduler.save_settings(enabled=False, interval_minutes=60)
        settings = scheduler.load_settings()
        self.assertFalse(settings['enabled'])
        self.assertEqual(settings['interval_minutes'], 60)

    def test_scheduler_trigger_now_empty(self):
        FacebookPage.objects.all().delete()
        job_id = scheduler.trigger_now()
        self.assertIsNone(job_id)

    def test_scheduler_trigger_now_with_pages(self):
        FacebookPage.objects.create(
            url='https://www.facebook.com/schedpage',
            name='Scheduled Page',
            followers=100,
            status='Éxito',
        )
        with patch('extractor.services.scheduler.start_extraction_job') as mock_starter:
            mock_job = ExtractionJob.objects.create(total_urls=1)
            mock_starter.return_value = mock_job

            job_id = scheduler.trigger_now()
            self.assertEqual(job_id, str(mock_job.id))

            setting = ExtractorSetting.objects.filter(key='last_auto_refresh_at').first()
            self.assertIsNotNone(setting)
