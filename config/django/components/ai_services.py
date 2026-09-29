"""Configuración de APIs de IA y proxies externos."""

from config.env import env

# OpenRouter API Key para Fanpage Creator
OPENROUTER_API_KEY = env.str(
    'OPENROUTER_API_KEY',
    default='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'
)

# CLI Proxy API Configuration (Google Gemini Proxy)
CLI_PROXY_URL = env.str('CLI_PROXY_URL', default='https://cli.serverdok.site')
CLI_SECRET_KEY = env.str('CLI_SECRET_KEY', default='')
CLI_PROXY_MODEL = env.str('CLI_PROXY_MODEL', default='gemini-3.7-flash-high')

# Public URL of Rebooy Panel for Webhook/Telemetry Callbacks
PANEL_PUBLIC_URL = env.str('PANEL_PUBLIC_URL', default='').rstrip('/')
