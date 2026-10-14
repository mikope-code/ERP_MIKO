# ERP MIKO — Módulo de Inventario y Ventas (v1)

## 1. Objetivo
Sistema web simple y de costo cero para una tienda pequeña que vende wall panels, pisos PVC, clips y pegamento. Controla stock, registra ventas con precios por cliente y alerta sobre stock mínimo y vencimientos.

**Usuarios:** 1 administrador (dueño) + 2 empleados. Acceso desde PC y celular vía web.
**Escala:** ~20 productos, volumen bajo de ventas diarias.
**Fuera de alcance:** facturación electrónica / SUNAT, contabilidad, código de barras, varias bodegas, pagos y deudas.

## 2. Stack
| Capa | Tecnología |
|---|---|
| Backend | Python 3.12 + FastAPI |
| ORM / migraciones | SQLAlchemy 2 + Alembic |
| Base de datos | SQLite (desarrollo) → PostgreSQL gratuito (producción: Neon/Supabase) |
| Interfaz | Plantillas Jinja2 + HTMX + Pico CSS (responsive, sin build) |
| Auth | Sesión con cookie firmada, contraseñas con hash (argon2/bcrypt) |
| Tests | pytest |

## 3. Roles y permisos
| Acción | Admin | Empleado |
|---|---|---|
| Ver stock y productos | Sí | Sí |
| Registrar entradas/ventas | Sí | Sí |
| Ver costos y márgenes | Sí | No |
| Crear/editar productos y precios | Sí | No |
| Cambiar precio o descuento en una venta | Sí | No |
| Anular venta / ajustar stock | Sí | No |
| Gestionar clientes con descuentos | Sí | No |
| Gestionar usuarios | Sí | No |

## 4. Modelo de datos
- **users**: id, nombre, usuario, password_hash, rol (admin|empleado), activo
- **products**: id, sku, nombre, categoría, unidad_base, costo (por unidad base), stock_minimo, controla_vencimiento (bool), activo
- **product_units**: id, product_id, nombre (caja|m²|pieza|paquete), factor_a_base (cuántas unidades base equivale), precio_lista
  - Ejemplo piso PVC: base = pieza; caja = 8; m² = 2 piezas (pieza de 0,5 m²).
- **customers**: id, nombre, teléfono, descuento_pct_defecto
- **customer_prices**: customer_id, product_id (o product_unit_id), descuento_pct *o* precio_especial
- **suppliers**: id, nombre, teléfono
- **stock_lots**: id, product_id, cantidad_base, fecha_vencimiento (null si no aplica)
- **stock_movements** (kardex, solo inserción): id, product_id, lot_id, tipo (entrada|salida|ajuste|anulación), cantidad_base (+/-), referencia (venta/compra), user_id, fecha, nota
- **purchases / purchase_lines**: entradas de mercadería con proveedor y costo
- **sales**: id, customer_id, user_id, fecha, total, estado (activa|anulada)
- **sale_lines**: sale_id, product_id, unit_id, cantidad_unidad, cantidad_base, precio_lista, descuento_pct, precio_final, subtotal

## 5. Reglas de negocio
1. El stock **siempre se guarda en unidad base** (entero). No hay fracciones de pieza.
2. Venta en m² (u otra unidad no entera): se **redondea hacia arriba a piezas completas**; la línea muestra los m² realmente entregados y se cobra por las piezas.
3. Precio de línea = precio de lista de la unidad vendida, con este orden de prioridad:
   precio especial del cliente para ese producto → descuento % del cliente para ese producto → descuento % por defecto del cliente → precio de lista.
   Solo el admin puede sobrescribir el valor final en la venta.
4. Se guarda el **precio real cobrado** en cada línea; cambiar la lista después no altera ventas pasadas.
5. No se permite vender más que el stock disponible (el admin puede forzar con ajuste explícito).
6. Productos con vencimiento: la salida consume primero el lote que vence antes (FEFO). Alerta a 30 días del vencimiento (configurable).
7. Alerta de stock bajo cuando stock ≤ stock_minimo.
8. Anular una venta repone el stock mediante un movimiento de anulación; los movimientos nunca se editan ni borran.
9. Toda operación registra usuario y fecha.

## 6. Pantallas
1. Login
2. Panel: stock bajo, próximos vencimientos, ventas del día
3. Productos (lista, alta/edición con unidades y precios) — admin
4. Stock y kardex por producto
5. Nueva venta (cliente → líneas → total) — optimizada para celular
6. Historial de ventas y detalle / anulación
7. Entradas de mercadería (compras)
8. Ajuste de stock — admin
9. Clientes y descuentos — admin
10. Proveedores — admin
11. Exportar a CSV (productos, stock, ventas)
12. Usuarios — admin

## 7. Orden de construcción
1. Estructura del proyecto, configuración, base de datos y migraciones
2. Autenticación y roles
3. Productos + unidades + conversión (con tests de conversión y redondeo)
4. Stock: entradas, lotes, kardex
5. Clientes y reglas de precio (con tests de prioridad de descuentos)
6. Ventas (con tests: descuento de stock, FEFO, anulación)
7. Panel y alertas
8. Exportaciones CSV
9. Respaldos y despliegue

## 8. Criterios de aceptación v1
- Vender 2 cajas + 3 m² de un piso descuenta las piezas correctas y el kardex lo refleja.
- Dos clientes distintos obtienen precios distintos para el mismo producto según su descuento.
- Un empleado no puede ver costos ni modificar precios.
- El stock calculado es igual a la suma de los movimientos del kardex.
- Funciona usable en un celular.
