"""
Procesa archivos Walmart (.xlsx) de Sell Out e Inventory
y vuelca los datos en la tabla daily_data de PostgreSQL.

Réplica de data-preparation/process-walmart-data.js pero con salida a DB.
"""

import os
import re
import shutil
from datetime import datetime, timedelta

import psycopg2
from psycopg2.extras import execute_values
from python_calamine import CalamineWorkbook

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TO_PROCESS_DIR = os.path.join(BASE_DIR, "..", "data-source", "to_process")
PROCESSED_DIR = os.path.join(BASE_DIR, "..", "data-source", "processed")

DB_DSN = "postgresql://postgres:postgres@localhost/db_massive_management"


# ---------------------------------------------------------------------------
# Excel helpers
# ---------------------------------------------------------------------------

def find_header_row(rows):
    """
    Busca la fila que contiene 'Consumer ID' y 'Item Nbr' con >10 columnas.
    rows: list of lists.
    Retorna el índice (0-based) de la fila header.
    """
    for idx, row in enumerate(rows[:30]):
        values = [str(c) for c in row if c is not None and str(c).strip()]
        has_consumer = any("Consumer ID" in v for v in values)
        has_item = any("Item Nbr" in v for v in values)
        if has_consumer and has_item and len(values) > 10:
            return idx
    return 0  # fallback


def read_excel_file(filepath):
    """
    Lee un archivo Excel con calamine (Rust, rápido).
    Retorna list[dict] con los headers como keys.
    """
    wb = CalamineWorkbook.from_path(filepath)
    sheet = wb.get_sheet_by_index(0)
    all_rows = sheet.to_python()

    if not all_rows:
        return []

    header_idx = find_header_row(all_rows)
    raw_headers = all_rows[header_idx]
    headers = [str(h).strip() if h is not None else "" for h in raw_headers]

    records = []
    for row in all_rows[header_idx + 1:]:
        row_dict = {}
        has_data = False
        for col_idx, cell_val in enumerate(row):
            if col_idx < len(headers) and headers[col_idx] and cell_val is not None and str(cell_val).strip():
                row_dict[headers[col_idx]] = cell_val
                has_data = True
        if has_data:
            records.append(row_dict)

    return records


# ---------------------------------------------------------------------------
# File grouping
# ---------------------------------------------------------------------------

def group_files_by_date():
    """
    Escanea to_process/ y agrupa archivos .xlsx por prefijo YYYYMMDD.
    Retorna dict { date_str: { 'sellOut': path, 'inventory': path } }
    """
    groups = {}
    if not os.path.isdir(TO_PROCESS_DIR):
        return groups

    for fname in os.listdir(TO_PROCESS_DIR):
        if not fname.endswith(".xlsx"):
            continue
        m = re.match(r"^(\d{8})", fname)
        if not m:
            continue
        date_str = m.group(1)
        if date_str not in groups:
            groups[date_str] = {}
        full = os.path.join(TO_PROCESS_DIR, fname)
        if "Sell Out" in fname:
            groups[date_str]["sellOut"] = full
        elif "Inventory" in fname:
            groups[date_str]["inventory"] = full

    return groups


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def deduplicate_sell_out(data):
    """
    Deduplica por Item Nbr + Store Nbr.
    Conserva el registro con mayor POS Qty (en empate conserva el último).
    Preserva Curr Traited = 1 y Curr Valid = 1 de cualquier duplicado.
    """
    dedup = {}
    dup_count = 0

    for row in data:
        key = f"{row.get('Item Nbr')}_{row.get('Store Nbr')}"
        existing = dedup.get(key)

        if existing is None:
            dedup[key] = row
        else:
            current_qty = row.get("POS Qty") or 0
            existing_qty = existing.get("POS Qty") or 0
            dup_count += 1

            selected = row if current_qty >= existing_qty else existing

            # Preservar flags = 1 de cualquier duplicado
            curr_traited = max(
                row.get("Curr Traited Store/Item Comb.") or 0,
                existing.get("Curr Traited Store/Item Comb.") or 0,
            )
            curr_valid = max(
                row.get("Curr Valid Store/Item Comb.") or 0,
                existing.get("Curr Valid Store/Item Comb.") or 0,
            )
            selected["Curr Traited Store/Item Comb."] = curr_traited
            selected["Curr Valid Store/Item Comb."] = curr_valid

            dedup[key] = selected

    return list(dedup.values()), dup_count


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def upsert_products(cur, products, upc_cache):
    """
    products: list of (upc, description) — solo los que no están en cache.
    Hace INSERT … ON CONFLICT (upc) DO UPDATE SET description.
    """
    if not products:
        return

    sql = """
        INSERT INTO products (upc, description)
        VALUES %s
        ON CONFLICT (upc) DO UPDATE SET description = EXCLUDED.description
    """
    execute_values(cur, sql, products, template="(%s, %s)")
    for upc, _ in products:
        upc_cache.add(upc)


