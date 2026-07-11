web: gunicorn wellnest.wsgi:application --worker-class gthread --workers ${WEB_CONCURRENCY:-3} --threads 4 --timeout 120 --graceful-timeout 30 --max-requests 800 --max-requests-jitter 100 --worker-tmp-dir /dev/shm --bind 0.0.0.0:$PORT
release: python manage.py migrate --noinput
