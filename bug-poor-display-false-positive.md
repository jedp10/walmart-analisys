# Bug: detect_poor_display falsos positivos por días no catalogados

## Archivo
`visualizer/processes/generate_alarms.py` — función `detect_poor_display()` (línea 100)

## Problema
La función compara `inv_on_hand` del día actual vs el día anterior para detectar aumentos de inventario. Cuando un día tiene `inv_on_hand=None` (no catalogado), lo convierte a 0 con `or 0`. Esto genera una transición falsa de 0→N que se interpreta como reposición de mercancía.

## Ejemplo concreto
UPC `0780460354172`, Store 12, alarma id 2297:

```
17/11: inv_on_hand=None, cataloged=False  ← día sin datos
18/11: inv_on_hand=12,   cataloged=True
19/11-26/11: inv_on_hand=12, so_units=0   ← 9 días sin ventas
```

- `dias_alarma` = 9, `start_index` = 25 (18/11)
- Al comparar 18/11 vs 17/11: `prev_stock = None or 0 = 0`, `curr_stock = 12`
- `12 > 0` → retorna `True` → clasifica como **poor_display**
- Debería ser **dead_inventory** porque el inventario se mantuvo constante en 12 durante los 9 días

## Lógica actual (líneas 100-112)
```python
def detect_poor_display(items, current_index, dead_days):
    start_index = current_index - dead_days + 1
    for i in range(start_index, current_index + 1):
        if i > 0:
            prev_stock = items[i - 1]["inv_on_hand"] or 0
            curr_stock = items[i]["inv_on_hand"] or 0
            if curr_stock > prev_stock:
                return True
    return False
```

## Fix necesario
Cuando `prev` o `curr` `inv_on_hand` es `None`, o el día anterior no está catalogado, saltar esa comparación en lugar de tratar None como 0.

## Impacto
Afecta cualquier grupo que tenga un día no catalogado (inv_on_hand=None) justo antes o dentro del período de días muertos. Convierte dead_inventory en poor_display erróneamente.
