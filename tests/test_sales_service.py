from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import (
    Customer,
    CustomerUnitPrice,
    Product,
    ProductUnit,
    Role,
    SaleStatus,
    StockLot,
    StockMovement,
    UnitKind,
)
from app.services.sales import (
    LineaPedido,
    VentaError,
    anular_venta,
    crear_venta,
    faltantes,
    calcular_lineas,
)
from app.services.stock import (
    StockInsuficiente,
    registrar_entrada,
    stock_segun_kardex,
    stock_total,
)
from tests.conftest import make_user

D = Decimal
HOY = date.today()


@pytest.fixture()
def empleado_u(db_session):
    return make_user(db_session, "ana", Role.EMPLEADO)


@pytest.fixture()
def admin_u(db_session):
    return make_user(db_session, "dueno", Role.ADMIN)


@pytest.fixture()
def tienda(db_session, empleado_u):
    """Piso (0,36 m²/pieza, caja de 8) con 5 cajas, y pegamento con 2 lotes."""
    piso = Product(
        sku="PISO", nombre="Piso PVC", categoria="Piso PVC", unidad_base="pieza",
        m2_por_pieza=D("0.36"),
    )
    piso.unidades = [
        ProductUnit(nombre="pieza", tipo=UnitKind.BASE, piezas_por_unidad=1, precio_lista=D("25")),
        ProductUnit(nombre="caja", tipo=UnitKind.CAJA, piezas_por_unidad=8, precio_lista=D("190")),
        ProductUnit(nombre="m²", tipo=UnitKind.AREA, piezas_por_unidad=1, precio_lista=D("70")),
    ]
    peg = Product(
        sku="PEG", nombre="Pegamento", categoria="Pegamento", unidad_base="unidad",
        controla_vencimiento=True,
    )
    peg.unidades = [
        ProductUnit(nombre="unidad", tipo=UnitKind.BASE, piezas_por_unidad=1, precio_lista=D("30")),
    ]
    db_session.add_all([piso, peg])
    db_session.commit()
    u = {(p.sku, x.nombre): x for p in (piso, peg) for x in p.unidades}

    registrar_entrada(db_session, piso, u["PISO", "caja"], 5, empleado_u)  # 40 piezas
    registrar_entrada(db_session, peg, u["PEG", "unidad"], 3, empleado_u,
                      vencimiento=HOY + timedelta(days=20), hoy=HOY)
    registrar_entrada(db_session, peg, u["PEG", "unidad"], 10, empleado_u,
                      vencimiento=HOY + timedelta(days=200), hoy=HOY)
    db_session.commit()
    return piso, peg, u


def test_venta_simple_en_cajas(db_session, tienda, empleado_u):
    piso, _, u = tienda
    venta = crear_venta(db_session, empleado_u, None, [LineaPedido(u["PISO", "caja"].id, 2)])
    db_session.commit()

    assert venta.total == D("380.00")
    assert venta.estado is SaleStatus.ACTIVA
    linea = venta.lineas[0]
    assert (linea.cantidad_base, linea.precio_unitario, linea.subtotal) == (16, D("190.00"), D("380.00"))
    assert stock_total(db_session, piso.id) == 24


def test_2_cajas_mas_3_m2_criterio_de_aceptacion(db_session, tienda, empleado_u):
    piso, _, u = tienda
    venta = crear_venta(
        db_session, empleado_u, None,
        [LineaPedido(u["PISO", "caja"].id, 2), LineaPedido(u["PISO", "m²"].id, 3)],
    )
    db_session.commit()
    # 16 piezas + ceil(3 / 0,36) = 9 piezas
    assert [l.cantidad_base for l in venta.lineas] == [16, 9]
    assert stock_total(db_session, piso.id) == 40 - 25
    # m²: 9 piezas * 0,36 = 3,24 m² entregados, cobrados a S/ 70 = 226,80
    m2 = venta.lineas[1]
    assert m2.cantidad_cobrada == D("3.24")
    assert m2.subtotal == D("226.80")
    assert venta.total == D("380.00") + D("226.80")


