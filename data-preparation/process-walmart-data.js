import ExcelJS from 'exceljs';
import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const DATA_SOURCE_DIR = path.join(__dirname, 'data-source');
const OUTPUT_DIR = path.join(__dirname, 'output');
const OUTPUT_FILE = path.join(OUTPUT_DIR, 'consolidado.csv');

/**
 * Encuentra la fila del header en el archivo Excel
 */
function findHeaderRow(worksheet) {
  for (let i = 1; i <= Math.min(30, worksheet.rowCount); i++) {
    const row = worksheet.getRow(i);
    const values = [];

    row.eachCell({ includeEmpty: false }, (cell) => {
      if (cell.value) {
        values.push(cell.value.toString());
      }
    });

    // El header es la fila que contiene "Consumer ID" y "Item Nbr" entre sus valores
    const hasConsumerId = values.some(v => v.includes('Consumer ID'));
    const hasItemNbr = values.some(v => v.includes('Item Nbr'));

    if (hasConsumerId && hasItemNbr && values.length > 10) {
      return i;
    }
  }

  return 1; // Fallback a la primera fila
}

/**
 * Lee un archivo Excel y retorna las filas como array de objetos
 */
async function readExcelFile(filePath) {
  const workbook = new ExcelJS.Workbook();
  await workbook.xlsx.readFile(filePath);

  const worksheet = workbook.worksheets[0]; // Primera hoja
  const rows = [];

  // Encontrar la fila del header
  const headerRowIndex = findHeaderRow(worksheet);
  const headerRow = worksheet.getRow(headerRowIndex);

  // Obtener headers
  const headers = [];
  headerRow.eachCell({ includeEmpty: false }, (cell) => {
    if (cell.value) {
      headers.push(cell.value.toString().trim());
    }
  });

  // Leer datos (empezando desde la fila después del header)
  for (let i = headerRowIndex + 1; i <= worksheet.rowCount; i++) {
    const row = worksheet.getRow(i);
    const rowData = {};
    let hasData = false;

    row.eachCell({ includeEmpty: false }, (cell, colNumber) => {
      const header = headers[colNumber - 1];
      if (header && cell.value !== null && cell.value !== undefined) {
        rowData[header] = cell.value;
        hasData = true;
      }
    });

    // Solo agregar filas que tengan datos
    if (hasData) {
      rows.push(rowData);
    }
  }

  return rows;
}

/**
 * Agrupa archivos por fecha
 */
async function groupFilesByDate() {
  const files = await fs.readdir(DATA_SOURCE_DIR);
  const fileGroups = {};

  for (const file of files) {
    if (!file.endsWith('.xlsx')) continue;

    // Extraer fecha del nombre del archivo (formato: YYYYMMDD)
    const dateMatch = file.match(/^(\d{8})/);
    if (!dateMatch) continue;

    const date = dateMatch[1];

    if (!fileGroups[date]) {
      fileGroups[date] = {};
    }

    if (file.includes('Sell Out')) {
      fileGroups[date].sellOut = path.join(DATA_SOURCE_DIR, file);
    } else if (file.includes('Inventory')) {
      fileGroups[date].inventory = path.join(DATA_SOURCE_DIR, file);
    }
  }

  return fileGroups;
}

/**
 * Elimina duplicados del Sell Out conservando el registro con mayor POS Qty
 * Preserva Curr Traited = 1 y Curr Valid = 1 si existen en cualquier duplicado
 * En caso de empate, conserva el último registro encontrado
 */
function deduplicateSellOut(sellOutData) {
  const deduplicatedMap = new Map();
  let duplicatesCount = 0;

  for (const row of sellOutData) {
    const key = `${row['Item Nbr']}_${row['Store Nbr']}`;
    const existingRow = deduplicatedMap.get(key);

    if (!existingRow) {
      // Primera vez que vemos esta combinación Item+Store
      deduplicatedMap.set(key, row);
    } else {
      // Ya existe, comparar POS Qty
      const currentQty = row['POS Qty'] || 0;
      const existingQty = existingRow['POS Qty'] || 0;

      // Determinar qué registro tiene mayor venta
      let selectedRow;
      if (currentQty > existingQty) {
        selectedRow = row;
        duplicatesCount++;
      } else if (currentQty === existingQty) {
        selectedRow = row;
        duplicatesCount++;
      } else {
        selectedRow = existingRow;
        duplicatesCount++;
      }

      // Preservar valores = 1 de campos críticos de cualquier duplicado
      const currTraited = Math.max(
        row['Curr Traited Store/Item Comb.'] || 0,
        existingRow['Curr Traited Store/Item Comb.'] || 0
      );
      const currValid = Math.max(
        row['Curr Valid Store/Item Comb.'] || 0,
        existingRow['Curr Valid Store/Item Comb.'] || 0
      );

      // Sobrescribir campos críticos en el registro seleccionado
      selectedRow['Curr Traited Store/Item Comb.'] = currTraited;
      selectedRow['Curr Valid Store/Item Comb.'] = currValid;

      deduplicatedMap.set(key, selectedRow);
    }
  }

  return {
    data: Array.from(deduplicatedMap.values()),
    duplicatesRemoved: duplicatesCount
  };
}

/**
 * Procesa un par de archivos (sell-out e inventario) para una fecha
 */
