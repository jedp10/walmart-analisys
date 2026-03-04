import { parse } from 'csv-parse';
import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const OUTPUT_DIR = path.join(__dirname, 'output');
const INPUT_FILE = path.join(OUTPUT_DIR, 'consolidado.csv');
const OUTPUT_FILE = path.join(OUTPUT_DIR, 'dead-inventory-by-day.csv');
const SETTINGS_FILE = path.join(__dirname, 'settings.json');

/**
 * Lee el archivo de configuración settings.json
 */
async function loadSettings() {
  const content = await fs.readFile(SETTINGS_FILE, 'utf-8');
  return JSON.parse(content);
}

/**
 * Obtiene el umbral de días sin ventas según la severidad
 */
function getDaysThreshold(settings, severity) {
  const severities = settings.alarms.dead_inventory.severities;
  const config = severities.find(s => s.severity === severity);
  return config ? config.days_without_sales_threshold : severity;
}

/**
 * Parsea una fecha en formato DD/MM/YYYY a un objeto Date
 */
function parseDate(dateStr) {
  const [day, month, year] = dateStr.split('/').map(Number);
  return new Date(year, month - 1, day);
}

/**
 * Formatea una fecha a DD/MM/YYYY
 */
function formatDate(date) {
  const day = String(date.getDate()).padStart(2, '0');
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const year = date.getFullYear();
  return `${day}/${month}/${year}`;
}

/**
 * Convierte un valor a número, tratando N/A y vacíos como 0
 */
function toNumber(value) {
  if (value === 'N/A' || value === '' || value === undefined || value === null) {
    return 0;
  }
  const num = parseFloat(String(value).replace(',', '.'));
  return isNaN(num) ? 0 : num;
}

/**
 * Lee el archivo CSV y retorna un array de registros
 */
async function readCSV(filePath) {
  const fileContent = await fs.readFile(filePath, 'utf-8');

  return new Promise((resolve, reject) => {
    parse(fileContent, {
      columns: true,
      skip_empty_lines: true,
      trim: true
    }, (err, records) => {
      if (err) reject(err);
      else resolve(records);
    });
  });
}

/**
 * Agrupa los registros por combinación UPC+Store
 */
function groupByUpcStore(records) {
  const groups = new Map();

  for (const record of records) {
    const key = `${record['UPC']}|${record['Store Nbr']}`;

    if (!groups.has(key)) {
      groups.set(key, []);
    }

    groups.get(key).push({
      fecha: parseDate(record['Fecha']),
      fechaStr: record['Fecha'],
      itemNbr: record['Item Nbr'],
      itemDesc: record['Item Desc 1'],
      upc: record['UPC'],
      storeNbr: record['Store Nbr'],
      storeName: record['Store Name'],
      posQty: toNumber(record['POS Qty']),
      posSales: toNumber(record['POS Sales']),
      stock: toNumber(record['Curr Str On Hand Qty']),
      inTransit: record['Curr Str In Transit Qty'],
      catalogado: toNumber(record['Catalogado'])
    });
  }

  // Ordenar cada grupo por fecha
  for (const [key, items] of groups) {
    items.sort((a, b) => a.fecha - b.fecha);
  }

  return groups;
}

/**
 * Obtiene todas las fechas únicas ordenadas
 */
function getUniqueDates(records) {
  const dateSet = new Set();
  for (const record of records) {
    dateSet.add(record['Fecha']);
  }

  const dates = Array.from(dateSet)
    .map(d => ({ str: d, date: parseDate(d) }))
    .sort((a, b) => a.date - b.date);

  return dates;
}

/**
 * Indexa registros por fecha para acceso rápido
 */
function indexByDate(records) {
  const index = new Map();

  for (const record of records) {
    const dateStr = record['Fecha'];
    if (!index.has(dateStr)) {
      index.set(dateStr, []);
    }
    index.get(dateStr).push(record);
  }

  return index;
}

/**
 * Calcula el quintil (1-5) basado en el porcentaje acumulado "piso"
 * El piso es el % acumulado ANTES de sumar el elemento actual
 * Quintil 1 = top 20% de facturación
 */
function getQuintileByRevenue(floorPercent) {
  if (floorPercent < 0.20) return 1;
  if (floorPercent < 0.40) return 2;
  if (floorPercent < 0.60) return 3;
  if (floorPercent < 0.80) return 4;
  return 5;
}

/**
 * Calcula quintiles por volumen de facturación
 * Los elementos se ordenan por facturación descendente y se asigna
 * quintil basado en el % acumulado "piso" (acumulado anterior)
 */
