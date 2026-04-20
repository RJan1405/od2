# urls.py - FIXED - All URLs with correct function names

from django.urls import path, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.urls import path


from . import views
# Import chat_ajax directly to avoid circular import
from .views.chat_ajax import chat_partial, unread_counts
# Import API auth views
from .views import api_auth
# Import chat API views
from .views import chat_api
from .views.react_serve import serve_react
# Import read receipt views
from .views import read_receipts


urlpatterns = [
    # API Authentication endpoints for React frontend
    path('api/login/', api_auth.api_login, name='api_login'),
    path('api/logout/', api_auth.api_logout, name='api_logout'),
    path('api/register/', api_auth.api_register, name='api_register'),
    path('api/check-availability/', api_auth.api_check_availability,
         name='api_check_availability'),
    path('api/firebase-register/', api_auth.api_firebase_register,
         name='api_firebase_register'),
    path('api/verify-email-otp/', api_auth.api_verify_email_otp,
         name='api_verify_email_otp'),
    path('api/profile/', api_auth.api_profile, name='api_profile'),
    path('api/profile/<str:username>/',
         api_auth.api_user_profile, name='api_user_profile'),
    path('api/csrf/', api_auth.get_csrf_token, name='api_csrf'),

    # API endpoints for React Chat
    # path('api/chat/<int:chat_id>/details/') is defined later in line 122


    # Read Receipt and Unread Count APIs
    path('api/messages/mark-read/', read_receipts.mark_messages_read,
         name='api_mark_messages_read'),
    path('api/chat/<int:chat_id>/mark-read/',
         read_receipts.mark_chat_read, name='api_mark_chat_read'),
    path('api/unread-counts/', read_receipts.get_unread_counts,
         name='api_unread_counts'),
    # Legacy unread counts endpoint (keeping for compatibility)
    path('api/unread_counts/', unread_counts, name='unread_counts'),

    # AJAX chat content endpoint
    # path('ajax/chat/<int:chat_id>/',
    # chat_ajax.chat_partial, name='ajax_chat_partial'),

    # React App (Home)
    path('', serve_react, name='home'),

    # Authentication URLs (Django templates - commented out for React)
    # path('login/', views.login_view, name='login'),
    # path('register/', views.register_view, name='register'),
    # path('logout/', views.logout_view, name='logout'),

    # Email verification URL
    path('verify-email/<str:token>/', views.verify_email, name='verify_email'),
    path('verify-email-otp/', views.verify_otp_view, name='verify_email_otp'),

    # Main application URLs (Commented out for React)
    # path('dashboard/', views.dashboard, name='dashboard'),
    path('explore/', views.explore, name='explore'),
    # path('profile/', views.profile_view, name='profile'),
    # path('profile/update/', views.update_profile, name='update_profile'),
    # path('profile/<str:username>/', views.profile_view, name='user_profile'),
    path('chat/<int:chat_id>/', views.chat_view, name='chat_detail'),
    # Dedicated messages page (chat list)
    # path('messages/', views.messages_page, name='messages'),
    path('delete-message-for-me/<int:message_id>/',
         views.delete_message_for_me, name='delete_message_for_me'),
    path('delete-message-for-everyone/<int:message_id>/',
         views.delete_message_for_everyone, name='delete_message_for_everyone'),

    # Group join URL
    path('join-group/<str:invite_code>/',
         views.join_group_view, name='join_group'),

    # Group discovery URL
    path('discover-groups/', views.discover_groups_view, name='discover_groups'),
    path('api/explore/load-more/', views.load_more_explore_content,
         name='load_more_explore'),
    path('api/explore-feed/', views.api_explore_feed, name='api_explore_feed'),

    # FIXED: Media serving URL with correct parameter name
    re_path(r'^media/(?P<file_path>.*)$',
            views.serve_media_file, name='serve_media'),

    # Story URLs
    path('api/create-story/', views.create_story, name='create_story'),
    path('api/story/<int:story_id>/', views.view_story, name='view_story'),
    # NEW: User stories API endpoint
    path('api/user-stories/<str:username>/',
         views.get_user_stories, name='get_user_stories'),
    # NEW: Following stories feed (Instagram-style)
    path('api/following-stories/',
         views.get_following_stories, name='get_following_stories'),

    # Scribe URLs - Enhanced
    path('api/post-scribe/', views.post_scribe, name='post_scribe'),
    path('api/repost/', views.api_repost, name='api_repost'),
    path('api/toggle-like/', views.toggle_like, name='toggle_like'),
    path('api/toggle-dislike/', views.toggle_dislike, name='toggle_dislike'),
    path('api/toggle-save-post/', views.toggle_save_post, name='toggle_save_post'),
    path('api/delete-post/', views.delete_post, name='delete_post'),
    path('api/report-post/', views.report_post, name='report_post'),
    path('api/saved-posts/', views.get_saved_posts, name='get_saved_posts'),
    path('api/copy-post-link/', views.copy_post_link, name='copy_post_link'),

    # Single post view (for shared links)
    path('post/<int:post_id>/', views.view_post, name='view_post'),

    # Comment URLs
    path('api/add-comment/', views.add_comment, name='add_comment'),
    path('api/toggle-comment-like/', views.toggle_comment_like,
         name='toggle_comment_like'),
    path('api/scribe/<int:scribe_id>/', views.get_scribe, name='get_scribe'),
    path('api/scribe/<int:scribe_id>/comments/',
         views.get_scribe_comments, name='get_scribe_comments'),

    # Chat API endpoints - FIXED
    path('api/chat/<int:chat_id>/details/',
         views.get_chat_details_api, name='get_chat_details_api'),
    path('api/chats/', views.get_chats_api, name='get_chats_api'),
    path('api/send-message/', views.send_message, name='send_message'),
    path('api/chat/<int:chat_id>/messages/',
         views.get_chat_messages, name='get_chat_messages'),
    path('api/create-chat/', views.create_chat, name='create_chat'),
    path('api/create-group/', views.create_group, name='create_group'),
    path('api/join-group/', views.join_group_api, name='join_group_api'),
    path('api/manage-join-request/', views.manage_join_request,
         name='manage_join_request'),

    path('api/consume-message/<int:message_id>/',
         views.consume_one_time_message, name='consume_message'),
    path('api/mark-read/<int:message_id>/',
         views.mark_message_read, name='mark_message_read'),
    path('api/react-message/<int:message_id>/',
         views.react_to_message, name='react_message'),
    path('api/chat/<int:chat_id>/typing/',
         views.update_typing_status, name='update_typing'),
    path('api/chat/<int:chat_id>/typing-status/',
         views.get_typing_status, name='get_typing_status'),
    path('api/update-chat-preference/',
         views.update_chat_preference, name='update_chat_preference'),

    # Message Context Menu
    path('api/message/<int:message_id>/context-menu/',
         views.get_message_context_menu, name='get_message_context_menu'),
    path('api/message/context-action/',
         views.message_context_action, name='message_context_action'),

    # Follow system
    path('api/toggle-follow/', views.toggle_follow, name='toggle_follow'),
    path('api/follow-states/', views.follow_states, name='follow_states'),
    path('api/toggle-block/', views.toggle_block, name='toggle_block'),
    path('api/dismiss-suggestion/', views.dismiss_suggestion,
         name='dismiss_suggestion'),
    path('api/manage-follow-request/', views.manage_follow_request,
         name='manage_follow_request'),
    path('api/follow-requests/', views.get_follow_requests,
         name='get_follow_requests'),
    path('api/blocked-users/', views.get_blocked_users, name='get_blocked_users'),
    path('api/toggle-account-privacy/', views.toggle_account_privacy,
         name='toggle_account_privacy'),
    path('api/manage-chat-acceptance/', views.manage_chat_acceptance,
         name='manage_chat_acceptance'),
    path('api/profile/<str:username>/followers/',
         views.get_profile_followers, name='get_profile_followers'),
    path('api/profile/<str:username>/following/',
         views.get_profile_following, name='get_profile_following'),

    # Story API endpoints - Instagram-like features
    path('api/story/mark-viewed/', views.mark_story_viewed,
         name='mark_story_viewed'),
    path('api/story/toggle-like/', views.toggle_story_like,
         name='toggle_story_like'),
    path('api/story/add-reply/', views.add_story_reply, name='add_story_reply'),
    # NEW: Repost story to your story
    path('api/story/repost/', views.repost_story, name='repost_story'),
    path('api/story/<int:story_id>/replies/',
         views.get_story_replies, name='get_story_replies'),
    path('api/story/<int:story_id>/viewers/',
         views.get_story_viewers, name='get_story_viewers'),
    path('api/replies/<int:reply_id>/delete/',
         views.delete_reply, name='delete_reply'),
    path('api/story-inbox/', views.get_story_inbox, name='get_story_inbox'),
    path('api/story-inbox/count/', views.get_story_inbox_count,
         name='get_story_inbox_count'),
    path('api/activity/', views.get_all_activity, name='get_all_activity'),
    path('api/notifications/<int:notification_id>/mark-read/',
         views.mark_notification_read, name='mark_notification_read'),

    # Message Editing feature
    path('api/edit-message/<int:message_id>/',
         views.edit_message, name='edit_message'),

    # Pinned Messages feature
    path('api/pin-message/<int:message_id>/',
         views.pin_message, name='pin_message'),
    path('api/unpin-message/<int:message_id>/',
         views.unpin_message, name='unpin_message'),
    path('api/chat/<int:chat_id>/pinned-messages/',
         views.get_pinned_messages, name='get_pinned_messages'),

    # Pin/Unpin Chat (conversation)
    path('api/pin-chat/<int:chat_id>/', views.pin_chat, name='pin_chat'),
    path('api/unpin-chat/<int:chat_id>/', views.unpin_chat, name='unpin_chat'),
    path('api/toggle-private-chat/', views.toggle_private_chat,
         name='toggle_private_chat'),

    # Save/Unsave functionality
    path('api/save-scribe/', views.toggle_save_scribe, name='toggle_save_scribe'),
    path('api/save-omzo/', views.toggle_save_omzo, name='toggle_save_omzo'),
    path('api/saved-items/', views.get_saved_items, name='get_saved_items'),


    # Hashtag & Mention features
    path('api/hashtag/<str:hashtag>/',
         views.get_hashtag_scribes, name='get_hashtag_scribes'),
    path('api/trending-hashtags/', views.get_trending_hashtags,
         name='get_trending_hashtags'),
    path('api/mentions/', views.get_user_mentions, name='get_user_mentions'),
    path('api/global-search/', views.global_search, name='global_search'),
    path('api/search-users/', views.search_users_for_mention,
         name='search_users_for_mention'),

    # Starred Messages feature
    path('api/star-message/<int:message_id>/',
         views.toggle_star_message, name='toggle_star_message'),
    path('api/starred-messages/', views.get_starred_messages,
         name='get_starred_messages'),
    path('api/message/<int:message_id>/is-starred/',
         views.is_message_starred, name='is_message_starred'),

    # Read Receipts feature
    path('api/chat/<int:chat_id>/mark-read/',
         views.mark_messages_read, name='mark_messages_read'),
    path('api/message/<int:message_id>/read-status/',
         views.get_message_read_status, name='get_message_read_status'),
    path('api/chat/<int:chat_id>/read-status/',
         views.get_chat_read_status, name='get_chat_read_status'),

    # User Online Status
    path('api/user/heartbeat/', views.user_heartbeat, name='user_heartbeat'),
    path('api/user/<int:user_id>/online-status/',
         views.get_user_online_status, name='get_user_online_status'),
    path('api/user/update-theme/', views.update_theme, name='update_theme'),
    path('api/chat/<int:chat_id>/participant-status/',
         views.get_chat_participant_status, name='get_chat_participant_status'),

    # Group Management
    path('api/group/<int:chat_id>/details/',
         views.get_group_details, name='get_group_details'),
    path('api/group/<int:chat_id>/update-settings/',
         views.update_group_settings, name='update_group_settings'),
    path('api/group/<int:chat_id>/remove-member/',
         views.remove_group_member, name='remove_group_member'),
    path('api/group/<int:chat_id>/leave/',
         views.leave_group, name='leave_group'),
    path('api/group/<int:chat_id>/regenerate-invite/',
         views.regenerate_invite_code, name='regenerate_invite_code'),

    # P2P File Sharing (WebRTC Signaling)
    path('api/p2p/send-signal/', views.p2p_send_signal, name='p2p_send_signal'),
    path('api/p2p/<int:chat_id>/signals/',
         views.p2p_get_signals, name='p2p_get_signals'),
    path('api/p2p/<int:chat_id>/participants/',
         views.get_chat_participants_for_p2p, name='p2p_participants'),
    path('api/p2p/clear-signals/', views.p2p_clear_signals,
         name='p2p_clear_signals'),

    # Call Notifications (HTTP fallback)
    path('api/call/notify/', views.send_call_notification,
         name='send_call_notification'),

    # Omzo
    path('omzo/', views.omzo_view, name='omzo'),
    path('omzo/<int:omzo_id>/', views.view_omzo,
         name='view_omzo'),  # Single Omzo view for sharing
    path('api/omzo/upload/', views.upload_omzo, name='upload_omzo'),
    path('api/omzo/batch/', views.get_omzo_batch, name='get_omzo_batch'),
    path('api/omzo/like/', views.toggle_omzo_like, name='toggle_omzo_like'),
    path('api/omzo/dislike/', views.toggle_omzo_dislike,
         name='toggle_omzo_dislike'),
    path('api/omzo/track-view/', views.track_omzo_view, name='track_omzo_view'),
    path('api/omzo/<int:omzo_id>/comments/',
         views.get_omzo_comments, name='get_omzo_comments'),
    path('api/omzo/comment/', views.add_omzo_comment, name='add_omzo_comment'),
    path('api/omzo/comment/like/', views.toggle_omzo_comment_like,
         name='toggle_omzo_comment_like'),
    path('api/omzo/report/', views.report_omzo, name='report_omzo'),
    path('api/omzo/delete/', views.delete_omzo, name='delete_omzo'),
    path('api/omzo/<int:omzo_id>/details/',
         views.get_omzo_detail, name='get_omzo_detail'),

    # Share API & Chat Requests
    path('api/share/send/', views.share_content_to_user,
         name='share_content_to_user'),
    path('api/share/search-users/', views.search_users_for_share,
         name='search_users_for_share'),
    path('api/chat-requests/', views.get_chat_requests, name='get_chat_requests'),
    path('api/chat-requests/count/', views.get_chat_requests_count,
         name='get_chat_requests_count'),
    path('api/chat-requests/<int:request_id>/accept/',
         views.accept_chat_request, name='accept_chat_request'),
    path('api/chat-requests/<int:request_id>/decline/',
         views.decline_chat_request, name='decline_chat_request'),

    # DM Request System (Instagram-style)
    path('api/dm-requests/', views.get_dm_requests, name='get_dm_requests'),
    path('api/dm-requests/count/', views.get_dm_requests_count,
         name='get_dm_requests_count'),
    path('api/dm-requests/<int:chat_id>/check/',
         views.check_dm_request, name='check_dm_request'),
    path('api/dm-requests/<int:chat_id>/accept/',
         views.accept_dm_request, name='accept_dm_request'),
    path('api/dm-requests/<int:chat_id>/decline/',
         views.decline_dm_request, name='decline_dm_request'),

    # Catch-all for React SPA (MUST BE LAST)
    re_path(r'^(?P<path>.*)$', serve_react, name='react_catch_all'),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL,
                          document_root=settings.MEDIA_ROOT)