def test_m2_se_cobra_por_piezas_completas(db_session, tienda, empleado_u):
    _, _, u = tienda
    venta = crear_venta(db_session, empleado_u, None, [LineaPedido(u["PISO", "m²"].id, 7)])
    l = venta.lineas[0]
    assert l.cantidad_pedida == D("7")
    assert l.cantidad_base == 20            # 19,44 → 20
    assert l.cantidad_cobrada == D("7.20")  # lo realmente entregado
    assert l.subtotal == D("504.00")        # 7,20 * 70


def test_precio_segun_cliente(db_session, tienda, empleado_u):
    _, _, u = tienda
    perez = Customer(nombre="Perez", ajuste_pct_defecto=D("10"))
    lopez = Customer(nombre="Lopez", ajuste_pct_defecto=D("-10"))
    db_session.add_all([perez, lopez])
    db_session.commit()
    a = crear_venta(db_session, empleado_u, perez, [LineaPedido(u["PISO", "caja"].id, 1)])
    b = crear_venta(db_session, empleado_u, lopez, [LineaPedido(u["PISO", "caja"].id, 1)])
    assert (a.total, b.total) == (D("171.00"), D("209.00"))
    assert a.lineas[0].ajuste_pct == D("10.00")
    assert a.customer_id == perez.id


def test_precio_especial_del_cliente(db_session, tienda, empleado_u):
    _, _, u = tienda
    c = Customer(nombre="Perez", ajuste_pct_defecto=D("10"))
    db_session.add(c)
    db_session.commit()
    db_session.add(CustomerUnitPrice(customer_id=c.id, unit_id=u["PISO", "caja"].id, precio=D("150")))
    db_session.commit()
    venta = crear_venta(db_session, empleado_u, c, [LineaPedido(u["PISO", "caja"].id, 2)])
    assert venta.total == D("300.00")


def test_historial_conserva_precio_aunque_cambie_la_lista(db_session, tienda, empleado_u):
    _, _, u = tienda
    venta = crear_venta(db_session, empleado_u, None, [LineaPedido(u["PISO", "caja"].id, 1)])
    db_session.commit()
    u["PISO", "caja"].precio_lista = D("250")
    db_session.commit()
    db_session.refresh(venta)
    assert venta.lineas[0].precio_unitario == D("190.00")
    assert venta.total == D("190.00")


def test_empleado_no_puede_fijar_precio(db_session, tienda, empleado_u):
    _, _, u = tienda
    with pytest.raises(VentaError, match="administrador"):
        crear_venta(
            db_session, empleado_u, None,
            [LineaPedido(u["PISO", "caja"].id, 1, precio_manual=D("1"))],
        )


def test_admin_fija_precio_manual(db_session, tienda, admin_u):
    _, _, u = tienda
    venta = crear_venta(
        db_session, admin_u, None,
        [LineaPedido(u["PISO", "caja"].id, 2, precio_manual=D("175.50"))],
    )
    l = venta.lineas[0]
    assert l.precio_manual is True
    assert (l.precio_unitario, l.subtotal, l.precio_lista) == (D("175.50"), D("351.00"), D("190.00"))
    assert l.ajuste_pct == D("7.63")  # (190 − 175,5) / 190


def test_venta_usa_fefo_y_marca_el_kardex(db_session, tienda, empleado_u):
    _, peg, u = tienda
    venta = crear_venta(db_session, empleado_u, None, [LineaPedido(u["PEG", "unidad"].id, 5)])
    db_session.commit()
    movs = db_session.scalars(
        select(StockMovement).where(StockMovement.referencia == f"venta-{venta.id}")
    ).all()
    por_venc = {m.lote.fecha_vencimiento: m.cantidad_base for m in movs}
    assert por_venc == {HOY + timedelta(days=20): -3, HOY + timedelta(days=200): -2}


def test_stock_insuficiente_no_deja_nada_a_medias(db_session, tienda, empleado_u):
    piso, peg, u = tienda
    antes = (stock_total(db_session, piso.id), stock_total(db_session, peg.id))
    with pytest.raises(StockInsuficiente):
        # la primera línea sí alcanza; la segunda no
        crear_venta(
            db_session, empleado_u, None,
            [LineaPedido(u["PISO", "caja"].id, 1), LineaPedido(u["PEG", "unidad"].id, 99)],
        )
    db_session.rollback()
    assert (stock_total(db_session, piso.id), stock_total(db_session, peg.id)) == antes
    from app.models import Sale
    assert db_session.scalar(select(Sale)) is None


