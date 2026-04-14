import time
from .service import AnalyticsService
from django.conf import settings


class PostHogAPIMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not getattr(settings, 'ENABLE_ANALYTICS', False):
            # Don't even log execution time if analytics is off to save cycles
            return self.get_response(request)

        start_time = time.time()

        response = self.get_response(request)

        # Calculate duration
        duration_ms = int((time.time() - start_time) * 1000)

        # Track ALL authenticated API traffic intelligently
        if hasattr(request, 'user') and request.user.is_authenticated and request.path.startswith('/api/'):

            # 1. Base API Event (Engine Tracking)
            AnalyticsService.track_event(
                user_id=request.user.id,
                event_name='api_called',
                properties={
                    'path': request.path,
                    'method': request.method,
                    'status_code': response.status_code,
                    'duration_ms': duration_ms,
                }
            )

            # 2. Automated Smart Business Events based on API Paths
            # This means your Mobile App is automatically tracked without changing mobile code!

            # --- Chat & Messaging (Spam & Retention Tracking) ---
            if request.method == 'POST' and 'send-message' in request.path:
                AnalyticsService.track_event(request.user.id, 'message_sent', properties={
                                             'status_code': response.status_code,
                                             'is_spam_candidate': duration_ms < 50})  # Flag unusually fast requests
            elif request.method == 'POST' and 'create-chat' in request.path:
                AnalyticsService.track_event(request.user.id, 'chat_created', properties={
                                             'status_code': response.status_code})
            elif request.method == 'POST' and 'create-group' in request.path:
                AnalyticsService.track_event(request.user.id, 'group_created', properties={
                                             'status_code': response.status_code})
            elif request.method == 'POST' and 'pin-chat' in request.path:
                AnalyticsService.track_event(request.user.id, 'chat_pinned')

            # --- Calling & P2P ---
            elif request.method == 'POST' and 'call/notify' in request.path:
                AnalyticsService.track_event(request.user.id, 'call_initiated')

            # --- Search & Discovery ---
            elif request.method == 'GET' and 'global-search' in request.path:
                AnalyticsService.track_event(request.user.id, 'search_performed', properties={
                                             'query': request.GET.get('q', 'unknown')})
            elif request.method == 'GET' and 'explore-feed' in request.path:
                AnalyticsService.track_event(
                    request.user.id, 'explore_feed_viewed')

            # --- Omzo (Video/Reels features) ---
            elif request.method == 'POST' and 'omzo/upload' in request.path:
                AnalyticsService.track_event(request.user.id, 'omzo_uploaded')
            elif request.method == 'POST' and 'omzo/track-view' in request.path:
                AnalyticsService.track_event(request.user.id, 'omzo_viewed')
            elif request.method == 'POST' and 'omzo/like' in request.path:
                AnalyticsService.track_event(request.user.id, 'omzo_liked')
            elif request.method == 'POST' and 'omzo/comment' in request.path:
                AnalyticsService.track_event(request.user.id, 'omzo_commented')

            # --- Stories & Social ---
            elif request.method == 'GET' and 'following-stories' in request.path:
                AnalyticsService.track_event(
                    request.user.id, 'stories_feed_viewed')
            elif request.method == 'GET' and 'story/' in request.path:
                AnalyticsService.track_event(
                    request.user.id, 'single_story_viewed')
            elif request.method == 'POST' and 'follow' in request.path:
                AnalyticsService.track_event(request.user.id, 'user_followed')

            # --- General Usage & App Activity ---
            elif request.method == 'GET' and 'unread-counts' in request.path:
                # The app constantly checks unread counts while opened
                AnalyticsService.track_event(
                    request.user.id, 'app_active_heartbeat')
            elif request.method == 'GET' and 'chats' in request.path:
                AnalyticsService.track_event(request.user.id, 'inbox_opened')
            elif request.method == 'GET' and ('profile' in request.path or 'user' in request.path):
                AnalyticsService.track_event(request.user.id, 'profile_viewed')

            # --- Auth (Retention Base Events) ---
            elif 'login' in request.path and request.method == 'POST':
                AnalyticsService.track_event(request.user.id, 'user_logged_in')
            elif 'register' in request.path and request.method == 'POST':
                AnalyticsService.track_event(
                    request.user.id, 'user_registered')
            elif 'logout' in request.path and request.method == 'POST':
                AnalyticsService.track_event(
                    request.user.id, 'user_logged_out')

        return response
