import io
from unittest.mock import patch

import pytest
from django.core.management import call_command

from extractor.models import ExtractionJob, FacebookPage


@pytest.mark.django_db
def test_update_followers_command_empty():
    FacebookPage.objects.all().delete()
    out = io.StringIO()
    call_command("update_followers", stdout=out)
    assert "No Facebook fanpages found" in out.getvalue()


@pytest.mark.django_db
def test_update_followers_command_execution():
    FacebookPage.objects.create(
        url="https://www.facebook.com/cmdpage",
        name="Cmd Page",
        followers=50,
        status="Éxito",
    )

    with patch(
        "extractor.management.commands.update_followers.start_extraction_job"
    ) as mock_starter:
        mock_job = ExtractionJob.objects.create(total_urls=1, successful_urls=1, failed_urls=0)
        mock_starter.return_value = mock_job

        out = io.StringIO()
        call_command("update_followers", stdout=out)
        output = out.getvalue()

        assert "Starting update for 1 Facebook fanpages" in output
        assert "Extraction job" in output
