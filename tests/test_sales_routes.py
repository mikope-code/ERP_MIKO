from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import Customer, Product, ProductUnit, Sale, SaleStatus, UnitKind
from app.services.stock import registrar_entrada, stock_total
from tests.conftest import login

D = Decimal


@pytest.fixture()
def tienda(db_session, admin):
    piso = Product(
        sku="PISO", nombre="Piso PVC", categoria="Piso PVC", unidad_base="pieza",
        m2_por_pieza=D("0.36"),
    )
    piso.unidades = [
        ProductUnit(nombre="pieza", tipo=UnitKind.BASE, piezas_por_unidad=1, precio_lista=D("25")),
        ProductUnit(nombre="caja", tipo=UnitKind.CAJA, piezas_por_unidad=8, precio_lista=D("190")),
        ProductUnit(nombre="m²", tipo=UnitKind.AREA, piezas_por_unidad=1, precio_lista=D("70")),
    ]
    db_session.add(piso)
    db_session.commit()
    u = {x.nombre: x for x in piso.unidades}
    registrar_entrada(db_session, piso, u["caja"], 5, admin)  # 40 piezas
    db_session.commit()
    return piso, u


def vender(client, lineas, cliente_id="", nota=""):
    """lineas: [(unit_id, cantidad)] o [(unit_id, cantidad, precio)]."""
    return client.post(
        "/ventas",
        data={
            "cliente_id": cliente_id,
            "nota": nota,
            "unit_id": [str(l[0]) for l in lineas],
            "cantidad": [str(l[1]) for l in lineas],
            "precio": [str(l[2]) if len(l) > 2 else "" for l in lineas],
        },
    )


def test_ventas_requieren_login(client):
    for ruta in ("/ventas", "/ventas/nueva", "/ventas/1"):
        assert client.get(ruta).status_code == 303
    assert client.post("/ventas", data={}).status_code == 303
    assert client.post("/ventas/previa", data={}).status_code == 303


def test_empleado_registra_venta(client, empleado, tienda, db_session):
    piso, u = tienda
    login(client, "ana")
    r = vender(client, [(u["caja"].id, 2)], nota="Entrega mañana")
    assert r.status_code == 303
    venta = db_session.scalar(select(Sale))
    assert r.headers["location"] == f"/ventas/{venta.id}"
    assert venta.total == D("380.00")
    assert venta.usuario.usuario == "ana"
    assert venta.nota == "Entrega mañana"
    assert stock_total(db_session, piso.id) == 24


def test_venta_mixta_cajas_y_m2(client, empleado, tienda, db_session):
    piso, u = tienda
    login(client, "ana")
    vender(client, [(u["caja"].id, 2), (u["m²"].id, 3)])
    venta = db_session.scalar(select(Sale))
    assert venta.total == D("606.80")
    assert stock_total(db_session, piso.id) == 15
    html = client.get(f"/ventas/{venta.id}").text
    assert "3 m² pedidos" in html
    assert "9 pieza = 3.24 m²" in html


def test_precio_del_cliente_se_aplica(client, empleado, tienda, db_session):
    _, u = tienda
    c = Customer(nombre="Perez", ajuste_pct_defecto=D("10"))
    db_session.add(c)
    db_session.commit()
    login(client, "ana")
    vender(client, [(u["caja"].id, 1)], cliente_id=c.id)
    venta = db_session.scalar(select(Sale))
    assert venta.total == D("171.00")
    assert venta.customer_id == c.id


def test_empleado_no_puede_forzar_precio(client, empleado, tienda, db_session):
    """Aunque manipule el formulario enviando un precio, no se usa."""
    _, u = tienda
    login(client, "ana")
    vender(client, [(u["caja"].id, 1, "1")])
    assert db_session.scalar(select(Sale)).total == D("190.00")


def test_empleado_no_ve_campo_de_precio(client, empleado, admin, tienda):
    login(client, "ana")
    assert 'name="precio"' not in client.get("/ventas/nueva").text
    client.post("/logout")
    login(client, "dueno")
    assert 'name="precio"' in client.get("/ventas/nueva").text


def test_admin_fija_precio(client, admin, tienda, db_session):
    _, u = tienda
    login(client, "dueno")
    vender(client, [(u["caja"].id, 2, "175,50")])
    venta = db_session.scalar(select(Sale))
    assert venta.total == D("351.00")
    assert venta.lineas[0].precio_manual is True


def test_stock_insuficiente_muestra_error_y_no_vende(client, empleado, tienda, db_session):
    piso, u = tienda
    login(client, "ana")
    r = vender(client, [(u["caja"].id, 6)])
    assert r.status_code == 422
    assert "Stock insuficiente" in r.text
    assert db_session.scalar(select(Sale)) is None
    assert stock_total(db_session, piso.id) == 40


