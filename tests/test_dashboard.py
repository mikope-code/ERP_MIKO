from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from app.clock import hoy_local, rango_utc_del_dia
from app.models import Product, ProductUnit, Sale, SaleStatus, UnitKind
from app.services.dashboard import resumen
from app.services.sales import LineaPedido, anular_venta, crear_venta
from app.services.stock import ajustar_lote, registrar_entrada
from tests.conftest import login

D = Decimal
HOY = hoy_local()


@pytest.fixture()
def tienda(db_session, admin):
    def producto(sku, nombre, minimo=0, vence=False):
        p = Product(
            sku=sku, nombre=nombre, categoria="Otro", unidad_base="pieza",
            stock_minimo=minimo, controla_vencimiento=vence,
        )
        p.unidades = [
            ProductUnit(nombre="pieza", tipo=UnitKind.BASE, piezas_por_unidad=1, precio_lista=D("10")),
        ]
        db_session.add(p)
        return p

    piso = producto("PISO", "Piso PVC", minimo=10)
    clip = producto("CLIP", "Clips", minimo=0)
    peg = producto("PEG", "Pegamento", vence=True)
    db_session.commit()
    return piso, clip, peg


def entrada(db, producto, cantidad, user, vence=None):
    registrar_entrada(
        db, producto, producto.unidades[0], cantidad, user, vencimiento=vence, hoy=HOY
    )


# --- Reloj ----------------------------------------------------------------

def test_rango_del_dia_lima_es_utc_menos_5():
    inicio, fin = rango_utc_del_dia(date(2026, 10, 14))
    assert inicio == datetime(2026, 10, 14, 5, 0)
    assert fin == datetime(2026, 10, 15, 5, 0)


# --- Stock bajo -----------------------------------------------------------

def test_stock_bajo_incluye_agotados_y_ordena_por_gravedad(db_session, admin, tienda):
    piso, clip, peg = tienda
    entrada(db_session, piso, 4, admin)   # 4 <= 10 → bajo
    entrada(db_session, clip, 50, admin)  # 50 > 0 → ok
    db_session.commit()
    r = resumen(db_session, HOY)
    nombres = [(b.producto.nombre, b.stock) for b in r.stock_bajo]
    # Pegamento: 0 <= 0 (agotado); Piso: 4 <= 10. Clips no aparece.
    assert ("Clips", 50) not in nombres
    assert ("Piso PVC", 4) in nombres
    assert ("Pegamento", 0) in nombres


def test_stock_en_el_minimo_cuenta_como_bajo(db_session, admin, tienda):
    piso, _, _ = tienda
    entrada(db_session, piso, 10, admin)
    db_session.commit()
    assert "Piso PVC" in [b.producto.nombre for b in resumen(db_session, HOY).stock_bajo]


def test_producto_inactivo_no_alerta(db_session, admin, tienda):
    piso, _, _ = tienda
    piso.activo = False
    db_session.commit()
    assert "Piso PVC" not in [b.producto.nombre for b in resumen(db_session, HOY).stock_bajo]


# --- Vencimientos ---------------------------------------------------------

def test_vencidos_y_por_vencer(db_session, admin, tienda):
    _, _, peg = tienda
    entrada(db_session, peg, 3, admin, vence=HOY + timedelta(days=10))
    entrada(db_session, peg, 4, admin, vence=HOY + timedelta(days=100))  # fuera del aviso
    entrada(db_session, peg, 5, admin, vence=HOY + timedelta(days=1))
    db_session.commit()

    # Pasan 2 días: el lote de +1 ya venció, el de +10 sigue por vencer
    r = resumen(db_session, HOY + timedelta(days=2))
    assert [(a.cantidad, a.dias) for a in r.vencidos] == [(5, -1)]
    assert [(a.cantidad, a.dias) for a in r.por_vencer] == [(3, 8)]


def test_lote_vacio_no_alerta(db_session, admin, tienda):
    from sqlalchemy import select
    from app.models import StockLot
    _, _, peg = tienda
    entrada(db_session, peg, 3, admin, vence=HOY + timedelta(days=5))
    ajustar_lote(db_session, db_session.scalar(select(StockLot)), 0, admin, "Se acabó")
    db_session.commit()
    assert resumen(db_session, HOY).por_vencer == []


def test_vence_hoy_aparece_como_por_vencer(db_session, admin, tienda):
    _, _, peg = tienda
    entrada(db_session, peg, 3, admin, vence=HOY)
    db_session.commit()
    r = resumen(db_session, HOY)
    assert [a.dias for a in r.por_vencer] == [0]
    assert r.vencidos == []


# --- Ventas del día -------------------------------------------------------

def test_ventas_del_dia_suma_y_excluye_anuladas(db_session, admin, tienda):
    piso, _, _ = tienda
    entrada(db_session, piso, 100, admin)
    db_session.commit()
    u = piso.unidades[0].id
    crear_venta(db_session, admin, None, [LineaPedido(u, 2)])
    crear_venta(db_session, admin, None, [LineaPedido(u, 3)])
    v3 = crear_venta(db_session, admin, None, [LineaPedido(u, 5)])
    anular_venta(db_session, v3, admin, "Error")
    db_session.commit()

    v = resumen(db_session, HOY).ventas
    assert (v.cantidad, v.total, v.anuladas) == (2, D("50.00"), 1)


def test_ventas_de_otro_dia_no_cuentan(db_session, admin, tienda):
    piso, _, _ = tienda
    entrada(db_session, piso, 10, admin)
    db_session.commit()
    venta = crear_venta(db_session, admin, None, [LineaPedido(piso.unidades[0].id, 1)])
    venta.fecha = venta.fecha - timedelta(days=1)
    db_session.commit()
    assert resumen(db_session, HOY).ventas.cantidad == 0


def test_venta_nocturna_cuenta_en_el_dia_local(db_session, admin, tienda):
    """9 p. m. en Lima = 02:00 UTC del día siguiente: debe contar para el día de Lima."""
    piso, _, _ = tienda
    entrada(db_session, piso, 10, admin)
    db_session.commit()
    venta = crear_venta(db_session, admin, None, [LineaPedido(piso.unidades[0].id, 1)])
    inicio, fin = rango_utc_del_dia(HOY)
    venta.fecha = fin - timedelta(hours=3)  # 21:00 hora local
    db_session.commit()
    assert resumen(db_session, HOY).ventas.cantidad == 1
    assert resumen(db_session, HOY + timedelta(days=1)).ventas.cantidad == 0


def test_sin_ventas(db_session, admin):
    v = resumen(db_session, HOY).ventas
    assert (v.cantidad, v.total, v.anuladas) == (0, D("0"), 0)


# --- Pantalla ---------------------------------------------------------------

def test_inicio_muestra_panel_a_empleado(client, empleado, admin, db_session, tienda):
    piso, _, peg = tienda
    entrada(db_session, piso, 4, admin)
    entrada(db_session, peg, 2, admin, vence=HOY + timedelta(days=7))
    db_session.commit()
    crear_venta(db_session, admin, None, [LineaPedido(piso.unidades[0].id, 1)])
    db_session.commit()

    login(client, "ana")
    html = client.get("/").text
    assert "S/ 10.00" in html
    assert "1 venta" in html
    assert "Stock bajo" in html
    assert "Por vencer" in html
    assert "Piso PVC" in html


def test_inicio_sin_alertas(client, empleado, db_session):
    login(client, "ana")
    html = client.get("/").text
    assert "Todo en orden" in html
    assert "S/ 0.00" in html


def test_inicio_requiere_login(client):
    assert client.get("/").status_code == 303
