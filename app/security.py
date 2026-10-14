from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()

# Hash de relleno: se verifica cuando el usuario no existe, para que el
# tiempo de respuesta no revele si el nombre de usuario es válido.
_DUMMY_HASH = _hasher.hash("relleno-para-igualar-tiempos")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and bool(
            password_hash
        )
    except (VerificationError, InvalidHashError):
        return False
