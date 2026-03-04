/**
 * Alarm Detection Thresholds Configuration
 * Based on "Descripción Alarmas" document
 *
 * Easy to adjust without changing code logic
 */

export const ALARM_THRESHOLDS = {
  // PHANTOM STOCK / NOT DISPLAYED
  // Inventory > 0 but no sales for X consecutive days
  phantom_stock: {
    min_inventory: 1,                  // Minimum inventory to consider (units)
    consecutive_days_no_sales: 7,      // Days without sales to trigger alarm
    consecutive_days_critical: 14,     // Days without sales for critical severity
    min_historical_sales: 0.14,        // Minimum avg daily sales in last 30 days (1 unit/week)
  },

  // OVERSTOCK
  // Days on Hand (DOH) exceeding normal levels
  overstock: {
    doh_threshold_medium: 45,          // DOH > 45 days = overstock (standard retail)
    doh_threshold_high: 60,            // DOH > 60 days = high severity
    doh_threshold_critical: 90,        // DOH > 90 days = critical severity
    min_avg_sales: 0.14,               // Minimum avg daily sales to consider (1 unit/week)
  },

  // LOW INVENTORY / REPLENISHMENT OPPORTUNITY
  // DOH too low or recurrent stockouts
  low_inventory: {
    doh_threshold_medium: 5,           // DOH < 5 days = opportunity
    doh_threshold_high: 3,             // DOH < 3 days = high risk
    doh_threshold_critical: 1,         // DOH < 1 day = critical risk
    recurrent_stockout_days: 3,        // Number of stockout days in period to be "recurrent"
    min_avg_sales: 0.14,               // Minimum avg daily sales to consider (1 unit/week)
  },

  // POOR DISPLAY
  // Recent inventory arrival but no sales - display/merchandising issue
  poor_display: {
    consecutive_days_no_sales: 7,      // Days without sales after inventory arrival
    days_since_inventory_increase: 2,  // Days to check for recent inventory increase (parametrizable)
    inventory_increase_threshold: 0.5, // 50% increase in inventory = "significant"
    min_inventory: 5,                  // Minimum inventory to consider (units)
    min_historical_sales: 0.14,        // Minimum avg daily sales in last 30 days (1 unit/week)
  },

  // GENERAL SETTINGS
  general: {
    analysis_period_days: 20,          // Days to analyze (your dataset: 24/10 to 11/11)
    min_data_points: 7,                // Minimum days of data required for analysis
    low_volume_threshold: 0.14,        // Products selling < 1 unit/week are low volume
  }
};

/**
 * Helper to get DOH severity level
 */
export function getDOHSeverity(doh, type = 'overstock') {
  if (type === 'overstock') {
    const { doh_threshold_critical, doh_threshold_high, doh_threshold_medium } = ALARM_THRESHOLDS.overstock;

    if (doh >= doh_threshold_critical) return 'critical';
    if (doh >= doh_threshold_high) return 'high';
    if (doh >= doh_threshold_medium) return 'medium';
    return 'none';
  }

  if (type === 'low_inventory') {
    const { doh_threshold_critical, doh_threshold_high, doh_threshold_medium } = ALARM_THRESHOLDS.low_inventory;

    if (doh <= doh_threshold_critical) return 'critical';
    if (doh <= doh_threshold_high) return 'high';
    if (doh <= doh_threshold_medium) return 'medium';
    return 'none';
  }

  return 'none';
}

/**
 * Helper to get phantom stock severity
 */
export function getPhantomStockSeverity(daysNoSales) {
  const { consecutive_days_critical, consecutive_days_no_sales } = ALARM_THRESHOLDS.phantom_stock;

  if (daysNoSales >= consecutive_days_critical) return 'critical';
  if (daysNoSales >= consecutive_days_no_sales) return 'high';
  return 'none';
}

/**
 * Helper to get poor display severity
 */
export function getPoorDisplaySeverity(daysNoSales) {
  const { consecutive_days_no_sales } = ALARM_THRESHOLDS.poor_display;

  // Same logic as phantom stock, but always high/critical for display issues
  if (daysNoSales >= 14) return 'critical';
  if (daysNoSales >= consecutive_days_no_sales) return 'high';
  return 'none';
}
