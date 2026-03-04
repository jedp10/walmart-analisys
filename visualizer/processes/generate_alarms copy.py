"""
Genera alarmas de Dead Inventory, Mala Exhibición y Overstock para una fecha objetivo.

Lee de PostgreSQL (daily_data) y escribe en la tabla alarms.

Uso:
    python generate_alarms.py [YYYY-MM-DD]

Sin argumento usa MAX(date) de daily_data.
"""

import json
import sys
from collections import defaultdict
from datetime import date, timedelta

import psycopg2
from psycopg2.extras import execute_values

DB_DSN = "postgresql://postgres:postgres@localhost/db_massive_management"


# ---------------------------------------------------------------------------
# Settings helpers
# ---------------------------------------------------------------------------

def load_settings(cur):
    """Lee las keys history_window, dead_inventory, overstock y max_alarm_days de la tabla settings."""
    cur.execute(
        "SELECT key, value FROM settings "
        "WHERE key IN ('history_window', 'dead_inventory', 'overstock', 'max_alarm_days')"
    )
    return {key: value for key, value in cur.fetchall()}


def get_days_threshold(settings, severity):
    """Retorna el umbral de días sin ventas para una severidad dada."""
    severities = settings["dead_inventory"]["severities"]
    for s in severities:
        if s["severity"] == severity:
            return s["days_without_sales_threshold"]
    return severity


def seed_settings(cur):
    """Inserta las settings faltantes."""
    cur.execute(
        "SELECT key FROM settings "
        "WHERE key IN ('history_window', 'dead_inventory', 'overstock', 'max_alarm_days')"
    )
    existing = {row[0] for row in cur.fetchall()}
    required = {'history_window', 'dead_inventory', 'overstock', 'max_alarm_days'}
    missing = required - existing
    if not missing:
        return

    print("Sembrando settings faltantes...")
    defaults = {
        'history_window': json.dumps({"min_days": 14, "max_days": 28}),
        'dead_inventory': json.dumps({"severities": [
            {"severity": i, "days_without_sales_threshold": i + 1}
            for i in range(1, 11)
        ]}),
        'overstock': json.dumps({"days_on_hand_threshold": 40, "min_days_threshold": 7}),
        'max_alarm_days': json.dumps(40),
    }
    rows_to_insert = [(k, defaults[k]) for k in missing]
    cur.executemany(
        "INSERT INTO settings (key, value) VALUES (%s, %s::jsonb) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
        rows_to_insert,
    )
    print(f"Settings insertados: {sorted(missing)}")


# ---------------------------------------------------------------------------
# Quintile calculation
# ---------------------------------------------------------------------------

def _quintile_from_floor(floor_pct):
    if floor_pct < 0.20:
        return 1
    if floor_pct < 0.40:
        return 2
    if floor_pct < 0.60:
        return 3
    if floor_pct < 0.80:
        return 4
    return 5


def calculate_revenue_quintiles(sales_map):
    """
    Dado {key: total_sales}, retorna {key: quintile(1-5)}
    ordenado por facturación descendente, quintil basado en % acumulado "piso".
    """
    total = sum(sales_map.values())
    if total == 0:
        return {}

    sorted_items = sorted(sales_map.items(), key=lambda x: x[1], reverse=True)
    quintiles = {}
    accumulated = 0.0

    for key, sales in sorted_items:
        quintiles[key] = _quintile_from_floor(accumulated)
        accumulated += sales / total

    return quintiles


# ---------------------------------------------------------------------------
# Shared math helpers
# ---------------------------------------------------------------------------

def calculate_average(items, end_index, days, field):
    """Promedio de los últimos `days` registros antes de end_index."""
    start_index = max(0, end_index - days)
    total = 0.0
    count = 0
    for i in range(start_index, end_index):
        val = items[i][field]
        total += float(val) if val is not None else 0.0
        count += 1
    return total / count if count > 0 else 0.0


# ---------------------------------------------------------------------------
# Dead-inventory / poor-display logic
# ---------------------------------------------------------------------------

def count_consecutive_dead_days(items, current_index):
    """Cuenta días sin ventas hacia atrás con inv_on_hand>0.
    Días con inv_on_hand=None se saltan (no rompen la cadena).
    Retorna last_date - break_date (fecha del último día con ventas o sin stock)."""
    last_date = items[current_index]["date"]
    break_date = None

    for i in range(current_index, -1, -1):
        item = items[i]
        if item["inv_on_hand"] is None:
            continue
        if (item["so_units"] or 0) == 0 and item["inv_on_hand"] > 0:
            continue
        else:
            break_date = item["date"]
            break

    if break_date is None:
        return (last_date - items[0]["date"]).days + 1

    return (last_date - break_date).days


