import asyncio
import json
import logging
import re
import ssl
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)


@dataclass
class ExtractionResult:
    """Represents the parsed outcome of a single page scrape."""

    url: str
    name: str
    followers: int
    status: str
    is_success: bool
    error: str | None = None


def normalize_url(raw_url: str) -> str:
    """Normalizes raw input URLs ensuring proper https protocol, clean domain, and stripped tracking params."""
    url = raw_url.strip()
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        p = urlparse(url)
        netloc = p.netloc.lower()
        if netloc in (
            "m.facebook.com",
            "mobile.facebook.com",
            "web.facebook.com",
            "touch.facebook.com",
        ):
            netloc = "www.facebook.com"

        path = p.path
        if "profile.php" in path:
            qs = parse_qs(p.query)
            clean_qs = {}
            if "id" in qs and qs["id"]:
                clean_qs["id"] = qs["id"][0]
            query = urlencode(clean_qs)
        else:
            query = ""

        return urlunparse((p.scheme or "https", netloc, path, "", query, ""))
    except Exception:
        return url


def parse_follower_count(text: str) -> int:
    """Parses follower string: 1.5K, 2,5M, 15 mil, 2.4 mill., 121,232,196, 500."""
    if not text:
        return 0
    clean = text.strip().replace("\xa0", " ").replace("\u202f", " ").lower()

    # 1. Billions
    bill_match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:billones\b|billón\b|bill\b|bill\.|b\b)", clean)
    if bill_match:
        val = bill_match.group(1).replace(",", ".")
        try:
            return int(float(val) * 1_000_000_000)
        except ValueError:
            pass

    # 2. Millions
    mill_match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:millones\b|millón\b|mill\b|mill\.|m\b)", clean)
    if mill_match:
        val = mill_match.group(1).replace(",", ".")
        try:
            return int(float(val) * 1_000_000)
        except ValueError:
            pass

    # 3. Thousands
    thous_match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:mil\b|k\b)", clean)
    if thous_match:
        val = thous_match.group(1).replace(",", ".")
        try:
            return int(float(val) * 1_000)
        except ValueError:
            pass

    digits_only = re.sub(r"[^\d]", "", clean)
    if digits_only:
        try:
            return int(digits_only)
        except ValueError:
            pass

    return 0


class MetaTagParser(HTMLParser):
    """Resilient, zero-dependency HTML parser for meta tags and page titles."""

    def __init__(self):
        super().__init__()
        self.metas: list[dict[str, str]] = []
        self.title: str = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        tag_lower = tag.lower()
        if tag_lower == "meta":
            attr_dict = {k.lower(): (v or "") for k, v in attrs}
            self.metas.append(attr_dict)
        elif tag_lower == "title":
            self._in_title = True

    def handle_endtag(self, tag: str):
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str):
        if self._in_title and not self.title:
            self.title = data.strip()


