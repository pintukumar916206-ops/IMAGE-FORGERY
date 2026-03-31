# Forensic Image Suite

A multi-layered system for verifying image authenticity. It utilizes classical forensic techniques alongside neural network scoring to identify structural and metadata inconsistencies.

## Capabilities

- **Metadata Scanner**: Extracts EXIF data and compares software signatures against known editing suites.
- **Error Level Analysis (ELA)**: Detects compression inconsistencies in JPEG bitstreams.
- **Copy-Move Detection**: Identifies cloned regions using SIFT-based feature matching and spatial clustering.
- **ML Scoring**: Provides a baseline forgery probability using an specialized CNN architecture.

## System Architecture

The suite is built with a decoupled architecture for scalability:

1. **Service Layer**: FastAPI for high-concurrency request handling.
2. **Analysis Pipeline**: Asynchronous background workers for processing forensic passes.
3. **Storage**: SQLite for persistent report management.
4. **Interface**: React-based dashboard for visual proof of manipulation.

## Local Configuration

1. Initialize environment:
   ```bash
   cp .env.example .env
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   npm install
   ```

3. Start services:
   ```bash
   npm run dev
   ```

## Development and Testing

The backend test suite covers API endpoints and core logic:
```bash
python -m pytest tests/
```

Frontend builds are managed via Vite:
```bash
cd frontend && npm run build
```

## Directory Structure
```
backend/        - API and Forensic Logic
frontend/       - Dashboard UI
scripts/        - Model utilities
tests/          - Backend verification suite
```
