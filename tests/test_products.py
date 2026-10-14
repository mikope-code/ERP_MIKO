from decimal import Decimal

from sqlalchemy import select

from app.models import Product, UnitKind
from tests.conftest import login

PISO = dict(
    sku="piso-roble", nombre="Piso PVC roble", categoria="Piso PVC",
    unidad_base="pieza", precio_base="25.50", costo="18", stock_minimo="16",
    m2_por_pieza="0.36",
)


def crear_piso(client, **over):
    return client.post("/productos", data={**PISO, **over})


def test_requiere_login(client):
    assert client.get("/productos").status_code == 303
    assert client.post("/productos", data=PISO).status_code == 303


def test_admin_crea_producto_con_unidad_base(client, admin, db_session):
    login(client, "dueno")
    r = crear_piso(client)
    assert r.status_code == 303

    p = db_session.scalar(select(Product))
    assert p.sku == "PISO-ROBLE"  # normalizado a mayúsculas
    assert p.m2_por_pieza == Decimal("0.36")
    assert len(p.unidades) == 1
    base = p.unidades[0]
    assert base.tipo is UnitKind.BASE
    assert base.nombre == "pieza"
    assert base.precio_lista == Decimal("25.50")


def test_empleado_no_puede_crear_ni_editar(client, admin, empleado, db_session):
    login(client, "dueno")
    crear_piso(client)
    client.post("/logout")

    login(client, "ana")
    assert client.get("/productos/nuevo").status_code == 403
    assert crear_piso(client, sku="X2").status_code == 403
    assert client.post(
        "/productos/1/editar",
        data=dict(nombre="Hack", categoria="Otro", costo="0", stock_minimo="0"),
    ).status_code == 403
    assert client.post("/productos/1/unidades", data=dict(tipo="caja", precio="1")).status_code == 403
    assert client.post("/productos/1/unidades/1/precio", data=dict(precio="1")).status_code == 403
    assert db_session.scalar(select(Product)).nombre == "Piso PVC roble"


def test_empleado_ve_precios_pero_no_costo(client, admin, empleado):
    login(client, "dueno")
    crear_piso(client, costo="18.00")
    client.post("/logout")

    login(client, "ana")
    lista = client.get("/productos")
    assert lista.status_code == 200
    assert "25.50" in lista.text
    assert "18.00" not in lista.text
    assert "Costo" not in lista.text
    detalle = client.get("/productos/1")
    assert detalle.status_code == 200
    assert "18.00" not in detalle.text


def test_sku_duplicado_rechazado(client, admin, db_session):
    login(client, "dueno")
    crear_piso(client)
    r = crear_piso(client, sku="PISO-ROBLE")
    assert r.status_code == 422
    assert "ya existe" in r.text
    assert len(db_session.scalars(select(Product)).all()) == 1


def test_validaciones_de_campos(client, admin, db_session):
    login(client, "dueno")
    for over in (
        dict(precio_base="abc"),
        dict(precio_base="-5"),
        dict(stock_minimo="1.5"),
        dict(m2_por_pieza="0"),
        dict(categoria="Inventada"),
        dict(nombre="   "),
    ):
        assert crear_piso(client, **over).status_code == 422, over
    assert db_session.scalar(select(Product)) is None


def test_precio_con_coma_decimal(client, admin, db_session):
    login(client, "dueno")
    crear_piso(client, precio_base="25,50")
    assert db_session.scalar(select(Product)).unidades[0].precio_lista == Decimal("25.50")


def test_agregar_caja_y_m2(client, admin, db_session):
    login(client, "dueno")
    crear_piso(client)
    assert client.post(
        "/productos/1/unidades", data=dict(tipo="caja", nombre="caja", piezas_por_unidad="8", precio="190")
    ).status_code == 303
    assert client.post(
        "/productos/1/unidades", data=dict(tipo="area", precio="70")
    ).status_code == 303

    p = db_session.scalar(select(Product))
    por_nombre = {u.nombre: u for u in p.unidades}
    assert por_nombre["caja"].piezas_por_unidad == 8
    assert por_nombre["caja"].tipo is UnitKind.CAJA
    assert por_nombre["m²"].tipo is UnitKind.AREA
    assert por_nombre["m²"].precio_lista == Decimal("70")


