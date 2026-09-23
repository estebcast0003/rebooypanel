import os
import tempfile
from unittest.mock import patch, MagicMock
import requests
from django.test import TestCase, Client
from django.urls import reverse
from django.core.exceptions import PermissionDenied

from accounts.models import CustomUser
from wordpress_manager.models import WordPressSite
from wordpress_manager.forms import WordPressSiteForm
from wordpress_manager.services.wordpress_service import (
    clean_instagram_url,
    build_instagram_embed_html,
    clean_slug_for_wordpress,
    append_utm_parameters,
    build_html5_video_player_html,
    build_wordpress_article_html,
    upload_featured_media_to_wordpress,
    publish_article_to_wordpress,
)


class WordPressSiteModelTests(TestCase):
    """
    Tests for WordPressSite model normalization, methods, and connection testing.
    """

    def test_site_url_normalization(self):
        # Missing protocol and trailing slash
        site1 = WordPressSite.objects.create(
            name="Blog Uno",
            site_url="  ejemplo.com/  ",
            username="admin",
            application_password="xxxx"
        )
        self.assertEqual(site1.site_url, "https://ejemplo.com")

        # Existing http protocol and multiple trailing slashes
        site2 = WordPressSite.objects.create(
            name="Blog Dos",
            site_url="http://otrodominio.org///",
            username="admin",
            application_password="yyyy"
        )
        self.assertEqual(site2.site_url, "http://otrodominio.org")

    def test_application_password_normalization(self):
        # Spaces between blocks stripped
        site = WordPressSite.objects.create(
            name="Blog Test",
            site_url="https://misfotos.com",
            username="editor",
            application_password=" abcd 1234 efgh 5678 "
        )
        self.assertEqual(site.application_password, "abcd1234efgh5678")

    def test_get_api_url(self):
        site = WordPressSite.objects.create(
            name="Portal Tech",
            site_url="https://portaltech.io/",
            username="bot",
            application_password="pass"
        )
        # Default endpoint
        self.assertEqual(site.get_api_url(), "https://portaltech.io/wp-json/wp/v2/posts")
        # Custom endpoint without leading slash
        self.assertEqual(site.get_api_url("users/me"), "https://portaltech.io/wp-json/wp/v2/users/me")
        # Custom endpoint with leading slash
        self.assertEqual(site.get_api_url("/categories"), "https://portaltech.io/wp-json/wp/v2/categories")

    def test_str_representation(self):
        site = WordPressSite.objects.create(
            name="Mi Blog",
            site_url="https://miblog.com",
            username="admin",
            application_password="pass"
        )
        self.assertEqual(str(site), "Mi Blog (https://miblog.com)")

    @patch("wordpress_manager.models.requests.get")
    def test_connection_success(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": 1, "name": "Super Admin WP", "slug": "superadmin"}
        mock_get.return_value = mock_response

        site = WordPressSite.objects.create(
            name="Blog Conectado",
            site_url="https://conectado.com",
            username="wpadmin",
            application_password="aaaa bbbb cccc dddd"
        )

        success, message = site.test_connection()

        self.assertTrue(success)
        self.assertIn("Super Admin WP", message)
        site.refresh_from_db()
        self.assertEqual(site.last_status, WordPressSite.STATUS_CONNECTED)
        self.assertEqual(site.last_error, "")

        # Verify auth used clean password without spaces
        mock_get.assert_called_once()
        args, kwargs = mock_get.call_args
        self.assertEqual(kwargs["auth"], ("wpadmin", "aaaabbbbccccdddd"))

    @patch("wordpress_manager.models.requests.get")
    def test_connection_http_error(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.json.return_value = {
            "code": "incorrect_password",
            "message": "La contraseña de aplicación no es válida."
        }
        mock_get.return_value = mock_response

        site = WordPressSite.objects.create(
            name="Blog Error",
            site_url="https://errorblog.com",
            username="wpadmin",
            application_password="badpassword"
        )

        success, message = site.test_connection()

        self.assertFalse(success)
        self.assertIn("La contraseña de aplicación no es válida", message)
        site.refresh_from_db()
        self.assertEqual(site.last_status, WordPressSite.STATUS_ERROR)
        self.assertIn("HTTP 401", site.last_error)

    @patch("wordpress_manager.models.requests.get")
    def test_connection_timeout(self, mock_get):
        mock_get.side_effect = requests.exceptions.Timeout("Connection timed out")

        site = WordPressSite.objects.create(
            name="Blog Timeout",
            site_url="https://timeoutblog.com",
            username="wpadmin",
            application_password="pass"
        )

        success, message = site.test_connection()

        self.assertFalse(success)
        self.assertIn("timeout", message.lower())
        site.refresh_from_db()
        self.assertEqual(site.last_status, WordPressSite.STATUS_ERROR)


class WordPressSiteFormTests(TestCase):
    """
    Tests for WordPressSiteForm validation and cleaning.
    """

    def test_form_valid_data(self):
        data = {
            'name': 'Sitio Nuevo',
            'site_url': 'https://sitionuevo.com',
            'username': 'admin',
            'application_password': 'abcd efgh ijkl mnop',
            'is_active': True,
            'test_connection_on_save': False,
        }
        form = WordPressSiteForm(data=data)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['application_password'], 'abcdefghijklmnop')
        self.assertEqual(form.cleaned_data['site_url'], 'https://sitionuevo.com')

    def test_form_strips_trailing_slash(self):
        data = {
            'name': 'Sitio Slash',
            'site_url': 'sitionuevo.com///',
            'username': 'admin',
            'application_password': 'secretpassword',
            'is_active': True,
        }
        form = WordPressSiteForm(data=data)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['site_url'], 'https://sitionuevo.com')


