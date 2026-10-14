"""Fecha y hora del negocio.

Las marcas de tiempo se guardan en UTC, pero "hoy" para la tienda es el día
de su zona horaria (ERP_TIMEZONE, por defecto America/Lima).
"""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.config import settings

_tz = ZoneInfo(settings.timezone)


def hoy_local() -> date:
    return datetime.now(_tz).date()


def rango_utc_del_dia(dia: date) -> tuple[datetime, datetime]:
    """[inicio, fin) del día local expresado como datetimes UTC sin zona,
    que es como se guardan en la base de datos."""
    inicio = datetime.combine(dia, time.min, tzinfo=_tz)
    fin = datetime.combine(dia + timedelta(days=1), time.min, tzinfo=_tz)

    def a_utc(dt: datetime) -> datetime:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)

    return a_utc(inicio), a_utc(fin)
