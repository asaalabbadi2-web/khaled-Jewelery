# Income Statement Gold Profit Analysis

## Issue
User reported that operating expenses affect "Cash Net Profit" but do not affect "Profit (Gold)".

## Investigation
1. **Database State**:
   - `InventoryCostingConfig` exists with `avg_total_cost_per_gram` = **382.59 SAR/g**.
   - `GoldPrice` table has entries.
   - Operating Expenses exist for the period (Total: **4500 SAR**).

2. **Backend Logic Verification**:
   - The code correctly calculates `expense_gold_equivalent = expense_total / gold_equivalent_rate`.
   - `summary['profit_gold']` is reduced by `expense_gold_equivalent`.

3. **API Test Results**:
   - Simulated request for `2025-11-22` to `2025-11-23`.
   - **Operating Expenses**: 4500.0 SAR
   - **Gold Equivalent Rate**: 382.5938 SAR/g
   - **Expense Gold Equivalent**: 11.762 g
   - **Profit Gold**: 20.285 g (Reduced from Gross Profit Gold)

## Conclusion
The system is working correctly. The expenses are being subtracted from the gold profit.
The user likely did not see the subtraction because the "Gross Profit (Gold)" was not displayed for comparison, or the amount was smaller than expected.

## Solution Implemented
To provide transparency, the following fields were added to the Income Statement Report UI:
1. **Expenses (Gold)**: Shows the operating expenses converted to grams.
2. **Conv. Rate**: Shows the rate used for conversion (Average Cost or Market Price).
3. **Profit (Gold) Column**: Added to the "Period Details" table to show the breakdown over time.

These changes allow the user to verify the calculation:
`Profit (Gold) = Gross Profit (Gold) - Expenses (Gold)`
