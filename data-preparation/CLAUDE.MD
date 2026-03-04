# Walmart Retail Analysis System

## Overview

This is a data analysis system for Walmart retail operations that processes daily sell-out and inventory data into a unified CSV dataset.

## What It Does

The system consolidates data from daily Walmart sell-out and inventory Excel files into a unified CSV dataset for further analysis.

## Project Structure

```
walmart-analysis/
├── data-source/                  # Excel files (YYYYMMDD format)
│   ├── 20251024 Sell Out Diario.xlsx
│   ├── 20251024 Inventory POS Diario.xlsx
│   └── ... (paired sell-out and inventory files)
├── output/
│   └── consolidado.csv           # Consolidated data output
├── utils/
│   ├── csv.js                    # CSV reading utilities
│   ├── grouping.js               # Data grouping functions
│   ├── metrics.js                # Metric calculations (DOH, sales, etc.)
│   └── ranking.js                # Store and product ranking
├── process-walmart-data.js       # Main consolidation script
└── package.json                  # Dependencies
```

## Key Features

### Data Consolidation

- **Automatic File Pairing**: Matches Sell Out and Inventory files by date (YYYYMMDD prefix)
- **Smart Header Detection**: Finds headers dynamically even if Excel files have metadata rows
- **Duplicate Handling**: Deduplicates sell-out records by Item+Store, preserving highest sales and critical flags
- **Field Calculation**: Computes "Catalogado" status based on business rules (Curr Traited=1, Curr Valid=1, Item Status='A')
- **Data Merging**: Combines inventory metrics with sell-out data for comprehensive analysis

## Installation

```bash
npm install
```

Dependencies:
- `exceljs`: Excel file parsing
- `csv-parse`: CSV parsing

## Usage

Place paired Excel files in `data-source/` with naming convention:
```
YYYYMMDD Sell Out Diario.xlsx
YYYYMMDD Inventory POS Diario.xlsx
```

Run consolidation:
```bash
npm run process
# or
node process-walmart-data.js
```

Output: `output/consolidado.csv` with columns:
- Fecha, Item Nbr, Item Desc 1, Item Status, UPC
- Store Nbr, Store Name, Unit Cost
- POS Sales, POS Qty (units sold)
- Curr Str On Hand Qty (inventory on-hand)
- Curr Str In Transit Qty (inventory in-transit)
- Curr Str In Whse Qty (inventory in warehouse)
- Curr Str On Order Qty (inventory on order)
- Catalogado (1 = active catalog item)

## Key Metrics Explained

### Days on Hand (DOH)
```
DOH = (On-Hand Inventory + In-Transit Inventory) / Average Daily Sales
```
Indicates how many days current inventory will last at current sales velocity.

### Catalogado Status
A product is "Catalogado" (active in catalog) when:
- `Curr Traited Store/Item Comb. = 1`
- `Curr Valid Store/Item Comb. = 1`
- `Item Status = 'A'`

Calculation: `process-walmart-data.js:212-217`

## Data Flow

1. **Input**: Daily Excel files from Walmart (Sell Out + Inventory)
2. **Consolidation**: Merge by Item Nbr + Store Nbr + Date
3. **Output**: CSV with consolidated data for analysis

## Technical Highlights

- **ES Modules**: Modern JavaScript with import/export
- **Defensive Coding**: Handles missing data, malformed files, edge cases

## Author Notes

- Written in Spanish comments for team collaboration
- Handles real Walmart data format quirks (metadata rows, inconsistent headers)
- Deduplication logic preserves critical business flags

## License

ISC
