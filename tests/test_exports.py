import csv
import io
from datetime import timedelta
from decimal import Decimal

import pytest

from app.clock import hoy_local, rango_utc_del_dia
from app.csvutil import BOM, generar_csv
from app.models import Customer, Product, ProductUnit, UnitKind
from app.services.sales import LineaPedido, crear_venta
from app.services.stock import registrar_entrada
from tests.conftest import login

D = Decimal
HOY = hoy_local()


def leer(respuesta, delimitador=","):
    texto = respuesta.content.decode("utf-8")
    assert texto.startswith(BOM)
    return list(csv.DictReader(io.StringIO(texto[1:]), delimiter=delimitador))


# --- Utilidad CSV ---------------------------------------------------------

def test_bom_y_tildes():
    texto = generar_csv(["nombre"], [["Piso Ñandú"]])
    assert texto.startswith(BOM)
    assert "Piso Ñandú" in texto


@pytest.mark.parametrize("peligroso", ["=1+1", "+cmd", "-2+3", "@SUM(A1)", '=HYPERLINK("http://x","y")'])
def test_neutraliza_formulas_en_texto(peligroso):
    filas = list(csv.reader(io.StringIO(generar_csv(["c"], [[peligroso]])[1:])))
    assert filas[1][0] == "'" + peligroso


def test_numeros_negativos_no_se_alteran():
    filas = list(csv.reader(io.StringIO(generar_csv(["n"], [[-5], [D("-1.50")]])[1:])))
    assert [f[0] for f in filas[1:]] == ["-5", "-1.50"]


def test_formatos():
    from datetime import date, datetime
    filas = list(csv.reader(io.StringIO(generar_csv(
        ["d", "dt", "dec", "b", "n"],
        [[date(2026, 10, 14), datetime(2026, 10, 14, 9, 5), D("1E+2"), True, None]],
    )[1:])))
    assert filas[1] == ["2026-10-14", "2026-10-14 09:05", "100", "sí", ""]


def test_delimitador_configurable():
    texto = generar_csv(["a", "b"], [["1", "x,y"]], delimitador=";")
    assert "a;b" in texto
    assert "1;x,y" in texto  # la coma ya no necesita comillas


def test_campos_con_coma_y_comillas_se_escapan():
    filas = list(csv.reader(io.StringIO(generar_csv(["c"], [['Perez, "el" Gran']])[1:])))
    assert filas[1][0] == 'Perez, "el" Gran'


# --- Fixture ----------------------------------------------------------------

