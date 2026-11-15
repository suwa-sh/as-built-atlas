"""Redis のキャッシュ (redis-py の薄いラッパー)。キーの設計は docs/keys.md。"""
from __future__ import annotations

import json
from typing import Iterator

import redis

from jobs import settings

_client: redis.Redis | None = None


def client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(settings.CACHE_URL, decode_responses=True)
    return _client


def get(key: str):
    raw = client().get(key)
    return json.loads(raw) if raw else None


def set(key: str, value) -> None:  # noqa: A001
    client().set(key, json.dumps(value, ensure_ascii=False))


def expire(key: str, seconds: int) -> None:
    client().expire(key, seconds)


def delete(*keys: str) -> int:
    return client().delete(*keys) if keys else 0


def scan(pattern: str) -> Iterator[str]:
    yield from client().scan_iter(match=pattern, count=500)
