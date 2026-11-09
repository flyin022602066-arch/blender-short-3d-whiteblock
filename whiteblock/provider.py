"""Small, explicit Eggfans connectivity probe; submission remains contract-gated."""
from __future__ import annotations
import json, urllib.error, urllib.request

def probe_pricing(base_url: str, endpoint: str, api_key: str, auth_header: str = "Authorization", auth_prefix: str = "Bearer", timeout: int = 20) -> dict:
    url = base_url.rstrip("/") + "/" + endpoint.lstrip("/")
    headers = {"Accept": "application/json", "User-Agent": "whiteblock-desktop/1.0"}
    if api_key:
        headers[auth_header] = (auth_prefix + " " + api_key).strip()
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            content_type = response.headers.get("Content-Type", "")
            try:
                payload = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                return {"ok": False, "status": response.status, "url": url, "content_type": content_type or "unknown", "error": "HTTP 响应不是 JSON（可能是接口路径错误或网关返回 HTML/空响应）"}
            return {"ok": 200 <= response.status < 300, "status": response.status, "url": url, "json_type": type(payload).__name__}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status": exc.code, "url": url, "error": "HTTP error"}
    except json.JSONDecodeError:
        return {"ok": False, "url": url, "error": "响应不是 JSON，可能是接口路径错误或网关返回了 HTML/空响应"}
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        return {"ok": False, "url": url, "error": "网络连接失败：" + str(reason)}
    except (TimeoutError, OSError) as exc:
        return {"ok": False, "url": url, "error": "网络请求失败：" + str(exc)}
