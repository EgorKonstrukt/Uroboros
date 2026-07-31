import requests
from requests.adapters import HTTPAdapter

_pool = None


def get_session() -> requests.Session:
    global _pool
    if _pool is None:
        _pool = requests.Session()
        adapter = HTTPAdapter(pool_connections=16, pool_maxsize=32, max_retries=0)
        _pool.mount("https://", adapter)
        _pool.mount("http://", adapter)
    return _pool
