"""Desktop configuration with Windows user-scoped secret storage."""
from __future__ import annotations
import base64, ctypes, json, os, tempfile
from pathlib import Path
from typing import Any

APP_DIR = Path(os.getenv("APPDATA", str(Path.home()))) / "Whiteblock"
CONFIG_PATH = APP_DIR / "config.json"
SECRETS_PATH = APP_DIR / "secrets.bin"

DEFAULT_CONFIG = {
    "eggfans": {"base_url": "https://api.eggfans.com", "pricing_endpoint": "/api/pricing", "agent_endpoint": "/v1/chat/completions", "model": "seedance-2.5", "agent_model": "gpt-6-astra", "auth_header": "Authorization", "auth_prefix": "Bearer"},
    "agent": {"online": False},
    "blender_path": "",
    "whiteblock": {"geometry_profile":"human_v3","render_engine":"eevee","preview_max_edge":1280},
    "offline_by_default": True,
}

def _merge(base: dict, value: dict) -> dict:
    result = dict(base)
    for key, item in value.items():
        result[key] = _merge(base.get(key, {}), item) if isinstance(item, dict) else item
    return result

def load_config() -> dict:
    try:
        value = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        result = _merge(DEFAULT_CONFIG, value)
        # Migrate the original planning-only paths to Eggfans' verified API prefix.
        if result["eggfans"].get("pricing_endpoint") == "/pricing": result["eggfans"]["pricing_endpoint"] = "/api/pricing"
        if result["eggfans"].get("agent_endpoint") in {"/chat/completions", "/api/chat/completions"}: result["eggfans"]["agent_endpoint"] = "/v1/chat/completions"
        return result
    except (OSError, json.JSONDecodeError):
        return json.loads(json.dumps(DEFAULT_CONFIG))

def _dpapi(data: bytes, protect: bool) -> bytes:
    class Blob(ctypes.Structure):
        _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]
    crypt = ctypes.windll.crypt32
    kernel = ctypes.windll.kernel32
    raw = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source = Blob(len(data), raw)
    target = Blob()
    fn = crypt.CryptProtectData if protect else crypt.CryptUnprotectData
    if not fn(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(target)):
        raise OSError("Windows DPAPI failed")
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        kernel.LocalFree(target.pbData)

def load_secrets() -> dict:
    try:
        encrypted = base64.b64decode(SECRETS_PATH.read_bytes())
        return json.loads(_dpapi(encrypted, False).decode("utf-8"))
    except (OSError, ValueError, json.JSONDecodeError, ctypes.ArgumentError):
        return {}

def save_config(config: dict, eggfans_api_key: str = "", agent_api_key: str | None = None) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="config.", suffix=".part", dir=APP_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(_merge(DEFAULT_CONFIG, config), handle, ensure_ascii=False, indent=2)
        os.replace(temp_name, CONFIG_PATH)
    finally:
        if os.path.exists(temp_name): os.unlink(temp_name)
    # Agent deliberately reuses the Eggfans credential; the old second argument is ignored for migration compatibility.
    secrets = {"eggfans_api_key": eggfans_api_key}
    encrypted = _dpapi(json.dumps(secrets, ensure_ascii=False).encode("utf-8"), True)
    SECRETS_PATH.write_bytes(base64.b64encode(encrypted))
