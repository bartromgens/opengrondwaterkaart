# OpenGrondWaterKaart

Interactive map showing current groundwater levels across the Netherlands.

**Stack:** Django + GeoDjango + Django REST Framework (backend) · Angular + Angular Material (frontend) · PostGIS (database)

## Data sources

- **Well locations & metadata** — [BRO Grondwatermonitoring in Samenhang](https://service.pdok.nl/tno/bro-grondwatermonitoring-in-samenhang-karakteristieken/atom/index.xml) GeoPackage via PDOK ATOM feed (TNO/BRO).
- **Measurements** — BRO REST API (`publiek.broservices.nl/gm/gld/v1`) per well, fetched incrementally. Only quality-approved (`goedgekeurd`) readings are stored, averaged to daily values in metres relative to NAP.
- **Baselines** — Computed locally from stored measurements: per-well weekly (ISO week) or monthly percentiles (p5–p95) over a configurable minimum number of years.

## Setup

### Prerequisites

- Python 3.12+
- PostgreSQL with PostGIS extension
- Node.js (for the Angular frontend)

### Backend

```bash
virtualenv --python=python3.12 env
source env/bin/activate
pip install -r requirements.txt
cp config/settings_local.py.example config/settings_local.py
# Edit config/settings_local.py — set DB credentials and SECRET_KEY
python manage.py migrate
python manage.py runserver
```

The API runs on [http://localhost:8000](http://localhost:8000).

### Frontend

```bash
cd client
npm install
npm start
```

The Angular dev server runs on [http://localhost:4200](http://localhost:4200) and proxies `/api` requests to the Django backend on port 8000.

## Data ingestion

Run these management commands in order to populate the database.

```bash
# 1. Download well locations from PDOK and sync to the database
python manage.py bootstrap_wells

# 2. Fetch measurements from the BRO API for all active wells
python manage.py fetch_measurements

# 3. (Re)compute seasonal baseline percentiles — run monthly
python manage.py compute_baselines

# 4. Classify each well relative to its historical baseline
python manage.py refresh_status

```

The `scripts/` directory contains cron-ready shell scripts for the nightly pipeline (`nightly_ingest.sh`) and monthly baseline recomputation (`monthly_baselines.sh`).
