"""Storage abstraction for uploaded documents.

Application code depends only on ``StorageBackend``. The local-disk adapter is for
development; an S3 adapter can implement the same protocol later without touching
callers. Keys are opaque, server-generated identifiers, never user input.
"""

import uuid
from typing import Protocol


class StorageError(Exception):
    """Base class for storage failures (the message never includes file contents)."""


class InvalidStorageKeyError(StorageError):
    """The key is not a server-generated key (possible traversal attempt)."""


class StorageNotFoundError(StorageError):
    """No object exists for the key."""


class StorageConfigurationError(StorageError):
    """The configured storage backend cannot be used."""


class StorageBackend(Protocol):
    async def put(self, key: str, data: bytes) -> None: ...

    async def get(self, key: str) -> bytes:
        """Return the object's bytes or raise ``StorageNotFoundError``."""
        ...

    async def delete(self, key: str) -> None:
        """Delete the object. Deleting a missing object is not an error."""
        ...


def new_storage_key(owner_id: uuid.UUID) -> str:
    """``<owner hex>/<random hex>``: namespaced per owner, unguessable, path-safe."""
    return f"{owner_id.hex}/{uuid.uuid4().hex}"
