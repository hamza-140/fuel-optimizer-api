# Fuel-price CSV analysis

Notes on `fuel-prices-for-be-assessment.csv` shipped with this project.

## Structure

- Rows: **8,151**
- Columns: **7**
- Missing values: **0** across all supplied columns
- Exact duplicate rows: **26** (8,125 distinct rows after exact deduplication)
- Distinct city/state combinations: **4,275**
- Columns: `OPIS Truckstop ID`, `Truckstop Name`, `Address`, `City`, `State`, `Rack ID`, `Retail Price`
- Coordinates: **not supplied**; latitude and longitude must be added before spatial route matching.

## Geographic coverage

The file contains 57 two-letter values in the `State` column. Nine are Canadian province/territory codes: `AB`, `BC`, `MB`, `NB`, `NS`, `ON`, `QC`, `SK`, and `YT`. The API targets US routes, so the importer keeps US state rows only:

- US rows: **7,531**
- Non-US rows excluded: **620**
- US state codes present: **48** (the dataset does not include every US state)

## Price distribution

Across the full dataset:

- Minimum: **$2.6873/gallon**
- Median: **$3.4323/gallon**
- Mean: **$3.4990/gallon**
- Maximum: **$6.3990/gallon**

For US-state rows only:

- Minimum: **$2.6873/gallon**
- Mean: **$3.4324/gallon**
- Maximum: **$6.3990/gallon**

These are statistics for the supplied snapshot, not live fuel prices.

## Data-quality considerations

1. `OPIS Truckstop ID` is not unique: the same ID appears with different names and/or prices.
2. Some station names and addresses describe interstate exits rather than standardized street addresses.
3. The importer preserves distinct price records using the OPIS ID, name, city, state, rack ID, and price as its lookup key; exact duplicate records collapse.
4. Because coordinates are missing, setup geocodes each unique City+State with free geocoders (Open-Meteo / Nominatim) and stores results locally. That is accurate enough for corridor screening, not for claiming an exact truck-stop driveway.
5. The provided dataset is a snapshot. The API does not refresh prices in real time.
