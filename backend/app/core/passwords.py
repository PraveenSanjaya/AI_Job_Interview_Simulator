"""Password hashing with Argon2id (via argon2-cffi's RFC 9106 default profile)."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()  # Argon2id with library defaults; salt is generated per hash.

# Verified against when an account does not exist, so that "unknown email" and
# "wrong password" take comparable time and cannot be told apart by timing.
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing-equalisation")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Return True only if the password matches; never raises on a mismatch."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """True when the stored hash uses weaker parameters than the current profile."""
    return _hasher.check_needs_rehash(password_hash)


def verify_against_dummy(password: str) -> None:
    """Spend the same effort as a real verification and discard the result."""
    verify_password(password, _DUMMY_HASH)
