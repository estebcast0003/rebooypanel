import re
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

# Common country codes to English/Spanish display names
COUNTRY_NAMES = {
    'US': 'United States',
    'BR': 'Brazil',
    'MX': 'Mexico',
    'CO': 'Colombia',
    'AR': 'Argentina',
    'PE': 'Peru',
    'CL': 'Chile',
    'EC': 'Ecuador',
    'ES': 'Spain',
    'VE': 'Venezuela',
    'GT': 'Guatemala',
    'DO': 'Dominican Republic',
    'BO': 'Bolivia',
    'CR': 'Costa Rica',
    'PA': 'Panama',
    'UY': 'Uruguay',
    'PY': 'Paraguay',
    'HN': 'Honduras',
    'SV': 'El Salvador',
    'NI': 'Nicaragua',
    'PR': 'Puerto Rico',
    'CA': 'Canada',
    'GB': 'United Kingdom',
    'FR': 'France',
    'DE': 'Germany',
    'IT': 'Italy',
    'PT': 'Portugal',
    'IN': 'India',
    'PK': 'Pakistan',
    'EG': 'Egypt',
    'TR': 'Turkey',
    'AE': 'United Arab Emirates',
}


def country_code_to_flag(code: str) -> str:
    """
    Converts 2-letter ISO country code into standard unicode flag emoji.
    Example: 'US' -> 🇺🇸, 'BR' -> 🇧🇷, 'MX' -> 🇲🇽.
    """
    if not code or len(code) != 2:
        return '🌐'
    clean = code.upper()
    if not (clean[0].isalpha() and clean[1].isalpha()):
        return '🌐'
    try:
        return ''.join(chr(127397 + ord(c)) for c in clean)
    except Exception:
        return '🌐'


def parse_client_device_and_software(user_agent: str) -> Dict[str, str]:
    """
    Parses User-Agent string to detect Device Type, Operating System, and Browser.
    Detects Facebook In-App Browser (FBAN/FBAV), Instagram, Chrome, Safari, etc.
    """
    ua = user_agent or ''
    ua_lower = ua.lower()

    # 1. Device Type
    device_type = 'desktop'
    if any(k in ua_lower for k in ['ipad', 'tablet', 'kindle', 'playbook', 'silk']):
        device_type = 'tablet'
    elif any(k in ua_lower for k in ['mobile', 'iphone', 'ipod', 'android', 'phone', 'blackberry', 'webos']):
        device_type = 'mobile'

    # 2. Operating System
    os_name = 'other'
    if 'android' in ua_lower:
        os_name = 'android'
    elif any(k in ua_lower for k in ['iphone', 'ipad', 'ipod', 'cpu iphone os', 'cpu os']):
        os_name = 'ios'
    elif 'windows' in ua_lower:
        os_name = 'windows'
    elif any(k in ua_lower for k in ['macintosh', 'mac os x', 'macos']):
        os_name = 'macos'
    elif 'linux' in ua_lower:
        os_name = 'linux'

    # 3. Browser / App
    browser_name = 'other'
    # Facebook In-App Browser detection (FBAN = FB App Name, FBAV = FB App Version, FB_IAB, FBSS)
    if any(k in ua for k in ['FBAN', 'FBAV', 'FB_IAB', 'FBSS', '[FB']):
        browser_name = 'facebook'
    elif 'Instagram' in ua:
        browser_name = 'instagram'
    elif any(k in ua for k in ['Edg/', 'Edge/']):
        browser_name = 'edge'
    elif 'Firefox/' in ua or 'FxiOS/' in ua:
        browser_name = 'firefox'
    elif any(k in ua for k in ['Chrome/', 'CriOS/']):
        browser_name = 'chrome'
    elif 'Safari/' in ua and 'Chrome/' not in ua:
        browser_name = 'safari'
    elif 'Opera' in ua or 'OPR/' in ua:
        browser_name = 'opera'

    return {
        'device_type': device_type,
        'os_name': os_name,
        'browser_name': browser_name,
    }


def resolve_ip_location(request, ip_address: str = None) -> Dict[str, str]:
    """
    Resolves country and city for incoming request.
    Priority 1: Cloudflare or Reverse Proxy headers (CF-IPCountry, CF-IPCity, X-Country-Code).
    Priority 2: In-memory cached resolver / fallback defaults.
    """
    country_code = ''
    country_name = ''
    city_name = ''

    if request:
        # Cloudflare / Reverse Proxy headers
        country_code = (
            request.META.get('HTTP_CF_IPCOUNTRY') or
            request.META.get('HTTP_X_COUNTRY_CODE') or
            request.META.get('HTTP_GEOIP_COUNTRY_CODE') or ''
        ).strip().upper()

        city_name = (
            request.META.get('HTTP_CF_IPCITY') or
            request.META.get('HTTP_X_CITY') or
            request.META.get('HTTP_GEOIP_CITY') or ''
        ).strip()

    if country_code:
        country_name = COUNTRY_NAMES.get(country_code, country_code)

    # Fallback to local / private indicators
    if not country_code:
        ip = (ip_address or '').strip()
        if ip in ('127.0.0.1', '::1', 'localhost') or ip.startswith(('192.168.', '10.', '172.16.')):
            country_code = 'LOCAL'
            country_name = 'Red Local'
            city_name = 'Desarrollo'
        else:
            country_code = 'XX'
            country_name = 'Desconocido'
            city_name = 'Ubicación Desconocida'

    return {
        'country_code': country_code,
        'country_name': country_name,
        'city_name': city_name,
        'flag_emoji': country_code_to_flag(country_code),
    }
