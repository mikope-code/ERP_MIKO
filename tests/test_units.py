from decimal import Decimal

import pytest

from app.models import Product, ProductUnit, UnitKind
from app.services.units import (
    CantidadInvalida,
    a_piezas,
    desglosar_en_cajas,
    m2_de_piezas,
)


@pytest.fixture()
def piso():
    """Piso PVC: lama de 0,36 m², caja de 8 lamas (2,88 m²)."""
    p = Product(
        id=1, sku="PISO-1", nombre="Piso PVC roble", categoria="Piso PVC",
        unidad_base="pieza", m2_por_pieza=Decimal("0.36"),
    )
    pieza = ProductUnit(id=1, product_id=1, nombre="pieza", tipo=UnitKind.BASE, piezas_por_unidad=1)
    caja = ProductUnit(id=2, product_id=1, nombre="caja", tipo=UnitKind.CAJA, piezas_por_unidad=8)
    m2 = ProductUnit(id=3, product_id=1, nombre="m²", tipo=UnitKind.AREA, piezas_por_unidad=1)
    return p, pieza, caja, m2


def test_pieza(piso):
    p, pieza, _, _ = piso
    assert a_piezas(p, pieza, 5) == 5


def test_caja(piso):
    p, _, caja, _ = piso
    assert a_piezas(p, caja, 2) == 16


def test_m2_exacto_no_redondea(piso):
    p, _, _, m2 = piso
    assert a_piezas(p, m2, Decimal("3.6")) == 10  # 3,6 / 0,36 = 10


def test_m2_redondea_hacia_arriba(piso):
    p, _, _, m2 = piso
    assert a_piezas(p, m2, 7) == 20  # 7 / 0,36 = 19,44 → 20
    assert a_piezas(p, m2, Decimal("0.01")) == 1


def test_m2_acepta_float_y_str(piso):
    p, _, _, m2 = piso
    assert a_piezas(p, m2, 0.72) == 2
    assert a_piezas(p, m2, "0.72") == 2


def test_2_cajas_mas_3_m2(piso):
    """Caso de aceptación del SPEC."""
    p, _, caja, m2 = piso
    total = a_piezas(p, caja, 2) + a_piezas(p, m2, 3)
    assert total == 16 + 9  # 3 / 0,36 = 8,33 → 9


def test_m2_entregados(piso):
    p, _, _, m2 = piso
    piezas = a_piezas(p, m2, 7)
    assert m2_de_piezas(p, piezas) == Decimal("7.20")


@pytest.mark.parametrize("qty", [0, -1, "0", "abc", None, "NaN", "Infinity"])
def test_cantidad_invalida(piso, qty):
    p, pieza, _, m2 = piso
    with pytest.raises(CantidadInvalida):
        a_piezas(p, pieza, qty)
    with pytest.raises(CantidadInvalida):
        a_piezas(p, m2, qty)


def test_no_fracciones_de_pieza_ni_caja(piso):
    p, pieza, caja, _ = piso
    with pytest.raises(CantidadInvalida):
        a_piezas(p, pieza, Decimal("1.5"))
    with pytest.raises(CantidadInvalida):
        a_piezas(p, caja, Decimal("0.5"))


def test_decimal_entero_se_acepta(piso):
    p, pieza, _, _ = piso
    assert a_piezas(p, pieza, Decimal("3.0")) == 3


def test_m2_sin_dato_de_cobertura(piso):
    p, _, _, m2 = piso
    p.m2_por_pieza = None
    with pytest.raises(CantidadInvalida):
        a_piezas(p, m2, 5)


def test_unidad_de_otro_producto(piso):
    p, _, _, _ = piso
    ajena = ProductUnit(id=9, product_id=99, nombre="pieza", tipo=UnitKind.BASE, piezas_por_unidad=1)
    with pytest.raises(CantidadInvalida):
        a_piezas(p, ajena, 1)


def test_desglose_en_cajas():
    assert desglosar_en_cajas(25, 8) == (3, 1)
    assert desglosar_en_cajas(7, 8) == (0, 7)
    with pytest.raises(CantidadInvalida):
        desglosar_en_cajas(5, 0)
