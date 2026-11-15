"""S3 互換のオブジェクトストレージ (boto3 の薄いラッパー)。"""
from __future__ import annotations

import boto3

_s3 = None


def client():
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3")
    return _s3


def put_object(bucket: str, key: str, body: bytes, content_type: str = "application/octet-stream") -> None:
    client().put_object(Bucket=bucket, Key=key, Body=body, ContentType=content_type)


def get_object(bucket: str, key: str) -> bytes:
    return client().get_object(Bucket=bucket, Key=key)["Body"].read()


def list_objects(bucket: str, prefix: str) -> list[str]:
    paginator = client().get_paginator("list_objects_v2")
    return [o["Key"] for page in paginator.paginate(Bucket=bucket, Prefix=prefix) for o in page.get("Contents", [])]


def delete_object(bucket: str, key: str) -> None:
    client().delete_object(Bucket=bucket, Key=key)
