# Image Forensic Analysis

FastAPI + React system for heuristic image forgery analysis with calibrated scoring, async task execution, and rotation-based authentication.

## Stack

- Frontend: React + Vite
- API: FastAPI
- Queue: Background executor or Celery + Redis
- DB: SQLite (local) / PostgreSQL (production)
- Migrations: Alembic

## Project Layout

```text
backend/
  app/
    api/routes.py
    core/config.py
    core/security.py
    db/models.py
    db/session.py
    services/detector.py
    services/tasks.py
    services/worker.py
    main.py

alembic/
  env.py
  versions/0001_initial_schema.py

scripts/
  benchmark_pipeline.py

benchmark/
  manifest.template.csv
```

## Environment

```env
PROJECT_NAME=Image Forensic Analysis System
SECRET_KEY=replace-this-with-a-strong-random-64-char-secret-key
DATABASE_URL=sqlite:///./forgery.sqlite
ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
UPLOAD_DIR=uploads
MAX_FILE_SIZE_MB=50
RATE_LIMIT_AUTH=20/minute
RATE_LIMIT_UPLOAD=10/minute
RATE_LIMIT_STATUS=120/minute
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7
REFRESH_COOKIE_NAME=forensic_refresh
REFRESH_COOKIE_SECURE=false
REFRESH_COOKIE_SAMESITE=lax
CSRF_COOKIE_NAME=forensic_csrf
CSRF_COOKIE_SECURE=false
CSRF_COOKIE_SAMESITE=lax
CALIBRATION_PATH=backend/app/services/calibration.json
PRODUCTION=false
USE_PROCESS_POOL=true
CELERY_ENABLED=false
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1
```

Production boot requires:

- strong `SECRET_KEY` (minimum 32 chars, non-default)
- `REFRESH_COOKIE_SECURE=true`
- `CSRF_COOKIE_SECURE=true`
- non-wildcard `ALLOWED_ORIGINS`

## Local Run

```bash
pip install -r requirements.txt
cd frontend && npm install && cd ..
alembic upgrade head
python -m uvicorn backend.main:app --reload --port 8000
```

```bash
cd frontend
npm run dev
```

## Auth Model

- Access token: short-lived bearer token kept in memory only
- Refresh token: HttpOnly cookie with rotation on `/api/auth/refresh`
- CSRF token: non-HttpOnly cookie + header validation on refresh/logout
- Session restore: frontend silently refreshes token on page reload
- Logout: `/api/auth/logout` revokes the active refresh token

## API

- `POST /api/auth/register`
- `POST /api/auth/token`
- `POST /api/auth/refresh`
- `POST /api/auth/logout`
- `POST /api/detect`
- `GET /api/progress/{task_id}`
- `GET /api/report/{task_id}`
- `GET /api/uploads/{filename}`
- `GET /api/health`

`/api/auth/token` and `/api/auth/refresh` return:

```json
{
  "access_token": "<jwt>",
  "csrf_token": "<csrf-token>",
  "token_type": "bearer"
}
```

## Benchmark + Calibration Pipeline

Run benchmark with an explicit manifest and produce:

- precision / recall / F1 / ROC-AUC
- calibrated weights and thresholds
- markdown benchmark report

```bash
python scripts/benchmark_pipeline.py \
  --manifest benchmark/manifest.csv \
  --metrics-json benchmark/latest_metrics.json \
  --metrics-md benchmark/latest_metrics.md \
  --calibration-json backend/app/services/calibration.json
```

Manifest format:

```csv
dataset,image_path,label,split
CASIA,/abs/path/img1.jpg,authentic,train
CASIA,/abs/path/img2.jpg,tampered,val
Columbia,/abs/path/img3.jpg,0,test
```

- `dataset` must be `CASIA` or `Columbia`
- `label` accepts `authentic/0` and `tampered/1`
- `split` is optional; if omitted, script creates stratified train/val/test splits
- Thresholds are selected on `val` and final metrics are reported on `test` only

The detector reads calibration from `backend/app/services/calibration.json`.

## Latest Metrics

CASIA and Columbia datasets are not bundled in this repository.  
When you run the benchmark command, generated outputs are written to:

- `benchmark/latest_metrics.json`
- `benchmark/latest_metrics.md`
