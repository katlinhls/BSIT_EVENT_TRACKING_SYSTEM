# Central project settings for apps, database access, templates, uploads, and email.
import os
from pathlib import Path
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

# Locate the project folder and load its local .env configuration.
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env", interpolate=False)

# Read the debug flag and signing key from the environment. A deployment requires its own key.
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("Set DJANGO_SECRET_KEY when DJANGO_DEBUG=0.")
    SECRET_KEY = "django-insecure-bsit-events-local-development-only"

# List the domain names Django accepts for incoming requests.
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
    if host.strip()
]

# Load Django features first, followed by the BSIT project apps.
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "events",
    "attendance",
    "stamps",
    "administration",
]

# Run these request handlers in order. Authentication comes before the password-change check.
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "accounts.middleware.prevent_account_page_cache",
    "accounts.middleware.RequirePasswordChangeMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "accounts.middleware.hide_debug_404_routes",
]

# Point Django to the file that connects URL paths to the apps.
ROOT_URLCONF = "config.urls"

# Find shared HTML templates and give them request, user, message, and role information.
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "accounts.access.navigation",
            ],
        },
    },
]

# Expose application entry points for synchronous and asynchronous web servers.
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Use a SQLite database in the project folder unless a database path is supplied.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("DJANGO_DB_PATH", BASE_DIR / "db.sqlite3"),
    }
}

# Check password strength when a form creates or changes a password.
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Use English labels and display dates in Manila time while Django handles timezone-aware
# timestamps.
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Manila"
USE_I18N = True
USE_TZ = True

# Static files are packaged styles and scripts. Media files are images users upload.
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
STATICFILES_DIRS = [BASE_DIR / "static"]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# These paths tell Django where to send users during sign-in and sign-out.
LOGIN_URL = "/accounts/student-login/"
LOGIN_REDIRECT_URL = "/accounts/dashboard/"
LOGOUT_REDIRECT_URL = "/"

# 25-second dynamic QR validity window.
QR_VALIDITY_SECONDS = 25

# Send email over SMTP. The .env file supplies the sending address and App Password.
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.environ.get("EMAIL_HOST", "").strip() or "smtp.gmail.com"
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "1") == "1"
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "").strip()
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_TIMEOUT = 10
sender_address = "noreply@bsit-events.local"
if EMAIL_HOST.lower() == "smtp.gmail.com":
    # Google displays app passwords in groups separated by spaces.
    EMAIL_HOST_PASSWORD = "".join(EMAIL_HOST_PASSWORD.split())
    if EMAIL_HOST_USER:
        sender_address = EMAIL_HOST_USER
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL") or f"BSIT Events <{sender_address}>"

# Use a configured site address in reset emails so the link can open the deployed app.
PASSWORD_RESET_EMAIL_CONTEXT = {} if DEBUG else {"protocol": "https"}
password_reset_origin = os.environ.get("PASSWORD_RESET_ORIGIN", "").strip()
if password_reset_origin:
    # Accept a site origin made of an HTTP or HTTPS scheme and a host.
    origin = urlsplit(password_reset_origin)
    if (
        origin.scheme not in ("http", "https")
        or not origin.hostname
        or origin.username is not None
        or origin.path not in ("", "/")
        or origin.query
        or origin.fragment
    ):
        raise ImproperlyConfigured(
            "Set PASSWORD_RESET_ORIGIN to a site address such as https://example.com."
        )
    PASSWORD_RESET_EMAIL_CONTEXT = {"protocol": origin.scheme, "domain": origin.netloc}
