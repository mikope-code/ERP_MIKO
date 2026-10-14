from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import (
    Customer,
    CustomerProductAdjustment,
    CustomerUnitPrice,
    Product,
    ProductUnit,
    UnitKind,
)
from tests.conftest import login

D = Decimal


@pytest.fixture()
def piso(db_session):
    p = Product(sku="PISO", nombre="Piso PVC", categoria="Piso PVC", unidad_base="pieza")
    p.unidades = [
        ProductUnit(nombre="pieza", tipo=UnitKind.BASE, piezas_por_unidad=1, precio_lista=D("25")),
        ProductUnit(nombre="caja", tipo=UnitKind.CAJA, piezas_por_unidad=8, precio_lista=D("190")),
    ]
    db_session.add(p)
    db_session.commit()
    return p


def nuevo_cliente(client, nombre="Constructora Perez", ajuste="5"):
    return client.post("/clientes", data=dict(nombre=nombre, ajuste_pct_defecto=ajuste))


def test_clientes_solo_admin(client, admin, empleado):
    assert client.get("/clientes").status_code == 303  # sin sesión
    login(client, "ana")
    assert client.get("/clientes").status_code == 403
    assert nuevo_cliente(client).status_code == 403
    assert client.get("/clientes/1").status_code == 403
    for ruta in (
        "/clientes/1/editar", "/clientes/1/precios", "/clientes/1/ajustes",
        "/clientes/1/precios/1/eliminar", "/clientes/1/ajustes/1/eliminar",
    ):
        assert client.post(ruta, data={}).status_code == 403, ruta


def test_crear_cliente(client, admin, db_session):
    login(client, "dueno")
    r = nuevo_cliente(client, ajuste="7,5")
    assert r.status_code == 303
    c = db_session.scalar(select(Customer))
    assert c.ajuste_pct_defecto == D("7.5")
    assert c.activo is True


def test_nombre_duplicado_sin_importar_mayusculas(client, admin, db_session):
    login(client, "dueno")
    nuevo_cliente(client)
    assert nuevo_cliente(client, nombre="constructora PEREZ").status_code == 422
    assert len(db_session.scalars(select(Customer)).all()) == 1


@pytest.mark.parametrize("ajuste", ["101", "-101", "abc", "1e400"])
def test_ajuste_fuera_de_rango(client, admin, db_session, ajuste):
    login(client, "dueno")
    assert nuevo_cliente(client, ajuste=ajuste).status_code == 422
    assert db_session.scalar(select(Customer)) is None


def test_recargo_permitido(client, admin, db_session):
    login(client, "dueno")
    nuevo_cliente(client, ajuste="-12")
    assert db_session.scalar(select(Customer)).ajuste_pct_defecto == D("-12")


def test_editar_cliente(client, admin, db_session):
    login(client, "dueno")
    nuevo_cliente(client)
    r = client.post(
        "/clientes/1/editar",
        data=dict(nombre="Constructora Perez SAC", telefono="999", ajuste_pct_defecto="10", activo="1"),
    )
    assert r.status_code == 303
    db_session.expire_all()
    c = db_session.scalar(select(Customer))
    assert (c.nombre, c.telefono, c.ajuste_pct_defecto) == ("Constructora Perez SAC", "999", D("10"))


def test_editar_rechazado_no_cambia_nada(client, admin, db_session):
    login(client, "dueno")
    nuevo_cliente(client)
    r = client.post("/clientes/1/editar", data=dict(nombre="", ajuste_pct_defecto="10"))
    assert r.status_code == 422
    db_session.expire_all()
    assert db_session.scalar(select(Customer)).ajuste_pct_defecto == D("5")


def test_precio_especial_alta_actualiza_y_quita(client, admin, db_session, piso):
    login(client, "dueno")
    nuevo_cliente(client)
    caja = next(u for u in piso.unidades if u.nombre == "caja")

    assert client.post("/clientes/1/precios", data=dict(unit_id=caja.id, precio="150")).status_code == 303
    assert client.post("/clientes/1/precios", data=dict(unit_id=caja.id, precio="145,50")).status_code == 303
    filas = db_session.scalars(select(CustomerUnitPrice)).all()
    assert len(filas) == 1  # actualiza, no duplica
    assert filas[0].precio == D("145.50")

    assert client.post(f"/clientes/1/precios/{filas[0].id}/eliminar").status_code == 303
    assert db_session.scalar(select(CustomerUnitPrice)) is None


def test_precio_especial_invalido(client, admin, db_session, piso):
    login(client, "dueno")
    nuevo_cliente(client)
    caja = piso.unidades[1]
    for datos in (
        dict(unit_id=caja.id, precio="-1"),
        dict(unit_id=caja.id, precio="x"),
        dict(unit_id="999", precio="10"),
        dict(unit_id="", precio="10"),
    ):
        assert client.post("/clientes/1/precios", data=datos).status_code == 422, datos
    assert db_session.scalar(select(CustomerUnitPrice)) is None


def test_ajuste_por_producto_alta_actualiza_y_quita(client, admin, db_session, piso):
    login(client, "dueno")
    nuevo_cliente(client)
    assert client.post("/clientes/1/ajustes", data=dict(product_id=piso.id, ajuste_pct="20")).status_code == 303
    assert client.post("/clientes/1/ajustes", data=dict(product_id=piso.id, ajuste_pct="0")).status_code == 303
    filas = db_session.scalars(select(CustomerProductAdjustment)).all()
    assert len(filas) == 1
    assert filas[0].ajuste_pct == D("0")
    assert client.post(f"/clientes/1/ajustes/{filas[0].id}/eliminar").status_code == 303
    assert db_session.scalar(select(CustomerProductAdjustment)) is None


def test_no_se_borra_regla_de_otro_cliente(client, admin, db_session, piso):
    login(client, "dueno")
    nuevo_cliente(client)
    nuevo_cliente(client, nombre="Otro")
    client.post("/clientes/1/ajustes", data=dict(product_id=piso.id, ajuste_pct="20"))
    fila = db_session.scalar(select(CustomerProductAdjustment))
    assert client.post(f"/clientes/2/ajustes/{fila.id}/eliminar").status_code == 404
    assert db_session.scalar(select(CustomerProductAdjustment)) is not None


def test_pantalla_muestra_precio_resultante_y_regla(client, admin, db_session, piso):
    login(client, "dueno")
    nuevo_cliente(client, ajuste="5")
    caja = piso.unidades[1]
    client.post("/clientes/1/precios", data=dict(unit_id=caja.id, precio="150"))
    html = client.get("/clientes/1").text
    assert "S/ 150.00" in html and "Precio especial" in html
    assert "S/ 23.75" in html and "Ajuste general del cliente" in html  # pieza: 25 − 5 %


def test_cliente_inexistente_404(client, admin):
    login(client, "dueno")
    assert client.get("/clientes/99").status_code == 404
