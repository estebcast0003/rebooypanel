import asyncio
import html
import json
import logging
import re
import ssl
from dataclasses import dataclass
from urllib.parse import urlparse

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
    """Normalizes raw input URLs ensuring proper https protocol and clean domain."""
    url = raw_url.strip()
    if not url:
        return ""
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
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


def _extract_meta_content(html_text: str, *attribute_patterns: str) -> list[str]:
    """Extracts all content attributes matching given attribute patterns."""
    found = []
    for pattern in attribute_patterns:
        for m in re.findall(rf'<meta\s+[^>]*?{pattern}[^>]*?content=["\']([^"\']+)["\']', html_text, re.IGNORECASE):
            if m.strip() and m.strip() not in found:
                found.append(m.strip())
        for m in re.findall(rf'<meta\s+[^>]*?content=["\']([^"\']+)["\'][^>]*?{pattern}', html_text, re.IGNORECASE):
            if m.strip() and m.strip() not in found:
                found.append(m.strip())
    return found


def parse_html(html_content: str) -> tuple[str, int, str]:
    """Extracts page title and follower/like counts from server-rendered HTML meta tags and JSON-LD."""
    text = html.unescape(html_content)

    followers_count = 0
    name = "Desconocido"
    status_msg = "No se encontraron seguidores en el DOM"

    # Strategy 1: JSON-LD schemas
    for json_script in re.findall(r'<script[^>]*?type=["\']application/ld\+json["\'][^>]*?>(.*?)</script>', text, re.DOTALL | re.IGNORECASE):
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

    # Strategy 2: Meta description & og:description
    descriptions = _extract_meta_content(
        text,
        r'name=["\']description["\']',
        r'property=["\']og:description["\']',
        r'name=["\']og:description["\']',
    )

    follower_regexes = [
        r"(\d+(?:[\s.,\xa0\u202f]\d+)*(?:\s*(?:k\b|m\b|b\b|mil\b|millones\b|millón\b|mill\b|mill\.))?)\s*(?:followers|seguidores|personas\s+siguen|personas\s+están\s+siguiendo|personas\s+que\s+siguen|siguen\s+esto|people\s+follow\s+this|likes|me\s+gusta|personas\s+les\s+gusta)",
        r"(?:followers|seguidores|likes|me gusta):\s*(\d+(?:[\s.,\xa0\u202f]\d+)*(?:\s*(?:k\b|m\b|b\b|mil\b|millones\b|millón\b|mill\b|mill\.))?)",
        r"(\d+(?:[\s.,\xa0\u202f]\d+)*(?:\s*(?:k\b|m\b|b\b|mil\b|millones\b|millón\b|mill\b|mill\.))?)\s*(?:•|·|,)\s*\d+.*?(?:followers|seguidores|likes|me gusta)",
    ]

    for desc in descriptions:
        for rgx in follower_regexes:
            match = re.search(rgx, desc, re.IGNORECASE)
            if match:
                f_count = parse_follower_count(match.group(1))
                if f_count > followers_count:
                    followers_count = f_count
                    status_msg = "Éxito"

        if (not name or name == "Desconocido") and "." in desc:
            first_sentence = desc.split(".")[0].strip()
            if first_sentence and len(first_sentence) < 80:
                name = first_sentence

    # Strategy 3: og:title & title tag
    titles = _extract_meta_content(text, r'property=["\']og:title["\']', r'name=["\']og:title["\']')
    if not titles:
        titles = re.findall(r'<title[^>]*>(.*?)</title>', text, re.IGNORECASE)

    for title in titles:
        extracted = title.strip()
        if extracted and extracted.lower() not in ("facebook", "log in to facebook", "iniciar sesión en facebook"):
            cleaned = re.sub(r"\s*(\||-)\s*Facebook.*$", "", extracted, flags=re.IGNORECASE).strip()
            if cleaned:
                name = cleaned
                break

    # Strategy 4: Raw embedded JSON search
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
            jmatch = re.search(jpat, text)
            if jmatch:
                try:
                    c = int(jmatch.group(1))
                    if c > followers_count:
                        followers_count = c
                        status_msg = "Éxito"
                except ValueError:
                    pass

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
    browser_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.9,en-US,en;q=0.8",
        "Sec-Ch-Ua": '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
    }

    # 1. Primary Strategy: Crawler Header
    response = await _execute_http_get(client, normalized_url, crawler_headers, timeout)
    response.raise_for_status()
    name, followers, status_msg = parse_html(response.text)

    # 2. Secondary Strategy if crawler returned 0 followers: Standard Browser User-Agent
    if followers == 0:
        try:
            b_response = await _execute_http_get(client, normalized_url, browser_headers, timeout)
            if b_response.is_success:
                b_name, b_followers, b_status = parse_html(b_response.text)
                if b_followers > 0:
                    name, followers, status_msg = b_name, b_followers, b_status
        except Exception:
            pass

    return name, followers, status_msg


async def fetch_page(
    client: httpx.AsyncClient,
    url: str,
    timeout: float = 15.0,
    direct_client: httpx.AsyncClient | None = None,
) -> ExtractionResult:
    """Fetches a single Facebook page via crawler headers through proxy with direct fallback."""
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
            return ExtractionResult(
                url=normalized_url,
                name=name,
                followers=followers,
                status=status_msg,
                is_success=True,
            )
    except Exception as first_err:
        logger.warning(f"Client fetch failed for {normalized_url}: {first_err}")
        # If proxy failed (SSL/connection error), attempt direct fallback
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
            name, followers, status_msg = await _fetch_with_client(direct_client, normalized_url, timeout)
            if followers > 0:
                return ExtractionResult(
                    url=normalized_url,
                    name=name,
                    followers=followers,
                    status=status_msg,
                    is_success=True,
                )
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
    """Executes concurrent fetching bounded by semaphore with transparent proxy & direct fallbacks."""
    proxy = proxy_url or getattr(settings, "EXTRACTOR_PROXY_URL", None)
    max_concurrency = concurrency or getattr(settings, "EXTRACTOR_CONCURRENCY", 10)
    req_timeout = timeout or getattr(settings, "EXTRACTOR_TIMEOUT", 15.0)

    semaphore = asyncio.Semaphore(max_concurrency)
    results: list[ExtractionResult] = []

    async def _sem_fetch(active_client: httpx.AsyncClient, target_url: str, fallback_client: httpx.AsyncClient | None = None):
        async with semaphore:
            res = await fetch_page(active_client, target_url, timeout=req_timeout, direct_client=fallback_client)
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
        if proxy:
            try:
                async with httpx.AsyncClient(proxy=proxy, limits=limits, verify=ssl_context) as proxy_client:
                    tasks = [_sem_fetch(proxy_client, u, fallback_client=direct_client) for u in clean_urls]
                    await asyncio.gather(*tasks, return_exceptions=True)
            except Exception as proxy_err:
                logger.warning(f"Proxy client crashed ({proxy_err}), executing via direct client...")
                tasks = [_sem_fetch(direct_client, u, fallback_client=None) for u in clean_urls]
                await asyncio.gather(*tasks, return_exceptions=True)
        else:
            tasks = [_sem_fetch(direct_client, u, fallback_client=None) for u in clean_urls]
            await asyncio.gather(*tasks, return_exceptions=True)

    return results


