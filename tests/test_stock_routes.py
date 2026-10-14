from datetime import date, timedelta

import pytest
from sqlalchemy import select
from app.clock import hoy_local

from app.models import Product, ProductUnit, StockLot, StockMovement, Supplier, UnitKind
from app.services.stock import stock_total
from tests.conftest import login


@pytest.fixture()
def catalogo(db_session):
    piso = Product(
        sku="PISO", nombre="Piso PVC", categoria="Piso PVC", unidad_base="pieza",
        stock_minimo=10,
    )
    piso.unidades = [
        ProductUnit(nombre="pieza", tipo=UnitKind.BASE, piezas_por_unidad=1),
        ProductUnit(nombre="caja", tipo=UnitKind.CAJA, piezas_por_unidad=8),
    ]
    peg = Product(
        sku="PEG", nombre="Pegamento", categoria="Pegamento", unidad_base="unidad",
        controla_vencimiento=True,
    )
    peg.unidades = [ProductUnit(nombre="unidad", tipo=UnitKind.BASE, piezas_por_unidad=1)]
    db_session.add_all([piso, peg])
    db_session.commit()
    return piso, peg


def unit(producto, nombre):
    return next(u for u in producto.unidades if u.nombre == nombre)


def test_stock_requiere_login(client):
    assert client.get("/stock").status_code == 303
    assert client.get("/stock/entrada").status_code == 303
    assert client.post("/stock/entrada", data={}).status_code == 303


def test_empleado_registra_entrada(client, empleado, catalogo, db_session):
    piso, _ = catalogo
    login(client, "ana")
    r = client.post(
        "/stock/entrada", data=dict(unit_id=unit(piso, "caja").id, cantidad="3")
    )
    assert r.status_code == 303
    assert r.headers["location"] == f"/stock/{piso.id}"
    assert stock_total(db_session, piso.id) == 24
    mov = db_session.scalar(select(StockMovement))
    assert mov.usuario.usuario == "ana"


def test_empleado_no_puede_poner_costo(client, empleado, catalogo, db_session):
    piso, _ = catalogo
    login(client, "ana")
    client.post(
        "/stock/entrada",
        data=dict(unit_id=unit(piso, "caja").id, cantidad="1", costo="190"),
    )
    assert db_session.scalar(select(StockMovement)).costo_unitario is None
    assert 'name="costo"' not in client.get("/stock/entrada").text


def test_admin_registra_costo_y_proveedor(client, admin, catalogo, db_session):
    piso, _ = catalogo
    prov = Supplier(nombre="Importadora Sur")
    db_session.add(prov)
    db_session.commit()
    login(client, "dueno")
    r = client.post(
        "/stock/entrada",
        data=dict(
            unit_id=unit(piso, "caja").id, cantidad="1", costo="190",
            supplier_id=prov.id, nota="Factura 123",
        ),
    )
    assert r.status_code == 303
    mov = db_session.scalar(select(StockMovement))
    assert mov.costo_unitario == 23.75
    assert mov.supplier_id == prov.id
    assert mov.nota == "Factura 123"


def test_entrada_con_vencimiento(client, empleado, catalogo, db_session):
    _, peg = catalogo
    login(client, "ana")
    venc = (hoy_local() + timedelta(days=90)).isoformat()
    r = client.post(
        "/stock/entrada",
        data=dict(unit_id=unit(peg, "unidad").id, cantidad="6", vencimiento=venc),
    )
    assert r.status_code == 303
    lote = db_session.scalar(select(StockLot))
    assert lote.fecha_vencimiento.isoformat() == venc
    assert lote.cantidad_base == 6


def test_entrada_sin_vencimiento_rechazada(client, empleado, catalogo, db_session):
    _, peg = catalogo
    login(client, "ana")
    r = client.post("/stock/entrada", data=dict(unit_id=unit(peg, "unidad").id, cantidad="6"))
    assert r.status_code == 422
    assert "vencimiento" in r.text
    assert db_session.scalar(select(StockMovement)) is None


