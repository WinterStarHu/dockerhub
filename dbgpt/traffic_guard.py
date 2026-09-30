"""
traffic_guard.py — DB-GPT 容器内出站流量守卫 v4(可配置版)
- 环境变量 TRAFFIC_GUARD_ENABLED 控制开关(默认 false:全放行,内网无感)
- 开启时(=true):
  - GET/HEAD/OPTIONS:放行(下载/clone/浏览)
  - POST/PUT/DELETE:拦截(防止上传/push 代码到外网)
  - 例外:白名单域名(LLM API)+ 内部地址(localhost/127.x/172.x/10.x/192.168.x)
"""
import os
import urllib.request
import urllib.parse

# ===== 可配置开关(内网默认关) =====
ENABLED = os.environ.get('TRAFFIC_GUARD_ENABLED', 'false').lower() in ('1', 'true', 'yes', 'on')

# 允许 POST 的域名/IP(可扩展为环境变量)
ALLOW_POST_DOMAINS = set()
_extra = os.environ.get('TRAFFIC_GUARD_ALLOW_DOMAINS', '')
if _extra:
    ALLOW_POST_DOMAINS = {d.strip().lower() for d in _extra.split(',') if d.strip()}

# 允许 POST 的内部 IP 前缀(localhost + 私有网段 + Docker 网段)
ALLOW_POST_IP_PREFIXES = (
    '127.', 'localhost', '0.0.0.0',
    '172.',      # Docker 网段(172.17.x.x 等)
    '10.',       # 内网
    '192.168.',  # 内网
    '::1',       # IPv6 localhost
)
ALLOW_METHODS = {'GET', 'HEAD', 'OPTIONS', 'CONNECT', 'TRACE'}


def _check(method, host):
    # 开关关:全放行
    if not ENABLED:
        return True
    method = (method or 'GET').upper()
    host = (host or '').lower()
    if method in ALLOW_METHODS:
        return True
    # 域名白名单
    for domain in ALLOW_POST_DOMAINS:
        if domain in host:
            return True
    # 内部地址白名单(localhost/内网/Docker)
    for prefix in ALLOW_POST_IP_PREFIXES:
        if host.startswith(prefix) or host == prefix.rstrip('.'):
            return True
    return False


def _block_msg(method, host):
    return f'BLOCKED by traffic_guard: {method} to {host} (only GET + internal/whitelisted POST allowed)'


# ========== 1. Patch urllib.request ==========
try:
    _orig_urlopen = urllib.request.urlopen

    def _guarded_urlopen(url, *args, **kwargs):
        req = url if isinstance(url, urllib.request.Request) else (args[0] if args and isinstance(args[0], urllib.request.Request) else None)
        if req:
            method = req.get_method()
            host = urllib.parse.urlparse(req.full_url).hostname or ''
        elif isinstance(url, str):
            method = kwargs.get('method', 'GET')
            host = urllib.parse.urlparse(url).hostname or ''
        else:
            method = 'GET'
            host = ''
        if not _check(method, host):
            raise PermissionError(_block_msg(method, host))
        return _orig_urlopen(url, *args, **kwargs)

    urllib.request.urlopen = _guarded_urlopen
    print(f'[traffic_guard] urllib patched (enabled={ENABLED})')
except Exception as e:
    print(f'[traffic_guard] urllib patch failed: {e}')

# ========== 2. Patch requests ==========
try:
    import requests
    _orig_request = requests.Session.request

    def _guarded_request(self, method, url, **kwargs):
        host = urllib.parse.urlparse(url).hostname or '' if isinstance(url, str) else ''
        if not _check(method, host):
            raise PermissionError(_block_msg(method, host))
        return _orig_request(self, method, url, **kwargs)

    requests.Session.request = _guarded_request
    print(f'[traffic_guard] requests patched (enabled={ENABLED})')
except ImportError:
    pass
except Exception as e:
    print(f'[traffic_guard] requests patch failed: {e}')

# ========== 3. Patch httpx ==========
try:
    import httpx
    _orig_send = httpx.Client.send

    def _guarded_send(self, request, **kwargs):
        host = urllib.parse.urlparse(str(request.url)).hostname or ''
        if not _check(request.method, host):
            raise PermissionError(_block_msg(request.method, host))
        return _orig_send(self, request, **kwargs)

    httpx.Client.send = _guarded_send
    _orig_async = httpx.AsyncClient.send

    async def _guarded_async(self, request, **kwargs):
        host = urllib.parse.urlparse(str(request.url)).hostname or ''
        if not _check(request.method, host):
            raise PermissionError(_block_msg(request.method, host))
        return await _orig_async(self, request, **kwargs)

    httpx.AsyncClient.send = _guarded_async
    print(f'[traffic_guard] httpx patched (enabled={ENABLED})')
except ImportError:
    pass
except Exception as e:
    print(f'[traffic_guard] httpx patch failed: {e}')

print(f'[traffic_guard] loaded — enabled={ENABLED} (GET always allowed; POST blocked except internal + whitelisted when enabled)')
