# Entry point used by a WSGI web server to load the Django application.
import os
from django.core.wsgi import get_wsgi_application

# Select the project settings before creating the application callable.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
application = get_wsgi_application()
