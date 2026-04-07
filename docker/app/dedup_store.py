import hashlib
import json
import os
import sqlite3
import time
from typing import Any, Iterable
from urllib.parse import urlparse, urlunparse
from loguru import logger
from helpers import strip_trailing_time


class DedupStore:
    """
    Persistent dedup cache stored in SQLite.
    Keeps message fingerprints so deleted MAX messages won't be resent.
    """

    def __init__(
        self,
        db_path: str = "/data/dedup.sqlite3",
        *,
        max_entries: int = 5000,
        ttl_seconds: int = 30 * 24 * 3600,  # 30 days
    ) -> None:
        self.db_path = db_path
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init(self) -> None:
        logger.info(f"Инициализируем дедупликацию: {self.db_path}")
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS seen (
                    fingerprint TEXT PRIMARY KEY,
                    created_at INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_seen_created_at ON seen(created_at)"
            )
        logger.info(f"Инициализировано дедупликацию: {self.db_path}")

    @staticmethod
    def fingerprint(message: dict[str, Any]) -> tuple[str, str]:
        normalized = DedupStore._normalize_message(message)
        try:
            text = (
                (message.get("text") or "")
                + (message.get("caption") or "")
                + (message.get("sender", {}).get("name") or "")
            )
            if not text:
                payload = json.dumps(
                    normalized,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                return hashlib.sha256(payload.encode("utf-8")).hexdigest(), text
        except Exception as e:
            logger.error(f"Ошибка при создании fingerprint: {e}")
        return hashlib.sha256(text.encode("utf-8")).hexdigest(), text

    @staticmethod
    def _strip_query(url: str) -> str:
        """Убирает query-параметры из URL (временные токены не должны влиять на хеш)."""
        try:
            p = urlparse(url)
            return urlunparse(p._replace(query="", fragment=""))
        except Exception:
            return url

    @staticmethod
    def _normalize_message(message: dict[str, Any]) -> dict[str, Any]:
        # Сообщение с фото в Максе рендерится постепенно: сначала только текст (type=text),
        # затем текст+фото (type=images/mixed). Если есть caption — используем его как
        # единственный ключ, иначе при смене типа получим разные хеши и дублирование.
        caption = (message.get("text") or message.get("caption") or "").strip()
        caption = strip_trailing_time(caption)
        if caption:
            return {"caption": caption}

        strip = DedupStore._strip_query
        t = message.get("type")
        if t in ("image", "images"):
            urls: Iterable[str]
            if "urls" in message and isinstance(message["urls"], list):
                urls = [strip(str(u)) for u in message["urls"] if u]
            else:
                u = message.get("url")
                urls = [strip(str(u))] if u else []
            return {"type": "images", "urls": sorted(urls)}
        if t == "attachments":
            items = message.get("items") or []
            norm_items: list[dict[str, str]] = []
            for it in sorted(
                [x for x in items if isinstance(x, dict)],
                key=lambda x: str(x.get("url") or ""),
            ):
                norm_items.append(
                    {
                        "url": strip(str(it.get("url") or "").strip()),
                        "kind": str(it.get("kind") or "document"),
                    }
                )
            return {"type": "attachments", "items": norm_items}
        if t == "mixed":
            imgs = [strip(str(u)) for u in (message.get("image_urls") or []) if u]
            att = message.get("attachments") or []
            norm_att: list[dict[str, str]] = []
            for it in sorted(
                [x for x in att if isinstance(x, dict)],
                key=lambda x: str(x.get("url") or ""),
            ):
                norm_att.append(
                    {
                        "url": strip(str(it.get("url") or "").strip()),
                        "kind": str(it.get("kind") or "document"),
                    }
                )
            return {
                "type": "mixed",
                "image_urls": sorted(imgs),
                "attachments": norm_att,
            }
        return {"type": str(t or "unknown"), "raw": message}

    def has(self, fingerprint: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM seen WHERE fingerprint = ? LIMIT 1", (fingerprint,)
            ).fetchone()
            return row is not None

    def count(self) -> int:
        with self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM seen").fetchone()[0])

    def add(self, fingerprint: str) -> None:
        now = int(time.time())
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO seen(fingerprint, created_at) VALUES(?, ?)",
                (fingerprint, now),
            )
        self.prune()

    def prune(self) -> None:
        now = int(time.time())
        cutoff = now - int(self.ttl_seconds)
        with self._connect() as conn:
            conn.execute("DELETE FROM seen WHERE created_at < ?", (cutoff,))
            # cap total size
            extra = conn.execute("SELECT COUNT(*) FROM seen").fetchone()[0] - int(
                self.max_entries
            )
            if extra > 0:
                conn.execute(
                    """
                    DELETE FROM seen
                    WHERE fingerprint IN (
                        SELECT fingerprint FROM seen
                        ORDER BY created_at ASC
                        LIMIT ?
                    )
                    """,
                    (extra,),
                )
