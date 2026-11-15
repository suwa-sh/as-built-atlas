"""メッセージキュー (pika / AMQP の薄いラッパー)。トピック名はキュー名と同じ。"""
from __future__ import annotations

import json
from typing import Iterator

import pika

from jobs import settings


def _channel():
    conn = pika.BlockingConnection(pika.URLParameters(settings.MQ_URL))
    return conn, conn.channel()


def publish(topic: str, payload: dict) -> None:
    conn, ch = _channel()
    try:
        ch.queue_declare(queue=topic, durable=True)
        ch.basic_publish(exchange="", routing_key=topic, body=json.dumps(payload, ensure_ascii=False))
    finally:
        conn.close()


def consume(topic: str, limit: int = 1000) -> Iterator[dict]:
    """メッセージを取り出して ACK する (キューから消える)。"""
    conn, ch = _channel()
    try:
        ch.queue_declare(queue=topic, durable=True)
        for _ in range(limit):
            method, _props, body = ch.basic_get(queue=topic, auto_ack=False)
            if method is None:
                break
            yield json.loads(body)
            ch.basic_ack(method.delivery_tag)
    finally:
        conn.close()


def peek(topic: str, limit: int = 1000) -> list[dict]:
    """メッセージを読むだけで ACK しない (NACK で戻す。dry-run 用)。"""
    conn, ch = _channel()
    try:
        ch.queue_declare(queue=topic, durable=True)
        tags, out = [], []
        for _ in range(limit):
            method, _props, body = ch.basic_get(queue=topic, auto_ack=False)
            if method is None:
                break
            tags.append(method.delivery_tag)
            out.append(json.loads(body))
        for tag in tags:
            ch.basic_nack(tag, requeue=True)
        return out
    finally:
        conn.close()
