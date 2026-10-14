from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Role, User

SESSION_KEY = "user_id"


class LoginRequired(Exception):
    """Se lanza cuando falta sesión; main.py la convierte en redirect a /login."""


def get_current_user(
    request: Request, db: Annotated[Session, Depends(get_db)]
) -> User:
    user_id = request.session.get(SESSION_KEY)
    if user_id is None:
        raise LoginRequired
    user = db.get(User, user_id)
    # Se relee en cada petición: desactivar un usuario corta su acceso al instante
    if user is None or not user.activo:
        request.session.clear()
        raise LoginRequired
    return user


def require_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    if user.rol != Role.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo el administrador")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
AdminUser = Annotated[User, Depends(require_admin)]


def authenticate(db: Session, usuario: str, password: str) -> User | None:
    from app.security import verify_password

    user = db.scalar(select(User).where(User.usuario == usuario.strip().lower()))
    ok = verify_password(password, user.password_hash if user else None)
    if user is None or not ok or not user.activo:
        return None
    return user
