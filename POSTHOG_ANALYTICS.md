# PostHog Analytics Architecture & Production Guide

This document outlines the architecture, data flow, and operational requirements for the PostHog Analytics integration built into the `react-odnix` Django backend.

## 1. High-Level Architecture

To ensure analytics tracking never impacts the performance of the user-facing API or WebSockets, the PostHog integration is built asynchronously using **Celery** and **Redis**.

### Core Components:
1. **Analytics Service (`analytics/service.py`)**: 
   A clean wrapper around PostHog. The rest of the Django application *only* interacts with this service, meaning the business logic is entirely decoupled from the analytics provider.
2. **Celery Tasks (`analytics/tasks.py`)**: 
   Handles the actual HTTP network calls to `us.i.posthog.com`. Includes exponential backoff and retries (`max_retries=3`) if the PostHog API goes down.
3. **API Tracking Middleware (`analytics/middleware.py`)**: 
   Automatically measures and tracks every single authenticated request to `/api/*`, capturing the route, method, status code, and latency (`duration_ms`).
4. **Proxy Endpoint (`analytics/views.py`)**: 
   An endpoint (`/api/analytics/proxy-event/`) that allows the React/React Native frontends to dispatch events securely through the backend, bypassing browser ad-blockers (like uBlock Origin).

---

## 2. Event Data Flow

When a user performs an action (or the Middleware intercepts an API call), the following non-blocking flow occurs:

1. **Trigger:** `AnalyticsService.track_event(user_id=1, event_name='message_sent')` is called.
2. **Queue:** The service immediately pushes the task dictionary (`async_track_event.delay(...)`) into **Redis** and returns control to Django. Latency impact: ~1ms.
3. **Background Processing:** A separate **Celery Worker** process picks up the task from Redis.
4. **Transmission:** The Celery worker makes the secure HTTP request to the PostHog ingestion servers (`https://us.i.posthog.com`).

---

## 3. Environment Configuration

The entire analytics pipeline is governed by environment variables. By default, **analytics are disabled in development** unless explicitly turned on.

### Required `.env` Variables:
```env
# Analytics Feature Flag
ENABLE_ANALYTICS=True # Set to False to completely disable tracking

# PostHog Credentials
POSTHOG_API_KEY=phc_YOUR_PROJECT_API_KEY
POSTHOG_HOST=https://us.i.posthog.com # Or https://eu.i.posthog.com

# Celery & Redis Defaults
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
```

---

## 4. Production Deployment Guide (e.g., Render.com)

To run this analytics pipeline in production, you must scale up a background worker and provide a Redis instance.

### Step 4.1: Provision Redis
You need a managed Redis instance (e.g., Render Redis, AWS ElastiCache, or Upstash). 
* Get the internal Redis URL (e.g., `redis://red-cxyz123:6379`).
* Replace `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND` in your production environment variables with this URL.

### Step 4.2: Add Environment Variables
In your heavily secured production environment settings (Render Dashboard -> Environment Variables), ensure you add:
* `ENABLE_ANALYTICS=True`
* `POSTHOG_API_KEY=...`
* `POSTHOG_HOST=https://us.i.posthog.com`

### Step 4.3: Define the Celery Worker Process
Your backend needs two processes running concurrently:
1. The **Web Worker** (Daphne/Gunicorn) handling HTTP/WebSockets.
2. The **Celery Worker** pulling tasks from Redis.

If you are using `render.yaml` or a Dockerfile, you need to define a new "Background Worker" service with the following start command:
```bash
celery -A odnix worker --loglevel=info --concurrency=4
```
*(Note: Remove `--pool=solo` in production, as that is only for local Windows development. Use `--concurrency=4` to allow handling multiple background events simultaneously).*

---

## 5. Tracking Custom Events in Code

To track a new business event anywhere in the Django application, simply import the service:

```python
from analytics.service import AnalyticsService

def my_django_view(request):
    # Perform business logic...
    
    # 1. Track the event
    AnalyticsService.track_event(
        user_id=request.user.id, 
        event_name="custom_action_completed", 
        properties={"item_id": 42, "category": "books"}
    )
    
    # 2. Update user properties in PostHog
    AnalyticsService.identify_user(
        user_id=request.user.id,
        properties={"plan_type": "premium"}
    )
```

### Safety Guarantees
* **Fail-safe:** If `ENABLE_ANALYTICS=False` is set (like in a developer's local environment), the `AnalyticsService` does absolutely nothing and returns instantly. Your code will not break.
* **Network-safe:** If PostHog servers go down, the API still responds 200 OK to the mobile app/web user. The Celery worker will hold the event and retry later.