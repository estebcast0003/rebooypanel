from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.contrib.auth import get_user_model
from extractor.models import FacebookPage, ExtractorSetting
from extractor.services.alerts import check_and_trigger_growth_alerts, dispatch_growth_alert

User = get_user_model()

class AlertsTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='alertuser', password='password123')
        self.page = FacebookPage.objects.create(
            user=self.user,
            url='https://facebook.com/alertpage',
            name='Alert Page',
            followers=10000
        )

    def test_no_alert_when_no_webhook(self):
        with patch('extractor.services.alerts._send_webhook_payload') as mock_send:
            check_and_trigger_growth_alerts(self.page, 10000, 15000)
            mock_send.assert_not_called()

    def test_alert_triggered_on_growth_with_webhook(self):
        ExtractorSetting.objects.create(key='alert_webhook_url', value='https://discord.com/api/webhooks/123/abc')
        
        with patch('extractor.services.alerts._send_webhook_payload') as mock_send:
            dispatch_growth_alert(self.page, 10000, 15000, 5000, 50.0)
            # Give thread a small moment
            import time
            time.sleep(0.1)
            self.assertTrue(mock_send.called)
