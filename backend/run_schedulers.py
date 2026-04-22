"""Dedicated scheduler runner.

Use this in production as a separate process/container, so the web server
(gunicorn) can run multiple workers without duplicating scheduler jobs.

Example:
	python run_schedulers.py
"""

import os
import sys

# When run as `python backend/run_schedulers.py`, Python adds /app/backend to
# sys.path (the script directory), not /app.  Insert it explicitly so that
# sibling modules (app, schedulers, …) are importable without the `backend.` prefix.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app
from schedulers import start_all_schedulers, run_forever


def main():
	os.environ.setdefault('YASAR_ENV', os.getenv('YASAR_ENV', 'production'))
	start_all_schedulers(app)
	print('[INFO] Schedulers are running')
	run_forever()


if __name__ == '__main__':
	main()
