"""Document storage backends."""

from app.core.config import Settings
from app.storage.base import StorageBackend, StorageConfigurationError
from app.storage.local import LocalStorage


def create_storage(settings: Settings) -> StorageBackend:
    if settings.storage_backend == "local":
        return LocalStorage(settings.local_storage_path)
    raise StorageConfigurationError(
        f"Storage backend {settings.storage_backend!r} is not implemented yet"
    )
