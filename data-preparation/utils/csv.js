import fs from 'fs/promises';
import { createReadStream, existsSync } from 'fs';
import { parse } from 'csv-parse';

/**
 * Reads and parses the consolidado.csv file
 * Converts dates from DD/MM/YYYY to YYYY-MM-DD format
 * Returns array of row objects
 */
export async function readConsolidadoCSV(filePath = './consolidado/consolidado.csv') {
  return new Promise((resolve, reject) => {
    const rows = [];

    if (!existsSync(filePath)) {
      reject(new Error(`File not found: ${filePath}`));
      return;
    }

    createReadStream(filePath)
      .pipe(parse({
        columns: true,
        skip_empty_lines: true,
        trim: true,
        relax_quotes: true,
        relax_column_count: true
      }))
      .on('data', (row) => {
        // Convert date from DD/MM/YYYY to YYYY-MM-DD
        if (row.Fecha) {
          const [day, month, year] = row.Fecha.split('/');
          row.date_normalized = `${year}-${month.padStart(2, '0')}-${day.padStart(2, '0')}`;
        }

        // Parse numeric fields
        row.unit_cost_parsed = parseFloat(row['Unit Cost']) || 0;
        row.pos_qty_parsed = parseFloat(row['POS Qty']) || 0;
        row.on_hand_parsed = parseFloat(row['Curr Str On Hand Qty']) || 0;
        row.in_transit_parsed = parseFloat(row['Curr Str In Transit Qty']) || 0;

        rows.push(row);
      })
      .on('error', (error) => {
        reject(error);
      })
      .on('end', () => {
        console.log(`✓ Read ${rows.length.toLocaleString()} rows from ${filePath}`);
        resolve(rows);
      });
  });
}

/**
 * Initializes the output CSV file with headers
 * Creates the file if it doesn't exist, overwrites if it does
 */
export async function initializeOutputCSV(filePath = './output/anomalies.csv') {
  const headers = [
    'store_number',
    'product_number',
    'risk_score',
    'risk_label',
    'confidence',
    'anomaly_type',
    'severity',
    'start_date',
    'end_date',
    'notes'
  ].join(',');

  await fs.writeFile(filePath, headers + '\n', 'utf-8');
  console.log(`✓ Initialized output file: ${filePath}`);
}

/**
 * Appends a CSV row to the output file
 * Expects a CSV-formatted string (with or without newline)
 */
export async function appendAnomalyRow(filePath, csvRow) {
  // Ensure the row ends with a newline
  const row = csvRow.endsWith('\n') ? csvRow : csvRow + '\n';

  try {
    await fs.appendFile(filePath, row, 'utf-8');
  } catch (error) {
    console.error(`Error appending row to ${filePath}:`, error.message);
    throw error;
  }
}

/**
 * Parses a CSV response from LLM
 * Handles cases where LLM might return markdown code blocks or extra text
 */
export function parseCSVResponse(text) {
  // Remove markdown code blocks if present
  let cleaned = text.replace(/```csv\n?/g, '').replace(/```\n?/g, '');

  // Split into lines and find the first line that looks like CSV data
  const lines = cleaned.split('\n').map(l => l.trim()).filter(l => l.length > 0);

  // Look for a line with commas (CSV format)
  for (const line of lines) {
    if (line.includes(',') && !line.toLowerCase().startsWith('store_number')) {
      return line;
    }
  }

  // If we can't find a proper CSV line, return the first non-empty line
  return lines[0] || '';
}
