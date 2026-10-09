import json
from unittest.mock import patch
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from extractor.models import FacebookPage

User = get_user_model()

class ExtractorViewsTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='password123')
        self.client = Client()
        self.client.login(username='testuser', password='password123')

    def test_dashboard_view_authenticated(self):
        response = self.client.get('/extractor/')
        self.assertEqual(response.status_code, 200)

    def test_save_cache_view(self):
        response = self.client.post(
            '/extractor/api/save-cache/',
            data=json.dumps({'urls': 'https://facebook.com/p1\nhttps://facebook.com/p2'}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'ok')

    def test_get_stats_api_view(self):
        FacebookPage.objects.create(user=self.user, url='https://facebook.com/statpage', name='Stat Page', followers=1000)
        response = self.client.get('/extractor/api/stats/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['total_pages'], 1)
        self.assertEqual(data['total_followers'], 1000)

    def test_page_history_api_view(self):
        page = FacebookPage.objects.create(user=self.user, url='https://facebook.com/histpage', name='Hist Page', followers=5000)
        response = self.client.get(f'/extractor/api/page/{page.id}/history/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['current_followers'], 5000)

    def test_bulk_delete_pages_view(self):
        p1 = FacebookPage.objects.create(user=self.user, url='https://facebook.com/del1', name='Del 1', followers=100)
        p2 = FacebookPage.objects.create(user=self.user, url='https://facebook.com/del2', name='Del 2', followers=200)
        p3 = FacebookPage.objects.create(user=self.user, url='https://facebook.com/keep3', name='Keep 3', followers=300)

        response = self.client.post(
            '/extractor/api/pages/bulk-delete/',
            data=json.dumps({'ids': [p1.id, p2.id]}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['deleted_count'], 2)
        self.assertFalse(FacebookPage.objects.filter(id__in=[p1.id, p2.id]).exists())
        self.assertTrue(FacebookPage.objects.filter(id=p3.id).exists())

    def test_start_extraction_duplicate_url_rejected(self):
        FacebookPage.objects.create(user=self.user, url='https://facebook.com/existing_page', name='Existing', followers=100)
        response = self.client.post(
            '/extractor/api/extract/',
            data=json.dumps({'urls': 'https://facebook.com/existing_page'}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 409)
        data = response.json()
        self.assertEqual(data.get("status"), "duplicate")
        self.assertEqual(data.get("duplicate_count"), 1)
        self.assertIn("duplicate_items", data)
