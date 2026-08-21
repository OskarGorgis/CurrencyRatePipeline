# Currency Rate Pipeline

A small medallion-architecture (raw → bronze → silver → gold) data pipeline that pulls PLN exchange rates from the [NBP API](https://api.nbp.pl/) and produces charts + insights for four currencies: EUR, USD, GBP, JPY.

```
NBP API
  │  nbp_client.py (HTTP + retry)
  ▼
tables/raw/{quarter}.json      raw JSON, 1 file per calendar quarter
  ▼
tables/bronze/rates.parquet    long format: date, currency, mid
  ▼
tables/silver/rates.parquet    wide format: date + one column per currency
  ▼
tables/gold/rates.parquet      long format, 4 target currencies + daily change
  ▼
charts/*.jpg + stdout          dynamics charts + answers to 4 summary questions
```


## Setup

Requires [conda](https://docs.conda.io/). Create the environment from the committed spec:

```bash
conda env create -f environment.yml
conda activate currency-rate-pipeline
```

This installs Python 3.11, pandas, pyarrow, requests, matplotlib, and pytest.

## Running the pipeline

```bash
python main.py --mode full --year 2025   # ingest Jan 1 of --year through today, then rebuild everything
python main.py --mode daily              # refresh only yesterday's data, then rebuild everything
```

Both modes end with the same rebuild step (bronze → silver → gold → charts/insights), so the output is always consistent regardless of which mode you ran. `--year` defaults to `2021` and is ignored (with a warning) in `--mode daily`.

Output lands in `tables/` (parquet at each layer) and `charts/` (`dynamics_by_currency.jpg`, `dynamics_indexed.jpg`); summary insights are printed to stdout.

Individual layers can also be run directly, e.g. `python ingest_bronze.py --start-date 2024-01-01 --end-date 2024-06-30`.

## Tests

```bash
pytest
```

Tests never hit the real NBP API or the real `tables/`/`charts/` directories — HTTP calls are mocked and file paths are redirected to a temp directory per test.
