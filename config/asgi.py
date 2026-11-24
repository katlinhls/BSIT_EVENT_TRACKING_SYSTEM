# Entry point used by an ASGI web server to load the Django application.
import os
from django.core.asgi import get_asgi_application

# Select the project settings before creating the application callable.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
application = get_asgi_application()
