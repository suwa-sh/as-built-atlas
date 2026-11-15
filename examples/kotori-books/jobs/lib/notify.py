"""運用チャットへの通知。Webhook の URL は環境変数 KOTORI_CHAT_WEBHOOK (リポジトリには置かない)。"""
from __future__ import annotations

import os

import requests


def post(text: str) -> None:
    url = os.environ.get("KOTORI_CHAT_WEBHOOK")
    if not url:
        return
    requests.post(url, json={"text": text}, timeout=(5, 10)).raise_for_status()