async function processDateFiles(date, files) {
  console.log(`Procesando fecha: ${date}`);

  if (!files.sellOut || !files.inventory) {
    console.warn(`  ⚠️  Archivos incompletos para la fecha ${date}`);
    return [];
  }

  // Leer ambos archivos
  const sellOutDataRaw = await readExcelFile(files.sellOut);
  const inventoryData = await readExcelFile(files.inventory);

  // Deduplicar Sell Out
  const { data: sellOutData, duplicatesRemoved } = deduplicateSellOut(sellOutDataRaw);

  // Logging mejorado
  if (duplicatesRemoved > 0) {
    console.log(`  - Sell Out: ${sellOutData.length} filas (eliminados ${duplicatesRemoved} duplicados)`);
  } else {
    console.log(`  - Sell Out: ${sellOutData.length} filas`);
  }
  console.log(`  - Inventory: ${inventoryData.length} filas`);

  // Crear índice de inventario por Item Nbr + Store Nbr para búsqueda rápida
  const inventoryIndex = new Map();
  for (const row of inventoryData) {
    const key = `${row['Item Nbr']}_${row['Store Nbr']}`;
    inventoryIndex.set(key, row);
  }

  // Combinar datos
  const consolidatedData = [];

  for (const sellOutRow of sellOutData) {
    const key = `${sellOutRow['Item Nbr']}_${sellOutRow['Store Nbr']}`;
    const inventoryRow = inventoryIndex.get(key);

    // Calcular Catalogado desde el Sell Out
    // Condiciones: Curr Traited = 1, Curr Valid = 1, y Item Status = "A"
    const currTraited = sellOutRow['Curr Traited Store/Item Comb.'];
    const currValid = sellOutRow['Curr Valid Store/Item Comb.'];
    const itemStatus = sellOutRow['Item Status'];
    const catalogado = (currTraited === 1 && currValid === 1 && itemStatus === 'A') ? 1 : 0;

    // Formatear fecha (YYYYMMDD -> DD/MM/YYYY)
    const formattedDate = `${date.substring(6, 8)}/${date.substring(4, 6)}/${date.substring(0, 4)}`;

    // Crear fila consolidada
    // Usar inventario del archivo de inventario si existe, sino del sell out
    const consolidatedRow = {
      'Fecha': formattedDate,
      'Item Nbr': sellOutRow['Item Nbr'] || '',
      'Item Desc 1': sellOutRow['Item Desc 1'] || '',
      'UPC': sellOutRow['UPC'] || '',
      'Store Nbr': sellOutRow['Store Nbr'] || '',
      'Store Name': sellOutRow['Store Name'] || '',
      'Unit Cost': sellOutRow['Unit Cost'] || 0,
      'POS Sales': sellOutRow['POS Sales'] || 0,
      'POS Qty': sellOutRow['POS Qty'] || 0,
      'Curr Str On Hand Qty': inventoryRow ? (inventoryRow['Curr Str On Hand Qty'] || 0) : 'N/A',
      'Curr Str In Transit Qty': inventoryRow ? (inventoryRow['Curr Str In Transit Qty'] || 0) : 'N/A',
      'Curr Str In Whse Qty': inventoryRow ? (inventoryRow['Curr Str In Whse Qty'] || 0) : 'N/A',
      'Curr Str On Order Qty': inventoryRow ? (inventoryRow['Curr Str On Order Qty'] || 0) : 'N/A',
      'Catalogado': catalogado,
      'Item Status': sellOutRow['Item Status'] || '',
      'Curr Traited Store/Item Comb.': sellOutRow['Curr Traited Store/Item Comb.'] || 0,
      'Curr Valid Store/Item Comb.': sellOutRow['Curr Valid Store/Item Comb.'] || 0
    };

    consolidatedData.push(consolidatedRow);
  }

  console.log(`  ✓ Consolidado: ${consolidatedData.length} filas`);
  return consolidatedData;
}

/**
 * Convierte array de objetos a formato CSV
 */
function arrayToCSV(data) {
  if (data.length === 0) return '';

  const headers = Object.keys(data[0]);
  const csvRows = [];

  // Header
  csvRows.push(headers.join(','));

  // Data rows
  for (const row of data) {
    const values = headers.map(header => {
      const value = row[header];
      // Escapar comillas y valores con comas
      if (typeof value === 'string' && (value.includes(',') || value.includes('"'))) {
        return `"${value.replace(/"/g, '""')}"`;
      }
      return value;
    });
    csvRows.push(values.join(','));
  }

  return csvRows.join('\n');
}

/**
 * Función principal
 */
async function main() {
  try {
    console.log('🚀 Iniciando procesamiento de datos Walmart\n');

    // Crear carpeta de salida si no existe
    await fs.mkdir(OUTPUT_DIR, { recursive: true });

    // Eliminar archivo de salida anterior si existe
    try {
      await fs.unlink(OUTPUT_FILE);
      console.log('🗑️  Archivo anterior eliminado\n');
    } catch (err) {
      // Archivo no existe, continuar
    }

    // Agrupar archivos por fecha
    const fileGroups = await groupFilesByDate();
    const dates = Object.keys(fileGroups).sort();

    console.log(`📁 Encontrados ${dates.length} grupos de archivos\n`);

    // Procesar cada fecha
    let allConsolidatedData = [];

    for (const date of dates) {
      const consolidatedData = await processDateFiles(date, fileGroups[date]);
      allConsolidatedData = allConsolidatedData.concat(consolidatedData);
    }

    // Escribir CSV consolidado
    console.log(`\n💾 Escribiendo archivo consolidado...`);
    const csv = arrayToCSV(allConsolidatedData);
    await fs.writeFile(OUTPUT_FILE, csv, 'utf-8');

    console.log(`✅ Proceso completado!`);
    console.log(`📊 Total de registros: ${allConsolidatedData.length}`);
    console.log(`📄 Archivo generado: ${OUTPUT_FILE}`);

  } catch (error) {
    console.error('❌ Error:', error);
    process.exit(1);
  }
}

// Ejecutar
main();
