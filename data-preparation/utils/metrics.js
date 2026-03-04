import { sortGroupByDate } from './grouping.js';

/**
 * Calculate key metrics for a store-product group
 * @param {Array} group - Array of rows for a specific store-product combination
 * @returns {Object} Calculated metrics
 */
export function calculateMetrics(group) {
  if (!group || group.length === 0) {
    return null;
  }

  // Sort chronologically
  const sortedGroup = sortGroupByDate([...group]);

  // Basic info
  const firstRow = sortedGroup[0];
  const lastRow = sortedGroup[sortedGroup.length - 1];

  const storeNumber = firstRow['Store Nbr'];
  const storeName = firstRow['Store Name'] || '';
  const productNumber = firstRow['Item Nbr'];
  const productName = firstRow['Item Desc 1'] || '';
  const lastDate = lastRow.date_normalized;

  // Inventory on last date
  const inHandLastDate = lastRow.on_hand_parsed || 0;
  const inTransitLastDate = lastRow.in_transit_parsed || 0;

  // Total days in history
  const totalDays = sortedGroup.length;

  // Total units sold across all history
  const totalUnitsSold = sortedGroup.reduce((sum, row) => sum + (row.pos_qty_parsed || 0), 0);

  // Average daily sales
  const avgDailySales = totalDays > 0 ? totalUnitsSold / totalDays : 0;

  // Total available inventory (in_hand + in_transit)
  const totalAvailableInventory = inHandLastDate + inTransitLastDate;

  // Days on Hand (DOH) - now includes in_transit inventory
  const doh = avgDailySales > 0 ? totalAvailableInventory / avgDailySales : (totalAvailableInventory > 0 ? 999 : 0);

  // Detect recent inventory increase (potential in_transit arrival)
  const hasRecentInventoryIncrease = detectRecentInventoryIncrease(sortedGroup, 2);

  // Consecutive days without sales (from end)
  const consecutiveDaysNoSales = countConsecutiveDaysNoSales(sortedGroup);

  // Stockout days (days where in_hand = 0)
  const stockoutDays = sortedGroup.filter(row => (row.on_hand_parsed || 0) === 0).length;

  // Sales in last 7 days
  const last7Days = sortedGroup.slice(-7);
  const salesLast7Days = last7Days.reduce((sum, row) => sum + (row.pos_qty_parsed || 0), 0);

  // Sales in last 30 days (or all available if less than 30)
  const last30Days = sortedGroup.slice(-30);
  const salesLast30Days = last30Days.reduce((sum, row) => sum + (row.pos_qty_parsed || 0), 0);
  const avgDailySalesLast30 = last30Days.length > 0 ? salesLast30Days / last30Days.length : 0;

  return {
    storeNumber,
    storeName,
    productNumber,
    productName,
    lastDate,
    totalDays,

    // Inventory metrics
    inHandLastDate,
    inTransitLastDate,
    totalAvailableInventory,
    hasRecentInventoryIncrease,

    // Sales metrics
    totalUnitsSold,
    avgDailySales,
    avgDailySalesLast30,
    salesLast7Days,
    salesLast30Days,

    // Derived metrics
    doh,
    consecutiveDaysNoSales,
    stockoutDays,

    // Raw data for further analysis
    history: sortedGroup
  };
}

/**
 * Detect if there was a recent significant inventory increase
 * (indicates potential in_transit arrival)
 * @param {Array} sortedGroup - Chronologically sorted group
 * @param {number} daysToCheck - Number of days to look back (default: 2)
 * @returns {boolean} True if significant increase detected
 */
function detectRecentInventoryIncrease(sortedGroup, daysToCheck = 2) {
  if (sortedGroup.length < daysToCheck + 1) {
    return false;
  }

  const INCREASE_THRESHOLD = 0.5; // 50% increase is significant

  // Get last N days of inventory
  const recentDays = sortedGroup.slice(-daysToCheck);
  const baselineDay = sortedGroup[sortedGroup.length - daysToCheck - 1];

  const baselineInventory = baselineDay.on_hand_parsed || 0;

  // Check if any recent day has significant increase
  for (const day of recentDays) {
    const currentInventory = day.on_hand_parsed || 0;

    if (baselineInventory > 0) {
      const increaseRate = (currentInventory - baselineInventory) / baselineInventory;
      if (increaseRate >= INCREASE_THRESHOLD) {
        return true;
      }
    } else if (currentInventory > 5) {
      // If baseline was 0 but now has inventory > 5 units, it's an increase
      return true;
    }
  }

  return false;
}

/**
 * Count consecutive days without sales starting from the end
 * @param {Array} sortedGroup - Chronologically sorted group
 * @returns {number} Number of consecutive days without sales
 */
function countConsecutiveDaysNoSales(sortedGroup) {
  let count = 0;

  // Count backwards from last date
  for (let i = sortedGroup.length - 1; i >= 0; i--) {
    const sold = sortedGroup[i].pos_qty_parsed || 0;
    if (sold > 0) {
      break; // Stop at first day with sales
    }
    count++;
  }

  return count;
}

/**
 * Calculate sell-through rate (sales / available inventory)
 * @param {Object} metrics - Metrics object
 * @returns {number} Sell-through rate (0-1)
 */
export function calculateSellThroughRate(metrics) {
  const { totalUnitsSold, inHandLastDate, totalDays } = metrics;

  if (totalDays === 0 || (totalUnitsSold + inHandLastDate) === 0) {
    return 0;
  }

  return totalUnitsSold / (totalUnitsSold + inHandLastDate);
}

/**
 * Check if product is low volume (sells < 1 unit per week on average)
 * @param {Object} metrics - Metrics object
 * @returns {boolean}
 */
export function isLowVolumeProduct(metrics) {
  const { avgDailySales } = metrics;
  const MIN_WEEKLY_SALES = 1;
  const MIN_DAILY_SALES = MIN_WEEKLY_SALES / 7; // 0.14 units/day

  return avgDailySales < MIN_DAILY_SALES;
}

/**
 * Get DOH trend (increasing, decreasing, stable)
 * Compare last 7 days vs previous period
 * @param {Array} sortedGroup - Chronologically sorted group
 * @returns {string} 'increasing', 'decreasing', or 'stable'
 */
export function getDOHTrend(sortedGroup) {
  if (sortedGroup.length < 14) {
    return 'insufficient_data';
  }

  const last7Days = sortedGroup.slice(-7);
  const previous7Days = sortedGroup.slice(-14, -7);

  const avgSalesLast7 = last7Days.reduce((sum, r) => sum + (r.pos_qty_parsed || 0), 0) / 7;
  const avgSalesPrev7 = previous7Days.reduce((sum, r) => sum + (r.pos_qty_parsed || 0), 0) / 7;

  const avgInventoryLast7 = last7Days.reduce((sum, r) => sum + (r.on_hand_parsed || 0), 0) / 7;
  const avgInventoryPrev7 = previous7Days.reduce((sum, r) => sum + (r.on_hand_parsed || 0), 0) / 7;

  const dohLast7 = avgSalesLast7 > 0 ? avgInventoryLast7 / avgSalesLast7 : 0;
  const dohPrev7 = avgSalesPrev7 > 0 ? avgInventoryPrev7 / avgSalesPrev7 : 0;

  if (dohLast7 > dohPrev7 * 1.2) return 'increasing'; // 20% increase
  if (dohLast7 < dohPrev7 * 0.8) return 'decreasing'; // 20% decrease

  return 'stable';
}
