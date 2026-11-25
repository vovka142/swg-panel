import os
import threading
from typing import Any

import requests
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

PANEL_URL = os.environ["PANEL_URL"].rstrip("/")
PANEL_USER = os.environ["PANEL_USER"]
PANEL_PASSWORD = os.environ["PANEL_PASSWORD"]
PANEL_TOTP_CODE = os.getenv("PANEL_TOTP_CODE", "")
GATEWAY_API_KEY = os.environ["GATEWAY_API_KEY"]
VERIFY_TLS = os.getenv("PANEL_VERIFY_TLS", "true").lower() not in {"0", "false", "no"}
TIMEOUT = float(os.getenv("PANEL_TIMEOUT", "30"))

app = FastAPI(title="SWG Panel Management API", version="0.1.0")

def require_api_key(authorization: str | None = Header(default=None)) -> None:
    if not GATEWAY_API_KEY or authorization != f"Bearer {GATEWAY_API_KEY}":
        raise HTTPException(status_code=401, detail="Invalid or missing gateway API token")

class Panel:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.lock = threading.RLock()
        self.logged_in = False

    def _login(self) -> None:
        r = self.session.post(
            f"{PANEL_URL}/api/login",
            json={"username": PANEL_USER, "password": PANEL_PASSWORD, **({"code": PANEL_TOTP_CODE} if PANEL_TOTP_CODE else {})},
            timeout=TIMEOUT, verify=VERIFY_TLS, headers={"X-SWG-Lang": "en"},
        )
        try:
            body = r.json()
        except ValueError:
            body = {}
        if r.status_code != 200 or body.get("ok") is not True:
            raise HTTPException(status_code=502, detail={
                "error": "Panel login failed", "panel_status": r.status_code, "panel_response": body
            })
        self.logged_in = True

    def call(self, method: str, path: str, *, params: dict | None = None,
             payload: dict | None = None) -> dict[str, Any]:
        if not path.startswith("/api/") or path.startswith("/api/v1/"):
            raise ValueError("Only internal panel API paths are allowed")
        with self.lock:
            for attempt in range(2):
                if not self.logged_in:
                    self._login()
                r = self.session.request(
                    method, f"{PANEL_URL}{path}", params=params, json=payload,
                    timeout=TIMEOUT, verify=VERIFY_TLS, headers={"X-SWG-Lang": "en"},
                )
                try:
                    body = r.json()
                except ValueError:
                    body = {"ok": False, "error": "Panel returned a non-JSON response"}
                if r.status_code == 401 and attempt == 0:
                    self.logged_in = False
                    self.session.cookies.clear()
                    continue
                if r.status_code >= 500:
                    raise HTTPException(status_code=502, detail={"error": "Panel upstream error", "response": body})
                if r.status_code >= 400:
                    raise HTTPException(status_code=r.status_code, detail=body)
                if isinstance(body, dict) and body.get("ok") is False:
                    raise HTTPException(status_code=400, detail=body)
                return body
        raise HTTPException(status_code=502, detail="Panel authentication expired")

panel = Panel()

class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    tag: str = Field(default="", max_length=32)
    note: str = Field(default="", max_length=200)

class UserUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=64)
    tag: str | None = Field(default=None, max_length=32)
    note: str | None = Field(default=None, max_length=200)
    expiry: int | None = None
    vk_links: list[str] | None = None
    vk_link: str | None = None

class PeerTarget(BaseModel):
    node: str
    iface: str
    ip: str = ""
    type: str = "wg"
    overrides: dict[str, Any] | None = None

class PeerCreate(BaseModel):
    user_id: str | None = None
    title: str = ""
    pubkey: str = ""
    psk: str = ""
    targets: list[PeerTarget] = Field(min_length=1)

@app.get("/healthz")
def healthz():
    return {"status": "ok"}

@app.get("/v1/state", dependencies=[Depends(require_api_key)])
def state():
    return panel.call("GET", "/api/state")

@app.get("/v1/users", dependencies=[Depends(require_api_key)])
def users():
    result = panel.call("GET", "/api/state")
    roster = (result.get("data") or {}).get("roster") or {}
    return {"users": list((roster.get("users") or {}).values())}

@app.post("/v1/users", dependencies=[Depends(require_api_key)])
def create_user(body: UserCreate):
    return panel.call("POST", "/api/users/create", payload=body.model_dump())

@app.patch("/v1/users/{user_id}", dependencies=[Depends(require_api_key)])
def update_user(user_id: str, body: UserUpdate):
    payload = body.model_dump(exclude_none=True)
    payload["id"] = user_id
    return panel.call("POST", "/api/users/update", payload=payload)

@app.delete("/v1/users/{user_id}", dependencies=[Depends(require_api_key)])
def delete_user(user_id: str):
    return panel.call("POST", "/api/users/delete", payload={"id": user_id})

@app.post("/v1/users/{user_id}/block", dependencies=[Depends(require_api_key)])
def block_user(user_id: str):
    return panel.call("POST", "/api/user/block", payload={"user_id": user_id})

@app.post("/v1/users/{user_id}/unblock", dependencies=[Depends(require_api_key)])
def unblock_user(user_id: str):
    return panel.call("POST", "/api/user/unblock", payload={"user_id": user_id})

@app.get("/v1/peers", dependencies=[Depends(require_api_key)])
def peers(user_id: str | None = Query(default=None)):
    result = panel.call("GET", "/api/state")
    roster = (result.get("data") or {}).get("roster") or {}
    items = list((roster.get("peers") or {}).values())
    if user_id:
        items = [p for p in items if p.get("user_id") == user_id]
    return {"peers": items}

@app.post("/v1/peers", dependencies=[Depends(require_api_key)])
def create_peer(body: PeerCreate):
    return panel.call("POST", "/api/peers/create", payload=body.model_dump(exclude_none=True))

@app.delete("/v1/peers/{peer_id}", dependencies=[Depends(require_api_key)])
def delete_peer(peer_id: str):
    return panel.call("POST", "/api/peers/delete", payload={"peer_id": peer_id})

@app.post("/v1/peers/{peer_id}/block", dependencies=[Depends(require_api_key)])
def block_peer(peer_id: str):
    return panel.call("POST", "/api/peers/block", payload={"peer_id": peer_id})

@app.post("/v1/peers/{peer_id}/unblock", dependencies=[Depends(require_api_key)])
def unblock_peer(peer_id: str):
    return panel.call("POST", "/api/peers/unblock", payload={"peer_id": peer_id})

@app.get("/v1/configs/{pubkey}", dependencies=[Depends(require_api_key)])
def legacy_config(pubkey: str, node: str, iface: str):
    return panel.call("GET", "/api/config", params={"pubkey": pubkey, "node": node, "iface": iface})