def test_varias_lineas_del_mismo_producto_se_suman_en_stock(db_session, tienda, empleado_u):
    piso, _, u = tienda  # 40 piezas
    # 4 cajas (32) + 9 piezas = 41 > 40
    with pytest.raises(StockInsuficiente):
        crear_venta(
            db_session, empleado_u, None,
            [LineaPedido(u["PISO", "caja"].id, 4), LineaPedido(u["PISO", "pieza"].id, 9)],
        )
    db_session.rollback()


def test_faltantes_avisa_en_la_vista_previa(db_session, tienda, empleado_u):
    _, _, u = tienda
    lineas = calcular_lineas(
        db_session, empleado_u, None,
        [LineaPedido(u["PISO", "caja"].id, 4), LineaPedido(u["PISO", "pieza"].id, 9)],
    )
    avisos = faltantes(db_session, lineas)
    assert len(avisos) == 1
    assert "Piso PVC" in avisos[0] and "41" in avisos[0] and "40" in avisos[0]


@pytest.mark.parametrize("cantidad", [0, -1, "abc", "1.5"])
def test_cantidad_invalida(db_session, tienda, empleado_u, cantidad):
    _, _, u = tienda
    with pytest.raises(VentaError):
        crear_venta(db_session, empleado_u, None, [LineaPedido(u["PISO", "pieza"].id, cantidad)])


def test_venta_vacia_o_unidad_inexistente(db_session, tienda, empleado_u):
    with pytest.raises(VentaError):
        crear_venta(db_session, empleado_u, None, [])
    with pytest.raises(VentaError):
        crear_venta(db_session, empleado_u, None, [LineaPedido(9999, 1)])


def test_cliente_inactivo_o_producto_inactivo(db_session, tienda, empleado_u):
    piso, _, u = tienda
    c = Customer(nombre="Baja", activo=False)
    db_session.add(c)
    db_session.commit()
    with pytest.raises(VentaError, match="inactivo"):
        crear_venta(db_session, empleado_u, c, [LineaPedido(u["PISO", "pieza"].id, 1)])
    piso.activo = False
    db_session.commit()
    with pytest.raises(VentaError, match="inactivo"):
        crear_venta(db_session, empleado_u, None, [LineaPedido(u["PISO", "pieza"].id, 1)])


def test_anular_repone_stock_en_los_mismos_lotes(db_session, tienda, empleado_u, admin_u):
    piso, peg, u = tienda
    lotes_antes = {l.id: l.cantidad_base for l in db_session.scalars(select(StockLot))}
    venta = crear_venta(
        db_session, empleado_u, None,
        [LineaPedido(u["PEG", "unidad"].id, 5), LineaPedido(u["PISO", "caja"].id, 2)],
    )
    db_session.commit()
    assert {l.id: l.cantidad_base for l in db_session.scalars(select(StockLot))} != lotes_antes

    anular_venta(db_session, venta, admin_u, "Cliente se arrepintió")
    db_session.commit()

    assert {l.id: l.cantidad_base for l in db_session.scalars(select(StockLot))} == lotes_antes
    assert venta.estado is SaleStatus.ANULADA
    assert venta.anulada_por_id == admin_u.id
    assert venta.motivo_anulacion == "Cliente se arrepintió"
    for p in (piso, peg):
        assert stock_total(db_session, p.id) == stock_segun_kardex(db_session, p.id)


def test_anular_solo_admin_con_motivo_y_una_vez(db_session, tienda, empleado_u, admin_u):
    _, _, u = tienda
    venta = crear_venta(db_session, empleado_u, None, [LineaPedido(u["PISO", "pieza"].id, 1)])
    db_session.commit()
    with pytest.raises(VentaError, match="administrador"):
        anular_venta(db_session, venta, empleado_u, "x")
    with pytest.raises(VentaError, match="motivo"):
        anular_venta(db_session, venta, admin_u, "  ")
    anular_venta(db_session, venta, admin_u, "Error de digitación")
    with pytest.raises(VentaError, match="ya está anulada"):
        anular_venta(db_session, venta, admin_u, "otra vez")
    assert stock_total(db_session, venta.lineas[0].producto.id) == 40
