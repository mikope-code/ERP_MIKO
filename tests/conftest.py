import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.db import Base, get_db
from app.main import app
from app.models import Role, User
from app.security import hash_password


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app, follow_redirects=False) as c:
        yield c
    app.dependency_overrides.clear()


def make_user(db, usuario, rol, password="clave-segura-1", activo=True):
    user = User(
        usuario=usuario,
        nombre=usuario.capitalize(),
        rol=rol,
        password_hash=hash_password(password),
        activo=activo,
    )
    db.add(user)
    db.commit()
    return user


@pytest.fixture()
def admin(db_session):
    return make_user(db_session, "dueno", Role.ADMIN)


@pytest.fixture()
def empleado(db_session):
    return make_user(db_session, "ana", Role.EMPLEADO)


def login(client, usuario, password="clave-segura-1"):
    return client.post("/login", data={"usuario": usuario, "password": password})
