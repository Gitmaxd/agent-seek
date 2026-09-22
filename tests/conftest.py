import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURES = ROOT / "fixtures"


@pytest.fixture(autouse=True)
def _rate_limit_disabled_by_default():
    """Keep pytest offline: a local .env with Upstash must not throttle other tests."""
    from apps.api.rate_limit import demo_quota, limiter

    limiter.configure(url="", token="", limit_per_min=60)
    demo_quota.configure(backend=limiter, limit=0, mode=False)
    yield
    limiter.configure(url="", token="", limit_per_min=60)
    demo_quota.configure(backend=limiter, limit=0, mode=False)
