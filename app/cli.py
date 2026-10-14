"""Comandos de administración.

    python -m app.cli crear-usuario <usuario> <nombre> --rol admin|empleado
"""

import argparse
import getpass
import sys

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Role, User
from app.security import hash_password

MIN_PASSWORD = 8


def crear_usuario(usuario: str, nombre: str, rol: Role, password: str) -> User:
    if len(password) < MIN_PASSWORD:
        raise ValueError(f"La contraseña debe tener al menos {MIN_PASSWORD} caracteres")
    usuario = usuario.strip().lower()
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.usuario == usuario)):
            raise ValueError(f"El usuario '{usuario}' ya existe")
        user = User(
            usuario=usuario,
            nombre=nombre,
            rol=rol,
            password_hash=hash_password(password),
        )
        db.add(user)
        db.commit()
        return user


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="comando", required=True)
    p = sub.add_parser("crear-usuario", help="Crea un usuario")
    p.add_argument("usuario")
    p.add_argument("nombre")
    p.add_argument("--rol", choices=[r.value for r in Role], default="empleado")
    args = parser.parse_args(argv)

    password = getpass.getpass("Contraseña: ")
    if password != getpass.getpass("Repetir contraseña: "):
        print("Las contraseñas no coinciden", file=sys.stderr)
        return 1
    try:
        user = crear_usuario(args.usuario, args.nombre, Role(args.rol), password)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(f"Usuario '{user.usuario}' creado con rol {user.rol.value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