@pytest.mark.parametrize("cantidad", ["0", "-2", "1.5", "abc", ""])
def test_entrada_cantidad_invalida(client, empleado, catalogo, db_session, cantidad):
    piso, _ = catalogo
    login(client, "ana")
    r = client.post(
        "/stock/entrada", data=dict(unit_id=unit(piso, "pieza").id, cantidad=cantidad)
    )
    assert r.status_code == 422
    assert db_session.scalar(select(StockMovement)) is None


def test_entrada_unidad_inexistente(client, empleado, catalogo):
    login(client, "ana")
    assert client.post("/stock/entrada", data=dict(unit_id="9999", cantidad="1")).status_code == 422
    assert client.post("/stock/entrada", data=dict(unit_id="", cantidad="1")).status_code == 422


def test_resumen_marca_stock_bajo(client, empleado, catalogo):
    piso, _ = catalogo
    login(client, "ana")
    client.post("/stock/entrada", data=dict(unit_id=unit(piso, "pieza").id, cantidad="4"))
    html = client.get("/stock").text
    assert "Stock bajo" in html
    assert "4 pieza" in html


def test_resumen_muestra_cajas_y_sueltas(client, empleado, catalogo):
    piso, _ = catalogo
    login(client, "ana")
    client.post("/stock/entrada", data=dict(unit_id=unit(piso, "pieza").id, cantidad="25"))
    assert "3 caja + 1 pieza (25 pieza)" in client.get("/stock").text


def test_resumen_avisa_vencimiento_cercano(client, empleado, catalogo):
    _, peg = catalogo
    login(client, "ana")
    cerca = (hoy_local() + timedelta(days=10)).isoformat()
    client.post(
        "/stock/entrada",
        data=dict(unit_id=unit(peg, "unidad").id, cantidad="5", vencimiento=cerca),
    )
    assert "Vence" in client.get("/stock").text


def test_detalle_muestra_kardex_sin_costos_a_empleado(client, admin, empleado, catalogo):
    piso, _ = catalogo
    login(client, "dueno")
    client.post(
        "/stock/entrada",
        data=dict(unit_id=unit(piso, "caja").id, cantidad="1", costo="190"),
    )
    assert "23.7500" in client.get(f"/stock/{piso.id}").text
    client.post("/logout")

    login(client, "ana")
    html = client.get(f"/stock/{piso.id}").text
    assert "entrada" in html
    assert "23.7500" not in html
    assert "Ajustar" not in html


def test_ajuste_solo_admin(client, admin, empleado, catalogo, db_session):
    piso, _ = catalogo
    login(client, "dueno")
    client.post("/stock/entrada", data=dict(unit_id=unit(piso, "caja").id, cantidad="1"))
    lote = db_session.scalar(select(StockLot))
    client.post("/logout")

    login(client, "ana")
    r = client.post(
        f"/stock/lotes/{lote.id}/ajuste", data=dict(cantidad_contada="2", nota="x")
    )
    assert r.status_code == 403
    client.post("/logout")

    login(client, "dueno")
    r = client.post(
        f"/stock/lotes/{lote.id}/ajuste",
        data=dict(cantidad_contada="5", nota="Rotura en traslado"),
    )
    assert r.status_code == 303
    assert stock_total(db_session, piso.id) == 5


def test_ajuste_sin_motivo_rechazado(client, admin, catalogo, db_session):
    piso, _ = catalogo
    login(client, "dueno")
    client.post("/stock/entrada", data=dict(unit_id=unit(piso, "caja").id, cantidad="1"))
    lote = db_session.scalar(select(StockLot))
    r = client.post(
        f"/stock/lotes/{lote.id}/ajuste", data=dict(cantidad_contada="2", nota="  ")
    )
    assert r.status_code == 422
    assert stock_total(db_session, piso.id) == 8


def test_proveedores_solo_admin(client, admin, empleado, db_session):
    login(client, "ana")
    assert client.get("/proveedores").status_code == 403
    assert client.post("/proveedores", data=dict(nombre="X")).status_code == 403
    client.post("/logout")

    login(client, "dueno")
    assert client.post("/proveedores", data=dict(nombre="Importadora Sur", telefono="999")).status_code == 303
    assert client.post("/proveedores", data=dict(nombre="importadora sur")).status_code == 422
    assert "Importadora Sur" in client.get("/proveedores").text
    assert len(db_session.scalars(select(Supplier)).all()) == 1
