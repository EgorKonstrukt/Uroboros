import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, max_hits: int = 10, window_seconds: float = 60.0):
        self.max_hits = max_hits
        self.window_seconds = window_seconds
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            bucket = self._hits[key]
            while bucket and bucket[0] < now - self.window_seconds:
                bucket.popleft()
            if len(bucket) >= self.max_hits:
                return False
            bucket.append(now)
            return True

    def remaining(self, key: str) -> int:
        now = time.monotonic()
        with self._lock:
            bucket = self._hits.get(key)
            if not bucket:
                return self.max_hits
            while bucket and bucket[0] < now - self.window_seconds:
                bucket.popleft()
            return max(0, self.max_hits - len(bucket))

    def clear(self, key: str):
        with self._lock:
            self._hits.pop(key, None)


auth_limiter = RateLimiter(max_hits=10, window_seconds=60.0)
login_limiter = RateLimiter(max_hits=5, window_seconds=300.0)
