from django.test import SimpleTestCase, TestCase
from accounts.models import CustomUser
from extractor.models import ExtractionJob, ExtractionItem, FacebookPage, PageGrowthSnapshot
from extractor.services.scraper import ExtractionResult, normalize_url, parse_follower_count, parse_html
from extractor.services.runner import save_item_to_db


class ScraperUnitTestCase(SimpleTestCase):
    def test_normalize_url(self):
        self.assertEqual(normalize_url("facebook.com/nike"), "https://facebook.com/nike")
        self.assertEqual(normalize_url("https://m.facebook.com/nike/"), "https://www.facebook.com/nike/")
        self.assertEqual(normalize_url("https://web.facebook.com/nike"), "https://www.facebook.com/nike")
        self.assertEqual(
            normalize_url("https://www.facebook.com/nike?mibextid=ZbWKwL&ref=bookmarks"),
            "https://www.facebook.com/nike",
        )
        self.assertEqual(
            normalize_url("https://www.facebook.com/profile.php?id=100064860875397&mibextid=ZbWKwL"),
            "https://www.facebook.com/profile.php?id=100064860875397",
        )

    def test_parse_follower_count_standard(self):
        self.assertEqual(parse_follower_count("1,126"), 1126)
        self.assertEqual(parse_follower_count("500"), 500)
        self.assertEqual(parse_follower_count("1.126"), 1126)
        self.assertEqual(parse_follower_count("15,400"), 15400)

    def test_parse_follower_count_suffixes(self):
        self.assertEqual(parse_follower_count("1.5K"), 1500)
        self.assertEqual(parse_follower_count("2M"), 2_000_000)
        self.assertEqual(parse_follower_count("10k"), 10000)
        self.assertEqual(parse_follower_count("2.5M"), 2500000)

    def test_parse_follower_count_invalid(self):
        self.assertEqual(parse_follower_count(""), 0)
        self.assertEqual(parse_follower_count("abc"), 0)

    def test_parse_html_spanish_description(self):
        sample_html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta property="og:title" content="Crónicas Urbanas | Facebook" />
            <meta name="description"
                  content="Crónicas Urbanas, Chicago. 1,126 likes · 5 talking about this." />
        </head>
        <body></body>
        </html>
        """
        name, followers, status = parse_html(sample_html)
        self.assertEqual(name, "Crónicas Urbanas")
        self.assertEqual(followers, 1126)
        self.assertEqual(status, "Éxito")

    def test_parse_html_english_seguidores(self):
        sample_html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta property="og:title" content="Tech News Daily" />
            <meta property="og:description"
                  content="Tech News Daily. 2.5M seguidores · Noticias de tecnología" />
        </head>
        <body></body>
        </html>
        """
        name, followers, status = parse_html(sample_html)
        self.assertEqual(name, "Tech News Daily")
        self.assertEqual(followers, 2_500_000)
        self.assertEqual(status, "Éxito")

    def test_parse_html_no_followers_found(self):
        sample_html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta property="og:title" content="Private Profile | Facebook" />
        </head>
        <body><div>No metadata</div></body>
        </html>
        """
        name, followers, status = parse_html(sample_html)
        self.assertEqual(name, "Private Profile")
        self.assertEqual(followers, 0)
        self.assertIn("No se encontraron seguidores", status)

    def test_parse_html_apostrophe_and_entity_not_truncated(self):
        """McDonald's with &#039; must not truncate metadata at the apostrophe."""
        sample_html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta property="og:title" content="McDonald&#039;s" />
            <meta property="og:description"
                  content="McDonald&#039;s. 82&#xa0;213&#xa0;384&#xa0;seguidores &#xb7; 102&#xa0;927 personas est&#xe1;n hablando de esto." />
        </head>
        <body></body>
        </html>
        """
        name, followers, status = parse_html(sample_html)
        self.assertEqual(name, "McDonald's")
        self.assertEqual(followers, 82_213_384)
        self.assertEqual(status, "Éxito")

    def test_parse_html_spanish_millones_de_seguidores(self):
        sample_html = """
        <html>
        <head>
            <meta property="og:title" content="Canal Oficial" />
            <meta name="description"
                  content="Canal Oficial. 2 millones de seguidores &#xb7; 15 mil me gusta." />
        </head>
        </html>
        """
        name, followers, status = parse_html(sample_html)
        self.assertEqual(name, "Canal Oficial")
        self.assertEqual(followers, 2_000_000)
        self.assertEqual(status, "Éxito")

    def test_parse_html_spanish_mill_de_seguidores(self):
        sample_html = """
        <html>
        <head>
            <meta property="og:title" content="Gran Marca" />
            <meta property="og:description"
                  content="Gran Marca. 1,5 mill. de seguidores." />
        </head>
        </html>
        """
        name, followers, status = parse_html(sample_html)
        self.assertEqual(name, "Gran Marca")
        self.assertEqual(followers, 1_500_000)
        self.assertEqual(status, "Éxito")

    def test_parse_html_followers_priority_over_likes(self):
        """Followers must win even when likes appears earlier in description."""
        sample_html = """
        <html>
        <head>
            <meta property="og:title" content="Comunidad Activa" />
            <meta property="og:description"
                  content="Comunidad Activa. 10 mil me gusta &#xb7; 25 mil seguidores." />
        </head>
        </html>
        """
        name, followers, status = parse_html(sample_html)
        self.assertEqual(name, "Comunidad Activa")
        self.assertEqual(followers, 25_000)
        self.assertEqual(status, "Éxito")

    def test_parse_html_spanish_personas_que_siguen(self):
        sample_html = """
        <html>
        <head>
            <meta property="og:title" content="Revista Digital" />
            <meta property="og:description"
                  content="Revista Digital. 15.420 personas que siguen esta página." />
        </head>
        </html>
        """
        name, followers, status = parse_html(sample_html)
        self.assertEqual(name, "Revista Digital")
        self.assertEqual(followers, 15_420)
        self.assertEqual(status, "Éxito")

    def test_parse_html_twitter_description_fallback(self):
        sample_html = """
        <html>
        <head>
            <meta name="twitter:title" content="Page with Twitter Meta" />
            <meta name="twitter:description"
                  content="Page with Twitter Meta. 450K followers." />
        </head>
        </html>
        """
        name, followers, status = parse_html(sample_html)
        self.assertEqual(name, "Page with Twitter Meta")
        self.assertEqual(followers, 450_000)
        self.assertEqual(status, "Éxito")


class RunnerDataProtectionTests(TestCase):
    """Verifies that extraction runner preserves existing metrics on scrape failure."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(username="runner_user", password="pwd")
        self.page = FacebookPage.objects.create(
            user=self.user,
            url="https://www.facebook.com/tested/",
            name="Tested Page",
            followers=50_000,
            status="Activa",
        )
        self.job = ExtractionJob.objects.create(
            user=self.user,
            total_urls=1,
        )

    def test_failed_scrape_preserves_positive_followers(self):
        failed_result = ExtractionResult(
            url="https://www.facebook.com/tested/",
            name="Desconocido",
            followers=0,
            status="No se encontraron seguidores en el DOM",
            is_success=False,
            error="Scrape returned 0",
        )

        save_item_to_db(str(self.job.id), failed_result)

        self.page.refresh_from_db()
        # Must retain 50,000 followers and not be overwritten with 0
        self.assertEqual(self.page.followers, 50_000)
        self.assertEqual(self.page.name, "Tested Page")
        self.assertIn("Alerta", self.page.status)

    def test_successful_scrape_updates_followers_and_creates_snapshot(self):
        success_result = ExtractionResult(
            url="https://www.facebook.com/tested/",
            name="Tested Page Updated",
            followers=55_000,
            status="Éxito",
            is_success=True,
        )

        save_item_to_db(str(self.job.id), success_result)

        self.page.refresh_from_db()
        self.assertEqual(self.page.followers, 55_000)
        self.assertEqual(self.page.name, "Tested Page Updated")
        self.assertEqual(self.page.status, "Éxito")
        self.assertEqual(PageGrowthSnapshot.objects.filter(page=self.page).count(), 1)

