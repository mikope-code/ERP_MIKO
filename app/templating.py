from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.templating import Jinja2Templates

from app.config import settings
from app.models import Product, UnitKind

BASE_DIR = Path(__file__).resolve().parent

templates = Jinja2Templates(directory=BASE_DIR / "templates")

_tz = ZoneInfo(settings.timezone)


def _local(valor: datetime | None) -> str:
    """Las fechas se guardan en UTC sin zona; se muestran en hora local."""
    if valor is None:
        return ""
    return valor.replace(tzinfo=timezone.utc).astimezone(_tz).strftime("%d/%m/%Y %H:%M")


def texto_stock(producto: Product, piezas: int) -> str:
    """'3 caja + 1 pieza (25 pieza)' o simplemente '25 pieza'."""
    base = producto.unidad_base
    caja = producto.unidad_de_tipo(UnitKind.CAJA)
    if caja is None or piezas < caja.piezas_por_unidad:
        return f"{piezas} {base}"
    cajas, sueltas = divmod(piezas, caja.piezas_por_unidad)
    partes = f"{cajas} {caja.nombre}" + (f" + {sueltas} {base}" if sueltas else "")
    return f"{partes} ({piezas} {base})"


templates.env.filters["local"] = _local
templates.env.globals["texto_stock"] = texto_stock