class WordPressManagerPermissionsTests(TestCase):
    """
    Tests verifying RBAC:
    - Unauthenticated users redirected to login.
    - Regular users (role='user' / role='admin') receive HTTP 403 Forbidden.
    - Superadmin users (role='superadmin') receive HTTP 200 OK.
    """

    def setUp(self):
        self.client = Client()
        self.regular_user = CustomUser.objects.create_user(
            username="regular_user", password="password123", role="user"
        )
        self.admin_user = CustomUser.objects.create_user(
            username="admin_user", password="password123", role="admin"
        )
        self.superadmin = CustomUser.objects.create_user(
            username="superadmin_user", password="password123", role="superadmin"
        )
        self.site = WordPressSite.objects.create(
            name="Sitio Permisos",
            site_url="https://permisos.com",
            username="wpadmin",
            application_password="password"
        )

    def test_unauthenticated_redirects(self):
        # List view
        res = self.client.get(reverse('wordpress_manager:site_list'))
        self.assertEqual(res.status_code, 302)

        # Create view
        res = self.client.get(reverse('wordpress_manager:site_create'))
        self.assertEqual(res.status_code, 302)

        # Edit view
        res = self.client.get(reverse('wordpress_manager:site_edit', kwargs={'pk': self.site.pk}))
        self.assertEqual(res.status_code, 302)

        # Delete view
        res = self.client.get(reverse('wordpress_manager:site_delete', kwargs={'pk': self.site.pk}))
        self.assertEqual(res.status_code, 302)

        # Toggle view
        res = self.client.post(reverse('wordpress_manager:site_toggle', kwargs={'pk': self.site.pk}))
        self.assertEqual(res.status_code, 302)

        # Test AJAX view
        res = self.client.post(reverse('wordpress_manager:test_connection_ajax', kwargs={'pk': self.site.pk}))
        self.assertEqual(res.status_code, 302)

    def test_regular_user_denied_403(self):
        self.client.login(username="regular_user", password="password123")

        # List view returns 403
        res = self.client.get(reverse('wordpress_manager:site_list'))
        self.assertEqual(res.status_code, 403)

        # Create view returns 403
        res = self.client.get(reverse('wordpress_manager:site_create'))
        self.assertEqual(res.status_code, 403)

        # Edit view returns 403
        res = self.client.get(reverse('wordpress_manager:site_edit', kwargs={'pk': self.site.pk}))
        self.assertEqual(res.status_code, 403)

        # Delete view returns 403
        res = self.client.get(reverse('wordpress_manager:site_delete', kwargs={'pk': self.site.pk}))
        self.assertEqual(res.status_code, 403)

        # Toggle view returns 403
        res = self.client.post(reverse('wordpress_manager:site_toggle', kwargs={'pk': self.site.pk}))
        self.assertEqual(res.status_code, 403)

        # AJAX test connection returns 403
        res = self.client.post(reverse('wordpress_manager:test_connection_ajax', kwargs={'pk': self.site.pk}))
        self.assertEqual(res.status_code, 403)

    def test_admin_user_denied_403(self):
        self.client.login(username="admin_user", password="password123")

        res = self.client.get(reverse('wordpress_manager:site_list'))
        self.assertEqual(res.status_code, 403)

    def test_superadmin_allowed_200(self):
        self.client.login(username="superadmin_user", password="password123")

        res = self.client.get(reverse('wordpress_manager:site_list'))
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, 'wordpress_manager/site_list.html')


