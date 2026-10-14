from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import (
    MovementType,
    Product,
    ProductUnit,
    Role,
    StockLot,
    StockMovement,
    Supplier,
    UnitKind,
)
from app.services.stock import (
    StockError,
    StockInsuficiente,
    ajustar_lote,
    registrar_entrada,
    registrar_salida,
    stock_segun_kardex,
    stock_total,
    stock_vendible,
)
from app.services.units import CantidadInvalida
from tests.conftest import make_user

HOY = date(2026, 10, 14)


@pytest.fixture()
def user(db_session):
    return make_user(db_session, "ana", Role.EMPLEADO)


def _producto(db, sku, nombre, **kw):
    p = Product(sku=sku, nombre=nombre, categoria="Otro", unidad_base="pieza", **kw)
    p.unidades = [
        ProductUnit(nombre="pieza", tipo=UnitKind.BASE, piezas_por_unidad=1),
        ProductUnit(nombre="caja", tipo=UnitKind.CAJA, piezas_por_unidad=8),
    ]
    db.add(p)
    db.commit()
    return p


@pytest.fixture()
def piso(db_session):
    p = _producto(db_session, "PISO", "Piso PVC", m2_por_pieza=Decimal("0.36"))
    p.unidades.append(ProductUnit(nombre="m²", tipo=UnitKind.AREA, piezas_por_unidad=1))
    db_session.commit()
    return p


@pytest.fixture()
def pegamento(db_session):
    return _producto(db_session, "PEG", "Pegamento", controla_vencimiento=True)


def u(producto, nombre):
    return next(x for x in producto.unidades if x.nombre == nombre)


def test_entrada_en_cajas_suma_piezas(db_session, piso, user):
    mov = registrar_entrada(db_session, piso, u(piso, "caja"), 3, user)
    assert mov.cantidad_base == 24
    assert mov.tipo is MovementType.ENTRADA
    assert stock_total(db_session, piso.id) == 24


def test_entradas_sin_vencimiento_comparten_un_lote(db_session, piso, user):
    registrar_entrada(db_session, piso, u(piso, "pieza"), 5, user)
    registrar_entrada(db_session, piso, u(piso, "caja"), 1, user)
    lotes = db_session.scalars(select(StockLot)).all()
    assert len(lotes) == 1
    assert lotes[0].cantidad_base == 13


def test_entrada_en_m2_rechazada(db_session, piso, user):
    with pytest.raises(StockError):
        registrar_entrada(db_session, piso, u(piso, "m²"), 5, user)


def test_entrada_fraccion_rechazada(db_session, piso, user):
    with pytest.raises(CantidadInvalida):
        registrar_entrada(db_session, piso, u(piso, "caja"), Decimal("1.5"), user)


def test_producto_con_vencimiento_exige_fecha(db_session, pegamento, user):
    with pytest.raises(StockError, match="vencimiento"):
        registrar_entrada(db_session, pegamento, u(pegamento, "pieza"), 6, user, hoy=HOY)


def test_vencimiento_pasado_rechazado(db_session, pegamento, user):
    with pytest.raises(StockError, match="pasó"):
        registrar_entrada(
            db_session, pegamento, u(pegamento, "pieza"), 6, user,
            vencimiento=HOY - timedelta(days=1), hoy=HOY,
        )


def test_vencimiento_se_ignora_si_no_aplica(db_session, piso, user):
    registrar_entrada(
        db_session, piso, u(piso, "pieza"), 4, user, vencimiento=HOY + timedelta(days=5)
    )
    assert db_session.scalar(select(StockLot)).fecha_vencimiento is None


def test_lotes_por_fecha_de_vencimiento(db_session, pegamento, user):
    v1, v2 = HOY + timedelta(days=30), HOY + timedelta(days=90)
    registrar_entrada(db_session, pegamento, u(pegamento, "pieza"), 5, user, vencimiento=v1, hoy=HOY)
    registrar_entrada(db_session, pegamento, u(pegamento, "pieza"), 7, user, vencimiento=v2, hoy=HOY)
    registrar_entrada(db_session, pegamento, u(pegamento, "pieza"), 2, user, vencimiento=v1, hoy=HOY)
    cant = {l.fecha_vencimiento: l.cantidad_base for l in db_session.scalars(select(StockLot))}
    assert cant == {v1: 7, v2: 7}


def test_costo_se_convierte_a_pieza(db_session, piso, user):
    mov = registrar_entrada(
        db_session, piso, u(piso, "caja"), 1, user, costo_unidad=Decimal("190")
    )
    assert mov.costo_unitario == Decimal("190") / 8


def test_proveedor_queda_en_el_movimiento(db_session, piso, user):
    prov = Supplier(nombre="Importadora Sur")
    db_session.add(prov)
    db_session.commit()
    mov = registrar_entrada(db_session, piso, u(piso, "pieza"), 1, user, proveedor=prov)
    assert mov.supplier_id == prov.id


def test_salida_descuenta_y_registra_kardex(db_session, piso, user):
    registrar_entrada(db_session, piso, u(piso, "caja"), 2, user)
    movs = registrar_salida(db_session, piso, 5, user, referencia="venta-1")
    assert [m.cantidad_base for m in movs] == [-5]
    assert movs[0].referencia == "venta-1"
    assert stock_total(db_session, piso.id) == 11


