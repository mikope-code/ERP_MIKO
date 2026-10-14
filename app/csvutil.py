"""Generación de CSV que Excel abre bien y que no ejecuta fórmulas ajenas."""

import csv
import io
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from decimal import Decimal

# Excel interpreta como fórmula toda celda de texto que empieza con estos
# caracteres. Notas o nombres con "=HYPERLINK(...)" serían ejecutados al abrir.
_INICIOS_PELIGROSOS = ("=", "+", "-", "@", "\t", "\r")

BOM = "﻿"  # sin él, Excel en Windows rompe tildes y la ñ


def _celda(valor: object) -> str:
    if valor is None:
        return ""
    if isinstance(valor, bool):
        return "sí" if valor else "no"
    if isinstance(valor, str):
        if valor.startswith(_INICIOS_PELIGROSOS):
            return "'" + valor
        return valor
    if isinstance(valor, Decimal):
        return format(valor, "f")  # nunca notación científica
    if isinstance(valor, datetime):
        return valor.strftime("%Y-%m-%d %H:%M")
    if isinstance(valor, date):
        return valor.isoformat()
    return str(valor)  # int y demás: los negativos numéricos no se tocan


def generar_csv(
    encabezados: Sequence[str],
    filas: Iterable[Sequence[object]],
    delimitador: str = ",",
) -> str:
    salida = io.StringIO()
    escritor = csv.writer(salida, delimiter=delimitador, lineterminator="\r\n")
    escritor.writerow(encabezados)
    for fila in filas:
        escritor.writerow([_celda(v) for v in fila])
    return BOM + salida.getvalue()
