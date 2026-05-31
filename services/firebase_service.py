"""Firebase Firestore upload service.

Preserves StreamRadar-style JSON export while optionally syncing to Firebase
collections: books, trending, new_releases, editor_picks, categories.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from config.settings import (
    CACHE_DIR,
    COLLECTION_BOOKS,
    COLLECTION_CATEGORIES,
    COLLECTION_EDITOR_PICKS,
    COLLECTION_NEW_RELEASES,
    COLLECTION_TRENDING,
    FIREBASE_CONFIG,
    OUTPUT_DIR,
)
from utils.json_export import write_json

logger = logging.getLogger(__name__)


class FirebaseService:
    def __init__(self) -> None:
        self.enabled = FIREBASE_CONFIG.enabled
        self._db = None
        self._initialized = False

    def _initialize(self) -> bool:
        if self._initialized:
            return self._db is not None
        self._initialized = True

        if not self.enabled:
            logger.info("Firebase upload disabled (FIREBASE_ENABLED=false)")
            return False

        if not FIREBASE_CONFIG.credentials_path:
            logger.warning("Firebase enabled but FIREBASE_CREDENTIALS_PATH is missing")
            self.enabled = False
            return False

        try:
            import firebase_admin
            from firebase_admin import credentials, firestore

            cred_path = Path(FIREBASE_CONFIG.credentials_path)
            if not cred_path.exists():
                logger.error("Firebase credentials file not found: %s", cred_path)
                self.enabled = False
                return False

            if not firebase_admin._apps:
                cred = credentials.Certificate(str(cred_path))
                firebase_admin.initialize_app(
                    cred,
                    {"projectId": FIREBASE_CONFIG.project_id} if FIREBASE_CONFIG.project_id else None,
                )
            self._db = firestore.client()
            logger.info("Firebase initialized project=%s", FIREBASE_CONFIG.project_id or "default")
            return True
        except ImportError:
            logger.error("firebase-admin not installed; pip install firebase-admin")
            self.enabled = False
            return False
        except Exception as exc:
            logger.exception("Firebase initialization failed: %s", exc)
            self.enabled = False
            return False

    def upload_books(self, items: list[dict[str, Any]]) -> int:
        if not self._initialize() or not self._db:
            return 0

        uploaded = 0
        batch_size = 400
        for idx in range(0, len(items), batch_size):
            chunk = items[idx : idx + batch_size]
            batch = self._db.batch()
            for item in chunk:
                doc_id = item.get("id")
                if not doc_id:
                    continue
                ref = self._db.collection(COLLECTION_BOOKS).document(str(doc_id))
                batch.set(ref, item, merge=True)
            batch.commit()
            uploaded += len(chunk)
            logger.info("Firebase upload success collection=%s count=%s", COLLECTION_BOOKS, len(chunk))
        return uploaded

    def upload_feed_collections(self, feeds: dict[str, list[dict[str, Any]]]) -> None:
        if not self._initialize() or not self._db:
            self._write_local_fallback(feeds)
            return

        mapping = {
            "books": COLLECTION_BOOKS,
            "trending": COLLECTION_TRENDING,
            "new_releases": COLLECTION_NEW_RELEASES,
            "editor_picks": COLLECTION_EDITOR_PICKS,
            "reviews": COLLECTION_EDITOR_PICKS,
        }

        for feed_name, items in feeds.items():
            collection = mapping.get(feed_name, COLLECTION_BOOKS)
            for item in items:
                doc_id = item.get("id")
                if not doc_id:
                    continue
                self._db.collection(collection).document(str(doc_id)).set(item, merge=True)
            logger.info(
                "Firebase upload success collection=%s feed=%s count=%s",
                collection,
                feed_name,
                len(items),
            )

        self._upload_categories(feeds)
        self._write_local_fallback(feeds)

    def _upload_categories(self, feeds: dict[str, list[dict[str, Any]]]) -> None:
        if not self._db:
            return
        category_map: dict[str, list[str]] = {}
        for feed_name, items in feeds.items():
            ids = [str(i.get("id")) for i in items if i.get("id")]
            category_map[feed_name] = ids
        self._db.collection(COLLECTION_CATEGORIES).document("index").set(category_map, merge=True)
        logger.info("Firebase upload success collection=%s", COLLECTION_CATEGORIES)

    def _write_local_fallback(self, feeds: dict[str, list[dict[str, Any]]]) -> None:
        """Always persist JSON locally (StreamRadar-compatible export pipeline)."""
        for feed_name, items in feeds.items():
            write_json(OUTPUT_DIR / f"{feed_name}.json", items)
        write_json(CACHE_DIR / "last_firebase_payload.json", feeds)

    def record_failed_upload(self, feed_name: str, error: str) -> None:
        path = CACHE_DIR / "failed_uploads.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        existing: list[dict[str, str]] = []
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    existing = raw
            except Exception:
                existing = []
        existing.append({"feed": feed_name, "error": error[:500]})
        path.write_text(json.dumps(existing[-200:], indent=2), encoding="utf-8")