def upsert_stores(cur, stores, store_cache):
    """
    stores: list of (id, description).
    INSERT … ON CONFLICT (id) DO UPDATE.
    """
    if not stores:
        return

    sql = """
        INSERT INTO stores (id, description)
        VALUES %s
        ON CONFLICT (id) DO UPDATE SET description = EXCLUDED.description
    """
    execute_values(cur, sql, stores, template="(%s, %s)")
    for sid, _ in stores:
        store_cache.add(sid)


def insert_daily_data(cur, rows):
    """
    Bulk insert con ON CONFLICT upsert.
    rows: list of tuples matching daily_data columns.
    """
    if not rows:
        return

    sql = """
        INSERT INTO daily_data
            (date, upc, store_id, so_units, unit_cost, so_amount,
             inv_on_hand, inv_in_transit, inv_in_warehouse, inv_on_order, cataloged)
        VALUES %s
        ON CONFLICT (date, upc, store_id)
        DO UPDATE SET
            so_units = EXCLUDED.so_units,
            unit_cost = EXCLUDED.unit_cost,
            so_amount = EXCLUDED.so_amount,
            inv_on_hand = EXCLUDED.inv_on_hand,
            inv_in_transit = EXCLUDED.inv_in_transit,
            inv_in_warehouse = EXCLUDED.inv_in_warehouse,
            inv_on_order = EXCLUDED.inv_on_order,
            cataloged = EXCLUDED.cataloged
    """
    BATCH = 1000
    for i in range(0, len(rows), BATCH):
        batch = rows[i : i + BATCH]
        execute_values(
            cur,
            sql,
            batch,
            template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        )


# ---------------------------------------------------------------------------
# Per-date processing
# ---------------------------------------------------------------------------

