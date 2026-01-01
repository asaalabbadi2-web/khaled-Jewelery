# Income Statement Update: Financial vs Weight Metrics

## Overview
The Income Statement report has been enhanced to clearly distinguish between **Financial (Cash)** metrics and **Weight (Gold)** metrics. This ensures that profit margins and other key indicators are calculated and displayed separately for both monetary value and gold weight.

## Backend Changes (`backend/routes.py`)
- **New Metrics**: Added calculation for:
  - `weight_revenue`: Total weight of gold sold.
  - `weight_cogs`: Total weight cost of goods sold.
  - `weight_gross_profit`: `weight_revenue` - `weight_cogs`.
  - `weight_expenses`: Total weight of expenses (including cash expenses converted to gold equivalent).
  - `weight_net_profit`: `weight_gross_profit` - `weight_expenses`.
  - `weight_gross_margin_pct`: Gross margin percentage based on weight.
  - `weight_net_margin_pct`: Net margin percentage based on weight.
- **API Response**: The `/api/reports/income_statement` endpoint now returns these fields in both the `summary` object and the `series` list.

## Frontend Changes (`frontend/lib/screens/reports/income_statement_report_screen.dart`)
- **Summary Card**: Split into two sections:
  - **Financial Metrics**: Net Revenue (Cash), Gross Profit (Cash), Expenses (Cash), Net Profit (Cash), Net Margin % (Cash).
  - **Weight Metrics (Gold)**: Net Revenue (Weight), Gross Profit (Weight), Expenses (Weight), Net Profit (Weight), Net Margin % (Weight).
- **Trend Charts**:
  - **Financial Trend (Cash)**: Displays Net Revenue, Expenses, and Net Profit in currency.
  - **Weight Trend (Gold)**: Displays Net Revenue, Expenses, and Net Profit in weight (grams).
- **Data Table**: Added columns for Weight Revenue and Weight Net Profit alongside the financial columns.

## Verification
- Restart the backend server to apply changes.
- Open the Income Statement report in the app.
- Verify that both Financial and Weight sections are visible and populated with data.
