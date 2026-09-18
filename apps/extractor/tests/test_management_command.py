from io import StringIO
from unittest.mock import patch
from django.core.management import call_command
from django.test import TestCase
from extractor.models import ExtractionJob, FacebookPage

class UpdateFollowersCommandTestCase(TestCase):
    def test_command_no_pages(self):
        FacebookPage.objects.all().delete()
        out = StringIO()
        call_command('update_followers', stdout=out)
        self.assertIn('No Facebook fanpages found', out.getvalue())

    def test_command_with_pages(self):
        FacebookPage.objects.create(
            url='https://www.facebook.com/cmdpage',
            name='Command Page',
            followers=500,
            status='Éxito',
        )
        out = StringIO()
        with patch('extractor.management.commands.update_followers.start_extraction_job') as mock_job_starter:
            mock_job = ExtractionJob.objects.create(total_urls=1)
            mock_job_starter.return_value = mock_job

            call_command('update_followers', stdout=out)
            self.assertIn('Starting update for 1 Facebook fanpages', out.getvalue())