def test_salida_fefo_consume_primero_el_que_vence_antes(db_session, pegamento, user):
    cerca, lejos = HOY + timedelta(days=20), HOY + timedelta(days=200)
    # Se ingresa primero el que vence más tarde: FEFO no debe depender del orden de ingreso
    registrar_entrada(db_session, pegamento, u(pegamento, "pieza"), 10, user, vencimiento=lejos, hoy=HOY)
    registrar_entrada(db_session, pegamento, u(pegamento, "pieza"), 4, user, vencimiento=cerca, hoy=HOY)

    movs = registrar_salida(db_session, pegamento, 6, user, hoy=HOY)
    assert len(movs) == 2
    por_lote = {m.lote.fecha_vencimiento: m.cantidad_base for m in movs}
    assert por_lote == {cerca: -4, lejos: -2}
    restante = {l.fecha_vencimiento: l.cantidad_base for l in db_session.scalars(select(StockLot))}
    assert restante == {cerca: 0, lejos: 8}


def test_salida_no_vende_lotes_vencidos(db_session, pegamento, user):
    vencido = HOY - timedelta(days=1)
    ok = HOY + timedelta(days=60)
    registrar_entrada(db_session, pegamento, u(pegamento, "pieza"), 5, user, vencimiento=HOY + timedelta(days=1), hoy=HOY)
    registrar_entrada(db_session, pegamento, u(pegamento, "pieza"), 3, user, vencimiento=ok, hoy=HOY)

    # Pasa el tiempo: el primer lote queda vencido
    mañana = HOY + timedelta(days=2)
    assert stock_total(db_session, pegamento.id) == 8
    assert stock_vendible(db_session, pegamento.id, hoy=mañana) == 3
    with pytest.raises(StockInsuficiente) as exc:
        registrar_salida(db_session, pegamento, 4, user, hoy=mañana)
    assert exc.value.disponible == 3
    assert vencido < mañana  # sanity


def test_salida_insuficiente_no_modifica_nada(db_session, piso, user):
    registrar_entrada(db_session, piso, u(piso, "pieza"), 3, user)
    with pytest.raises(StockInsuficiente):
        registrar_salida(db_session, piso, 4, user)
    assert stock_total(db_session, piso.id) == 3
    assert len(db_session.scalars(select(StockMovement)).all()) == 1


@pytest.mark.parametrize("cantidad", [0, -3])
def test_salida_cantidad_invalida(db_session, piso, user, cantidad):
    with pytest.raises(CantidadInvalida):
        registrar_salida(db_session, piso, cantidad, user)


def test_ajuste_fija_cantidad_contada(db_session, piso, user):
    registrar_entrada(db_session, piso, u(piso, "caja"), 1, user)  # 8
    lote = db_session.scalar(select(StockLot))
    mov = ajustar_lote(db_session, lote, 5, user, "Rotura en bodega")
    assert mov.cantidad_base == -3
    assert mov.tipo is MovementType.AJUSTE
    assert stock_total(db_session, piso.id) == 5


def test_ajuste_sin_cambio_no_crea_movimiento(db_session, piso, user):
    registrar_entrada(db_session, piso, u(piso, "pieza"), 4, user)
    lote = db_session.scalar(select(StockLot))
    assert ajustar_lote(db_session, lote, 4, user, "Conteo") is None
    assert len(db_session.scalars(select(StockMovement)).all()) == 1


def test_ajuste_exige_motivo_y_no_negativo(db_session, piso, user):
    registrar_entrada(db_session, piso, u(piso, "pieza"), 4, user)
    lote = db_session.scalar(select(StockLot))
    with pytest.raises(StockError):
        ajustar_lote(db_session, lote, 2, user, "   ")
    with pytest.raises(StockError):
        ajustar_lote(db_session, lote, -1, user, "motivo")


def test_stock_siempre_igual_al_kardex(db_session, piso, pegamento, user):
    """Invariante del SPEC: stock = suma de movimientos."""
    v = HOY + timedelta(days=40)
    registrar_entrada(db_session, piso, u(piso, "caja"), 3, user)
    registrar_salida(db_session, piso, 7, user)
    registrar_entrada(db_session, pegamento, u(pegamento, "pieza"), 6, user, vencimiento=v, hoy=HOY)
    registrar_entrada(db_session, pegamento, u(pegamento, "pieza"), 6, user, vencimiento=v + timedelta(days=30), hoy=HOY)
    registrar_salida(db_session, pegamento, 9, user, hoy=HOY)
    ajustar_lote(db_session, db_session.scalar(select(StockLot).where(StockLot.product_id == piso.id)), 10, user, "Conteo")
    for p in (piso, pegamento):
        assert stock_total(db_session, p.id) == stock_segun_kardex(db_session, p.id)


def test_kardex_es_inmutable(db_session, piso, user):
    mov = registrar_entrada(db_session, piso, u(piso, "pieza"), 4, user)
    db_session.commit()
    mov.cantidad_base = 999
    with pytest.raises(ValueError, match="no se modifican"):
        db_session.commit()
    db_session.rollback()
    db_session.delete(mov)
    with pytest.raises(ValueError, match="no se modifican"):
        db_session.commit()
    db_session.rollback()
