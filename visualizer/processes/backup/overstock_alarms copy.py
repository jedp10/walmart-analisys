"""
Genera alarmas de Overstock para una fecha objetivo.

Réplica de data-preparation/generate-overstock.js pero leyendo de
PostgreSQL (daily_data) y escribiendo en la tabla alarms.

Uso:
    python overstock_alarms.py [YYYY-MM-DD]

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
    """Lee las keys history_window, overstock y max_alarm_days de la tabla settings."""
    cur.execute("SELECT key, value FROM settings WHERE key IN ('history_window', 'overstock', 'max_alarm_days')")
    rows = cur.fetchall()
    settings = {}
    for key, value in rows:
        settings[key] = value
    return settings


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
# Core overstock logic
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
        # Si no hay suficiente historial mínimo, parar
        if i < min_days:
            break

        item = items[i]

        # Si stock es 0 o negativo, saltar sin romper
        stock = item["inv_on_hand"]
        if stock is None or stock <= 0:
            continue

        # Calcular promedio de ventas para este día
        effective_days = min(i, history_days)
        avg_qty = calculate_average(items, i, effective_days, "so_units")
        doh = calculate_doh(stock, avg_qty)

        if doh > doh_threshold:
            count += 1
        else:
            break

    return count


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def generate_overstock_alarms(cur, target_date):
    """Genera alarmas de overstock para la fecha objetivo y las inserta en la tabla alarms."""

    # 1. Leer settings
    settings = load_settings(cur)
    if "history_window" not in settings or "overstock" not in settings:
        print("ERROR: Faltan settings (history_window o overstock).")
        return 0

    min_days = settings["history_window"]["min_days"]
    max_days = settings["history_window"]["max_days"]
    max_alarm_days = settings.get("max_alarm_days", max_days)

    doh_threshold = settings["overstock"]["days_on_hand_threshold"]
    min_days_threshold = settings["overstock"]["min_days_threshold"]

    # 2. Rango de fechas
    date_from = target_date - timedelta(days=max_alarm_days)
    date_to = target_date

    print(f"Fecha objetivo: {target_date}")
    print(f"Rango de datos: {date_from} a {date_to}")
    print(f"Ventana de historial: {min_days}-{max_days} días")
    print(f"Umbrales: DOH > {doh_threshold} días, mínimo {min_days_threshold} días en situación")

    # 3. Query principal
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
    print(f"Registros en rango: {len(rows)}")

    if not rows:
        print("No hay datos para procesar.")
        return 0

    # 4. Agrupar por (product_id, store_id)
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

    # 5. Calcular quintiles de facturación sobre [target - effective_history, target)
    all_dates = sorted({r[0] for r in rows})
    date_to_idx = {d: i for i, d in enumerate(all_dates)}

    target_idx = date_to_idx.get(target_date)
    if target_idx is None:
        print(f"ERROR: La fecha objetivo {target_date} no tiene datos en daily_data.")
        return 0

    effective_history = min(target_idx, max_days)

    if effective_history < min_days:
        print(f"ERROR: Solo hay {effective_history} días de historial, se necesitan al menos {min_days}.")
        return 0

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

    # 6. Evaluar cada grupo en la fecha objetivo
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

        ref_id = f"{target_date}_{product_id}_{store_id}_overstock"

        alarms.append((
            product_id,
            store_id,
            "overstock",
            json.dumps({
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
            }),
            ref_id,
            "open",
        ))

    print(f"\nAlarmas overstock generadas: {len(alarms)}")

    if not alarms:
        return 0

    # 7. Insert: delete existing overstock alarms for this date (idempotency)
    like_pattern = f"{target_date}_%_overstock"
    cur.execute("DELETE FROM alarms WHERE ref_id LIKE %s", (like_pattern,))
    deleted = cur.rowcount
    if deleted:
        print(f"Alarmas overstock previas eliminadas: {deleted}")

    execute_values(
        cur,
        """
        INSERT INTO alarms (product_id, store_id, alarm_type, alarm_data, ref_id, status)
        VALUES %s
        """,
        alarms,
        template="(%s, %s, %s, %s, %s, %s)",
    )

    return len(alarms)


# ---------------------------------------------------------------------------
# Seed settings
# ---------------------------------------------------------------------------

def seed_settings(cur):
    """Inserta la configuración de overstock si no existe."""
    cur.execute("SELECT COUNT(*) FROM settings WHERE key = 'overstock'")
    count = cur.fetchone()[0]
    if count > 0:
        return

    print("Sembrando setting overstock...")
    cur.execute("""
        INSERT INTO settings (key, value) VALUES
            ('overstock', %s::jsonb)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
    """, (
        json.dumps({"days_on_hand_threshold": 40, "min_days_threshold": 7}),
    ))
    print("Setting overstock insertado.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Parse optional date argument
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

        # Seed settings if needed
        seed_settings(cur)
        conn.commit()

        # Determine target date
        if target_date is None:
            cur.execute("SELECT MAX(date) FROM daily_data")
            row = cur.fetchone()
            if row[0] is None:
                print("ERROR: No hay datos en daily_data.")
                sys.exit(1)
            target_date = row[0]

        # Generate alarms
        total = generate_overstock_alarms(cur, target_date)
        conn.commit()

        print(f"\nProceso completado. Total alarmas overstock: {total}")

        cur.close()
    except Exception as e:
        conn.rollback()
        print(f"ERROR: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