def detect_poor_display(items, current_index, dead_days):
    """
    Retorna True si durante el período sin ventas hubo un aumento de inv_on_hand
    respecto al día anterior.
    """
    start_index = current_index - dead_days + 1
    for i in range(start_index, current_index + 1):
        if i > 0:
            prev_stock = items[i - 1]["inv_on_hand"]
            curr_stock = items[i]["inv_on_hand"]
            if prev_stock is None or curr_stock is None:
                continue
            if curr_stock > prev_stock:
                return True
    return False


# ---------------------------------------------------------------------------
# Overstock logic
# ---------------------------------------------------------------------------

def calculate_doh(stock, avg_daily_sales):
    """Calcula Days On Hand. Retorna float('inf') si no hay ventas."""
    if avg_daily_sales <= 0:
        return float("inf")
    return stock / avg_daily_sales


def count_consecutive_overstock_days(items, current_index, doh_threshold, history_days, min_days):
    """
    Cuenta los días consecutivos en situación de sobre-inventario hacia atrás.

    - Si stock <= 0: skip (sin romper la racha)
    - Para cada día: calcula avg_qty usando calculate_average, luego DOH
    - Si DOH > threshold: count++, sino: break
    - Si i < min_days: break (no hay suficiente historial)
    """
    count = 0

    for i in range(current_index, -1, -1):
        if i < min_days:
            break

        item = items[i]

        stock = item["inv_on_hand"]
        if stock is None or stock <= 0:
            continue

        effective_days = min(i, history_days)
        avg_qty = calculate_average(items, i, effective_days, "so_units")
        doh = calculate_doh(stock, avg_qty)

        if doh > doh_threshold:
            count += 1
        else:
            break

    return count


# ---------------------------------------------------------------------------
# Shared data loader
# ---------------------------------------------------------------------------

def load_data(cur, target_date, settings):
    """
    Carga datos de daily_data para el rango requerido, agrupa por (product_id, store_id)
    y calcula quintiles de facturación. Retorna un dict con todo lo necesario para
    ambos evaluadores de alarmas, o None si hay un error irrecuperable.
    """
    min_days = settings["history_window"]["min_days"]
    max_days = settings["history_window"]["max_days"]
    max_alarm_days = settings.get("max_alarm_days", max_days)

    date_from = target_date - timedelta(days=max_alarm_days)
    date_to = target_date

    print(f"Fecha objetivo:       {target_date}")
    print(f"Rango de datos:       {date_from} a {date_to}")
    print(f"Ventana de historial: {min_days}-{max_days} días")

    cur.execute("""
        SELECT d.date, d.product_id, p.upc, d.store_id,
               d.so_units, d.so_amount, d.inv_on_hand,
               d.cataloged, d.unit_cost
        FROM daily_data d
        JOIN products p ON p.id = d.product_id
        WHERE d.date BETWEEN %s AND %s
        ORDER BY d.product_id, d.store_id, d.date
    """, (date_from, date_to))

    rows = cur.fetchall()
    print(f"Registros en rango:   {len(rows)}")

    if not rows:
        print("No hay datos para procesar.")
        return None

    # Agrupar por (product_id, store_id)
    groups = defaultdict(list)
    for row in rows:
        d_date, product_id, upc, store_id, so_units, so_amount, inv_on_hand, cataloged, unit_cost = row
        groups[(product_id, store_id)].append({
            "date": d_date,
            "product_id": product_id,
            "upc": upc,
            "store_id": store_id,
            "so_units": so_units,
            "so_amount": so_amount,
            "inv_on_hand": inv_on_hand,
            "cataloged": cataloged,
            "unit_cost": unit_cost,
        })

    print(f"Combinaciones producto+tienda: {len(groups)}")

    # Determinar historial efectivo
    all_dates = sorted({r[0] for r in rows})
    date_to_idx = {d: i for i, d in enumerate(all_dates)}

    target_idx = date_to_idx.get(target_date)
    if target_idx is None:
        print(f"ERROR: La fecha objetivo {target_date} no tiene datos en daily_data.")
        return None

    effective_history = min(target_idx, max_days)

    if effective_history < min_days:
        print(f"ERROR: Solo hay {effective_history} días de historial, se necesitan al menos {min_days}.")
        return None

    # Quintiles sobre [target - effective_history, target)
    history_start_idx = target_idx - effective_history
    history_dates = set(all_dates[history_start_idx:target_idx])

    product_sales = defaultdict(float)
    store_sales = defaultdict(float)

    for row in rows:
        d_date, product_id, upc, store_id, so_units, so_amount, inv_on_hand, cataloged, unit_cost = row
        if d_date not in history_dates:
            continue
        sales = float(so_amount) if so_amount is not None else 0.0
        product_sales[upc] += sales
        store_sales[store_id] += sales

    product_quintiles = calculate_revenue_quintiles(dict(product_sales))
    store_quintiles = calculate_revenue_quintiles(dict(store_sales))

    print(f"Productos con quintil: {len(product_quintiles)}, Tiendas con quintil: {len(store_quintiles)}")

    return {
        "target_date": target_date,
        "groups": groups,
        "min_days": min_days,
        "effective_history": effective_history,
        "product_quintiles": product_quintiles,
        "store_quintiles": store_quintiles,
    }