def parse_html(html_content: str) -> tuple[str, int, str]:
    """Extracts page title and follower/like counts from server-rendered HTML meta tags and JSON-LD."""
    followers_count = 0
    name = "Desconocido"
    status_msg = "No se encontraron seguidores en el DOM"

    lower_html = html_content.lower()
    if "login/?next=" in lower_html or "iniciar sesión en facebook" in lower_html or "log in to facebook" in lower_html:
        status_msg = "Requiere inicio de sesión (perfil privado o restringido)"
    elif "contenido no está disponible" in lower_html or "se eliminó" in lower_html or "content isn't available" in lower_html:
        status_msg = "Página no disponible o eliminada"

    # Strategy 1: HTMLParser extraction for meta tags
    parser = MetaTagParser()
    try:
        parser.feed(html_content)
    except Exception:
        pass

    descriptions: list[str] = []
    titles: list[str] = []

    for meta in parser.metas:
        prop = meta.get("property", "").lower()
        m_name = meta.get("name", "").lower()
        content = meta.get("content", "").strip()
        if not content:
            continue

        if prop in ("og:description", "description", "twitter:description") or m_name in (
            "og:description",
            "description",
            "twitter:description",
        ):
            if content not in descriptions:
                descriptions.append(content)

        if prop in ("og:title", "title", "twitter:title") or m_name in (
            "og:title",
            "title",
            "twitter:title",
        ):
            if content not in titles:
                titles.append(content)

    if parser.title and parser.title not in titles:
        titles.append(parser.title)

    # Strategy 2: JSON-LD schemas
    for json_script in re.findall(
        r'<script[^>]*?type=["\']application/ld\+json["\'][^>]*?>(.*?)</script>',
        html_content,
        re.DOTALL | re.IGNORECASE,
    ):
        try:
            data = json.loads(json_script.strip())
            if isinstance(data, dict):
                if not name or name == "Desconocido":
                    name = data.get("name") or name
                stats = data.get("interactionStatistic")
                if isinstance(stats, dict) and stats.get("userInteractionCount"):
                    followers_count = int(stats["userInteractionCount"])
                    status_msg = "Éxito"
                elif isinstance(stats, list):
                    for st in stats:
                        if isinstance(st, dict) and st.get("userInteractionCount"):
                            followers_count = int(st["userInteractionCount"])
                            status_msg = "Éxito"
                            break
        except Exception:
            pass

    # Strategy 3: Bilingual Followers & Likes Matching on Meta Descriptions
    # Priority A: Explicit follower patterns (Spanish & English)
    follower_patterns = [
        # "82 213 384 seguidores", "2 millones de seguidores", "1,5 mill. de seguidores", "15K followers", "300 personas siguen esto"
        r"(\d+(?:[\s.,\xa0\u202f]\d+)*(?:\s*(?:k\b|m\b|b\b|mil\b|millones\b|millón\b|mill\b|mill\.))?)\s*(?:de\s+)?(?:followers|seguidores|personas\s+(?:que\s+)?(?:están\s+)?(?:siguiendo|siguen)(?:\s+(?:a\s+)?esta\s+página|\s+esto)?|people\s+follow\s+this)",
        # "Followers: 15K", "Seguidores: 1.5M", "Seguidores · 1500"
        r"(?:followers|seguidores)\s*[:\-•·]\s*(\d+(?:[\s.,\xa0\u202f]\d+)*(?:\s*(?:k\b|m\b|b\b|mil\b|millones\b|millón\b|mill\b|mill\.))?)",
    ]

    # Priority B: Fallback likes patterns (Spanish & English)
    like_patterns = [
        r"(\d+(?:[\s.,\xa0\u202f]\d+)*(?:\s*(?:k\b|m\b|b\b|mil\b|millones\b|millón\b|mill\b|mill\.))?)\s*(?:de\s+)?(?:likes|me\s+gusta|personas\s+les\s+gusta(?:\s+esto)?|people\s+like\s+this)",
        r"(?:likes|me\s+gusta)\s*[:\-•·]\s*(\d+(?:[\s.,\xa0\u202f]\d+)*(?:\s*(?:k\b|m\b|b\b|mil\b|millones\b|millón\b|mill\b|mill\.))?)",
    ]

    # First check Priority A (followers)
    for desc in descriptions:
        for rgx in follower_patterns:
            match = re.search(rgx, desc, re.IGNORECASE)
            if match:
                f_count = parse_follower_count(match.group(1))
                if f_count > followers_count:
                    followers_count = f_count
                    status_msg = "Éxito"

    # If no followers found, fallback to Priority B (likes)
    if followers_count == 0:
        for desc in descriptions:
            for rgx in like_patterns:
                match = re.search(rgx, desc, re.IGNORECASE)
                if match:
                    f_count = parse_follower_count(match.group(1))
                    if f_count > followers_count:
                        followers_count = f_count
                        status_msg = "Éxito"

    # Resolve Page Name from titles or description
    for title in titles:
        extracted = title.strip()
        if extracted and extracted.lower() not in (
            "facebook",
            "log in to facebook",
            "iniciar sesión en facebook",
            "error facebook",
        ):
            cleaned = re.sub(r"\s*(\||-)\s*Facebook.*$", "", extracted, flags=re.IGNORECASE).strip()
            if cleaned:
                name = cleaned
                break

    if (not name or name == "Desconocido") and descriptions:
        for desc in descriptions:
            if "." in desc:
                first_sentence = desc.split(".")[0].strip()
                if first_sentence and len(first_sentence) < 80:
                    name = first_sentence
                    break

    # Strategy 4: Raw embedded JSON search if still 0
    if followers_count == 0:
        json_count_patterns = [
            r'"follower_count":\s*(\d+)',
            r'"followers_count":\s*(\d+)',
            r'"userInteractionCount":\s*"?(\d+)"?',
            r'"like_count":\s*(\d+)',
            r'"likes_count":\s*(\d+)',
            r'"page_likers":\s*(\d+)',
            r'"page_followers":\s*(\d+)',
        ]
        for jpat in json_count_patterns:
            jmatch = re.search(jpat, html_content)
            if jmatch:
                try:
                    c = int(jmatch.group(1))
                    if c > followers_count:
                        followers_count = c
                        status_msg = "Éxito"
                except ValueError:
                    pass

    if followers_count == 0 and status_msg == "No se encontraron seguidores en el DOM":
        if not descriptions and (not titles or all(t.strip().lower() in ("facebook", "log in to facebook", "iniciar sesión en facebook", "error facebook") for t in titles)):
            status_msg = "Página no encontrada, privada o sin datos públicos"
        elif descriptions:
            status_msg = "No se encontraron seguidores en la descripción"

    return name, followers_count, status_msg


