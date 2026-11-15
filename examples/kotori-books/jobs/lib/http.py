"""外部 API 呼び出し (requests の薄いラッパー)。認証ヘッダはホストごとの環境変数 KOTORI_API_TOKEN_<HOST> から付ける。"""
from __future__ import annotations

import os

import requests

TIMEOUT = (5, 30)


def _headers(host: str) -> dict:
    token = os.environ.get("KOTORI_API_TOKEN_" + host.split(".")[1].upper(), "")
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def get_json(host: str, path: str, params: dict | None = None) -> dict:
    r = requests.get(f"https://{host}{path}", params=params, headers=_headers(host), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def post_json(host: str, path: str, body: dict) -> dict:
    r = requests.post(f"https://{host}{path}", json=body, headers=_headers(host), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()
