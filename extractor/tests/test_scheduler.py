from unittest.mock import patch

import pytest

from extractor.models import ExtractionJob, ExtractorSetting, FacebookPage
from extractor.services.scheduler import scheduler


@pytest.mark.django_db
def test_scheduler_load_and_save_settings():
    scheduler.save_settings(enabled=True, interval_minutes=30)
    settings = scheduler.load_settings()

    assert settings["enabled"] is True
    assert settings["interval_minutes"] == 30
    assert settings["next_run"] is not None
    assert settings["remaining_seconds"] > 0

    scheduler.save_settings(enabled=False, interval_minutes=60)
    settings = scheduler.load_settings()
    assert settings["enabled"] is False
    assert settings["interval_minutes"] == 60


@pytest.mark.django_db
def test_scheduler_trigger_now_empty():
    FacebookPage.objects.all().delete()
    job_id = scheduler.trigger_now()
    assert job_id is None


@pytest.mark.django_db
def test_scheduler_trigger_now_with_pages():
    FacebookPage.objects.create(
        url="https://www.facebook.com/schedpage",
        name="Scheduled Page",
        followers=100,
        status="Éxito",
    )
    with patch("extractor.services.scheduler.start_extraction_job") as mock_starter:
        mock_job = ExtractionJob.objects.create(total_urls=1)
        mock_starter.return_value = mock_job

        job_id = scheduler.trigger_now()
        assert job_id == str(mock_job.id)

        setting = ExtractorSetting.objects.filter(key="last_auto_refresh_at").first()
        assert setting is not None
