import logging
import time
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlparse

from django.conf import settings

logger = logging.getLogger(__name__)


class ProxyState(str, Enum):
    HEALTHY = 'healthy'
    COOLDOWN = 'cooldown'
    FAILED = 'failed'


@dataclass
class ProxyNode:
    url: str
    state: ProxyState = ProxyState.HEALTHY
    consecutive_failures: int = 0
    total_requests: int = 0
    total_successes: int = 0
    cooldown_until: float = 0.0
    last_error: str | None = None

    @property
    def is_available(self) -> bool:
        if self.state == ProxyState.HEALTHY:
            return True
        if self.state == ProxyState.COOLDOWN:
            if time.time() >= self.cooldown_until:
                return True
        return False

    def mark_success(self):
        self.state = ProxyState.HEALTHY
        self.consecutive_failures = 0
        self.total_requests += 1
        self.total_successes += 1
        self.last_error = None

    def mark_failure(self, error_msg: str, is_rate_limit: bool = False, cooldown_seconds: int = 300):
        self.total_requests += 1
        self.consecutive_failures += 1
        self.last_error = error_msg

        if is_rate_limit or self.consecutive_failures >= 3:
            self.state = ProxyState.COOLDOWN
            self.cooldown_until = time.time() + cooldown_seconds
            logger.warning(
                f'Proxy {self._safe_repr()} entered COOLDOWN for {cooldown_seconds}s (reason: {error_msg})'
            )
        elif self.consecutive_failures >= 10:
            self.state = ProxyState.FAILED
            logger.error(f'Proxy {self._safe_repr()} marked as permanently FAILED')

    def _safe_repr(self) -> str:
        try:
            parsed = urlparse(self.url)
            host = parsed.hostname or 'unknown'
            port = parsed.port or ''
            return f'{parsed.scheme}://{host}:{port}'
        except Exception:
            return 'proxy'


class ProxyManager:
    def __init__(self, proxy_urls=None, cooldown_seconds=300):
        self.cooldown_seconds = cooldown_seconds
        self._nodes = []
        self._current_index = 0

        raw = proxy_urls or getattr(settings, 'EXTRACTOR_PROXIES', None) or getattr(settings, 'EXTRACTOR_PROXY_URL', None)
        self.set_proxies(raw)

    def set_proxies(self, raw_proxies):
        urls = []
        if isinstance(raw_proxies, str):
            urls = [p.strip() for p in raw_proxies.split(',') if p.strip()]
        elif isinstance(raw_proxies, list):
            urls = [str(p).strip() for p in raw_proxies if str(p).strip()]

        self._nodes = [ProxyNode(url=u) for u in urls]
        self._current_index = 0

    def get_next_available_proxy(self):
        if not self._nodes:
            return None

        total = len(self._nodes)
        for _ in range(total):
            node = self._nodes[self._current_index % total]
            self._current_index = (self._current_index + 1) % total
            if node.is_available:
                return node.url

        logger.warning('Circuit Breaker: All proxies in COOLDOWN or FAILED. Falling back to direct connection.')
        return None

    def record_outcome(self, proxy_url, is_success, error_msg=None, is_rate_limit=False):
        if not proxy_url:
            return

        for node in self._nodes:
            if node.url == proxy_url:
                if is_success:
                    node.mark_success()
                else:
                    node.mark_failure(
                        error_msg=error_msg or 'Unknown error',
                        is_rate_limit=is_rate_limit,
                        cooldown_seconds=self.cooldown_seconds,
                    )
                break

    def get_stats(self):
        return [
            {
                'url': node._safe_repr(),
                'state': node.state.value,
                'consecutive_failures': node.consecutive_failures,
                'total_requests': node.total_requests,
                'total_successes': node.total_successes,
                'cooldown_remaining': max(0, int(node.cooldown_until - time.time())) if node.state == ProxyState.COOLDOWN else 0,
                'last_error': node.last_error,
            }
            for node in self._nodes
        ]


default_proxy_manager = ProxyManager()