def get_ssl_context() -> ssl.SSLContext:
    """Creates a resilient SSL context that bypasses handshake failures and ciphers restrictions."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
    except Exception:
        pass
    return ctx


async def _execute_http_get(client: httpx.AsyncClient, url: str, headers: dict, timeout: float) -> httpx.Response:
    return await client.get(url, headers=headers, timeout=timeout, follow_redirects=True)


async def _fetch_with_client(client: httpx.AsyncClient, normalized_url: str, timeout: float) -> tuple[str, int, str]:
    crawler_headers = {
        "User-Agent": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
        "Accept": "*/*",
        "Accept-Language": "es-ES,es;q=0.9,en-US,en;q=0.8",
    }
    bot_fallback_headers = {
        "User-Agent": "Twitterbot/1.0",
        "Accept": "*/*",
        "Accept-Language": "es-ES,es;q=0.9,en-US,en;q=0.8",
    }

    # 1. Primary Strategy: Facebook Crawler Header
    response = await _execute_http_get(client, normalized_url, crawler_headers, timeout)
    response.raise_for_status()

    # Detect login wall redirect immediately
    final_url_str = str(response.url).lower()
    if "/login" in final_url_str:
        return "Desconocido", 0, "Requiere inicio de sesión (perfil privado o restringido)"

    name, followers, status_msg = parse_html(response.text)

    # 2. Secondary Strategy if crawler returned 0 followers: Secondary Bot Header
    if followers == 0:
        try:
            b_response = await _execute_http_get(client, normalized_url, bot_fallback_headers, timeout)
            if b_response.is_success and "login/?next=" not in str(b_response.url).lower():
                b_name, b_followers, b_status = parse_html(b_response.text)
                if b_followers > 0:
                    name, followers, status_msg = b_name, b_followers, b_status
        except Exception:
            pass

    return name, followers, status_msg


from extractor.services.proxy_manager import default_proxy_manager

async def fetch_page(
    client: httpx.AsyncClient,
    url: str,
    timeout: float = 15.0,
    direct_client: httpx.AsyncClient | None = None,
    current_proxy: str | None = None,
) -> ExtractionResult:
    """Fetches a single Facebook page via crawler headers through proxy with direct fallback and circuit breaker."""
    normalized_url = normalize_url(url)
    if not normalized_url:
        return ExtractionResult(
            url=url,
            name="URL Inválida",
            followers=0,
            status="URL vacía o formato inválido",
            is_success=False,
        )

    # Attempt 1: via main client (proxy or direct)
    try:
        name, followers, status_msg = await _fetch_with_client(client, normalized_url, timeout)
        if followers > 0:
            if current_proxy:
                default_proxy_manager.record_outcome(current_proxy, is_success=True)
            return ExtractionResult(
                url=normalized_url,
                name=name,
                followers=followers,
                status=status_msg,
                is_success=True,
            )
    except Exception as first_err:
        err_text = str(first_err)
        is_rate_limit = "429" in err_text or "checkpoint" in err_text.lower()
        if current_proxy:
            default_proxy_manager.record_outcome(current_proxy, is_success=False, error_msg=err_text, is_rate_limit=is_rate_limit)

        logger.warning(f"Client fetch failed for {normalized_url} (proxy: {current_proxy}): {first_err}")
        # If proxy failed (SSL/connection/rate-limit error), attempt direct fallback
        if direct_client and direct_client != client:
            try:
                name, followers, status_msg = await _fetch_with_client(direct_client, normalized_url, timeout)
                return ExtractionResult(
                    url=normalized_url,
                    name=name,
                    followers=followers,
                    status=status_msg,
                    is_success=followers > 0,
                )
            except Exception as direct_err:
                return ExtractionResult(
                    url=normalized_url,
                    name="Error",
                    followers=0,
                    status=f"Error: {str(direct_err)[:45]}",
                    is_success=False,
                    error=str(direct_err),
                )

        return ExtractionResult(
            url=normalized_url,
            name="Error",
            followers=0,
            status=f"Error: {str(first_err)[:45]}",
            is_success=False,
            error=str(first_err),
        )

    # If first attempt returned 0 followers and we have a direct client, give it a direct try
    if direct_client and direct_client != client:
        try:
            d_name, d_followers, d_status = await _fetch_with_client(direct_client, normalized_url, timeout)
            if d_followers > 0:
                return ExtractionResult(
                    url=normalized_url,
                    name=d_name,
                    followers=d_followers,
                    status=d_status,
                    is_success=True,
                )
            if "Requiere inicio de sesión" in d_status or "Página no disponible" in d_status:
                status_msg = d_status
        except Exception:
            pass

    return ExtractionResult(
        url=normalized_url,
        name=name,
        followers=followers,
        status=status_msg,
        is_success=followers > 0,
    )


async def extract_all_urls(
    urls: list[str],
    proxy_url: str | None = None,
    concurrency: int | None = None,
    timeout: float | None = None,
    item_callback=None,
) -> list[ExtractionResult]:
    """Executes concurrent fetching bounded by semaphore with circuit breaker proxy management & direct fallbacks."""
    max_concurrency = concurrency or getattr(settings, "EXTRACTOR_CONCURRENCY", 10)
    req_timeout = timeout or getattr(settings, "EXTRACTOR_TIMEOUT", 15.0)

    # Select proxy from manager or explicit arg
    active_proxy = proxy_url or default_proxy_manager.get_next_available_proxy()

    semaphore = asyncio.Semaphore(max_concurrency)
    results: list[ExtractionResult] = []

    async def _sem_fetch(active_client: httpx.AsyncClient, target_url: str, fallback_client: httpx.AsyncClient | None = None, proxy_used: str | None = None):
        async with semaphore:
            res = await fetch_page(active_client, target_url, timeout=req_timeout, direct_client=fallback_client, current_proxy=proxy_used)
            results.append(res)
            if item_callback:
                if asyncio.iscoroutinefunction(item_callback):
                    await item_callback(res)
                else:
                    item_callback(res)
            return res

    ssl_context = get_ssl_context()
    limits = httpx.Limits(max_connections=50, max_keepalive_connections=20)
    clean_urls = [normalize_url(u) for u in urls if u and u.strip()]

    async with httpx.AsyncClient(limits=limits, verify=ssl_context) as direct_client:
        if active_proxy:
            try:
                async with httpx.AsyncClient(proxy=active_proxy, limits=limits, verify=ssl_context) as proxy_client:
                    tasks = [_sem_fetch(proxy_client, u, fallback_client=direct_client, proxy_used=active_proxy) for u in clean_urls]
                    await asyncio.gather(*tasks, return_exceptions=True)
            except Exception as proxy_err:
                logger.warning(f"Proxy client connection crashed ({proxy_err}), switching to direct fallback...")
                default_proxy_manager.record_outcome(active_proxy, is_success=False, error_msg=str(proxy_err))
                tasks = [_sem_fetch(direct_client, u, fallback_client=None, proxy_used=None) for u in clean_urls]
                await asyncio.gather(*tasks, return_exceptions=True)
        else:
            tasks = [_sem_fetch(direct_client, u, fallback_client=None, proxy_used=None) for u in clean_urls]
            await asyncio.gather(*tasks, return_exceptions=True)

    return results
