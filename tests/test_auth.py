from fastapi import Depends

from app.auth import AdminUser
from app.main import app
from tests.conftest import login, make_user
from app.models import Role


# Ruta solo-admin de prueba: los módulos reales (productos, usuarios) la usarán igual
@app.get("/_test/solo-admin")
def _solo_admin(user: AdminUser):
    return {"ok": True}


def test_home_sin_sesion_redirige_a_login(client):
    r = client.get("/")
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_login_correcto_crea_sesion(client, admin):
    r = login(client, "dueno")
    assert r.status_code == 303
    assert r.headers["location"] == "/"
    assert client.get("/").status_code == 200


def test_login_normaliza_mayusculas_y_espacios(client, admin):
    assert login(client, "  DUENO ").status_code == 303


def test_password_incorrecta(client, admin):
    r = login(client, "dueno", "otra-clave")
    assert r.status_code == 401
    assert "incorrectos" in r.text
    assert client.get("/").status_code == 303


def test_usuario_inexistente_mismo_mensaje(client, admin):
    r = login(client, "fantasma")
    assert r.status_code == 401
    assert "Usuario o contraseña incorrectos" in r.text


def test_usuario_inactivo_no_puede_entrar(client, db_session):
    make_user(db_session, "baja", Role.EMPLEADO, activo=False)
    assert login(client, "baja").status_code == 401


def test_desactivar_corta_sesion_activa(client, db_session, empleado):
    login(client, "ana")
    assert client.get("/").status_code == 200
    empleado.activo = False
    db_session.commit()
    assert client.get("/").status_code == 303


def test_logout_cierra_sesion(client, admin):
    login(client, "dueno")
    r = client.post("/logout")
    assert r.status_code == 303
    assert client.get("/").status_code == 303


def test_empleado_no_accede_a_ruta_admin(client, empleado):
    login(client, "ana")
    assert client.get("/_test/solo-admin").status_code == 403


def test_admin_accede_a_ruta_admin(client, admin):
    login(client, "dueno")
    assert client.get("/_test/solo-admin").status_code == 200


def test_ruta_admin_sin_sesion_redirige(client):
    assert client.get("/_test/solo-admin").status_code == 303


def test_password_no_se_guarda_en_claro(admin):
    assert "clave-segura-1" not in admin.password_hash
    assert admin.password_hash.startswith("$argon2")
