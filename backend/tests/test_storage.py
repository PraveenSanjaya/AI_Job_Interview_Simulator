import uuid
from pathlib import Path

import pytest

from app.core.config import Settings
from app.storage import create_storage
from app.storage.base import (
    InvalidStorageKeyError,
    StorageConfigurationError,
    StorageNotFoundError,
    new_storage_key,
)
from app.storage.local import LocalStorage

pytestmark = pytest.mark.anyio


async def test_put_get_delete_round_trip(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    key = new_storage_key(uuid.uuid4())
    await storage.put(key, b"hello")
    assert await storage.get(key) == b"hello"
    await storage.delete(key)
    with pytest.raises(StorageNotFoundError):
        await storage.get(key)


async def test_delete_is_idempotent(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    await storage.delete(new_storage_key(uuid.uuid4()))


async def test_put_overwrites_atomically_and_leaves_no_temp_files(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    key = new_storage_key(uuid.uuid4())
    await storage.put(key, b"one")
    await storage.put(key, b"two")
    assert await storage.get(key) == b"two"
    assert [p.name for p in tmp_path.rglob("*") if p.is_file()] == [key.split("/")[1]]


def test_generated_keys_are_unique_and_path_safe() -> None:
    owner = uuid.uuid4()
    keys = {new_storage_key(owner) for _ in range(100)}
    assert len(keys) == 100
    for key in keys:
        assert key.startswith(owner.hex + "/")
        assert len(key) == 65


@pytest.mark.parametrize(
    "key",
    [
        "../etc/passwd",
        "..\\..\\windows\\system32",
        "/absolute/path",
        "a" * 32 + "/../" + "b" * 32,
        "a" * 32 + "/" + "b" * 31,
        "A" * 32 + "/" + "b" * 32,  # uppercase is not generated
        ("a" * 32 + "/" + "b" * 32) + "/extra",
        ("a" * 32 + "/" + "b" * 32) + "\n",
        "",
        "C:\\temp\\x",
        "a" * 32 + "\x00/" + "b" * 32,
    ],
)
async def test_malicious_or_malformed_keys_are_rejected(tmp_path: Path, key: str) -> None:
    storage = LocalStorage(tmp_path)
    for operation in (storage.get(key), storage.put(key, b"x"), storage.delete(key)):
        with pytest.raises(InvalidStorageKeyError):
            await operation
    assert list(tmp_path.rglob("*")) == []


async def test_nothing_is_written_outside_the_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    storage = LocalStorage(root)
    await storage.put(new_storage_key(uuid.uuid4()), b"data")
    assert set(tmp_path.iterdir()) == {root}


def test_factory_returns_local_storage_and_rejects_unimplemented_backends(
    tmp_path: Path,
) -> None:
    local = create_storage(Settings(_env_file=None, local_storage_path=str(tmp_path)))
    assert isinstance(local, LocalStorage)
    with pytest.raises(StorageConfigurationError):
        create_storage(Settings(_env_file=None, storage_backend="s3"))
