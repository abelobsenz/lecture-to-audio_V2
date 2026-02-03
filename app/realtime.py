from __future__ import annotations

from typing import Any, Dict, Optional

import httpx


REALTIME_CLIENT_SECRET_URL = "https://api.openai.com/v1/realtime/client_secrets"


def _extract_client_secret(payload: Dict[str, Any]) -> Dict[str, Any]:
    if "client_secret" in payload:
        secret = payload["client_secret"]
    elif "session" in payload and isinstance(payload["session"], dict) and "client_secret" in payload["session"]:
        secret = payload["session"]["client_secret"]
    elif "value" in payload and "expires_at" in payload:
        secret = {"value": payload["value"], "expires_at": payload["expires_at"]}
    else:
        raise RuntimeError("Realtime client secret missing from response")

    value = secret.get("value") if isinstance(secret, dict) else None
    expires_at = secret.get("expires_at") if isinstance(secret, dict) else None
    if not value or expires_at is None:
        raise RuntimeError("Realtime client secret response missing value or expires_at")
    if isinstance(expires_at, str) and expires_at.isdigit():
        expires_at = int(expires_at)
    if isinstance(expires_at, float):
        expires_at = int(expires_at)
    return {"value": value, "expires_at": expires_at}


def mint_realtime_client_secret(
    api_key: str,
    model: str,
    voice: str,
    instructions: Optional[str] = None,
    timeout_sec: float = 10.0,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "session": {
            "type": "realtime",
            "model": model,
            "audio": {"output": {"voice": voice}},
        }
    }
    if instructions:
        payload["session"]["instructions"] = instructions

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=timeout_sec) as client:
        response = client.post(REALTIME_CLIENT_SECRET_URL, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()

    return _extract_client_secret(data)