def safe_int(val):
    if val is None or val == "N/A":
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def safe_float(val):
    if val is None or val == "N/A":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def process_date(cur, date_str, files, upc_cache, store_cache):
    """
    Procesa un par de archivos (Sell Out + Inventory) para una fecha.
    Retorna la cantidad de filas insertadas.
    """
    if "sellOut" not in files:
        raise RuntimeError(f"Falta archivo Sell Out para {date_str}. Abortando importación.")

    # Leer archivos
    sell_out_raw = read_excel_file(files["sellOut"])
    inventory_data = read_excel_file(files["inventory"]) if "inventory" in files else []

    if "inventory" not in files:
        print(f"  WARN: falta Inventory para {date_str}, campos de inventario serán NULL")

    # Deduplicar Sell Out
    sell_out_data, dups = deduplicate_sell_out(sell_out_raw)

    if dups:
        print(f"  Sell Out: {len(sell_out_data)} filas ({dups} duplicados eliminados)")
    else:
        print(f"  Sell Out: {len(sell_out_data)} filas")
    print(f"  Inventory: {len(inventory_data)} filas")

    # Indexar inventory por Item Nbr + Store Nbr
    inv_index = {}
    for row in inventory_data:
        key = f"{row.get('Item Nbr')}_{row.get('Store Nbr')}"
        inv_index[key] = row

    # Convertir fecha YYYYMMDD → date object
    date_obj = datetime.strptime(date_str, "%Y%m%d").date()

    # ---- Recolectar productos y tiendas únicos (no cacheados) ----
    new_products = {}  # upc → description
    new_stores = {}    # store_id → description
    skipped = 0

    for row in sell_out_data:
        upc = str(row.get("UPC", "")).strip()
        store_nbr = row.get("Store Nbr")

        if not upc or not store_nbr:
            skipped += 1
            continue

        try:
            store_id = int(store_nbr)
        except (ValueError, TypeError):
            skipped += 1
            continue

        if upc not in upc_cache and upc not in new_products:
            new_products[upc] = row.get("Item Desc 1", "") or ""
        if store_id not in store_cache:
            new_stores[store_id] = row.get("Store Name", "") or ""

    if skipped:
        print(f"  WARN: {skipped} filas sin UPC o Store Nbr")

    # ---- Upsert products ----
    if new_products:
        upsert_products(
            cur,
            [(upc, desc) for upc, desc in new_products.items()],
            upc_cache,
        )

    # ---- Upsert stores ----
    if new_stores:
        upsert_stores(
            cur,
            [(sid, desc) for sid, desc in new_stores.items()],
            store_cache,
        )

    # ---- Construir filas de daily_data ----
    daily_rows = []
    for row in sell_out_data:
        upc = str(row.get("UPC", "")).strip()
        store_nbr = row.get("Store Nbr")
        if not upc or not store_nbr:
            continue
        try:
            store_id = int(store_nbr)
        except (ValueError, TypeError):
            continue

        if upc not in upc_cache:
            continue

        key = f"{row.get('Item Nbr')}_{row.get('Store Nbr')}"
        inv_row = inv_index.get(key)

        # Cataloged: Curr Traited == 1 AND Curr Valid == 1 AND Item Status == 'A'
        # Values may come as float from Excel (1.0 instead of 1)
        curr_traited = row.get("Curr Traited Store/Item Comb.") or 0
        curr_valid = row.get("Curr Valid Store/Item Comb.") or 0
        item_status = str(row.get("Item Status", "")).strip()
        cataloged = (int(curr_traited) == 1 and int(curr_valid) == 1 and item_status == "A")

        daily_rows.append((
            date_obj,
            upc,
            store_id,
            safe_int(row.get("POS Qty")),
            safe_float(row.get("Unit Cost")),
            safe_float(row.get("POS Sales")),
            safe_int(inv_row.get("Curr Str On Hand Qty")) if inv_row else None,
            safe_int(inv_row.get("Curr Str In Transit Qty")) if inv_row else None,
            safe_int(inv_row.get("Curr Str In Whse Qty")) if inv_row else None,
            safe_int(inv_row.get("Curr Str On Order Qty")) if inv_row else None,
            cataloged,
        ))

    # ---- Deduplicar por (date, upc, store_id) ----
    # Diferentes Item Nbr pueden mapear al mismo UPC.
    # Campos: 0=date, 1=upc, 2=store_id, 3=so_units, 4=unit_cost,
    #         5=so_amount, 6=inv_on_hand, 7=inv_in_transit, 8=inv_in_warehouse,
    #         9=inv_on_order, 10=cataloged
    def _safe_add(a, b):
        if a is None:
            return b
        if b is None:
            return a
        return a + b

    def _safe_max(a, b):
        if a is None:
            return b
        if b is None:
            return a
        return max(a, b)

    seen = {}
    for t in daily_rows:
        pk = (t[0], t[1], t[2])
        if pk not in seen:
            seen[pk] = list(t)
        else:
            e = seen[pk]
            e[3] = _safe_add(e[3], t[3])   # so_units: sum
            e[4] = _safe_max(e[4], t[4])    # unit_cost: max
            e[5] = _safe_add(e[5], t[5])    # so_amount: sum
            e[6] = _safe_add(e[6], t[6])    # inv_on_hand: sum
            e[7] = _safe_add(e[7], t[7])    # inv_in_transit: sum
            e[8] = _safe_add(e[8], t[8])    # inv_in_warehouse: sum
            e[9] = _safe_add(e[9], t[9])    # inv_on_order: sum
            e[10] = e[10] or t[10]          # cataloged: OR
    unique_rows = [tuple(v) for v in seen.values()]

    # ---- Bulk insert ----
    insert_daily_data(cur, unique_rows)
    print(f"  Insertadas: {len(unique_rows)} filas en daily_data (de {len(daily_rows)} pre-dedup)")

    return len(unique_rows)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("Iniciando procesamiento de datos Walmart\n")

    os.makedirs(PROCESSED_DIR, exist_ok=True)

    file_groups = group_files_by_date()
    dates = sorted(file_groups.keys())

    if not dates:
        print("No se encontraron archivos para procesar.")
        return

    print(f"Encontrados {len(dates)} grupos de archivos\n")

    conn = psycopg2.connect(DB_DSN)

    # Chequeo de continuidad: primer fecha en to_process debe ser día siguiente al último en daily_data
    cur = conn.cursor()
    cur.execute("SELECT MAX(date) FROM daily_data")
    last_db_date = cur.fetchone()[0]
    cur.close()

    if last_db_date is not None:
        expected_next = last_db_date + timedelta(days=1)
        first_file_date = datetime.strptime(dates[0], "%Y%m%d").date()
        if first_file_date != expected_next:
            conn.close()
            print(f"ERROR: Discontinuidad detectada.")
            print(f"  Último día en daily_data: {last_db_date}")
            print(f"  Primer archivo en to_process: {first_file_date}")
            print(f"  Se esperaba: {expected_next}")
            print(f"  Abortando importación.")
            return

    total_rows = 0
    upc_cache = set()    # known UPCs
    store_cache = set()  # store ids

    try:
        for date_str in dates:
            print(f"Procesando fecha: {date_str}")
            cur = conn.cursor()
            try:
                rows = process_date(
                    cur, date_str, file_groups[date_str], upc_cache, store_cache
                )
                conn.commit()
                total_rows += rows

                # Mover archivos a processed/
                for fkey in ("sellOut", "inventory"):
                    src = file_groups[date_str].get(fkey)
                    if src and os.path.exists(src):
                        shutil.move(src, os.path.join(PROCESSED_DIR, os.path.basename(src)))

                print()
            except RuntimeError:
                conn.rollback()
                raise
            except Exception as e:
                conn.rollback()
                print(f"  ERROR procesando {date_str}: {e}\n")
            finally:
                cur.close()

        # Resetear secuencia de stores para que el próximo autoincrement no colisione
        cur = conn.cursor()
        cur.execute(
            "SELECT setval('stores_id_seq', COALESCE((SELECT MAX(id) FROM stores), 1))"
        )
        conn.commit()
        cur.close()

    finally:
        conn.close()

    print(f"Proceso completado. Total de registros insertados: {total_rows}")


if __name__ == "__main__":
    main()
