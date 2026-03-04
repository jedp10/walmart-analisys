/**
 * Computes store rankings by total sales value
 * Sales value = sum of (POS Qty × Unit Cost) across all products and dates
 * Returns Map<store_number, {rank, totalSales}>
 */
export function computeStoreRankings(rows) {
  // Aggregate sales by store
  const storeSales = new Map();

  for (const row of rows) {
    const storeNumber = row['Store Nbr'];
    const salesValue = row.pos_qty_parsed * row.unit_cost_parsed;

    if (!storeSales.has(storeNumber)) {
      storeSales.set(storeNumber, 0);
    }

    storeSales.set(storeNumber, storeSales.get(storeNumber) + salesValue);
  }

  // Sort stores by total sales (descending)
  const sortedStores = Array.from(storeSales.entries())
    .sort((a, b) => b[1] - a[1]);

  // Create ranking map
  const rankings = new Map();
  sortedStores.forEach(([storeNumber, totalSales], index) => {
    rankings.set(storeNumber, {
      rank: index + 1,
      totalSales: totalSales
    });
  });

  console.log(`✓ Computed rankings for ${rankings.size} stores`);
  console.log(`  Top store: ${sortedStores[0][0]} with $${sortedStores[0][1].toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`);

  return rankings;
}

/**
 * Computes product rankings by total sales value
 * Sales value = sum of (POS Qty × Unit Cost) across all stores and dates
 * Returns Map<product_number, {rank, totalSales}>
 */
export function computeProductRankings(rows) {
  // Aggregate sales by product
  const productSales = new Map();

  for (const row of rows) {
    const productNumber = row['Item Nbr'];
    const salesValue = row.pos_qty_parsed * row.unit_cost_parsed;

    if (!productSales.has(productNumber)) {
      productSales.set(productNumber, 0);
    }

    productSales.set(productNumber, productSales.get(productNumber) + salesValue);
  }

  // Sort products by total sales (descending)
  const sortedProducts = Array.from(productSales.entries())
    .sort((a, b) => b[1] - a[1]);

  // Create ranking map
  const rankings = new Map();
  sortedProducts.forEach(([productNumber, totalSales], index) => {
    rankings.set(productNumber, {
      rank: index + 1,
      totalSales: totalSales
    });
  });

  console.log(`✓ Computed rankings for ${rankings.size} products`);
  console.log(`  Top product: ${sortedProducts[0][0]} with $${sortedProducts[0][1].toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`);

  return rankings;
}

/**
 * Filters store-product groups to include only top-ranked combinations
 * @param {Map} groups - Map of store-product groups
 * @param {Map} storeRankings - Store rankings
 * @param {Map} productRankings - Product rankings
 * @param {number} topN - Number of top stores/products to include
 * @returns {Map} Filtered groups
 */
export function filterTopRankedGroups(groups, storeRankings, productRankings, topN) {
  const filtered = new Map();

  for (const [key, value] of groups.entries()) {
    const [storeNumber, productNumber] = key.split('_');

    const storeRank = storeRankings.get(storeNumber)?.rank || Infinity;
    const productRank = productRankings.get(productNumber)?.rank || Infinity;

    // Include if both store and product are in top N
    if (storeRank <= topN && productRank <= topN) {
      filtered.set(key, value);
    }
  }

  console.log(`✓ Filtered to ${filtered.size} groups (top ${topN} stores × top ${topN} products)`);

  return filtered;
}
