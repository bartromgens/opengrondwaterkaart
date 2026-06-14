from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = "django-insecure-placeholder-override-in-settings-local"

DEBUG = False

ALLOWED_HOSTS: list[str] = []

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.gis",
    "rest_framework",
    "api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "NAME": "opengrondwaterkaart",
        "USER": "opengrondwaterkaart",
        "PASSWORD": "",
        "HOST": "localhost",
        "PORT": "5432",
    }
}

# Classification thresholds (empirical percentile within seasonal baseline)
SGI_THRESHOLDS = {
    "very_low": 0.10,
    "low": 0.25,
    "normal": 0.75,
    "high": 0.90,
    # above 0.90 -> very_high
}

# Minimum years of data per calendar period required to compute a baseline
SGI_MIN_YEARS = 5

# Rolling measurement retention window (days)
MEASUREMENT_RETENTION_DAYS = 9 * 365

# Mark a well stale if latest measurement is older than this many days
STALE_THRESHOLD_DAYS = 35

# PDOK GM-in-samenhang ATOM feed (used by bootstrap_wells for bulk well + GLD linking)
SAMENHANG_ATOM_URL = (
    "https://service.pdok.nl/tno/bro-grondwatermonitoring-in-samenhang-karakteristieken"
    "/atom/index.xml"
)

# BRO GLD REST API rate limit (requests per second, used by fetch_measurements)
BRO_RATE_LIMIT_RPS = 2

# Parallel BRO API workers (shared rate-limited bucket)
BRO_PARALLEL_WORKERS = 3

# Use single GLD object fetch when the time window exceeds this many days
BRO_BULK_FETCH_DAYS = 14

# Skip wells whose last observation is older than this many days
INACTIVE_WELL_DAYS = 365

# Optional minx,miny,maxx,maxy (WGS84) to limit ingest commands during local dev.
DEV_WELL_BBOX: tuple[float, float, float, float] | None = None

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"  # noqa: E501
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"
    },  # noqa: E501
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"
    },  # noqa: E501
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"
    },  # noqa: E501
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
}

try:
    from .settings_local import *  # noqa: F401 F403
except ImportError:
    pass
