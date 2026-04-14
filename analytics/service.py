from typing import Dict, Any, Optional
from django.conf import settings
from .tasks import async_track_event, async_identify_user
import logging

logger = logging.getLogger(__name__)


class AnalyticsService:
    """
    Clean wrapper for Analytics. Protects the core application from
    failing if the analytics provider is down or misconfigured.
    """

    @staticmethod
    def track_event(user_id: int, event_name: str, properties: Optional[Dict[str, Any]] = None):
        """Track a discrete event"""
        if not getattr(settings, 'ENABLE_ANALYTICS', False):
            return  # Do nothing if analytics disabled

        properties = properties or {}
        try:
            # Enqueue the Celery Task
            async_track_event.delay(str(user_id), event_name, properties)
        except Exception as e:
            logger.error(f"Failed to queue track_event for {event_name}: {e}")

    @staticmethod
    def identify_user(user_id: int, properties: Dict[str, Any]):
        """Attach properties (like plan, username) to a user"""
        if not getattr(settings, 'ENABLE_ANALYTICS', False):
            return

        # Sanitize sensitive data just in case
        sanitized_props = {k: v for k, v in properties.items() if k not in [
            'password', 'token', 'secret']}

        try:
            # Enqueue the Celery Task
            async_identify_user.delay(str(user_id), sanitized_props)
        except Exception as e:
            logger.error(f"Failed to queue identify_user: {e}")

    @staticmethod
    def is_feature_enabled(user_id: int, flag_key: str, default: bool = False) -> bool:
        """
        Check if a PostHog Feature Flag is enabled for the specific user.
        Used for A/B Testing and Gradual Rollouts.
        """
        if not getattr(settings, 'ENABLE_ANALYTICS', False) or not getattr(settings, 'POSTHOG_API_KEY', None):
            return default

        try:
            # Requires synchronous Check
            from posthog import Posthog
            ph_client = Posthog(
                project_api_key=settings.POSTHOG_API_KEY,
                host=getattr(settings, 'POSTHOG_HOST',
                             'https://us.i.posthog.com')
            )
            # Evaluate the flag (returns True, False, or a multivariate string variant)
            result = ph_client.feature_enabled(flag_key, str(user_id))
            return bool(result)
        except Exception as e:
            logger.error(f"Failed to fetch feature flag {flag_key}: {e}")
            return default
