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
    Dado {key: total_sales}, retorna:
      - dict {key: quintile(1-5)}
      - list of (key, total_sales, cumulative_pct, quintile) para persistir
    Ordenado por facturación descendente, quintil basado en % acumulado "piso".
    """
    total = sum(sales_map.values())
    if total == 0:
        return {}, []

    sorted_items = sorted(sales_map.items(), key=lambda x: x[1], reverse=True)
    quintiles = {}
    details = []
    accumulated = 0.0

    for key, sales in sorted_items:
        q = _quintile_from_floor(accumulated)
        quintiles[key] = q
        accumulated += sales / total
        details.append((key, round(sales, 2), round(accumulated * 100, 2), q))

    return quintiles, details


# ---------------------------------------------------------------------------
# Quintile persistence
# ---------------------------------------------------------------------------

def save_quintiles_to_db(cur, target_date, product_details, store_details):
    """
    Persiste los quintiles calculados en product_sales_quintiles y store_sales_quintiles.
    Borra los registros del día (idempotencia) y luego inserta en batch.
    """
    from psycopg2.extras import execute_values

    # Product quintiles
    cur.execute("DELETE FROM product_sales_quintiles WHERE date = %s", (target_date,))
    if product_details:
        execute_values(
            cur,
            "INSERT INTO product_sales_quintiles (date, upc, total_sales, cumulative_sales_pct, quintile) VALUES %s",
            [(target_date, upc, sales, cum_pct, q) for upc, sales, cum_pct, q in product_details],
            template="(%s, %s, %s, %s, %s)",
        )

    # Store quintiles
    cur.execute("DELETE FROM store_sales_quintiles WHERE date = %s", (target_date,))
    if store_details:
        execute_values(
            cur,
            "INSERT INTO store_sales_quintiles (date, store_id, total_sales, cumulative_sales_pct, quintile) VALUES %s",
            [(target_date, store_id, sales, cum_pct, q) for store_id, sales, cum_pct, q in store_details],
            template="(%s, %s, %s, %s, %s)",
        )

    print(f"Quintiles persistidos: {len(product_details)} productos, {len(store_details)} tiendas")


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
            if (item["so_units"] or 0) > 0:
                break_date = item["date"]
                break
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
    Carga datos de daily_data para el rango requerido, agrupa por (upc, store_id)
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
        SELECT d.date, d.upc, d.store_id,
               d.so_units, d.so_amount, d.inv_on_hand,
               d.cataloged, d.unit_cost
        FROM daily_data d
        WHERE d.date BETWEEN %s AND %s
        ORDER BY d.upc, d.store_id, d.date
    """, (date_from, date_to))

    rows = cur.fetchall()
    print(f"Registros en rango:   {len(rows)}")

    if not rows:
        print("No hay datos para procesar.")
        return None

    # Agrupar por (upc, store_id)
    groups = defaultdict(list)
    for row in rows:
        d_date, upc, store_id, so_units, so_amount, inv_on_hand, cataloged, unit_cost = row
        groups[(upc, store_id)].append({
            "date": d_date,
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
        d_date, upc, store_id, so_units, so_amount, inv_on_hand, cataloged, unit_cost = row
        if d_date not in history_dates:
            continue
        sales = float(so_amount) if so_amount is not None else 0.0
        product_sales[upc] += sales
        store_sales[store_id] += sales

    product_quintiles, product_quintile_details = calculate_revenue_quintiles(dict(product_sales))
    store_quintiles, store_quintile_details = calculate_revenue_quintiles(dict(store_sales))

    print(f"Productos con quintil: {len(product_quintiles)}, Tiendas con quintil: {len(store_quintiles)}")

    return {
        "target_date": target_date,
        "groups": groups,
        "min_days": min_days,
        "effective_history": effective_history,
        "product_quintiles": product_quintiles,
        "store_quintiles": store_quintiles,
        "product_quintile_details": product_quintile_details,
        "store_quintile_details": store_quintile_details,
    }


# ---------------------------------------------------------------------------
# Alarm evaluators
# ---------------------------------------------------------------------------

def evaluate_dead_poor_display_alarms(shared, settings):
    """
    Evalúa dead_inventory y poor_display sobre los grupos pre-cargados.
    Retorna dict {(upc, store_id): {"alarm_type": ..., "data_item": {...}}}.
    """
    target_date = shared["target_date"]
    groups = shared["groups"]
    min_days = shared["min_days"]
    effective_history = shared["effective_history"]
    product_quintiles = shared["product_quintiles"]
    store_quintiles = shared["store_quintiles"]

    alarms = {}

    for (upc, store_id), items in groups.items():
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
        q_product = product_quintiles.get(upc, 5)
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

        alarms[(upc, store_id)] = {
            "alarm_type": alarm_type,
            "data_item": {
                "date": str(target_date),
                "alarm_days": alarm_days,
                "severity": severity,
                "q_product": q_product,
                "q_store": q_store,
                "avg_units": round(avg_units, 2),
                "avg_sales": round(avg_sales, 2),
                "unit_cost": round(unit_cost, 2),
            },
        }

    print(f"Alarmas dead/poor_display: {len(alarms)}")
    return alarms


def evaluate_overstock_alarms(shared, settings):
    """
    Evalúa overstock sobre los grupos pre-cargados.
    Retorna dict {(upc, store_id): {"alarm_type": ..., "data_item": {...}}}.
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

    alarms = {}

    for (upc, store_id), items in groups.items():
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
        q_product = product_quintiles.get(upc, 5)
        q_store = store_quintiles.get(store_id, 5)
        severity = min(10, max(1, q_product + q_store - 1))

        # Economic impact = (avg_sales / avg_qty) * stock
        economic_impact = (avg_sales / avg_qty) * stock

        unit_cost = float(target_item["unit_cost"]) if target_item["unit_cost"] is not None else 0.0

        alarms[(upc, store_id)] = {
            "alarm_type": "overstock",
            "data_item": {
                "date": str(target_date),
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
            },
        }

    print(f"Alarmas overstock: {len(alarms)}")
    return alarms


# ---------------------------------------------------------------------------
# Upsert & stale-close logic
# ---------------------------------------------------------------------------

def upsert_alarms(cur, today_alarms, target_date):
    """
    Fase 2: Compara alarmas evaluadas hoy contra alarmas abiertas existentes.

    Caso A: Misma alarma (mismo tipo) → UPDATE append data_item al array.
    Caso B: Tipo cambió → cerrar la vieja, crear nueva con ref_id.
    Caso C: Nueva → INSERT.

    Retorna dict con contadores {inserted, updated, type_changed}.
    """
    # Load existing open alarms indexed by (upc, store_id)
    cur.execute(
        "SELECT id, upc, store_id, alarm_type, alarm_data FROM alarms WHERE status = 'open'"
    )
    open_alarms = {}
    for row in cur.fetchall():
        alarm_id, upc, store_id, alarm_type, alarm_data = row
        open_alarms[(upc, store_id)] = {
            "id": alarm_id,
            "alarm_type": alarm_type,
            "alarm_data": alarm_data,
        }

    stats = {"inserted": 0, "updated": 0, "type_changed": 0}

    for (upc, store_id), alarm_info in today_alarms.items():
        new_type = alarm_info["alarm_type"]
        data_item = alarm_info["data_item"]
        existing = open_alarms.get((upc, store_id))

        if existing is None:
            # Caso C: Nueva alarma
            cur.execute(
                "INSERT INTO alarms (upc, store_id, alarm_type, alarm_data, ref_id, status, started_at, updated_at) "
                "VALUES (%s, %s, %s, %s, NULL, 'open', %s, %s)",
                (upc, store_id, new_type, json.dumps([data_item]), target_date, target_date),
            )
            stats["inserted"] += 1

        elif existing["alarm_type"] == new_type:
            # Caso A: Misma alarma, append data_item
            cur.execute(
                "UPDATE alarms SET alarm_data = alarm_data || %s::jsonb, updated_at = %s WHERE id = %s",
                (json.dumps([data_item]), target_date, existing["id"]),
            )
            stats["updated"] += 1

        else:
            # Caso B: Tipo cambió → cerrar vieja, crear nueva con ref_id
            old_data = existing["alarm_data"]
            if isinstance(old_data, str):
                old_data = json.loads(old_data)
            close_item = dict(data_item)
            close_item["closed"] = True
            cur.execute(
                "UPDATE alarms SET alarm_data = alarm_data || %s::jsonb, status = 'closed', "
                "finished_at = %s, updated_at = %s WHERE id = %s",
                (json.dumps([close_item]), target_date, target_date, existing["id"]),
            )
            cur.execute(
                "INSERT INTO alarms (upc, store_id, alarm_type, alarm_data, ref_id, status, started_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, 'open', %s, %s)",
                (upc, store_id, new_type, json.dumps([data_item]), existing["id"], target_date, target_date),
            )
            stats["type_changed"] += 1

    return stats


def close_stale_alarms(cur, today_alarms, shared, target_date):
    """
    Fase 3: Cierra alarmas abiertas que no fueron tocadas hoy (la condición ya no aplica).

    Busca alarmas con updated_at < target_date, construye un último data_item
    con los datos actuales del par (upc, store_id) y "closed": true.

    Retorna cantidad de alarmas cerradas.
    """
    cur.execute(
        "SELECT id, upc, store_id, alarm_type, alarm_data "
        "FROM alarms WHERE status = 'open' AND updated_at < %s",
        (target_date,),
    )
    stale_rows = cur.fetchall()

    if not stale_rows:
        return 0

    groups = shared["groups"]
    target_date_obj = shared["target_date"]
    effective_history = shared["effective_history"]
    product_quintiles = shared["product_quintiles"]
    store_quintiles = shared["store_quintiles"]

    closed = 0

    for alarm_id, upc, store_id, alarm_type, alarm_data in stale_rows:
        # Build a close item from current data if available
        items = groups.get((upc, store_id))
        close_item = {"date": str(target_date), "closed": True}

        if items:
            # Find target date record for current values
            target_item = None
            target_item_idx = None
            for i, item in enumerate(items):
                if item["date"] == target_date_obj:
                    target_item = item
                    target_item_idx = i
                    break

            if target_item is not None:
                q_product = product_quintiles.get(target_item["upc"], 5)
                q_store = store_quintiles.get(store_id, 5)
                severity = min(10, max(1, q_product + q_store - 1))
                unit_cost = float(target_item["unit_cost"]) if target_item["unit_cost"] is not None else 0.0
                avg_units = calculate_average(items, target_item_idx, effective_history, "so_units")
                avg_sales = calculate_average(items, target_item_idx, effective_history, "so_amount")

                close_item.update({
                    "severity": severity,
                    "q_product": q_product,
                    "q_store": q_store,
                    "avg_units": round(avg_units, 2),
                    "avg_sales": round(avg_sales, 2),
                    "unit_cost": round(unit_cost, 2),
                })

                if alarm_type == "overstock":
                    stock = target_item["inv_on_hand"] or 0
                    avg_qty = avg_units
                    doh = calculate_doh(stock, avg_qty) if avg_qty > 0 else 0
                    close_item["doh"] = round(doh, 1) if doh != float("inf") else 0
                    close_item["stock"] = stock
                else:
                    close_item["alarm_days"] = 0

        cur.execute(
            "UPDATE alarms SET alarm_data = alarm_data || %s::jsonb, status = 'closed', "
            "finished_at = %s, updated_at = %s WHERE id = %s",
            (json.dumps([close_item]), target_date, target_date, alarm_id),
        )
        closed += 1

    return closed


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------

def generate_all_alarms(cur, target_date):
    """
    Orquesta la generación incremental de alarmas para target_date.
    Fase 1: Evalúa alarmas del día.
    Fase 2: Upsert contra alarmas abiertas existentes.
    Fase 3: Cierra alarmas stale que ya no aplican.
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

    # 2b. Persist quintiles
    print("\n--- Persistiendo quintiles ---")
    save_quintiles_to_db(
        cur, target_date,
        shared["product_quintile_details"],
        shared["store_quintile_details"],
    )

    # 3. Fase 1: Evaluate each alarm type
    print("\n--- Evaluando dead_inventory / poor_display ---")
    dead_poor_alarms = evaluate_dead_poor_display_alarms(shared, settings)

    print("\n--- Evaluando overstock ---")
    overstock_alarms = evaluate_overstock_alarms(shared, settings)

    # Merge both dicts (dead/poor_display wins on collision)
    today_alarms = {**overstock_alarms, **dead_poor_alarms}

    # 4. Fase 2: Upsert
    print("\n--- Upsert alarmas ---")
    stats = upsert_alarms(cur, today_alarms, target_date)
    print(f"  Nuevas (caso C): {stats['inserted']}")
    print(f"  Actualizadas (caso A): {stats['updated']}")
    print(f"  Tipo cambió (caso B): {stats['type_changed']}")

    # 5. Fase 3: Cerrar stale
    print("\n--- Cerrando alarmas stale ---")
    stale_closed = close_stale_alarms(cur, today_alarms, shared, target_date)
    print(f"  Alarmas cerradas por stale: {stale_closed}")

    # 6. Summary
    total_evaluated = len(today_alarms)
    total_actions = stats["inserted"] + stats["updated"] + stats["type_changed"] + stale_closed
    print(f"\nResumen: {total_evaluated} alarmas evaluadas, {total_actions} acciones en BD")
    counts = {}
    for alarm_info in today_alarms.values():
        t = alarm_info["alarm_type"]
        counts[t] = counts.get(t, 0) + 1
    for alarm_type, count in sorted(counts.items()):
        print(f"  {alarm_type}: {count}")

    return total_evaluated


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
