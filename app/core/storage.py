"""File storage abstraction.

Uses Cloudflare R2 (S3-compatible, via boto3) when credentials are configured.
Otherwise falls back to local disk storage so uploads work in development
without any cloud account. Zero egress cost on R2; signed/public URLs supported.
"""

from __future__ import annotations

import mimetypes
import re
import uuid
from pathlib import Path

from fastapi.concurrency import run_in_threadpool

from app.core.config import get_settings

settings = get_settings()

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def _client():
    """Lazily build a boto3 S3 client pointed at the R2 endpoint."""
    import boto3  # imported lazily so local dev doesn't require the dep at import time
    from botocore.config import Config

    endpoint = f"https://{settings.r2_account_id}.r2.cloudflarestorage.com"
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def safe_filename(name: str) -> str:
    name = (name or "file").strip().replace(" ", "_")
    cleaned = _SAFE_NAME.sub("", name)
    return cleaned or "file"


def build_key(company_id, kind: str, filename: str) -> str:
    """A namespaced object key: <company>/<kind>/<uuid>-<filename>."""
    return f"{company_id}/{kind}/{uuid.uuid4().hex}-{safe_filename(filename)}"


def _local_path(key: str) -> Path:
    base = Path(settings.local_storage_dir).resolve()
    target = (base / key).resolve()
    # Prevent path traversal outside the storage dir.
    if not str(target).startswith(str(base)):
        raise ValueError("Invalid storage key")
    return target


def guess_content_type(key: str, fallback: str = "application/octet-stream") -> str:
    ctype, _ = mimetypes.guess_type(key)
    return ctype or fallback


async def save(key: str, data: bytes, content_type: str) -> None:
    if settings.storage_enabled:
        def _put():
            _client().put_object(
                Bucket=settings.r2_bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
            )

        await run_in_threadpool(_put)
        return

    def _write():
        path = _local_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    await run_in_threadpool(_write)


async def load(key: str) -> bytes:
    if settings.storage_enabled:
        def _get() -> bytes:
            obj = _client().get_object(Bucket=settings.r2_bucket, Key=key)
            return obj["Body"].read()

        return await run_in_threadpool(_get)

    def _read() -> bytes:
        return _local_path(key).read_bytes()

    return await run_in_threadpool(_read)


async def delete(key: str) -> None:
    if settings.storage_enabled:
        def _del():
            _client().delete_object(Bucket=settings.r2_bucket, Key=key)

        await run_in_threadpool(_del)
        return

    def _unlink():
        path = _local_path(key)
        if path.exists():
            path.unlink()

    await run_in_threadpool(_unlink)


def public_url(key: str) -> str:
    """A stable URL for a stored object (used for logos shown in the app)."""
    if settings.storage_enabled and settings.r2_public_url:
        return f"{settings.r2_public_url.rstrip('/')}/{key}"
    if settings.storage_enabled:
        # No public bucket configured — return a long-lived signed URL.
        return _client().generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.r2_bucket, "Key": key},
            ExpiresIn=7 * 24 * 3600,
        )
    # Local dev: serve through the public raw endpoint.
    base = settings.backend_public_url.rstrip("/")
    return f"{base}{settings.api_v1_prefix}/files/public/{key}"
