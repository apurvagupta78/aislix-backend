"""Persist learned SKU catalog to Supabase (storage + optional table)."""

from __future__ import annotations

import json
import os
from typing import Any

import requests

LEARNED_BUCKET = os.getenv("LEARNED_CATALOG_BUCKET", "catalog-data")
LEARNED_CATALOG_OBJECT = "learned_catalog.json"
LEARNED_INDEX_OBJECT = "learned.index"


def _headers(content_type: str | None = "application/json") -> dict[str, str]:
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not key:
        return {}
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def is_configured() -> bool:
    return bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_ROLE_KEY"))


def fetch_learned_from_supabase() -> list[dict]:
    if not is_configured():
        return []
    base = os.getenv("SUPABASE_URL", "").rstrip("/")
    url = f"{base}/rest/v1/learned_skus?select=sku,brand,product_name,variant,category,embedding,hit_count,source_scan_id"
    try:
        response = requests.get(url, headers=_headers(), timeout=30)
        if response.status_code == 404:
            return []
        response.raise_for_status()
        rows = response.json()
        entries = []
        for row in rows:
            embedding = row.get("embedding")
            if not embedding:
                continue
            entries.append(
                {
                    "sku": row["sku"],
                    "brand": row.get("brand") or "",
                    "product_name": row.get("product_name") or "",
                    "variant": row.get("variant") or "",
                    "category": row.get("category") or "General",
                    "embedding": embedding,
                    "hit_count": row.get("hit_count") or 1,
                    "source_scan_id": row.get("source_scan_id"),
                    "recognition_source": "learned",
                }
            )
        return entries
    except Exception as exc:
        print(f"learned_skus fetch skipped: {exc}")
        return []


def upsert_learned_row(entry: dict) -> None:
    if not is_configured():
        return
    base = os.getenv("SUPABASE_URL", "").rstrip("/")
    url = f"{base}/rest/v1/learned_skus"
    payload = {
        "sku": entry["sku"],
        "brand": entry.get("brand") or "",
        "product_name": entry.get("product_name") or "",
        "variant": entry.get("variant") or "",
        "category": entry.get("category") or "General",
        "embedding": entry["embedding"],
        "source_scan_id": entry.get("source_scan_id"),
        "hit_count": entry.get("hit_count") or 1,
    }
    headers = _headers()
    headers["Prefer"] = "resolution=merge-duplicates"
    try:
        requests.post(url, headers=headers, json=payload, timeout=30).raise_for_status()
    except Exception as exc:
        print(f"learned_skus upsert skipped: {exc}")


def download_learned_files(catalog_path, index_path) -> bool:
    if not is_configured():
        return False
    base = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    ok = False
    for obj, dest in ((LEARNED_CATALOG_OBJECT, catalog_path), (LEARNED_INDEX_OBJECT, index_path)):
        url = f"{base}/storage/v1/object/{LEARNED_BUCKET}/{obj}"
        try:
            response = requests.get(url, headers=headers, timeout=60)
            if response.status_code == 200 and response.content:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(response.content)
                ok = True
        except Exception as exc:
            print(f"learned file download skipped ({obj}): {exc}")
    return ok


def upload_learned_files(catalog_path, index_path) -> None:
    if not is_configured():
        return
    if not catalog_path.exists():
        return
    base = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    uploads = [(LEARNED_CATALOG_OBJECT, catalog_path, "application/json")]
    if index_path.exists():
        uploads.append((LEARNED_INDEX_OBJECT, index_path, "application/octet-stream"))
    for obj, path, content_type in uploads:
        url = f"{base}/storage/v1/object/{LEARNED_BUCKET}/{obj}"
        try:
            requests.post(
                url,
                headers={**headers, "Content-Type": content_type, "x-upsert": "true"},
                data=path.read_bytes(),
                timeout=120,
            ).raise_for_status()
        except Exception as exc:
            print(f"learned file upload skipped ({obj}): {exc}")