@pytest.fixture()
def tienda(db_session, admin, empleado):
    piso = Product(
        sku="PISO", nombre="Piso PVC", categoria="Piso PVC", unidad_base="pieza",
        costo=D("23.75"), stock_minimo=10, m2_por_pieza=D("0.36"),
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
    peg.unidades = [ProductUnit(nombre="unidad", tipo=UnitKind.BASE, piezas_por_unidad=1, precio_lista=D("30"))]
    clip = Product(sku="CLIP", nombre="Clips", categoria="Clips", unidad_base="unidad")
    clip.unidades = [ProductUnit(nombre="unidad", tipo=UnitKind.BASE, piezas_por_unidad=1, precio_lista=D("0.5"))]
    db_session.add_all([piso, peg, clip])
    db_session.commit()
    u = {(p.sku, x.nombre): x for p in (piso, peg, clip) for x in p.unidades}

    registrar_entrada(db_session, piso, u["PISO", "caja"], 5, empleado, costo_unidad=D("190"))
    registrar_entrada(db_session, peg, u["PEG", "unidad"], 6, empleado, vencimiento=HOY + timedelta(days=60), hoy=HOY)
    registrar_entrada(db_session, peg, u["PEG", "unidad"], 2, empleado, vencimiento=HOY + timedelta(days=1), hoy=HOY)
    db_session.commit()
    return piso, peg, clip, u


# --- Permisos ---------------------------------------------------------------

RUTAS = ["/exportar", "/exportar/productos.csv", "/exportar/stock.csv",
         "/exportar/ventas.csv", "/exportar/kardex.csv"]


def test_exportes_requieren_login(client):
    for r in RUTAS:
        assert client.get(r).status_code == 303, r


def test_empleado_no_puede_exportar(client, empleado):
    login(client, "ana")
    for r in RUTAS:
        assert client.get(r).status_code == 403, r


# --- Contenido --------------------------------------------------------------

def test_descarga_como_adjunto(client, admin, tienda):
    login(client, "dueno")
    r = client.get("/exportar/productos.csv")
    assert r.headers["content-type"].startswith("text/csv")
    assert f"erp-miko-productos-{HOY.isoformat()}.csv" in r.headers["content-disposition"]
    assert r.headers["content-disposition"].startswith("attachment")


def test_productos_una_fila_por_unidad_con_costo(client, admin, tienda):
    login(client, "dueno")
    filas = leer(client.get("/exportar/productos.csv"))
    piso = [f for f in filas if f["sku"] == "PISO"]
    assert [f["unidad_venta"] for f in piso] == ["pieza", "caja", "m²"]
    assert piso[0]["costo_por_unidad_base"] == "23.75"
    assert piso[1]["piezas_por_unidad"] == "8"
    assert piso[2]["tipo_unidad"] == "area"
    assert piso[2]["piezas_por_unidad"] == ""
    assert piso[2]["precio_lista"] == "70.00"
    assert piso[0]["m2_por_pieza"] == "0.3600"


def test_stock_por_lote_y_estado(client, admin, tienda):
    login(client, "dueno")
    filas = leer(client.get("/exportar/stock.csv"))
    por_sku = {}
    for f in filas:
        por_sku.setdefault(f["sku"], []).append(f)
    assert [(f["cantidad"], f["estado"]) for f in por_sku["PISO"]] == [("40", "sin vencimiento")]
    assert sorted(f["cantidad"] for f in por_sku["PEG"]) == ["2", "6"]
    assert {f["estado"] for f in por_sku["PEG"]} == {"vigente"}
    # producto sin existencias aparece igual, con 0
    assert [(f["cantidad"], f["estado"]) for f in por_sku["CLIP"]] == [("0", "sin stock")]


def test_ventas_una_fila_por_linea(client, admin, empleado, db_session, tienda):
    piso, _, _, u = tienda
    perez = Customer(nombre="Perez", ajuste_pct_defecto=D("10"))
    db_session.add(perez)
    db_session.commit()
    crear_venta(db_session, empleado, perez,
                [LineaPedido(u["PISO", "caja"].id, 2), LineaPedido(u["PISO", "m²"].id, 7)],
                nota="=cmd|' /C calc'!A0")
    db_session.commit()

    login(client, "dueno")
    filas = leer(client.get("/exportar/ventas.csv"))
    assert len(filas) == 2
    caja, m2 = filas
    assert (caja["venta"], caja["cliente"], caja["vendedor"], caja["estado"]) == ("1", "Perez", "Ana", "activa")
    assert (caja["cantidad_pedida"], caja["piezas"], caja["precio_unitario"], caja["subtotal"]) == (
        "2", "16", "171.00", "342.00")
    assert (m2["cantidad_pedida"], m2["piezas"], m2["cantidad_cobrada"], m2["subtotal"]) == (
        "7", "20", "7.2", "453.60")  # 7,2 m² × (70 − 10 %) = 63 → 453,60
    assert m2["nota"].startswith("'=")  # fórmula neutralizada


def test_ventas_filtro_por_fechas_locales(client, admin, empleado, db_session, tienda):
    _, _, _, u = tienda
    antigua = crear_venta(db_session, empleado, None, [LineaPedido(u["PISO", "pieza"].id, 1)])
    antigua.fecha = rango_utc_del_dia(HOY - timedelta(days=10))[0] + timedelta(hours=15)
    crear_venta(db_session, empleado, None, [LineaPedido(u["PISO", "pieza"].id, 2)])
    db_session.commit()

    login(client, "dueno")
    todas = leer(client.get("/exportar/ventas.csv"))
    assert [f["venta"] for f in todas] == ["1", "2"]
    solo_hoy = leer(client.get(f"/exportar/ventas.csv?desde={HOY.isoformat()}&hasta={HOY.isoformat()}"))
    assert [f["venta"] for f in solo_hoy] == ["2"]
    hasta_ayer = leer(client.get(f"/exportar/ventas.csv?hasta={(HOY - timedelta(days=1)).isoformat()}"))
    assert [f["venta"] for f in hasta_ayer] == ["1"]


def test_ventas_fecha_en_hora_local(client, admin, empleado, db_session, tienda):
    _, _, _, u = tienda
    v = crear_venta(db_session, empleado, None, [LineaPedido(u["PISO", "pieza"].id, 1)])
    v.fecha = rango_utc_del_dia(HOY)[0] + timedelta(hours=14, minutes=30)  # 14:30 en Lima
    db_session.commit()
    login(client, "dueno")
    assert leer(client.get("/exportar/ventas.csv"))[0]["fecha"] == f"{HOY.isoformat()} 14:30"


@pytest.mark.parametrize("query", ["desde=abc", "hasta=2026-13-45", "desde=2026-10-20&hasta=2026-10-01"])
def test_fechas_invalidas(client, admin, tienda, query):
    login(client, "dueno")
    assert client.get(f"/exportar/ventas.csv?{query}").status_code == 422
    assert client.get(f"/exportar/kardex.csv?{query}").status_code == 422


def test_kardex_incluye_costo_proveedor_y_ventas(client, admin, empleado, db_session, tienda):
    _, _, _, u = tienda
    crear_venta(db_session, empleado, None, [LineaPedido(u["PISO", "pieza"].id, 3)])
    db_session.commit()
    login(client, "dueno")
    filas = leer(client.get("/exportar/kardex.csv"))
    entrada = next(f for f in filas if f["sku"] == "PISO" and f["tipo"] == "entrada")
    assert (entrada["cantidad"], entrada["costo_unitario"]) == ("40", "23.7500")
    salida = next(f for f in filas if f["tipo"] == "salida")
    assert (salida["cantidad"], salida["referencia"], salida["usuario"]) == ("-3", "venta-1", "Ana")
    assert len(filas) == 4  # 3 entradas + 1 salida


def test_pagina_de_exportes(client, admin):
    login(client, "dueno")
    html = client.get("/exportar").text
    for ruta in RUTAS[1:]:
        assert ruta in html


def test_delimitador_desde_configuracion(client, admin, tienda, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "csv_delimiter", ";")
    login(client, "dueno")
    r = client.get("/exportar/stock.csv")
    assert "PISO" in {f["sku"] for f in leer(r, ";")}
