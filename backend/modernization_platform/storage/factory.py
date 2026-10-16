"""Factory for instantiating the configured storage adapter."""

import logging
from functools import lru_cache

from modernization_platform.config.settings import Settings, get_settings
from modernization_platform.core.decorators import log_errors
from modernization_platform.storage.base import StorageAdapter
from modernization_platform.storage.memory import MemoryStorageAdapter
from modernization_platform.storage.s3 import S3StorageAdapter

logger = logging.getLogger(__name__)


@log_errors
def create_storage_adapter(settings: Settings | None = None) -> StorageAdapter:
    """Instantiate a storage adapter based on application configuration."""
    try:
        cfg = settings or get_settings()

        if cfg.storage_backend == "memory":
            logger.info(
                "Initializing in-memory storage adapter for bucket '%s'.", cfg.storage_s3_bucket
            )
            return MemoryStorageAdapter(
                bucket=cfg.storage_s3_bucket,
                max_artifact_size_bytes=cfg.storage_max_artifact_size_bytes,
            )

        logger.info(
            "Initializing S3 storage adapter for bucket '%s' at endpoint '%s'.",
            cfg.storage_s3_bucket,
            cfg.storage_s3_endpoint_masked,
        )
        return S3StorageAdapter(
            bucket=cfg.storage_s3_bucket,
            endpoint_url=cfg.storage_s3_endpoint_url,
            region_name=cfg.storage_s3_region,
            access_key_id=(
                cfg.storage_s3_access_key_id.get_secret_value()
                if cfg.storage_s3_access_key_id
                else None
            ),
            secret_access_key=(
                cfg.storage_s3_secret_access_key.get_secret_value()
                if cfg.storage_s3_secret_access_key
                else None
            ),
            use_ssl=cfg.storage_s3_use_ssl,
            max_artifact_size_bytes=cfg.storage_max_artifact_size_bytes,
            timeout_seconds=cfg.storage_timeout_seconds,
            max_retries=cfg.storage_max_retries,
        )
    except Exception as exc:
        logger.exception("create_storage_adapter failed | %s: %s", type(exc).__name__, exc)
        raise


@lru_cache(maxsize=1)
def get_storage_adapter() -> StorageAdapter:
    """Return a singleton storage adapter instance."""
    try:
        return create_storage_adapter()
    except Exception as exc:
        logger.exception("get_storage_adapter failed | %s: %s", type(exc).__name__, exc)
        raise


__all__ = ["create_storage_adapter", "get_storage_adapter"]
