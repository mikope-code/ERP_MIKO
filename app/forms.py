"""Lectura tolerante de campos de formulario (acepta coma decimal)."""

from datetime import date
from decimal import Decimal, InvalidOperation


def leer_decimal(
    valor: str, campo: str, errores: list[str], minimo: Decimal = Decimal("0")
) -> Decimal | None:
    try:
        d = Decimal(valor.strip().replace(",", "."))
    except (InvalidOperation, AttributeError):
        errores.append(f"{campo}: número no válido")
        return None
    if not d.is_finite() or d < minimo:
        errores.append(f"{campo}: debe ser {minimo} o mayor")
        return None
    return d


def leer_entero(valor: str, campo: str, errores: list[str], minimo: int = 0) -> int | None:
    d = leer_decimal(valor, campo, errores, Decimal(minimo))
    if d is None:
        return None
    if d != d.to_integral_value():
        errores.append(f"{campo}: debe ser un número entero")
        return None
    return int(d)


def leer_fecha(valor: str, campo: str, errores: list[str]) -> date | None:
    try:
        return date.fromisoformat(valor.strip())
    except ValueError:
        errores.append(f"{campo}: fecha no válida")
        return None
