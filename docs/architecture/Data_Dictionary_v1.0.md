# RestaurantOS Data Dictionary

## Version 1.0

Core tables:

- Calendar
- POS Sales Raw
- Menu Items
- TABC Receipts
- Austin Market
- Beverage Catalog
- Employees
- Experiments

## Data Quality Rules

1. Every table must have a stable unique identifier where possible.
2. Every financial value must reconcile to its source export.
3. Dates must use true date types.
4. Raw data tabs should never be edited directly except during controlled imports.
5. Calculated fields belong in the model layer, not raw data.
