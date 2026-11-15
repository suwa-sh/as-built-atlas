"""設定値。秘密 (パスワード・トークン) は環境変数からだけ読み、既定値を持たない。"""
from __future__ import annotations

import os

DATABASE_URL = os.environ.get("KOTORI_DATABASE_URL", "postgresql://kotori@db.internal:5432/kotori")
CACHE_URL = os.environ.get("KOTORI_CACHE_URL", "redis://cache.internal:6379/0")
MQ_URL = os.environ.get("KOTORI_MQ_URL", "amqp://kotori@mq.internal:5672/%2F")

PAYMENT_API_HOST = "api.payment.example"
CARRIER_API_HOST = "api.carrier.example"
MAIL_API_HOST = "api.mail.example"
TAX_API_HOST = "api.tax.example"
FX_API_HOST = "api.fx.example"
SEARCH_HOST = "search.example"
PUSH_API_HOST = "api.push.example"
RECOMMEND_API_HOST = "api.recommend.example"

REPORTS_BUCKET = os.environ.get("REPORTS_BUCKET", "kotori-reports")
EXPORTS_BUCKET = os.environ.get("EXPORTS_BUCKET", "kotori-exports")
BACKUPS_BUCKET = os.environ.get("BACKUPS_BUCKET", "kotori-backups")

EXPORT_DIR = "var/export"
INBOX_DIR = "var/inbox"
LOG_DIR = "var/log"
TMP_DIR = "var/tmp"
BACKUP_DIR = "var/backup"
