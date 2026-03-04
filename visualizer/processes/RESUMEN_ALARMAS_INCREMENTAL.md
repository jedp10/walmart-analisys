# Resumen: Proceso Incremental de Alarmas

## Problema original

El proceso anterior (`generate_alarms.py`) solo hacía **INSERT** de alarmas nuevas cada vez que se ejecutaba. No existía:

- **Upsert**: si una alarma ya existía para el mismo producto+tienda, se duplicaba en vez de actualizarse.
- **Cierre automático**: las alarmas que dejaban de cumplir la condición quedaban abiertas indefinidamente.

Esto generaba acumulación de registros duplicados y alarmas "fantasma" que nunca se cerraban.

---

## Solución implementada: 3 fases

El nuevo flujo en `generate_all_alarms()` ejecuta 3 fases secuenciales:

### Fase 1 — Evaluación

Se evalúan las condiciones de alarma para la fecha objetivo usando los datos de `daily_data`. Se ejecutan dos evaluadores:

- `evaluate_dead_poor_display_alarms()` — detecta dead inventory y mala exhibición.
- `evaluate_overstock_alarms()` — detecta sobre-inventario.

Ambos retornan un **dict** con clave `(product_id, store_id)` y valor:

```python
{
    "alarm_type": "dead_inventory" | "poor_display" | "overstock",
    "data_item": { ... }  # métricas del día
}
```

### Fase 2 — Upsert (`upsert_alarms`)

Compara las alarmas evaluadas hoy contra las alarmas abiertas (`status = 'open'`) en la tabla `alarms`. Maneja 3 casos:

| Caso | Condición | Acción |
|------|-----------|--------|
| **A** | Misma alarma (mismo tipo, mismo producto+tienda) | `UPDATE`: append del `data_item` al array `alarm_data` |
| **B** | Tipo cambió (ej: dead_inventory → poor_display) | Cierra la alarma vieja, crea una nueva con `ref_id` apuntando a la anterior |
| **C** | Nueva alarma (no existe alarma abierta para ese par) | `INSERT` con `alarm_data = [data_item]` |

### Fase 3 — Cierre de alarmas stale (`close_stale_alarms`)

Busca alarmas abiertas cuyo `updated_at < target_date` (no fueron tocadas en la Fase 2, es decir, la condición ya no aplica). Para cada una:

1. Construye un último `data_item` con `"closed": true` y las métricas actuales del par producto+tienda.
2. Hace append de ese item al array `alarm_data`.
3. Actualiza `status = 'closed'` y `finished_at = target_date`.

---

## Cambios en los evaluadores

Antes, los evaluadores retornaban una **lista de tuplas** con los campos posicionales para hacer INSERT directo. Ahora retornan un **dict** indexado por `(product_id, store_id)`:

```python
# Antes (lista de tuplas)
[(product_id, store_id, alarm_type, alarm_data, started_at, updated_at), ...]

# Ahora (dict)
{
    (product_id, store_id): {
        "alarm_type": "dead_inventory",
        "data_item": {
            "date": "2025-03-01",
            "alarm_days": 12,
            "severity": 5,
            ...
        }
    }
}
```

Este cambio permite buscar eficientemente por `(product_id, store_id)` durante el upsert.

---

## Estructura del `alarm_data`

El campo `alarm_data` en la tabla `alarms` es un **array JSON acumulativo**. Cada ejecución del proceso agrega un elemento al array:

```json
[
    {"date": "2025-02-25", "alarm_days": 8, "severity": 5, "avg_units": 1.2, ...},
    {"date": "2025-02-26", "alarm_days": 9, "severity": 5, "avg_units": 1.1, ...},
    {"date": "2025-02-27", "alarm_days": 10, "severity": 5, "avg_units": 1.1, ..., "closed": true}
]
```

- El último elemento con `"closed": true` indica que la alarma fue cerrada (ya sea por stale o por cambio de tipo).
- Esto permite ver la evolución de la alarma a lo largo del tiempo.

---

## Nuevas funciones

| Función | Descripción |
|---------|-------------|
| `upsert_alarms(cur, today_alarms, target_date)` | Fase 2: compara alarmas del día contra abiertas existentes. Retorna `{"inserted", "updated", "type_changed"}` |
| `close_stale_alarms(cur, today_alarms, shared, target_date)` | Fase 3: cierra alarmas abiertas que no fueron tocadas hoy. Retorna cantidad cerrada |

---

## Cómo verificar que funciona

### 1. Ejecutar el proceso

```bash
python visualizer/processes/generate_alarms.py 2025-03-01
```

### 2. Revisar la salida esperada

```
--- Evaluando dead_inventory / poor_display ---
Alarmas dead/poor_display: N

--- Evaluando overstock ---
Alarmas overstock: N

--- Upsert alarmas ---
  Nuevas (caso C): X
  Actualizadas (caso A): Y
  Tipo cambió (caso B): Z

--- Cerrando alarmas stale ---
  Alarmas cerradas por stale: W

Resumen: N alarmas evaluadas, X acciones en BD
```

### 3. Verificar en la base de datos

```sql
-- Alarmas abiertas actuales
SELECT alarm_type, COUNT(*) FROM alarms WHERE status = 'open' GROUP BY alarm_type;

-- Alarmas cerradas recientemente
SELECT id, alarm_type, started_at, finished_at
FROM alarms WHERE status = 'closed' ORDER BY finished_at DESC LIMIT 10;

-- Verificar que alarm_data es un array con historial
SELECT id, alarm_type, jsonb_array_length(alarm_data) AS entries
FROM alarms WHERE status = 'open' ORDER BY jsonb_array_length(alarm_data) DESC LIMIT 5;

-- Verificar que no hay duplicados abiertos para el mismo producto+tienda
SELECT product_id, store_id, COUNT(*)
FROM alarms WHERE status = 'open'
GROUP BY product_id, store_id HAVING COUNT(*) > 1;
```

### 4. Ejecución idempotente

Ejecutar dos veces seguidas con la misma fecha debe producir:
- `Nuevas (caso C): 0` en la segunda ejecución
- `Actualizadas (caso A): N` (las mismas alarmas se actualizan)
- Sin alarmas stale cerradas (ya fueron tocadas)
