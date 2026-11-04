from argon2 import PasswordHasher

from app.core.passwords import hash_password, needs_rehash, verify_against_dummy, verify_password

PASSWORD = "correct horse battery 42"


def test_hash_is_argon2id_and_not_plaintext() -> None:
    hashed = hash_password(PASSWORD)
    assert hashed.startswith("$argon2id$")
    assert PASSWORD not in hashed


def test_same_password_produces_different_hashes() -> None:
    assert hash_password(PASSWORD) != hash_password(PASSWORD)


def test_verify_accepts_correct_and_rejects_wrong_password() -> None:
    hashed = hash_password(PASSWORD)
    assert verify_password(PASSWORD, hashed) is True
    assert verify_password("wrong password 1", hashed) is False


def test_verify_returns_false_for_malformed_hash() -> None:
    assert verify_password(PASSWORD, "not-a-hash") is False
    assert verify_password(PASSWORD, "") is False


def test_needs_rehash_detects_weaker_parameters() -> None:
    weak = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash(PASSWORD)
    assert needs_rehash(weak) is True
    assert needs_rehash(hash_password(PASSWORD)) is False


def test_dummy_verification_never_raises() -> None:
    verify_against_dummy(PASSWORD)
