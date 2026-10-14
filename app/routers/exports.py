from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from app.auth import AdminUser
from app.clock import hoy_local
from app.config import settings
from app.csvutil import generar_csv
from app.db import get_db
from app.forms import leer_fecha
from app.services import exports as datos
from app.templating import templates

# Solo el administrador: los exportes incluyen costos y todo el historial.
router = APIRouter(prefix="/exportar")
DB = Annotated[Session, Depends(get_db)]


def _csv(nombre: str, encabezados, filas) -> Response:
    contenido = generar_csv(encabezados, filas, settings.csv_delimiter)
    archivo = f"erp-miko-{nombre}-{hoy_local().isoformat()}.csv"
    return Response(
        content=contenido.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{archivo}"'},
    )


def _rango(desde: str, hasta: str) -> tuple[date | None, date | None, list[str]]:
    errores: list[str] = []
    d = leer_fecha(desde, "Desde", errores) if desde.strip() else None
    h = leer_fecha(hasta, "Hasta", errores) if hasta.strip() else None
    if d and h and d > h:
        errores.append("La fecha 'Desde' no puede ser posterior a 'Hasta'")
    return d, h, errores


@router.get("", response_class=HTMLResponse)
def pagina(request: Request, user: AdminUser):
    return templates.TemplateResponse(
        request, "exports/index.html", {"app_name": settings.app_name, "user": user}
    )


@router.get("/productos.csv")
def productos(user: AdminUser, db: DB):
    return _csv("productos", *datos.productos(db))


@router.get("/stock.csv")
def stock(user: AdminUser, db: DB):
    return _csv("stock", *datos.stock(db))


@router.get("/ventas.csv")
def ventas(
    user: AdminUser,
    db: DB,
    desde: Annotated[str, Query()] = "",
    hasta: Annotated[str, Query()] = "",
):
    d, h, errores = _rango(desde, hasta)
    if errores:
        return Response("\n".join(errores), status_code=422, media_type="text/plain; charset=utf-8")
    return _csv("ventas", *datos.ventas(db, d, h))


@router.get("/kardex.csv")
def kardex(
    user: AdminUser,
    db: DB,
    desde: Annotated[str, Query()] = "",
    hasta: Annotated[str, Query()] = "",
):
    d, h, errores = _rango(desde, hasta)
    if errores:
        return Response("\n".join(errores), status_code=422, media_type="text/plain; charset=utf-8")
    return _csv("kardex", *datos.kardex(db, d, h))