function calculateRevenueQuintiles(salesMap) {
  const total = Array.from(salesMap.values()).reduce((a, b) => a + b, 0);
  if (total === 0) return new Map();

  // Ordenar por facturación descendente
  const sorted = Array.from(salesMap.entries())
    .sort((a, b) => b[1] - a[1]);

  // Asignar quintiles usando el "piso" (% acumulado anterior)
  const quintiles = new Map();
  let accumulatedPercent = 0;

  for (const [key, sales] of sorted) {
    quintiles.set(key, getQuintileByRevenue(accumulatedPercent));
    accumulatedPercent += sales / total;
  }

  return quintiles;
}

/**
 * Calcula rankings de productos (por UPC) y tiendas para el período de historial
 */
function calculateRankings(dateIndex, dates, endDateIndex, historyDays) {
  const startDateIndex = Math.max(0, endDateIndex - historyDays);

  const productSales = new Map(); // UPC -> total sales
  const storeSales = new Map();   // storeNbr -> total sales

  for (let i = startDateIndex; i < endDateIndex; i++) {
    const dateStr = dates[i].str;
    const records = dateIndex.get(dateStr) || [];

    for (const record of records) {
      // Solo considerar productos catalogados para quintiles
      if (toNumber(record['Catalogado']) !== 1) continue;

      const sales = toNumber(record['POS Sales']);
      const upc = record['UPC'];
      const storeNbr = record['Store Nbr'];

      productSales.set(upc, (productSales.get(upc) || 0) + sales);
      storeSales.set(storeNbr, (storeSales.get(storeNbr) || 0) + sales);
    }
  }

  // Calcular quintiles por volumen de facturación
  const productQuintiles = calculateRevenueQuintiles(productSales);
  const storeQuintiles = calculateRevenueQuintiles(storeSales);

  return {
    productSales,
    storeSales,
    productQuintiles,
    storeQuintiles
  };
}

/**
 * Cuenta los días consecutivos de stock inmovilizado hacia atrás
 */
function countConsecutiveDeadDays(items, currentIndex) {
  let count = 0;

  for (let i = currentIndex; i >= 0; i--) {
    const item = items[i];
    if (item.posQty === 0 && item.stock > 0) {
      count++;
    } else {
      break;
    }
  }

  return count;
}

/**
 * Detecta si hubo aumento de stock durante el período sin ventas
 * Retorna true si en algún día del período el stock subió respecto al día anterior
 */
function detectarMalaExhibicion(items, currentIndex, diasAlarma) {
  const startIndex = currentIndex - diasAlarma + 1;

  for (let i = startIndex; i <= currentIndex; i++) {
    if (i > 0 && items[i].stock > items[i - 1].stock) {
      return true;
    }
  }

  return false;
}

/**
 * Calcula el promedio de los últimos N días
 */
function calculateAverage(items, endIndex, days, field) {
  const startIndex = Math.max(0, endIndex - days);
  let sum = 0;
  let count = 0;

  for (let i = startIndex; i < endIndex; i++) {
    sum += items[i][field];
    count++;
  }

  return count > 0 ? sum / count : 0;
}

/**
 * Procesa los datos y genera las alertas de stock inmovilizado
 */
