/**
 * Groups rows by the combination of (Store Number, Product Number)
 * Returns Map with key: "storeNumber_productNumber", value: array of rows
 */
export function groupByStoreProduct(rows) {
  const groups = new Map();

  for (const row of rows) {
    const storeNumber = row['Store Nbr'];
    const productNumber = row['Item Nbr'];

    // Create unique key
    const key = `${storeNumber}_${productNumber}`;

    if (!groups.has(key)) {
      groups.set(key, []);
    }

    groups.get(key).push(row);
  }

  console.log(`✓ Grouped ${rows.length.toLocaleString()} rows into ${groups.size.toLocaleString()} store-product combinations`);

  return groups;
}

/**
 * Sorts a group of rows chronologically by date
 * Modifies the array in place and returns it
 */
export function sortGroupByDate(group) {
  return group.sort((a, b) => {
    const dateA = new Date(a.date_normalized);
    const dateB = new Date(b.date_normalized);
    return dateA - dateB;
  });
}

/**
 * Gets the date range for a group of rows
 * @param {Array} group - Array of rows (should be sorted by date)
 * @returns {{from: string, to: string}} Date range in YYYY-MM-DD format
 */
export function getDateRange(group) {
  if (group.length === 0) {
    return { from: '', to: '' };
  }

  // Assumes group is sorted by date
  const sortedGroup = sortGroupByDate([...group]);

  return {
    from: sortedGroup[0].date_normalized,
    to: sortedGroup[sortedGroup.length - 1].date_normalized
  };
}
