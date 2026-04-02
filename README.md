# Image Forgery Detection System

Forensic image analysis pipeline that combines classical signals and CNN inference.

## What It Does

- Error Level Analysis (ELA) highlights JPEG recompression inconsistencies.
- Copy-move detection uses ORB feature matching to detect duplicated regions.
- Wavelet noise residue estimates high-frequency entropy anomalies.
- CNN inference adds a learned tamper probability signal.
- Final verdict is a weighted fusion of all four signals.

If the ONNX model is missing or fails at runtime, the pipeline uses a neutral CNN score (`0.5`) and continues.

## Limitations

- Performance depends heavily on image quality and source.
- ELA is strongest on JPEG; PNG/WebP can reduce signal quality.
- Copy-move features degrade on heavily compressed or tiny images.
- Current model metadata marks the shipped model as a testing/reference artifact.
- This is not legal-grade or court-grade forensic proof.

## Security Notes

- JWT bearer token required for detection, progress, and report endpoints.
- Upload-media retrieval requires a token query parameter (`?token=<jwt>`).
- Upload size capped at 50MB and streamed in chunks.
- Upload directory cleanup runs periodically (older than 48 hours).
- Detect endpoint is rate-limited (`10/minute` per IP).

## Stack

- Backend: FastAPI, SQLAlchemy, ONNX Runtime, OpenCV, PyWavelets
- Frontend: React 19, Vite, Framer Motion
- Database: SQLite (dev), PostgreSQL (recommended for production)

## Setup

### Prerequisites

- Python 3.9+
- Node.js 18+

### Install

```bash
pip install -r requirements.txt
cd frontend && npm install && cd ..
```

### Configure Backend

```bash
cp .env.example .env
```

### Configure Frontend

Set frontend auth vars in `frontend/.env`:

```bash
VITE_API_URL=http://localhost:8000/api
VITE_API_USERNAME=analyst
VITE_API_PASSWORD=change-me-analyst
```

The frontend auto-registers this user if it does not exist.

### Run (Development)

```bash
# Terminal 1
python -m uvicorn backend.main:app --reload --port 8000

# Terminal 2
cd frontend && npm run dev
```

Frontend: `http://localhost:5173`

## API

### Register

```http
POST /api/auth/register
Content-Type: application/json

{
  "username": "analyst",
  "password": "change-me-analyst"
}
```

### Get Token

```http
POST /api/auth/token
Content-Type: application/json

{
  "username": "analyst",
  "password": "change-me-analyst"
}
```

Response:

```json
{
  "access_token": "<jwt>",
  "token_type": "bearer"
}
```

### Submit Image

```http
POST /api/detect
Authorization: Bearer <token>
Content-Type: multipart/form-data
```

### Poll Progress

```http
GET /api/progress/{task_id}
Authorization: Bearer <token>
```

### Get Report

```http
GET /api/report/{task_id}
Authorization: Bearer <token>
```

Sample response:

```json
{
  "isForged": false,
  "verdict": "AUTHENTIC",
  "confidence": 72.4,
  "confidence_score": 0.27,
  "confidence_display": 72.4,
  "execution_time_ms": 3210.5,
  "analyses": {
    "ela": { "score": 0.12, "map": "..." },
    "copy_move": { "matches": 3, "status": "Clean" },
    "wavelet_noise": { "wavelet_std": 0.0032, "entropy": 3.1, "fingerprint_score": 0.3 },
    "cnn_inference": 0.2341
  }
}
```

### Fetch Generated ELA Asset

```http
GET /api/uploads/{filename}?token=<jwt>
```

## Testing

```bash
pytest backend/test_detector.py -v
pytest backend/test_api.py -v
pytest -q
```

## Troubleshooting

- `Missing token`: call `/api/auth/token` and send bearer token.
- `File exceeds maximum size of 50MB`: reduce input size or raise backend limit.
- `Uploaded file is not a valid image`: file content failed decode validation.
- `Model file not found`: CNN score falls back to neutral `0.5`.
