import json
import os
import time
import concurrent.futures
from typing import Dict, Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from pyicloud import PyiCloudService
from pyicloud.exceptions import PyiCloudFailedLoginException

app = FastAPI(title="Find My Ring Service", version="1.0.0")

USERNAME = os.environ.get("ICLOUD_USERNAME", "")
PASSWORD = os.environ.get("ICLOUD_PASSWORD", "")
API_TOKEN = os.environ.get("API_TOKEN", "")
PYICLOUD_DIR = os.environ.get("PYICLOUD_DIR", "/data/pyicloud")
COOLDOWN_SECONDS = int(os.environ.get("COOLDOWN_SECONDS", "20"))

DEVICE_MAP_JSON = os.environ.get("DEVICE_MAP_JSON", "{}")
DEVICE_MAP: Dict[str, str] = json.loads(DEVICE_MAP_JSON)

_last_ring: Dict[str, float] = {}

_last_auth_fail = 0.0
_AUTH_FAIL_COOLDOWN = 120  # seconds

_ic: Optional[PyiCloudService] = None


def _create_ic() -> PyiCloudService:
    print("Creating PyiCloudService (contacting Apple)...", flush=True)
    return PyiCloudService(USERNAME, PASSWORD, cookie_directory=PYICLOUD_DIR)


def get_ic() -> PyiCloudService:
    global _ic, _last_auth_fail

    # If Apple is flaky / blocking, avoid hammering SRP auth
    if time.time() - _last_auth_fail < _AUTH_FAIL_COOLDOWN:
        raise HTTPException(
            status_code=503,
            detail="Apple iCloud auth temporarily unavailable (cooldown). Try again shortly."
        )

    if not USERNAME or not PASSWORD:
        raise HTTPException(status_code=500, detail="ICLOUD_USERNAME/ICLOUD_PASSWORD not set")

    if _ic is not None:
        return _ic

    # Hard timeout so requests don't hang forever
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(_create_ic)
        try:
            _ic = fut.result(timeout=20)
            return _ic
        except concurrent.futures.TimeoutError:
            _last_auth_fail = time.time()
            raise HTTPException(status_code=504, detail="Timeout contacting iCloud (Apple). Try again.")
        except Exception as e:
            _last_auth_fail = time.time()
            raise HTTPException(status_code=502, detail=f"iCloud auth error: {e}")

def find_device(ic: PyiCloudService, target: str):
    """
    target can be:
      - exact device name (e.g. "phone_1")
      - device_id (the long base64-ish string)
    """
    for d in ic.devices:
        if getattr(d, "name", None) == target:
            return d
        if getattr(d, "id", None) == target:
            return d
    return None

class TwoFARequest(BaseModel):
    code: str

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/auth/status")
def auth_status(x_api_token: Optional[str] = Header(default=None)):
    require_token(x_api_token)
    try:
        ic = get_ic()
        return {
            "requires_2fa": bool(getattr(ic, "requires_2fa", False)),
            "requires_2sa": bool(getattr(ic, "requires_2sa", False)),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/auth/2fa")
def submit_2fa(body: TwoFARequest, x_api_token: Optional[str] = Header(default=None)):
    require_token(x_api_token)
    try:
        ic = get_ic()

        if not getattr(ic, "requires_2fa", False):
            return {"ok": True, "message": "2FA not required", "trusted": True}

        code = body.code.strip().replace(" ", "")
        ok = ic.validate_2fa_code(code)
        if not ok:
            raise HTTPException(status_code=400, detail="Invalid 2FA code")

        # IMPORTANT: don't swallow trust_session errors
        try:
            trusted = bool(ic.trust_session())
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"2FA accepted but trust_session failed: {e}")

        return {"ok": True, "message": "2FA accepted", "trusted": trusted}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class TwoSASelect(BaseModel):
    device_index: int

def require_token(x_api_token: Optional[str]):
    if not API_TOKEN:
        raise HTTPException(status_code=500, detail="API_TOKEN not set")
    if x_api_token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid API token")