class WordPressManagerCRUDTests(TestCase):
    """
    Tests for full CRUD operations and AJAX endpoints by superadmin.
    """

    def setUp(self):
        self.client = Client()
        self.superadmin = CustomUser.objects.create_user(
            username="superadmin_crud", password="password123", role="superadmin"
        )
        self.client.login(username="superadmin_crud", password="password123")

    @patch("wordpress_manager.models.requests.get")
    def test_site_create_with_immediate_test(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"name": "Admin Root"}
        mock_get.return_value = mock_response

        data = {
            'name': 'Nuevo Sitio WP',
            'site_url': 'https://sitio1.com/',
            'username': 'admin1',
            'application_password': '1111 2222 3333 4444',
            'is_active': True,
            'test_connection_on_save': True,
        }
        res = self.client.post(reverse('wordpress_manager:site_create'), data=data, follow=True)
        self.assertEqual(res.status_code, 200)

        site = WordPressSite.objects.get(site_url='https://sitio1.com')
        self.assertEqual(site.name, 'Nuevo Sitio WP')
        self.assertEqual(site.application_password, '1111222233334444')
        self.assertEqual(site.last_status, WordPressSite.STATUS_CONNECTED)

    def test_site_create_without_immediate_test(self):
        data = {
            'name': 'Sitio Sin Test',
            'site_url': 'https://sitio2.com',
            'username': 'admin2',
            'application_password': 'mypassword',
            'is_active': True,
            'test_connection_on_save': False,
        }
        res = self.client.post(reverse('wordpress_manager:site_create'), data=data, follow=True)
        self.assertEqual(res.status_code, 200)

        site = WordPressSite.objects.get(site_url='https://sitio2.com')
        self.assertEqual(site.last_status, WordPressSite.STATUS_UNTESTED)

    def test_site_edit(self):
        site = WordPressSite.objects.create(
            name="Nombre Viejo",
            site_url="https://sitioedit.com",
            username="admin_edit",
            application_password="password_edit"
        )
        edit_url = reverse('wordpress_manager:site_edit', kwargs={'pk': site.pk})

        # GET form
        res = self.client.get(edit_url)
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, 'wordpress_manager/site_form.html')

        # POST update
        data = {
            'name': 'Nombre Actualizado',
            'site_url': 'https://sitioedit.com',
            'username': 'admin_edit_2',
            'application_password': 'newpassword123',
            'is_active': False,
            'test_connection_on_save': False,
        }
        res = self.client.post(edit_url, data=data, follow=True)
        self.assertEqual(res.status_code, 200)

        site.refresh_from_db()
        self.assertEqual(site.name, 'Nombre Actualizado')
        self.assertEqual(site.username, 'admin_edit_2')
        self.assertEqual(site.application_password, 'newpassword123')
        self.assertFalse(site.is_active)

    def test_site_delete(self):
        site = WordPressSite.objects.create(
            name="A Borrar",
            site_url="https://aborrar.com",
            username="admin",
            application_password="pass"
        )
        delete_url = reverse('wordpress_manager:site_delete', kwargs={'pk': site.pk})

        # GET confirm page
        res = self.client.get(delete_url)
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, 'wordpress_manager/site_confirm_delete.html')

        # POST delete
        res = self.client.post(delete_url, follow=True)
        self.assertEqual(res.status_code, 200)
        self.assertFalse(WordPressSite.objects.filter(pk=site.pk).exists())

    def test_site_toggle(self):
        site = WordPressSite.objects.create(
            name="Sitio Toggle",
            site_url="https://toggle.com",
            username="admin",
            application_password="pass",
            is_active=True
        )
        toggle_url = reverse('wordpress_manager:site_toggle', kwargs={'pk': site.pk})

        # POST toggle standard
        res = self.client.post(toggle_url, follow=True)
        self.assertEqual(res.status_code, 200)
        site.refresh_from_db()
        self.assertFalse(site.is_active)

        # POST toggle via AJAX
        res = self.client.post(toggle_url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res.status_code, 200)
        json_data = res.json()
        self.assertEqual(json_data['status'], 'success')
        self.assertTrue(json_data['is_active'])
        site.refresh_from_db()
        self.assertTrue(site.is_active)

    @patch("wordpress_manager.models.requests.get")
    def test_test_connection_ajax_endpoint(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"name": "Test User"}
        mock_get.return_value = mock_response

        site = WordPressSite.objects.create(
            name="Sitio Ajax Test",
            site_url="https://ajaxtest.com",
            username="admin",
            application_password="pass"
        )
        test_url = reverse('wordpress_manager:test_connection_ajax', kwargs={'pk': site.pk})

        res = self.client.post(test_url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['status'], WordPressSite.STATUS_CONNECTED)
        self.assertIn("Test User", data['message'])

    def test_site_list_filtering(self):
        site1 = WordPressSite.objects.create(
            name="Tecnologia Alfa",
            site_url="https://alfa.com",
            username="alfa",
            application_password="p",
            last_status=WordPressSite.STATUS_CONNECTED
        )
        site2 = WordPressSite.objects.create(
            name="Cocina Beta",
            site_url="https://beta.com",
            username="beta",
            application_password="p",
            last_status=WordPressSite.STATUS_ERROR
        )

        list_url = reverse('wordpress_manager:site_list')

        # Filter by search term
        res = self.client.get(f"{list_url}?q=Tecnologia")
        self.assertEqual(res.status_code, 200)
        sites = list(res.context['sites'])
        self.assertIn(site1, sites)
        self.assertNotIn(site2, sites)

        # Filter by status
        res = self.client.get(f"{list_url}?status=connected")
        self.assertEqual(res.status_code, 200)
        sites = list(res.context['sites'])
        self.assertIn(site1, sites)
        self.assertNotIn(site2, sites)


