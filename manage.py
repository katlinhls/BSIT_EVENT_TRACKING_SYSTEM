#!/usr/bin/env python
# This is the entry point for Django commands such as runserver, migrate, and createsuperuser.
import os
import sys

# Load the project settings and hand the command-line arguments to Django.
def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)

# Start Django when this file is run directly from the command line.
if __name__ == "__main__":
    main()
