from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from .service import AnalyticsService


class ProxyAnalyticsEventView(APIView):
    """
    Allows the frontend to send events securely through the backend
    to prevent dropping requests due to AdBlockers or strict firewalls.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        event_name = request.data.get('event_name')
        properties = request.data.get('properties', {})

        if not event_name:
            return Response({"error": "event_name is required"}, status=status.HTTP_400_BAD_REQUEST)

        # Only forward trusted frontend events if you want strict validation
        trusted_events = ['video_watched', 'frontend_button_clicked']
        if event_name not in trusted_events:
            return Response({"error": "Untrusted event type"}, status=status.HTTP_400_BAD_REQUEST)

        # Let the service layer handle Celery & PostHog
        AnalyticsService.track_event(
            user_id=request.user.id,
            event_name=f"frontend_{event_name}",
            properties=properties
        )

        return Response({"status": "event_queued"}, status=status.HTTP_202_ACCEPTED)