def test_m2_requiere_cobertura_definida(client, admin, db_session):
    login(client, "dueno")
    crear_piso(client, sku="CLIP", nombre="Clips", categoria="Clips", m2_por_pieza="")
    r = client.post("/productos/1/unidades", data=dict(tipo="area", precio="70"))
    assert r.status_code == 422
    assert len(db_session.scalar(select(Product)).unidades) == 1


def test_no_duplica_unidades(client, admin, db_session):
    login(client, "dueno")
    crear_piso(client)
    data = dict(tipo="caja", nombre="caja", piezas_por_unidad="8", precio="190")
    assert client.post("/productos/1/unidades", data=data).status_code == 303
    assert client.post("/productos/1/unidades", data=data).status_code == 422
    assert client.post("/productos/1/unidades", data=dict(tipo="area", precio="70")).status_code == 303
    assert client.post("/productos/1/unidades", data=dict(tipo="area", precio="70")).status_code == 422


def test_caja_con_piezas_invalidas(client, admin):
    login(client, "dueno")
    crear_piso(client)
    for piezas in ("0", "-2", "2.5", "abc", ""):
        r = client.post(
            "/productos/1/unidades",
            data=dict(tipo="caja", nombre="caja", piezas_por_unidad=piezas, precio="1"),
        )
        assert r.status_code == 422, piezas


def test_actualizar_precio_y_quitar_unidad(client, admin, db_session):
    login(client, "dueno")
    crear_piso(client)
    client.post("/productos/1/unidades", data=dict(tipo="caja", nombre="caja", piezas_por_unidad="8", precio="190"))
    p = db_session.scalar(select(Product))
    caja = next(u for u in p.unidades if u.tipo is UnitKind.CAJA)

    assert client.post(f"/productos/1/unidades/{caja.id}/precio", data=dict(precio="195.5")).status_code == 303
    db_session.refresh(caja)
    assert caja.precio_lista == Decimal("195.5")

    assert client.post(f"/productos/1/unidades/{caja.id}/eliminar").status_code == 303
    db_session.expire_all()
    assert len(db_session.scalar(select(Product)).unidades) == 1


def test_no_se_puede_quitar_la_unidad_base(client, admin, db_session):
    login(client, "dueno")
    crear_piso(client)
    base_id = db_session.scalar(select(Product)).unidades[0].id
    assert client.post(f"/productos/1/unidades/{base_id}/eliminar").status_code == 400


def test_no_se_puede_quitar_m2_del_producto_si_hay_unidad_m2(client, admin, db_session):
    login(client, "dueno")
    crear_piso(client)
    client.post("/productos/1/unidades", data=dict(tipo="area", precio="70"))
    r = client.post(
        "/productos/1/editar",
        data=dict(nombre="Piso", categoria="Piso PVC", costo="18", stock_minimo="0", m2_por_pieza=""),
    )
    assert r.status_code == 422
    assert db_session.scalar(select(Product)).m2_por_pieza == Decimal("0.36")


def test_editar_producto(client, admin, db_session):
    login(client, "dueno")
    crear_piso(client)
    r = client.post(
        "/productos/1/editar",
        data=dict(
            nombre="Piso PVC nogal", categoria="Piso PVC", costo="20", stock_minimo="24",
            m2_por_pieza="0.36", controla_vencimiento="1",
        ),
    )
    assert r.status_code == 303
    db_session.expire_all()
    p = db_session.scalar(select(Product))
    assert p.nombre == "Piso PVC nogal"
    assert p.stock_minimo == 24
    assert p.controla_vencimiento is True
    assert p.activo is False  # el checkbox "activo" no se envió


def test_producto_inexistente_404(client, admin):
    login(client, "dueno")
    assert client.get("/productos/999").status_code == 404
