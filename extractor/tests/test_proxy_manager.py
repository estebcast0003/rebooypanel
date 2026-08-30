import time
from django.test import TestCase
from extractor.services.proxy_manager import ProxyManager, ProxyState

class ProxyManagerTestCase(TestCase):
    def test_proxy_manager_rotation_and_cooldown(self):
        pm = ProxyManager(proxy_urls=['http://proxy1:8080', 'http://proxy2:8080'], cooldown_seconds=1)
        
        p1 = pm.get_next_available_proxy()
        self.assertEqual(p1, 'http://proxy1:8080')
        p2 = pm.get_next_available_proxy()
        self.assertEqual(p2, 'http://proxy2:8080')
        
        # Mark p1 as rate limited (triggers immediate COOLDOWN)
        pm.record_outcome('http://proxy1:8080', is_success=False, error_msg='429 Too Many Requests', is_rate_limit=True)
        
        # Next proxy should be p2
        self.assertEqual(pm.get_next_available_proxy(), 'http://proxy2:8080')
        self.assertEqual(pm.get_next_available_proxy(), 'http://proxy2:8080')
        
        # Check stats
        stats = pm.get_stats()
        self.assertEqual(len(stats), 2)
        self.assertEqual(stats[0]['state'], ProxyState.COOLDOWN.value)
        
        # Wait for cooldown to expire
        time.sleep(1.1)
        # Half-open: p1 is available again
        self.assertEqual(pm.get_next_available_proxy(), 'http://proxy1:8080')
        
        # Mark p1 success resets state to healthy
        pm.record_outcome('http://proxy1:8080', is_success=True)
        stats2 = pm.get_stats()
        self.assertEqual(stats2[0]['state'], ProxyState.HEALTHY.value)