class WordPressManagerAdminTests(TestCase):
    """
    Tests for Django Admin integration.
    """

    def setUp(self):
        self.client = Client()
        self.superadmin = CustomUser.objects.create_user(
            username="superadmin_admin", password="password123", role="superadmin", is_staff=True, is_superuser=True
        )
        self.client.login(username="superadmin_admin", password="password123")
        self.site = WordPressSite.objects.create(
            name="Admin Site",
            site_url="https://adminsite.com",
            username="admin",
            application_password="pass"
        )

    def test_admin_changelist_accessible(self):
        url = reverse('admin:wordpress_manager_wordpresssite_changelist')
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Admin Site")

    def test_admin_change_form_accessible(self):
        url = reverse('admin:wordpress_manager_wordpresssite_change', args=[self.site.pk])
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "https://adminsite.com")


class WordPressServiceTests(TestCase):
    """
    Unit tests for WordPress service:
    - Instagram embed generator (Option A) and URL cleaning
    - Article HTML combination and placement
    - Randomized multi-domain rotation
    - Failover loop and error recording
    - Multi-domain total failure handling
    """

    def setUp(self):
        self.site1 = WordPressSite.objects.create(
            name="Sitio Principal",
            site_url="https://sitiouno.com",
            username="admin1",
            application_password="aaaa bbbb cccc dddd",
            is_active=True,
        )
        self.site2 = WordPressSite.objects.create(
            name="Sitio Respaldo",
            site_url="https://sitiodos.com",
            username="admin2",
            application_password="eeee ffff gggg hhhh",
            is_active=True,
        )

    def test_clean_instagram_url(self):
        # URL with tracking parameters
        url_with_params = "https://www.instagram.com/reel/C8qL_yGsq6n/?igsh=MWQ4&utm_source=ig_web_copy_link"
        self.assertEqual(
            clean_instagram_url(url_with_params),
            "https://www.instagram.com/reel/C8qL_yGsq6n/"
        )

        # Post URL without trailing slash
        post_url = "https://www.instagram.com/p/Cz12345"
        self.assertEqual(
            clean_instagram_url(post_url),
            "https://www.instagram.com/p/Cz12345/"
        )

        # URL without scheme
        raw_url = "instagram.com/reel/AbcDef123/"
        self.assertEqual(
            clean_instagram_url(raw_url),
            "https://instagram.com/reel/AbcDef123/"
        )

        # Empty and None values
        self.assertEqual(clean_instagram_url(""), "")
        self.assertEqual(clean_instagram_url(None), "")
        self.assertEqual(clean_instagram_url("   "), "")

    def test_build_instagram_embed_html(self):
        raw_url = "https://www.instagram.com/reel/C8qL_yGsq6n/?utm_medium=copy_link"
        embed_html = build_instagram_embed_html(raw_url)

        # Structure checks (Option A WordPress standard responsive embed)
        self.assertIn('<figure class="wp-block-embed is-type-rich is-provider-instagram wp-block-embed-instagram">', embed_html)
        self.assertIn('<div class="wp-block-embed__wrapper">', embed_html)
        self.assertIn('<blockquote class="instagram-media"', embed_html)
        self.assertIn('data-instgrm-permalink="https://www.instagram.com/reel/C8qL_yGsq6n/"', embed_html)
        self.assertIn('data-instgrm-version="14"', embed_html)
        self.assertIn('<script async src="//www.instagram.com/embed.js"></script>', embed_html)
        self.assertIn('</div></figure>', embed_html)

        # Query parameters stripped from permalink
        self.assertNotIn('utm_medium', embed_html)

        # Empty / whitespace / None returns empty string
        self.assertEqual(build_instagram_embed_html(""), "")
        self.assertEqual(build_instagram_embed_html(None), "")
        self.assertEqual(build_instagram_embed_html("   "), "")

    def test_build_wordpress_article_html(self):
        ig_url = "https://www.instagram.com/p/Cxyz123/"
        
        # 1. Places embed neatly after the first paragraph </p>
        article_multi_p = "<p>Primer párrafo de introducción.</p><p>Segundo párrafo de desarrollo.</p>"
        result_multi_p = build_wordpress_article_html(article_multi_p, ig_url)
        first_p = "<p>Primer párrafo de introducción.</p>"
        second_p = "<p>Segundo párrafo de desarrollo.</p>"
        
        self.assertTrue(result_multi_p.startswith(first_p))
        self.assertIn("wp-block-embed-instagram", result_multi_p)
        self.assertTrue(result_multi_p.endswith(second_p))
        
        # Verify ordering: first p -> embed -> second p
        p1_pos = result_multi_p.find(first_p)
        embed_pos = result_multi_p.find("wp-block-embed-instagram")
        p2_pos = result_multi_p.find(second_p)
        self.assertTrue(p1_pos < embed_pos < p2_pos)

        # 2. Places embed at the top when no </p> tag exists
        article_no_p = "<h1>Título sin párrafos</h1><div>Texto suelto</div>"
        result_no_p = build_wordpress_article_html(article_no_p, ig_url)
        self.assertTrue(result_no_p.startswith('<figure class="wp-block-embed'))
        self.assertIn(article_no_p, result_no_p)

        # 3. If instagram_url is None or empty, returns unmodified article HTML
        self.assertEqual(build_wordpress_article_html("<p>Solo texto</p>", None), "<p>Solo texto</p>")
        self.assertEqual(build_wordpress_article_html("<p>Solo texto</p>", ""), "<p>Solo texto</p>")
        self.assertEqual(build_wordpress_article_html("<p>Solo texto</p>", "   "), "<p>Solo texto</p>")

        # 4. If article_html is empty, returns embed alone
        result_empty_article = build_wordpress_article_html("", ig_url)
        self.assertIn("wp-block-embed-instagram", result_empty_article)

    def test_publish_article_to_wordpress_no_active_sites(self):
        # Deactivate all sites
        WordPressSite.objects.update(is_active=False)

        with self.assertRaises(ValueError) as ctx:
            publish_article_to_wordpress(
                title="Prueba Sin Sitios",
                content_html="<p>Contenido</p>"
            )

        self.assertIn("No hay dominios de WordPress activos configurados en el sistema.", str(ctx.exception))

    @patch("wordpress_manager.services.wordpress_service.requests.post")
    def test_publish_article_to_wordpress_success(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "id": 789,
            "link": "https://sitiouno.com/articulo-nuevo/",
            "status": "publish",
        }
        mock_post.return_value = mock_response

        # Deactivate site2 so site1 is deterministic
        self.site2.is_active = False
        self.site2.save()

        title = "Artículo de Prueba Exitoso"
        content = "<p>Primer párrafo con datos.</p><p>Segundo párrafo.</p>"
        ig_url = "https://www.instagram.com/reel/C8qL_yGsq6n/"

        result = publish_article_to_wordpress(
            title=title,
            content_html=content,
            instagram_url=ig_url
        )

        self.assertTrue(result['success'])
        self.assertEqual(result['post_id'], 789)
        self.assertEqual(result['post_url'], "https://sitiouno.com/articulo-nuevo/")
        self.assertEqual(result['site_id'], self.site1.id)
        self.assertEqual(result['site_name'], self.site1.name)
        self.assertEqual(result['site_url'], self.site1.site_url)

        # Verify site DB updates
        self.site1.refresh_from_db()
        self.assertEqual(self.site1.posts_published_count, 1)
        self.assertEqual(self.site1.last_status, WordPressSite.STATUS_CONNECTED)
        self.assertEqual(self.site1.last_error, "")
        self.assertIsNotNone(self.site1.last_used_at)

        # Verify POST payload and auth
        mock_post.assert_called_once()
        call_args, call_kwargs = mock_post.call_args
        self.assertEqual(call_args[0], "https://sitiouno.com/wp-json/wp/v2/posts")
        self.assertEqual(call_kwargs['auth'], ("admin1", "aaaabbbbccccdddd"))
        self.assertEqual(call_kwargs['timeout'], 15)
        self.assertEqual(call_kwargs['json']['title'], title)
        self.assertEqual(call_kwargs['json']['status'], 'publish')
        self.assertIn("wp-block-embed-instagram", call_kwargs['json']['content'])
        self.assertIn("https://www.instagram.com/reel/C8qL_yGsq6n/", call_kwargs['json']['content'])

    @patch("wordpress_manager.services.wordpress_service.requests.post")
    def test_publish_article_to_wordpress_with_tags(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": 101, "link": "https://sitiouno.com/post-tags/"}
        mock_post.return_value = mock_response

        self.site2.is_active = False
        self.site2.save()

        publish_article_to_wordpress(
            title="Con Tags",
            content_html="<p>Texto</p>",
            tags=[12, 34]
        )

        call_args, call_kwargs = mock_post.call_args
        self.assertEqual(call_kwargs['json']['tags'], [12, 34])

    @patch("wordpress_manager.services.wordpress_service.random.shuffle")
    @patch("wordpress_manager.services.wordpress_service.requests.post")
    def test_publish_article_to_wordpress_failover_success(self, mock_post, mock_shuffle):
        # Force order: site1 fails, site2 succeeds
        def set_order(lst):
            lst.sort(key=lambda s: s.id)
        mock_shuffle.side_effect = set_order

        # Site 1 returns 500 error
        fail_response = MagicMock()
        fail_response.status_code = 500
        fail_response.json.return_value = {"code": "internal_error", "message": "Fallo en base de datos"}
        
        # Site 2 returns 201 created
        success_response = MagicMock()
        success_response.status_code = 201
        success_response.json.return_value = {"id": 999, "link": "https://sitiodos.com/post-recuperado/"}

        mock_post.side_effect = [fail_response, success_response]

        result = publish_article_to_wordpress(
            title="Prueba Failover",
            content_html="<p>Párrafo principal.</p>"
        )

        # Successful on second site
        self.assertTrue(result['success'])
        self.assertEqual(result['post_id'], 999)
        self.assertEqual(result['site_id'], self.site2.id)
        self.assertEqual(result['site_url'], self.site2.site_url)

        # Site 1 recorded error
        self.site1.refresh_from_db()
        self.assertEqual(self.site1.last_status, WordPressSite.STATUS_ERROR)
        self.assertIn("Fallo en base de datos", self.site1.last_error)
        self.assertEqual(self.site1.posts_published_count, 0)

        # Site 2 recorded success
        self.site2.refresh_from_db()
        self.assertEqual(self.site2.last_status, WordPressSite.STATUS_CONNECTED)
        self.assertEqual(self.site2.last_error, "")
        self.assertEqual(self.site2.posts_published_count, 1)

        # Assert requests.post called twice
        self.assertEqual(mock_post.call_count, 2)

    @patch("wordpress_manager.services.wordpress_service.random.shuffle")
    @patch("wordpress_manager.services.wordpress_service.requests.post")
    def test_publish_article_to_wordpress_failover_timeout(self, mock_post, mock_shuffle):
        # Site 1 raises Timeout, Site 2 succeeds
        def set_order(lst):
            lst.sort(key=lambda s: s.id)
        mock_shuffle.side_effect = set_order

        success_response = MagicMock()
        success_response.status_code = 201
        success_response.json.return_value = {"id": 456, "link": "https://sitiodos.com/post-timeout-ok/"}

        mock_post.side_effect = [
            requests.exceptions.Timeout("Connection timed out after 15s"),
            success_response
        ]

        result = publish_article_to_wordpress(
            title="Prueba Timeout Failover",
            content_html="<p>Párrafo.</p>"
        )

        self.assertTrue(result['success'])
        self.assertEqual(result['post_id'], 456)
        self.assertEqual(result['site_id'], self.site2.id)

        self.site1.refresh_from_db()
        self.assertEqual(self.site1.last_status, WordPressSite.STATUS_ERROR)
        self.assertIn("Timeout", self.site1.last_error)

        self.site2.refresh_from_db()
        self.assertEqual(self.site2.last_status, WordPressSite.STATUS_CONNECTED)

    @patch("wordpress_manager.services.wordpress_service.requests.post")
    def test_publish_article_to_wordpress_all_sites_fail(self, mock_post):
        # Both sites fail with HTTP 403 / 500
        resp1 = MagicMock()
        resp1.status_code = 403
        resp1.json.return_value = {"code": "forbidden", "message": "No tienes permisos"}

        resp2 = MagicMock()
        resp2.status_code = 502
        resp2.json.side_effect = Exception("Not JSON")
        resp2.text = "Bad Gateway"

        mock_post.side_effect = [resp1, resp2]

        with self.assertRaises(RuntimeError) as ctx:
            publish_article_to_wordpress(
                title="Prueba Todos Fallan",
                content_html="<p>Párrafo.</p>"
            )

        err_msg = str(ctx.exception)
        self.assertIn("No se pudo publicar en ningún sitio de WordPress. Errores:", err_msg)
        self.assertIn("No tienes permisos", err_msg)
        self.assertIn("HTTP 502", err_msg)

        # Both sites marked with error
        self.site1.refresh_from_db()
        self.site2.refresh_from_db()
        self.assertEqual(self.site1.last_status, WordPressSite.STATUS_ERROR)
        self.assertEqual(self.site2.last_status, WordPressSite.STATUS_ERROR)

    def test_clean_slug_for_wordpress(self):
        # Strips emojis and generates clean ASCII slug
        title_with_emojis = "¡Aprende este tip increíble 🔥🚀! 100% real #1"
        self.assertEqual(
            clean_slug_for_wordpress(title_with_emojis),
            "aprende-este-tip-increible-100-real-1"
        )

        # Title with only emojis returns empty string
        self.assertEqual(clean_slug_for_wordpress("🔥🚀✨💰"), "")

        # Title with Spanish characters and special punctuation
        title_spanish = "¿Cómo ganar dinero en 2026? 💰✨ ¡Secreto revelado!"
        self.assertEqual(
            clean_slug_for_wordpress(title_spanish),
            "como-ganar-dinero-en-2026-secreto-revelado"
        )

        # Title with accents and ñ
        self.assertEqual(
            clean_slug_for_wordpress("Café con leche y ñoquis"),
            "cafe-con-leche-y-noquis"
        )

        # Empty and None values
        self.assertEqual(clean_slug_for_wordpress(""), "")
        self.assertEqual(clean_slug_for_wordpress(None), "")
        self.assertEqual(clean_slug_for_wordpress("   "), "")

    def test_append_utm_parameters(self):
        base_url = "https://sitiouno.com/mi-articulo/"

        # Appends with '?' when no query parameters exist
        attributed_url = append_utm_parameters(base_url, username="editor_fb")
        self.assertEqual(
            attributed_url,
            "https://sitiouno.com/mi-articulo/?utm_source=facebook&utm_medium=social&utm_campaign=editor_fb&utm_content=comment"
        )

        # Appends with '&' when query parameters already exist
        query_url = "https://sitiouno.com/?p=456"
        attributed_query_url = append_utm_parameters(query_url, username="admin_social")
        self.assertEqual(
            attributed_query_url,
            "https://sitiouno.com/?p=456&utm_source=facebook&utm_medium=social&utm_campaign=admin_social&utm_content=comment"
        )

        # If username is None or whitespace, returns unchanged URL
        self.assertEqual(append_utm_parameters(base_url, username=None), base_url)
        self.assertEqual(append_utm_parameters(base_url, username=""), base_url)
        self.assertEqual(append_utm_parameters(base_url, username="   "), base_url)

        # If post_url is None or empty, returns post_url
        self.assertIsNone(append_utm_parameters(None, username="editor_fb"))
        self.assertEqual(append_utm_parameters("", username="editor_fb"), "")

    def test_build_html5_video_player_html(self):
        video_url = "https://instagram.fcor1.fna.fbcdn.net/video.mp4"
        poster_url = "https://sitiouno.com/wp-content/uploads/portada.jpg"

        player_html = build_html5_video_player_html(direct_video_url=video_url, poster_url=poster_url)

        # Structure and required attributes
        self.assertIn('style="text-align: center; margin: 24px auto; max-width: 600px; width: 100%;"', player_html)
        self.assertIn('controls=""', player_html)
        self.assertIn('playsinline=""', player_html)
        self.assertIn('autoplay=""', player_html)
        self.assertIn('muted=""', player_html)
        self.assertIn('preload="metadata"', player_html)
        self.assertIn(f'poster="{poster_url}"', player_html)
        self.assertIn('class="w-full max-h-[600px] mx-auto bg-black"', player_html)
        self.assertIn(f'<source src="{video_url}" type="video/mp4">', player_html)
        self.assertIn('Tu navegador no soporta la reproducción de video HTML5.', player_html)

        # Without poster URL produces empty poster attribute
        player_without_poster = build_html5_video_player_html(video_url=video_url, poster_url=None)
        self.assertIn('poster=""', player_without_poster)

        # Empty video URL returns empty string
        self.assertEqual(build_html5_video_player_html(""), "")
        self.assertEqual(build_html5_video_player_html(None), "")

    def test_build_wordpress_article_html_with_direct_video(self):
        direct_url = "https://instagram.cdn/reel.mp4"
        poster_url = "https://sitiouno.com/media/poster.jpg"
        ig_url = "https://www.instagram.com/reel/C8qL_yGsq6n/"

        # 1. Places HTML5 player after the first paragraph </p>
        article = "<p>Párrafo inicial del artículo.</p><p>Párrafo final de cierre.</p>"
        result = build_wordpress_article_html(
            article,
            instagram_url=ig_url,
            direct_video_url=direct_url,
            poster_url=poster_url,
        )

        first_p = "<p>Párrafo inicial del artículo.</p>"
        second_p = "<p>Párrafo final de cierre.</p>"
        self.assertTrue(result.startswith(first_p))
        self.assertTrue(result.endswith(second_p))
        self.assertIn('<video controls=""', result)
        self.assertIn(f'poster="{poster_url}"', result)
        self.assertIn(f'<source src="{direct_url}" type="video/mp4">', result)
        # Direct video takes precedence over Instagram embed
        self.assertNotIn("wp-block-embed-instagram", result)

        # 2. Places HTML5 player at the top when no </p> tag exists
        article_no_p = "<div>Contenido sin etiquetas de párrafo</div>"
        result_no_p = build_wordpress_article_html(
            article_no_p,
            direct_video_url=direct_url,
            poster_url=poster_url,
        )
        self.assertTrue(result_no_p.startswith('<div style="text-align: center;'))
        self.assertIn(article_no_p, result_no_p)

    @patch("wordpress_manager.services.wordpress_service.requests.post")
    def test_upload_featured_media_to_wordpress_success(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "id": 88,
            "source_url": "https://sitiouno.com/wp-content/uploads/portada_test.jpg",
        }
        mock_post.return_value = mock_response

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff\xd8\xff\xe0" + b"\x00" * 50)  # fake jpeg header + bytes
            temp_thumb_path = f.name

        try:
            media_id, source_url = upload_featured_media_to_wordpress(
                self.site1,
                thumbnail_path=temp_thumb_path,
                title="Título de la imagen"
            )

            self.assertEqual(media_id, 88)
            self.assertEqual(source_url, "https://sitiouno.com/wp-content/uploads/portada_test.jpg")

            mock_post.assert_called_once()
            call_args, call_kwargs = mock_post.call_args
            self.assertEqual(call_args[0], "https://sitiouno.com/wp-json/wp/v2/media")
            self.assertEqual(call_kwargs['auth'], ("admin1", "aaaabbbbccccdddd"))
            self.assertEqual(call_kwargs['headers']['Content-Type'], "image/jpeg")
            self.assertIn(os.path.basename(temp_thumb_path), call_kwargs['headers']['Content-Disposition'])
            self.assertEqual(call_kwargs['timeout'], 20)
        finally:
            if os.path.exists(temp_thumb_path):
                os.remove(temp_thumb_path)

    def test_upload_featured_media_to_wordpress_file_not_found(self):
        # Non-existent file path
        media_id, source_url = upload_featured_media_to_wordpress(
            self.site1,
            thumbnail_path="/ruta/inexistente/no_existe.jpg"
        )
        self.assertIsNone(media_id)
        self.assertIsNone(source_url)

        # Empty / None path
        self.assertEqual(upload_featured_media_to_wordpress(self.site1, ""), (None, None))
        self.assertEqual(upload_featured_media_to_wordpress(self.site1, None), (None, None))

    @patch("wordpress_manager.services.wordpress_service.requests.post")
    def test_upload_featured_media_to_wordpress_errors(self, mock_post):
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"fake jpeg data")
            temp_path = f.name

        try:
            # HTTP 500 error
            mock_post.return_value = MagicMock(status_code=500, text="Internal Server Error")
            media_id, source_url = upload_featured_media_to_wordpress(self.site1, temp_path)
            self.assertIsNone(media_id)
            self.assertIsNone(source_url)

            # RequestException
            mock_post.side_effect = requests.exceptions.RequestException("Upload connection error")
            media_id, source_url = upload_featured_media_to_wordpress(self.site1, temp_path)
            self.assertIsNone(media_id)
            self.assertIsNone(source_url)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @patch("wordpress_manager.services.wordpress_service.requests.post")
    def test_publish_article_to_wordpress_with_thumbnail_video_and_utm(self, mock_post):
        # Setup: deactivate site2 so site1 is deterministic
        self.site2.is_active = False
        self.site2.save()

        # 1st call: upload media (201)
        media_response = MagicMock()
        media_response.status_code = 201
        media_response.json.return_value = {
            "id": 150,
            "source_url": "https://sitiouno.com/wp-content/uploads/portada_thumb.jpg",
        }

        # 2nd call: publish post (201)
        post_response = MagicMock()
        post_response.status_code = 201
        post_response.json.return_value = {
            "id": 500,
            "link": "https://sitiouno.com/top-5-secretos-revelados/",
            "status": "publish",
        }

        mock_post.side_effect = [media_response, post_response]

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff\xd8\xff\xe0" + b"\x00" * 20)
            temp_thumb = f.name

        try:
            result = publish_article_to_wordpress(
                title="¡Top 5 Secretos Revelados 🔥🚀!",
                content_html="<p>Introducción.</p><p>Cuerpo del artículo.</p>",
                thumbnail_path=temp_thumb,
                direct_video_url="https://video.cdn.com/reel123.mp4",
                username="social_creator",
            )

            self.assertTrue(result['success'])
            self.assertEqual(result['post_id'], 500)
            # Verifies UTM parameters appended to returned post_url
            self.assertEqual(
                result['post_url'],
                "https://sitiouno.com/top-5-secretos-revelados/?utm_source=facebook&utm_medium=social&utm_campaign=social_creator&utm_content=comment"
            )

            # Assert 2 POST calls made: 1 media, 1 post
            self.assertEqual(mock_post.call_count, 2)

            # Inspect post creation payload (call 2)
            post_call_kwargs = mock_post.call_args_list[1][1]
            payload = post_call_kwargs['json']

            # Clean slug without emojis
            self.assertEqual(payload['slug'], "top-5-secretos-revelados")
            # Featured media ID assigned
            self.assertEqual(payload['featured_media'], 150)
            # HTML5 video player injected with poster and video URL
            self.assertIn('<video controls=""', payload['content'])
            self.assertIn('poster="https://sitiouno.com/wp-content/uploads/portada_thumb.jpg"', payload['content'])
            self.assertIn('<source src="https://video.cdn.com/reel123.mp4" type="video/mp4">', payload['content'])
        finally:
            if os.path.exists(temp_thumb):
                os.remove(temp_thumb)


