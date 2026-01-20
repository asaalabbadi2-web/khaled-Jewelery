"""Dedicated scheduler runner.

Use this in production as a separate process/container, so the web server
(gunicorn) can run multiple workers without duplicating scheduler jobs.

Example:
	python run_schedulers.py
"""

import os

from backend.app import app
from backend.schedulers import start_all_schedulers, run_forever


def main():
	os.environ.setdefault('YASAR_ENV', os.getenv('YASAR_ENV', 'production'))
	start_all_schedulers(app)
	print('[INFO] Schedulers are running')
	run_forever()


if __name__ == '__main__':
	main()