async function generateDeadInventoryReport() {
  console.log('Cargando configuración...');
  const settings = await loadSettings();
  console.log('Configuración cargada.');

  console.log('Leyendo archivo consolidado...');
  const records = await readCSV(INPUT_FILE);
  console.log(`Registros leídos: ${records.length}`);

  console.log('Agrupando por UPC+Store...');
  const groups = groupByUpcStore(records);
  console.log(`Combinaciones UPC+Store: ${groups.size}`);

  console.log('Obteniendo fechas únicas...');
  const dates = getUniqueDates(records);
  console.log(`Fechas disponibles: ${dates.length} (${dates[0].str} - ${dates[dates.length - 1].str})`);

  console.log('Indexando por fecha...');
  const dateIndex = indexByDate(records);

  // Crear mapa de fecha string a índice
  const dateToIndex = new Map();
  dates.forEach((d, i) => dateToIndex.set(d.str, i));

  // Obtener configuración de ventana de historial (configuración global)
  const historyWindow = settings.history_window;
  const minDays = historyWindow.min_days;
  const maxDays = historyWindow.max_days;

  // Validar que hay suficientes días para la ventana mínima
  if (dates.length - 1 < minDays) {
    console.log(`Error: Se necesitan al menos ${minDays + 1} días de datos. Solo hay ${dates.length} días.`);
    return;
  }

  console.log(`Ventana de historial: crece de ${minDays} a ${maxDays} días`);

  const alerts = [];

  // Iterar desde el día siguiente al mínimo de historial hasta el último día
  const startDayIndex = minDays;

  console.log(`Procesando días ${startDayIndex + 1} a ${dates.length}...`);

  for (let dayIndex = startDayIndex; dayIndex < dates.length; dayIndex++) {
    const currentDate = dates[dayIndex];

    // Calcular ventana de historial efectiva (crece de minDays a maxDays)
    const effectiveHistoryDays = Math.min(dayIndex, maxDays);

    // Calcular rankings para el período de historial
    const rankings = calculateRankings(dateIndex, dates, dayIndex, effectiveHistoryDays);

    // Evaluar cada combinación UPC+Store
    for (const [, items] of groups) {
      // Verificar que tenga suficientes días de datos
      if (items.length < minDays + 1) continue;

      // Encontrar el registro del día actual
      const currentItem = items.find(item => item.fechaStr === currentDate.str);
      if (!currentItem) continue;

      // Verificar condición básica: sin ventas y con stock
      const isDeadToday = currentItem.posQty === 0 && currentItem.stock > 0;
      if (!isDeadToday) continue;

      // Solo generar alarmas para productos catalogados
      if (currentItem.catalogado !== 1) continue;

      // Encontrar índice del item actual en su grupo
      const currentItemIndex = items.findIndex(item => item.fechaStr === currentDate.str);

      // Calcular días de alarma (días consecutivos sin ventas con stock)
      const diasAlarma = countConsecutiveDeadDays(items, currentItemIndex);

      // Calcular severidad usando quintiles por volumen de facturación
      const productQuintile = rankings.productQuintiles.get(currentItem.upc) || 5;
      const storeQuintile = rankings.storeQuintiles.get(currentItem.storeNbr) || 5;

      // Severidad: suma de quintiles, mapeado a 1-10
      const severidad = Math.min(10, Math.max(1, productQuintile + storeQuintile - 1));

      // Obtener umbral de días sin ventas según la severidad
      const threshold = getDaysThreshold(settings, severidad);

      // Solo generar alarma si los días sin ventas alcanzan el umbral
      if (diasAlarma < threshold) continue;

      // Determinar tipo de alarma: Mala exhibición si hubo aumento de stock durante el período sin ventas
      const alarma = detectarMalaExhibicion(items, currentItemIndex, diasAlarma)
        ? 'Mala exhibición'
        : 'Stock Inmovilizado';

      // Calcular promedios del período de historial
      const avgQty = calculateAverage(items, currentItemIndex, effectiveHistoryDays, 'posQty');
      const avgSales = calculateAverage(items, currentItemIndex, effectiveHistoryDays, 'posSales');

      alerts.push({
        fecha: currentDate.str,
        itemNbr: currentItem.itemNbr,
        itemDesc: currentItem.itemDesc,
        upc: currentItem.upc,
        storeNbr: currentItem.storeNbr,
        storeName: currentItem.storeName,
        alarma,
        avgQty: avgQty.toFixed(2),
        avgSales: avgSales.toFixed(2),
        diasAlarma,
        severidad,
        qUpc: productQuintile,
        qStore: storeQuintile,
        inTransit: currentItem.inTransit
      });
    }

    if ((dayIndex - startDayIndex + 1) % 5 === 0) {
      console.log(`  Procesado día ${dayIndex - startDayIndex + 1} de ${dates.length - startDayIndex}`);
    }
  }

  console.log(`\nAlertas generadas: ${alerts.length}`);

  // Generar CSV de salida
  const header = [
    'Fecha',
    'Item Nbr',
    'Item Desc 1',
    'UPC',
    'Store Nbr',
    'Store Name',
    'Alarma',
    'Sell out Promedio Un.',
    'Sell out Promedio $',
    'Días de alarma',
    'Severidad',
    'Q. UPC',
    'Q. Store',
    'Curr Str In Transit Qty'
  ].join(',');

  const rows = alerts.map(a => [
    a.fecha,
    a.itemNbr,
    `"${a.itemDesc}"`,
    a.upc,
    a.storeNbr,
    `"${a.storeName}"`,
    a.alarma,
    a.avgQty,
    a.avgSales,
    a.diasAlarma,
    a.severidad,
    a.qUpc,
    a.qStore,
    a.inTransit
  ].join(','));

  const csvContent = [header, ...rows].join('\n');

  await fs.writeFile(OUTPUT_FILE, csvContent, 'utf-8');
  console.log(`\nArchivo generado: ${OUTPUT_FILE}`);
}

// Ejecutar
generateDeadInventoryReport().catch(console.error);
