# ONE worker on B1 (1 vCPU): the ambient-transcription job registry is an in-memory
# dict (apps/scribe/services/triage_jobs.py), so the submit and the poll MUST hit the
# same process. --threads gives concurrency inside that one process (shared memory).
# Multiple workers = the poll can land on a worker that doesn't have the job -> HTTP 404
# "Not found." Going multi-worker/multi-instance later requires a DB/Redis-backed job store.
web: gunicorn wellnest.wsgi:application --worker-class gthread --workers ${WEB_CONCURRENCY:-1} --threads ${WEB_THREADS:-8} --timeout 300 --graceful-timeout 30 --max-requests 1200 --max-requests-jitter 150 --worker-tmp-dir /dev/shm --bind 0.0.0.0:$PORT
release: python manage.py migrate --noinput
