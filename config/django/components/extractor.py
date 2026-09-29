"""Configuración de Facebook Fan Extractor e Instagram cookies."""

from config.env import env, BASE_DIR

# Facebook Fan Extractor Configuration
EXTRACTOR_PROXY_URL = env.str(
    'EXTRACTOR_PROXY_URL',
    default='http://16cd081adb430f3592f4__cr.us:f95ce491ea42ffa9@gw.dataimpulse.com:823'
)
EXTRACTOR_CONCURRENCY = env.int('EXTRACTOR_CONCURRENCY', default=10)
EXTRACTOR_TIMEOUT = env.float('EXTRACTOR_TIMEOUT', default=15.0)

# Instagram / Facebook Session Cookies Path
INSTAGRAM_COOKIE_FILE = env.str(
    'INSTAGRAM_COOKIE_FILE',
    default=str(BASE_DIR / 'cookies.txt')
)
