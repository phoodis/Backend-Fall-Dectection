# Elderly Surveillance System Backend

A Flask-based backend for elderly surveillance with bed exit and fall detection, camera management, logging, and Telegram notifications.

## Installation

1. Copy `.env.example` to `.env` and configure your values
2. Build and run with Docker Compose:
   ```sh
   docker-compose up -d --build
   ```
3. For higher load, scale workers:
   ```sh
   docker-compose up --scale celery_worker=5 -d
   ```

## Usage

- The API will be available at `http://localhost:8932/api/`
- Flower (Celery monitoring) at `http://localhost:5555/`
- Default admin credentials: `admin` / `admin123`
- See [API Documentation](API_DOCUMENTATION.md) for complete endpoint reference