@app.get("/auth/2sa/devices")
def list_2sa_devices(x_api_token: Optional[str] = Header(default=None)):
    require_token(x_api_token)
    ic = get_ic()

    if not getattr(ic, "requires_2sa", False):
        return {"ok": True, "message": "2SA not required"}

    # This is a list of trusted devices Apple can send a code to
    return {"devices": ic.trusted_devices}

@app.post("/auth/2sa/send")
def send_2sa_code(body: TwoSASelect, x_api_token: Optional[str] = Header(default=None)):
    require_token(x_api_token)
    ic = get_ic()

    if not getattr(ic, "requires_2sa", False):
        return {"ok": True, "message": "2SA not required"}

    devices = ic.trusted_devices
    if body.device_index < 0 or body.device_index >= len(devices):
        raise HTTPException(status_code=400, detail=f"device_index out of range (0..{len(devices)-1})")

    ic.send_verification_code(devices[body.device_index])
    return {"ok": True, "message": "Verification code sent"}

class TwoSACode(BaseModel):
    code: str

@app.post("/auth/2sa/validate")
def validate_2sa_code(body: TwoSACode, x_api_token: Optional[str] = Header(default=None)):
    require_token(x_api_token)
    try:
        ic = get_ic()
        if not getattr(ic, "requires_2sa", False):
            return {"ok": True, "message": "2SA not required"}

        code = body.code.strip().replace(" ", "")
        ok = ic.validate_verification_code(code)
        if not ok:
            raise HTTPException(status_code=400, detail="Invalid verification code")

        try:
            ic.trust_session()
        except Exception:
            pass

        return {"ok": True, "message": "2SA accepted"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/devices")
def list_devices(x_api_token: Optional[str] = Header(default=None)):
    require_token(x_api_token)
    ic = get_ic()

    if getattr(ic, "requires_2fa", False):
        raise HTTPException(status_code=409, detail="2FA required. Use /auth/2fa")

    devs = []
    for d in ic.devices:
        # AppleDevice exposes attributes like .name
        devs.append({
            "name": getattr(d, "name", None),
            "device_id": getattr(d, "id", None),
            "model": getattr(d, "deviceModel", None),
        })

    return {"devices": devs, "device_map": DEVICE_MAP}

def find_device_by_name(ic: PyiCloudService, target_name: str):
    for d in ic.devices:
        if getattr(d, "name", None) == target_name:
            return d
    return None

@app.post("/ring/{who}")
def ring(who: str, x_api_token: Optional[str] = Header(default=None)):
    require_token(x_api_token)
    ic = get_ic()

    if getattr(ic, "requires_2fa", False):
        raise HTTPException(status_code=409, detail="2FA required. Use /auth/2fa")

    if who not in DEVICE_MAP:
        raise HTTPException(status_code=404, detail=f"Unknown target '{who}'. Known: {list(DEVICE_MAP.keys())}")

    # Cooldown to prevent spamming
    now = time.time()
    last = _last_ring.get(who, 0)
    if now - last < COOLDOWN_SECONDS:
        raise HTTPException(status_code=429, detail=f"Cooldown active. Try again in {int(COOLDOWN_SECONDS - (now-last))}s")
    _last_ring[who] = now

    target = DEVICE_MAP[who]  # can be name OR id
    device = find_device(ic, target)
    if device is None:
        raise HTTPException(status_code=404, detail=f"Device not found: '{target}'. Check /devices output.")

    try:
        device.play_sound()
    except Exception as e:
        msg = str(e)
        # If session expired, tell caller to re-auth and clear cached client
        if "Re-authentication required" in msg or "reauthentication required" in msg.lower():
            global _ic
            _ic = None
            raise HTTPException(status_code=409, detail="Re-authentication required")
        raise HTTPException(status_code=500, detail=f"Failed to play sound: {e}")

    return {"ok": True, "who": who, "device": getattr(device, "name", None), "target": target}
