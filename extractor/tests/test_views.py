import json
from unittest.mock import patch

import pytest
from django.test import Client
from django.urls import reverse

from extractor.models import ExtractionItem, ExtractionJob, ExtractorSetting, FacebookPage


@pytest.mark.django_db
def test_dashboard_view_renders():
    client = Client()
    FacebookPage.objects.create(
        url="https://www.facebook.com/testpage",
        name="Test Page",
        followers=5000,
        status="Éxito",
    )
    response = client.get(reverse("extractor:dashboard"))
    assert response.status_code == 200
    assert "Test Page" in response.content.decode("utf-8")
    assert "5000" in response.content.decode("utf-8") or "5,000" in response.content.decode("utf-8")


@pytest.mark.django_db
def test_save_cache_view():
    client = Client()
    payload = {"urls": "https://www.facebook.com/page1\nhttps://www.facebook.com/page2"}
    response = client.post(
        reverse("extractor:save_cache"),
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert ExtractorSetting.objects.get(key="urls_cache").value == payload["urls"]


@pytest.mark.django_db
def test_start_extraction_endpoint_validation():
    client = Client()
    response = client.post(
        reverse("extractor:start_extraction"),
        data=json.dumps({"urls": ""}),
        content_type="application/json",
    )
    assert response.status_code == 400

    with patch("extractor.views.start_extraction_job") as mock_job_starter:
        mock_job = ExtractionJob(total_urls=1)
        mock_job_starter.return_value = mock_job

        response = client.post(
            reverse("extractor:start_extraction"),
            data=json.dumps({"urls": "https://www.facebook.com/testpage"}),
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["total_urls"] == 1


@pytest.mark.django_db
def test_job_status_endpoint():
    client = Client()
    job = ExtractionJob.objects.create(
        total_urls=1,
        processed_urls=1,
        successful_urls=1,
        status=ExtractionJob.JobStatus.COMPLETED,
    )
    page = FacebookPage.objects.create(
        url="https://www.facebook.com/jobpage",
        name="Job Page",
        followers=1000,
        status="Éxito",
    )
    ExtractionItem.objects.create(
        job=job,
        page=page,
        url=page.url,
        name=page.name,
        followers=page.followers,
        status="Éxito",
        is_success=True,
    )

    response = client.get(reverse("extractor:job_status", kwargs={"job_id": job.id}))
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "COMPLETED"
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["name"] == "Job Page"


@pytest.mark.django_db
def test_scheduler_endpoints():
    client = Client()

    # Get status
    resp = client.get(reverse("extractor:scheduler_status"))
    assert resp.status_code == 200
    assert "scheduler" in resp.json()

    # Update scheduler config
    update_resp = client.post(
        reverse("extractor:scheduler_update"),
        data=json.dumps({"enabled": True, "interval_minutes": 15}),
        content_type="application/json",
    )
    assert update_resp.status_code == 200
    update_data = update_resp.json()
    assert update_data["status"] == "ok"
    assert update_data["scheduler"]["enabled"] is True
    assert update_data["scheduler"]["interval_minutes"] == 15

    # Trigger with no pages
    FacebookPage.objects.all().delete()
    trigger_resp = client.post(reverse("extractor:scheduler_trigger"))
    assert trigger_resp.status_code == 200
    assert trigger_resp.json()["status"] == "warning"

    # Trigger with pages
    FacebookPage.objects.create(url="https://www.facebook.com/p1", name="P1", followers=10)
    with patch("extractor.services.scheduler.scheduler.trigger_now") as mock_trig:
        mock_trig.return_value = "dummy-job-id"
        trigger_resp2 = client.post(reverse("extractor:scheduler_trigger"))
        assert trigger_resp2.status_code == 200
        assert trigger_resp2.json()["status"] == "ok"
        assert trigger_resp2.json()["job_id"] == "dummy-job-id"


@pytest.mark.django_db
def test_delete_page_endpoint():
    client = Client()
    page = FacebookPage.objects.create(
        url="https://www.facebook.com/todelete",
        name="Delete Me",
        followers=120,
        status="Éxito",
    )
    response = client.post(reverse("extractor:delete_page", kwargs={"page_id": page.id}))
    assert response.status_code == 200
    assert not FacebookPage.objects.filter(id=page.id).exists()


@pytest.mark.django_db
def test_clear_all_pages_endpoint():
    client = Client()
    FacebookPage.objects.create(url="https://www.facebook.com/p1", name="P1", followers=10)
    FacebookPage.objects.create(url="https://www.facebook.com/p2", name="P2", followers=20)
    assert FacebookPage.objects.count() == 2

    response = client.post(reverse("extractor:clear_pages"))
    assert response.status_code == 200
    assert FacebookPage.objects.count() == 0


@pytest.mark.django_db
def test_export_csv_and_excel():
    client = Client()
    FacebookPage.objects.create(
        url="https://www.facebook.com/exportpage",
        name="Export Page",
        followers=999,
        status="Éxito",
    )
    csv_resp = client.get(reverse("extractor:export_csv"))
    assert csv_resp.status_code == 200
    assert "text/csv" in csv_resp["Content-Type"]
    assert "Export Page" in csv_resp.content.decode("utf-8-sig")

    excel_resp = client.get(reverse("extractor:export_excel"))
    assert excel_resp.status_code == 200
    assert "spreadsheetml" in excel_resp["Content-Type"] or "text/csv" in excel_resp["Content-Type"]
