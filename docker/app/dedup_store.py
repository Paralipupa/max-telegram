import hashlib
import json
import os
import re
import sqlite3
import time
from typing import Any, Iterable
from urllib.parse import urlparse, urlunparse


def _strip_trailing_time(s: str) -> str:
    """Match bridge display logic: DOM may add/remove HH:MM suffix between polls."""
    t = s.strip()
    if re.search(r"\d{2}:\d{2}$", t):
        return re.sub(r"\s*\d{2}:\d{2}$", "", t).strip()
    return t


def _collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _normalize_url_for_dedup(url: str) -> str:
    """Strip volatile query/fragment (signed CDN URLs change every poll)."""
    u = (url or "").strip()
    if not u:
        return ""
    if u.startswith("blob:") or u.startswith("data:"):
        return u[:256]
    p = urlparse(u)
    return urlunparse((p.scheme, p.netloc, p.path, "", "", ""))


def _norm_caption(s: str) -> str:
    return _collapse_ws(_strip_trailing_time(s))


def _norm_text(s: str) -> str:
    return _collapse_ws(_strip_trailing_time(s))


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
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS seen (
                    fingerprint TEXT PRIMARY KEY,
                    created_at INTEGER NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_seen_created_at ON seen(created_at)")

    @staticmethod
    def fingerprint(message: dict[str, Any]) -> str:
        # stable_id from DOM is often a React/recycled id and changes between polls — breaks dedup.
        m = {k: v for k, v in message.items() if k != "stable_id"}
        normalized = DedupStore._normalize_message(m)
        payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _normalize_message(message: dict[str, Any]) -> dict[str, Any]:
        t = message.get("type")
        if t == "text":
            return {
                "type": "text",
                "text": _norm_text((message.get("text") or "").strip()),
            }
        if t in ("image", "images"):
            urls: Iterable[str]
            if "urls" in message and isinstance(message["urls"], list):
                urls = [str(u) for u in message["urls"] if u]
            else:
                u = message.get("url")
                urls = [str(u)] if u else []
            norm_urls = sorted({_normalize_url_for_dedup(u) for u in urls if u})
            return {
                "type": "images",
                "urls": norm_urls,
                "caption": _norm_caption((message.get("caption") or "").strip()),
            }
        if t == "attachments":
            items = message.get("items") or []
            norm_items: list[dict[str, str]] = []
            for it in sorted(
                [x for x in items if isinstance(x, dict)],
                key=lambda x: _normalize_url_for_dedup(str(x.get("url") or "")),
            ):
                norm_items.append(
                    {
                        "url": _normalize_url_for_dedup(str(it.get("url") or "").strip()),
                        "kind": str(it.get("kind") or "document"),
                        "name": (str(it.get("name") or "")).strip(),
                    }
                )
            return {
                "type": "attachments",
                "items": norm_items,
                "caption": _norm_caption((message.get("caption") or "").strip()),
            }
        if t == "mixed":
            imgs = [
                _normalize_url_for_dedup(str(u))
                for u in (message.get("image_urls") or [])
                if u
            ]
            att = message.get("attachments") or []
            norm_att: list[dict[str, str]] = []
            for it in sorted(
                [x for x in att if isinstance(x, dict)],
                key=lambda x: _normalize_url_for_dedup(str(x.get("url") or "")),
            ):
                norm_att.append(
                    {
                        "url": _normalize_url_for_dedup(str(it.get("url") or "").strip()),
                        "kind": str(it.get("kind") or "document"),
                        "name": (str(it.get("name") or "")).strip(),
                    }
                )
            return {
                "type": "mixed",
                "image_urls": sorted(imgs),
                "attachments": norm_att,
                "caption": _norm_caption((message.get("caption") or "").strip()),
            }
        return {"type": str(t or "unknown"), "raw": message}

    def claim_fingerprint(self, fingerprint: str) -> bool:
        """Atomically insert fingerprint. True if this caller was first (safe across processes)."""
        now = int(time.time())
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO seen(fingerprint, created_at) VALUES(?, ?)",
                (fingerprint, now),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
            return False
        finally:
            conn.close()
        self.prune()
        return True

    def has(self, fingerprint: str) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM seen WHERE fingerprint = ? LIMIT 1", (fingerprint,)).fetchone()
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
            extra = conn.execute("SELECT COUNT(*) FROM seen").fetchone()[0] - int(self.max_entries)
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
