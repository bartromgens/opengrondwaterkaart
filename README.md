# OpenGrondWaterKaart

Interactive map showing groundwater levels across the Netherlands for any selected day.

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

## Classification

Wells are classified lazily per request for a user-selected day. When the API receives `GET /api/wells/?date=YYYY-MM-DD`:

1. For each active well, look up its measurement on that exact date.
2. Look up the seasonal baseline (ISO-week percentiles) for that date's week.
3. Interpolate the measurement's percentile rank within the baseline and map it to one of five classes: `very_low` / `low` / `normal` / `high` / `very_high`.
4. Wells with no measurement on the selected date, or no baseline for that week, are returned as grey (no classification).

This means comparisons are always fair: all visible colours reflect conditions on the same day.

## Data ingestion

Run these management commands in order to populate the database.

```bash
# 1. Download well locations from PDOK and sync to the database
python manage.py bootstrap_wells

# 2. Fetch measurements from the BRO API for all active wells
python manage.py fetch_measurements

# 3. (Re)compute seasonal baseline percentiles — run monthly
python manage.py compute_baselines
```

The `scripts/` directory contains cron-ready shell scripts for the nightly pipeline (`nightly_ingest.sh`) and monthly baseline recomputation (`monthly_baselines.sh`).

## Deployment

Before deploying, make sure all local commits are pushed to `origin/master`. Then run:

```bash
./deploy.sh
```

This will SSH into the production server, pull the latest code, rebuild the Docker images, restart the containers, and run `migrate` and `collectstatic`.

## Management commands on production

Run management commands inside the `api` container on the production server:

```bash
docker compose -f docker-compose.prod.yml exec api python manage.py <command>
```

For example, to trigger a manual data ingestion:

```bash
docker compose -f docker-compose.prod.yml exec api python manage.py fetch_measurements
```

## Viewing production logs

```bash
# Follow logs from all containers
docker compose -f docker-compose.prod.yml logs -f

# Follow logs from a specific container (api, client, or db)
docker compose -f docker-compose.prod.yml logs -f api
```
