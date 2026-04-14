import logging
from celery import shared_task
from django.conf import settings
from posthog import Posthog

logger = logging.getLogger(__name__)

# Safely instantiate a dedicated Posthog client instance for Celery
posthog_client = None

if getattr(settings, 'ENABLE_ANALYTICS', False) and getattr(settings, 'POSTHOG_API_KEY', None):
    try:
        posthog_client = Posthog(
            project_api_key=settings.POSTHOG_API_KEY,
            host=getattr(settings, 'POSTHOG_HOST', 'https://app.posthog.com')
        )
        posthog_client.sync_mode = True  # Disable threading since we use celery
    except Exception as e:
        logger.error(f"Failed to initialize PostHog: {e}")


@shared_task(bind=True, max_retries=3, ignore_result=True)
def async_track_event(self, distinct_id, event_name, properties):
    """Async task to send events to PostHog without blocking the API"""
    if not getattr(settings, 'ENABLE_ANALYTICS', False) or not posthog_client:
        return

    try:
        posthog_client.capture(
            distinct_id=str(distinct_id),
            event=event_name,
            properties=properties
        )
    except Exception as e:
        logger.warning(f"PostHog Tracking failed for {event_name}: {e}")
        # Retry with exponential backoff if it's a network issue
        self.retry(exc=e, countdown=2 ** self.request.retries)


@shared_task(bind=True, max_retries=3, ignore_result=True)
def async_identify_user(self, distinct_id, properties):
    """Async task to link user identities in PostHog"""
    if not getattr(settings, 'ENABLE_ANALYTICS', False) or not posthog_client:
        return

    try:
        posthog_client.identify(
            str(distinct_id),
            properties=properties
        )
    except Exception as e:
        logger.warning(f"PostHog Identify failed: {e}")
        self.retry(exc=e, countdown=2 ** self.request.retries)