# ---------------------------------------------------------------------------
# Alarm evaluators
# ---------------------------------------------------------------------------

def evaluate_dead_poor_display_alarms(shared, settings):
    """
    Evalúa dead_inventory y poor_display sobre los grupos pre-cargados.
    Retorna lista de tuplas listas para INSERT en alarms.
    """
    target_date = shared["target_date"]
    groups = shared["groups"]
    min_days = shared["min_days"]
    effective_history = shared["effective_history"]
    product_quintiles = shared["product_quintiles"]
    store_quintiles = shared["store_quintiles"]

    alarms = []

    for (product_id, store_id), items in groups.items():
        if len(items) < min_days + 1:
            continue

        # Find target date record
        target_item = None
        target_item_idx = None
        for i, item in enumerate(items):
            if item["date"] == target_date:
                target_item = item
                target_item_idx = i
                break

        if target_item is None:
            continue

        # Must be cataloged
        if not target_item["cataloged"]:
            continue

        # Skip if inv_on_hand is unknown
        if target_item["inv_on_hand"] is None:
            continue

        # Condition: no sales and stock > 0
        so = target_item["so_units"] or 0
        stock = target_item["inv_on_hand"]
        if so != 0 or stock <= 0:
            continue

        # Consecutive dead days
        alarm_days = count_consecutive_dead_days(items, target_item_idx)

        # Severity from quintiles
        q_product = product_quintiles.get(target_item["upc"], 5)
        q_store = store_quintiles.get(store_id, 5)
        severity = min(10, max(1, q_product + q_store - 1))

        # Check threshold
        threshold = get_days_threshold(settings, severity)
        if alarm_days < threshold:
            continue

        # Alarm type
        is_poor_display = detect_poor_display(items, target_item_idx, alarm_days)
        alarm_type = "poor_display" if is_poor_display else "dead_inventory"

        # Averages
        avg_units = calculate_average(items, target_item_idx, effective_history, "so_units")
        avg_sales = calculate_average(items, target_item_idx, effective_history, "so_amount")

        unit_cost = float(target_item["unit_cost"]) if target_item["unit_cost"] is not None else 0.0

        alarms.append((
            product_id,
            store_id,
            alarm_type,
            json.dumps([{
                "alarm_days": alarm_days,
                "severity": severity,
                "q_product": q_product,
                "q_store": q_store,
                "avg_units": round(avg_units, 2),
                "avg_sales": round(avg_sales, 2),
                "unit_cost": round(unit_cost, 2),
            }]),
            None,
            "open",
            target_date,
        ))

    print(f"Alarmas dead/poor_display: {len(alarms)}")
    return alarms


