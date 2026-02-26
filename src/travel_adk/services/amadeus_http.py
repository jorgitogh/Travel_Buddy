import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional
import requests


@dataclass
class _Token:
    access_token: str
    expires_at: float  


class AmadeusHTTPError(RuntimeError):
    pass


class AmadeusHTTPClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        host: str = "https://test.api.amadeus.com",
        timeout_s: int = 20,
    ) -> None:
        if not client_id or not client_secret:
            raise ValueError("Faltan AMADEUS_CLIENT_ID / AMADEUS_CLIENT_SECRET")

        self.client_id = client_id
        self.client_secret = client_secret
        self.host = host.rstrip("/")
        self.timeout_s = timeout_s
        self._token: Optional[_Token] = None

    def _token_valid(self) -> bool:
        return self._token is not None and (time.time() < self._token.expires_at - 60)

    def _fetch_token(self) -> _Token:
        url = f"{self.host}/v1/security/oauth2/token"
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }

        r = requests.post(url, headers=headers, data=data, timeout=self.timeout_s)
        if r.status_code != 200:
            raise AmadeusHTTPError(f"Token error {r.status_code}: {r.text}")

        payload = r.json()
        access_token = payload["access_token"]
        expires_in = int(payload.get("expires_in", 1799))
        return _Token(access_token=access_token, expires_at=time.time() + expires_in)

    def _get_token(self) -> str:
        if not self._token_valid():
            self._token = self._fetch_token()
        return self._token.access_token

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._request("GET", path, params=params)

    def post(self, path: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._request("POST", path, json=data)

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        max_retries: int = 3,
    ) -> Dict[str, Any]:
        url = f"{self.host}{path}"
        token = self._get_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

        last_err: Optional[str] = None

        for attempt in range(max_retries + 1):
            r = requests.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json,
                timeout=self.timeout_s,
            )

            if r.status_code == 401 and attempt < max_retries:
                self._token = None
                token = self._get_token()
                headers["Authorization"] = f"Bearer {token}"
                last_err = f"401: {r.text}"
                continue

            if r.status_code == 429 and attempt < max_retries:
                retry_after = r.headers.get("Retry-After")
                sleep_s = int(retry_after) if retry_after and retry_after.isdigit() else (2 ** attempt)
                time.sleep(sleep_s)
                last_err = f"429: {r.text}"
                continue

            if r.status_code >= 500 and attempt < max_retries:
                time.sleep(2 ** attempt)
                last_err = f"{r.status_code}: {r.text}"
                continue

            if 200 <= r.status_code < 300:
                return r.json()

            raise AmadeusHTTPError(f"Amadeus {method} {path} -> {r.status_code}: {r.text}")

        raise AmadeusHTTPError(last_err or "Unknown Amadeus error")


_client: Optional[AmadeusHTTPClient] = None


def get_amadeus_client() -> AmadeusHTTPClient:
    global _client
    if _client is None:
        _client = AmadeusHTTPClient(
            client_id=os.getenv("AMADEUS_CLIENT_ID", ""),
            client_secret=os.getenv("AMADEUS_CLIENT_SECRET", ""),
            host=os.getenv("AMADEUS_HOST", "https://test.api.amadeus.com"),
            timeout_s=int(os.getenv("AMADEUS_TIMEOUT_S", "20")),
        )
    return _client