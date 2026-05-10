#!/bin/bash
cd ~/projects/phos/backend
source ~/projects/phos/backend/.venv/bin/activate
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
exec uv run celery -A app.celery_app worker \
  --concurrency=1 --loglevel=info --queues=default --pool=solo