def evaluate_overstock_alarms(shared, settings):
    """
    Evalúa overstock sobre los grupos pre-cargados.
    Retorna lista de tuplas listas para INSERT en alarms.
    """
    target_date = shared["target_date"]
    groups = shared["groups"]
    min_days = shared["min_days"]
    effective_history = shared["effective_history"]
    product_quintiles = shared["product_quintiles"]
    store_quintiles = shared["store_quintiles"]

    doh_threshold = settings["overstock"]["days_on_hand_threshold"]
    min_days_threshold = settings["overstock"]["min_days_threshold"]

    print(f"Umbrales overstock: DOH > {doh_threshold} días, mínimo {min_days_threshold} días en situación")

    alarms = []

    for (product_id, store_id), items in groups.items():
        if len(items) < min_days + 1:
            continue

        # Find target date record
        target_item = None
        target_item_idx = None
        for i, item in enumerate(items):
            if item["date"] == target_date:
                target_item = item
                target_item_idx = i
                break

        if target_item is None:
            continue

        # Must be cataloged
        if not target_item["cataloged"]:
            continue

        # Must have stock > 0
        stock = target_item["inv_on_hand"]
        if stock is None or stock <= 0:
            continue

        # Calculate averages
        avg_qty = calculate_average(items, target_item_idx, effective_history, "so_units")
        avg_sales = calculate_average(items, target_item_idx, effective_history, "so_amount")

        # Exclude products without sales (that's dead inventory, not overstock)
        if avg_qty <= 0:
            continue

        # Calculate DOH
        doh = calculate_doh(stock, avg_qty)

        # Must exceed DOH threshold
        if doh <= doh_threshold:
            continue

        # Count consecutive overstock days
        days_in_situation = count_consecutive_overstock_days(
            items, target_item_idx, doh_threshold, effective_history, min_days
        )

        # Must meet minimum days threshold
        if days_in_situation < min_days_threshold:
            continue

        # Severity from quintiles
        q_product = product_quintiles.get(target_item["upc"], 5)
        q_store = store_quintiles.get(store_id, 5)
        severity = min(10, max(1, q_product + q_store - 1))

        # Economic impact = (avg_sales / avg_qty) * stock
        economic_impact = (avg_sales / avg_qty) * stock

        unit_cost = float(target_item["unit_cost"]) if target_item["unit_cost"] is not None else 0.0

        alarms.append((
            product_id,
            store_id,
            "overstock",
            json.dumps([{
                "doh": round(doh, 1),
                "days_in_situation": days_in_situation,
                "severity": severity,
                "q_product": q_product,
                "q_store": q_store,
                "avg_units": round(avg_qty, 2),
                "avg_sales": round(avg_sales, 2),
                "stock": stock,
                "economic_impact": round(economic_impact, 2),
                "unit_cost": round(unit_cost, 2),
            }]),
            None,
            "open",
            target_date,
        ))

    print(f"Alarmas overstock: {len(alarms)}")
    return alarms


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------

def generate_all_alarms(cur, target_date):
    """
    Orquesta la generación de todos los tipos de alarma para target_date.
    Carga datos una sola vez, ejecuta ambos evaluadores y hace un único
    ciclo de delete-then-insert.
    """
    # 1. Load and validate settings
    settings = load_settings(cur)
    for required_key in ("history_window", "dead_inventory", "overstock"):
        if required_key not in settings:
            print(f"ERROR: Falta setting requerido: '{required_key}'.")
            return 0

    # 2. Load shared data (query once, group once, quintiles once)
    shared = load_data(cur, target_date, settings)
    if shared is None:
        return 0

    # 3. Evaluate each alarm type
    print("\n--- Evaluando dead_inventory / poor_display ---")
    dead_poor_alarms = evaluate_dead_poor_display_alarms(shared, settings)

    print("\n--- Evaluando overstock ---")
    overstock_alarms = evaluate_overstock_alarms(shared, settings)

    all_alarms = dead_poor_alarms + overstock_alarms

    if not all_alarms:
        print("\nNo se generaron alarmas.")
        return 0

    # 4. Idempotency: delete existing alarms for target_date
    cur.execute("DELETE FROM alarms WHERE started_at = %s", (target_date,))
    deleted = cur.rowcount
    if deleted:
        print(f"\nAlarmas previas eliminadas: {deleted}")

    # 5. Bulk insert
    execute_values(
        cur,
        "INSERT INTO alarms (product_id, store_id, alarm_type, alarm_data, ref_id, status, started_at) VALUES %s",
        all_alarms,
        template="(%s, %s, %s, %s, %s, %s, %s)",
    )

    # 6. Summary
    counts = {}
    for alarm in all_alarms:
        counts[alarm[2]] = counts.get(alarm[2], 0) + 1
    print(f"\nAlarmas generadas: {len(all_alarms)}")
    for alarm_type, count in sorted(counts.items()):
        print(f"  {alarm_type}: {count}")

    return len(all_alarms)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    target_date = None
    if len(sys.argv) > 1:
        try:
            target_date = date.fromisoformat(sys.argv[1])
        except ValueError:
            print(f"ERROR: Formato de fecha inválido: {sys.argv[1]} (esperado YYYY-MM-DD)")
            sys.exit(1)

    conn = psycopg2.connect(DB_DSN)
    try:
        cur = conn.cursor()

        seed_settings(cur)
        conn.commit()

        if target_date is None:
            cur.execute("SELECT MAX(date) FROM daily_data")
            row = cur.fetchone()
            if row[0] is None:
                print("ERROR: No hay datos en daily_data.")
                sys.exit(1)
            target_date = row[0]

        total = generate_all_alarms(cur, target_date)
        conn.commit()

        print(f"\nProceso completado. Total alarmas: {total}")

        cur.close()
    except Exception as e:
        conn.rollback()
        print(f"ERROR: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