@pytest.mark.parametrize(
    "lineas",
    [
        [],
        [("", "")],
        [("1", "")],
        [("", "2")],
        [("1", "abc")],
        [("1", "0")],
        [("1", "1.5")],  # fracción de pieza
        [("9999", "1")],
    ],
)
def test_pedidos_invalidos(client, empleado, tienda, db_session, lineas):
    login(client, "ana")
    r = vender(client, lineas)
    assert r.status_code == 422
    assert db_session.scalar(select(Sale)) is None


def test_filas_vacias_se_ignoran(client, empleado, tienda, db_session):
    _, u = tienda
    login(client, "ana")
    r = vender(client, [("", ""), (u["pieza"].id, 3), ("", "")])
    assert r.status_code == 303
    assert db_session.scalar(select(Sale)).total == D("75.00")


def test_cliente_invalido(client, empleado, tienda, db_session):
    _, u = tienda
    login(client, "ana")
    assert vender(client, [(u["pieza"].id, 1)], cliente_id="999").status_code == 422
    assert db_session.scalar(select(Sale)) is None


def test_previa_calcula_sin_registrar(client, empleado, tienda, db_session):
    piso, u = tienda
    login(client, "ana")
    r = client.post(
        "/ventas/previa",
        data={"cliente_id": "", "unit_id": [str(u["m²"].id)], "cantidad": ["7"], "precio": [""]},
    )
    assert r.status_code == 200
    assert "S/ 504.00" in r.text
    assert "20 pieza = 7.20 m²" in r.text
    assert db_session.scalar(select(Sale)) is None
    assert stock_total(db_session, piso.id) == 40


def test_previa_avisa_stock_insuficiente(client, empleado, tienda):
    _, u = tienda
    login(client, "ana")
    r = client.post(
        "/ventas/previa",
        data={"unit_id": [str(u["caja"].id)], "cantidad": ["9"], "precio": [""]},
    )
    assert "Stock insuficiente" in r.text


def test_previa_no_revela_regla_al_empleado(client, empleado, admin, tienda, db_session):
    _, u = tienda
    c = Customer(nombre="Perez", ajuste_pct_defecto=D("10"))
    db_session.add(c)
    db_session.commit()
    datos = {
        "cliente_id": str(c.id),
        "unit_id": [str(u["caja"].id)], "cantidad": ["1"], "precio": [""],
    }
    login(client, "ana")
    html = client.post("/ventas/previa", data=datos).text
    assert "S/ 171.00" in html
    assert "Ajuste general" not in html
    client.post("/logout")
    login(client, "dueno")
    assert "Ajuste general del cliente" in client.post("/ventas/previa", data=datos).text


def test_nueva_linea_devuelve_fila(client, empleado, tienda):
    login(client, "ana")
    r = client.post("/ventas/linea")
    assert r.status_code == 200
    assert 'name="unit_id"' in r.text


def test_historial_y_detalle(client, empleado, tienda, db_session):
    _, u = tienda
    login(client, "ana")
    vender(client, [(u["pieza"].id, 2)])
    assert "S/ 50.00" in client.get("/ventas").text
    assert client.get("/ventas/1").status_code == 200
    assert client.get("/ventas/99").status_code == 404


def test_solo_admin_anula(client, admin, empleado, tienda, db_session):
    piso, u = tienda
    login(client, "ana")
    vender(client, [(u["caja"].id, 2)])
    assert client.post("/ventas/1/anular", data={"motivo": "x"}).status_code == 403
    assert "Anular venta" not in client.get("/ventas/1").text
    client.post("/logout")

    login(client, "dueno")
    assert client.post("/ventas/1/anular", data={"motivo": "  "}).status_code == 422
    r = client.post("/ventas/1/anular", data={"motivo": "Cliente devolvió"})
    assert r.status_code == 303
    db_session.expire_all()
    assert db_session.get(Sale, 1).estado is SaleStatus.ANULADA
    assert stock_total(db_session, piso.id) == 40
    assert "Cliente devolvió" in client.get("/ventas/1").text
    assert client.post("/ventas/1/anular", data={"motivo": "otra"}).status_code == 422
    assert stock_total(db_session, piso.id) == 40


def test_admin_ve_ajuste_en_detalle_empleado_no(client, admin, empleado, tienda, db_session):
    _, u = tienda
    c = Customer(nombre="Perez", ajuste_pct_defecto=D("10"))
    db_session.add(c)
    db_session.commit()
    login(client, "ana")
    vender(client, [(u["caja"].id, 1)], cliente_id=c.id)
    assert "lista S/" not in client.get("/ventas/1").text
    client.post("/logout")
    login(client, "dueno")
    assert "lista S/ 190.00" in client.get("/ventas/1").text
