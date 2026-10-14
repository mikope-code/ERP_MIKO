from decimal import Decimal

import pytest

from app.models import (
    Customer,
    CustomerProductAdjustment,
    CustomerUnitPrice,
    Product,
    ProductUnit,
    UnitKind,
)
from app.services.pricing import Origen, calcular_precio, resolver_precio

D = Decimal


# --- Función pura: prioridad ---------------------------------------------

def test_sin_nada_es_precio_de_lista():
    r = resolver_precio(D("100"))
    assert (r.precio_final, r.origen, r.ajuste_pct) == (D("100.00"), Origen.LISTA, D("0.00"))


def test_ajuste_general_del_cliente():
    r = resolver_precio(D("100"), ajuste_cliente=D("10"))
    assert r.precio_final == D("90.00")
    assert r.origen is Origen.AJUSTE_CLIENTE
    assert r.ajuste_pct == D("10.00")


def test_ajuste_del_producto_gana_al_general():
    r = resolver_precio(D("100"), ajuste_producto=D("20"), ajuste_cliente=D("10"))
    assert r.precio_final == D("80.00")
    assert r.origen is Origen.AJUSTE_PRODUCTO


def test_precio_especial_gana_a_todo():
    r = resolver_precio(
        D("100"), precio_especial=D("70"), ajuste_producto=D("20"), ajuste_cliente=D("10")
    )
    assert r.precio_final == D("70.00")
    assert r.origen is Origen.PRECIO_ESPECIAL
    assert r.ajuste_pct == D("30.00")


def test_recargo_con_ajuste_negativo():
    r = resolver_precio(D("100"), ajuste_cliente=D("-15"))
    assert r.precio_final == D("115.00")
    assert r.ajuste_pct == D("-15.00")


def test_ajuste_producto_cero_anula_el_descuento_general():
    """Un 0 % explícito en el producto significa 'a este cliente, este producto va a lista'."""
    r = resolver_precio(D("100"), ajuste_producto=D("0"), ajuste_cliente=D("10"))
    assert r.precio_final == D("100.00")
    assert r.origen is Origen.AJUSTE_PRODUCTO


def test_precio_especial_cero_es_valido():
    r = resolver_precio(D("100"), precio_especial=D("0"), ajuste_cliente=D("10"))
    assert r.precio_final == D("0.00")
    assert r.origen is Origen.PRECIO_ESPECIAL


def test_descuento_total():
    assert resolver_precio(D("50"), ajuste_cliente=D("100")).precio_final == D("0.00")


def test_redondeo_al_centavo_half_up():
    # 25.50 * 0.95 = 24.225 → 24.23
    assert resolver_precio(D("25.50"), ajuste_cliente=D("5")).precio_final == D("24.23")
    # 10.05 * 0.90 = 9.045 → 9.05
    assert resolver_precio(D("10.05"), ajuste_cliente=D("10")).precio_final == D("9.05")


def test_lista_cero_no_divide_por_cero():
    r = resolver_precio(D("0"), ajuste_cliente=D("10"))
    assert r.precio_final == D("0.00")
    assert r.ajuste_pct == D("0.00")


# --- Con base de datos ----------------------------------------------------

@pytest.fixture()
def datos(db_session):
    piso = Product(sku="PISO", nombre="Piso", categoria="Piso PVC", unidad_base="pieza")
    clip = Product(sku="CLIP", nombre="Clip", categoria="Clips", unidad_base="unidad")
    piso.unidades = [
        ProductUnit(nombre="pieza", tipo=UnitKind.BASE, piezas_por_unidad=1, precio_lista=D("25")),
        ProductUnit(nombre="caja", tipo=UnitKind.CAJA, piezas_por_unidad=8, precio_lista=D("190")),
    ]
    clip.unidades = [
        ProductUnit(nombre="unidad", tipo=UnitKind.BASE, piezas_por_unidad=1, precio_lista=D("0.50")),
    ]
    cliente = Customer(nombre="Constructora Perez", ajuste_pct_defecto=D("5"))
    db_session.add_all([piso, clip, cliente])
    db_session.commit()
    u = {(p.sku, x.nombre): x for p in (piso, clip) for x in p.unidades}
    return piso, clip, cliente, u


def test_mostrador_paga_lista(db_session, datos):
    _, _, _, u = datos
    r = calcular_precio(db_session, None, u["PISO", "caja"])
    assert r.precio_final == D("190.00")
    assert r.origen is Origen.LISTA


def test_cliente_con_ajuste_general(db_session, datos):
    _, _, cliente, u = datos
    r = calcular_precio(db_session, cliente, u["PISO", "caja"])
    assert r.precio_final == D("180.50")
    assert r.origen is Origen.AJUSTE_CLIENTE


def test_dos_clientes_distintos_precio_distinto(db_session, datos):
    """Criterio de aceptación del SPEC."""
    _, _, perez, u = datos
    otro = Customer(nombre="Ferreteria Lopez", ajuste_pct_defecto=D("-10"))
    db_session.add(otro)
    db_session.commit()
    a = calcular_precio(db_session, perez, u["PISO", "caja"]).precio_final
    b = calcular_precio(db_session, otro, u["PISO", "caja"]).precio_final
    assert (a, b) == (D("180.50"), D("209.00"))


def test_ajuste_por_producto_aplica_a_todas_sus_unidades(db_session, datos):
    piso, _, cliente, u = datos
    db_session.add(CustomerProductAdjustment(customer_id=cliente.id, product_id=piso.id, ajuste_pct=D("20")))
    db_session.commit()
    assert calcular_precio(db_session, cliente, u["PISO", "caja"]).precio_final == D("152.00")
    assert calcular_precio(db_session, cliente, u["PISO", "pieza"]).precio_final == D("20.00")
    # otro producto sigue con el ajuste general
    assert calcular_precio(db_session, cliente, u["CLIP", "unidad"]).origen is Origen.AJUSTE_CLIENTE


def test_precio_especial_solo_afecta_su_unidad(db_session, datos):
    piso, _, cliente, u = datos
    db_session.add(CustomerProductAdjustment(customer_id=cliente.id, product_id=piso.id, ajuste_pct=D("20")))
    db_session.add(CustomerUnitPrice(customer_id=cliente.id, unit_id=u["PISO", "caja"].id, precio=D("150")))
    db_session.commit()
    caja = calcular_precio(db_session, cliente, u["PISO", "caja"])
    pieza = calcular_precio(db_session, cliente, u["PISO", "pieza"])
    assert (caja.precio_final, caja.origen) == (D("150.00"), Origen.PRECIO_ESPECIAL)
    assert (pieza.precio_final, pieza.origen) == (D("20.00"), Origen.AJUSTE_PRODUCTO)


def test_ajustes_de_otro_cliente_no_se_filtran(db_session, datos):
    piso, _, cliente, u = datos
    otro = Customer(nombre="Otro")
    db_session.add(otro)
    db_session.commit()
    db_session.add(CustomerUnitPrice(customer_id=otro.id, unit_id=u["PISO", "caja"].id, precio=D("1")))
    db_session.commit()
    assert calcular_precio(db_session, cliente, u["PISO", "caja"]).precio_final == D("180.50")
