from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_http_methods
from django.contrib import messages
from django.utils import timezone
from django.db.models import Count, Q
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import json
import logging
import random
from datetime import timedelta
from chat.utils import notify_sidebar_for_chat, broadcast_message_to_chat, broadcast_message_consumed
from chat.utils import clear_sidebar_unread, is_user_online
from chat.recommendations import ContentRecommender
from chat.models import (
    CustomUser, Chat, Message, GroupJoinRequest, Follow, Story, StoryView,
    StoryLike, StoryReply, Scribe, Like, Comment, MessageDeletion, MessageRead,
    MessageReaction, StarredMessage, PinnedChat, SavedPost, Omzo, Dislike,
    DismissedSuggestion, ChatAcceptance, SavedScribeItem, SavedOmzoItem,
    OmzoLike, OmzoDislike, OmzoComment, Block, Notification
)
from chat.forms import ScribeForm
from .media import handle_media_upload
from django.conf import settings
import json as _json
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import TokenAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser
from chat.encryption import encrypt_text, decrypt_text

logger = logging.getLogger(__name__)


def get_gender_balanced_suggestions(user, total_count=5, female_priority=3, male_priority=2):
    """
    Get gender-balanced user suggestions for the dashboard.

    Algorithm:
    1. Try to get 3 females and 2 males (priority ratio)
    2. If not enough females, fill remaining slots with males
    3. If not enough males, fill remaining slots with females
    4. If still not enough, fill with any available users
    5. Shuffle the final result for natural appearance

    Args:
        user: Current logged-in user
        total_count: Total suggestions to return (default 5)
        female_priority: Number of females to prioritize (default 3)
        male_priority: Number of males to prioritize (default 2)

    Returns:
        List of CustomUser objects
    """
    # Get IDs of users already being followed
    following_ids = list(Follow.objects.filter(
        follower=user).values_list('following', flat=True))

    # Get IDs of dismissed suggestions
    dismissed_ids = list(DismissedSuggestion.objects.filter(
        user=user).values_list('dismissed_user', flat=True))

    # Base queryset: exclude self, followed users, and dismissed users
    candidates = CustomUser.objects.exclude(
        id=user.id
    ).exclude(
        id__in=following_ids
    ).exclude(
        id__in=dismissed_ids
    )

    # Get available females and males
    available_females = list(candidates.filter(gender='female').order_by('?'))
    available_males = list(candidates.filter(gender='male').order_by('?'))

    suggestions = []

    # Step 1: Try to get priority females (3)
    females_to_add = min(female_priority, len(available_females))
    suggestions.extend(available_females[:females_to_add])
    remaining_females = available_females[females_to_add:]

    # Step 2: Try to get priority males (2)
    males_to_add = min(male_priority, len(available_males))
    suggestions.extend(available_males[:males_to_add])
    remaining_males = available_males[males_to_add:]

    # Step 3: Fill remaining slots if we don't have enough
    slots_remaining = total_count - len(suggestions)

    if slots_remaining > 0:
        # Calculate how many we're short of each gender
        female_shortage = female_priority - females_to_add
        male_shortage = male_priority - males_to_add

        # If short on females, try to fill with more males first
        if female_shortage > 0 and remaining_males:
            fill_from_males = min(female_shortage, len(remaining_males))
            suggestions.extend(remaining_males[:fill_from_males])
            remaining_males = remaining_males[fill_from_males:]
            slots_remaining -= fill_from_males

        # If short on males, try to fill with more females
        if male_shortage > 0 and remaining_females and slots_remaining > 0:
            fill_from_females = min(male_shortage, len(
                remaining_females), slots_remaining)
            suggestions.extend(remaining_females[:fill_from_females])
            remaining_females = remaining_females[fill_from_females:]
            slots_remaining -= fill_from_females

        # If still need more, use any remaining users
        if slots_remaining > 0:
            remaining_all = remaining_females + remaining_males
            random.shuffle(remaining_all)
            suggestions.extend(remaining_all[:slots_remaining])

    # Shuffle final result for natural appearance
    random.shuffle(suggestions)

    return suggestions[:total_count]


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def dashboard(request):
    """FIXED - Enhanced dashboard with proper multiple stories support"""

    # Get user's chats
    user_chats = Chat.objects.filter(
        participants=request.user).select_related('admin')
    private_chats = user_chats.filter(chat_type='private')
    group_chats = user_chats.filter(chat_type='group')

    # Get other users
    other_users = CustomUser.objects.exclude(
        id=request.user.id).distinct().order_by('name', 'lastname')

    # Get pending join requests
    pending_requests = GroupJoinRequest.objects.filter(
        group__admin=request.user,
        status='pending'
    ).select_related('user', 'group').order_by('-requested_at')

    # Get following users
    following_users = list(Follow.objects.filter(
        follower=request.user).values_list('following', flat=True))

    # Get gender-balanced suggestions (3 females, 2 males priority)
    suggestion_users = get_gender_balanced_suggestions(
        user=request.user,
        total_count=5,
        female_priority=3,
        male_priority=2
    )

    # FIXED: Get active stories from followed users - SUPPORT MULTIPLE STORIES PER USER
    active_stories = Story.objects.filter(
        user__in=following_users,
        is_active=True,
        expires_at__gt=timezone.now()
    ).select_related('user').order_by('-created_at')

    # FIXED: Group stories by user (latest first) - ALLOW MULTIPLE STORIES
    stories_by_user = {}
    for story in active_stories:
        if story.user.id not in stories_by_user:
            stories_by_user[story.user.id] = {
                'user': story.user,
                'stories': [],
                'latest_story': story,
                'story_count': 0,
                'viewed_count': 0,
                'all_viewed': True
            }
        stories_by_user[story.user.id]['stories'].append(story)
        stories_by_user[story.user.id]['story_count'] += 1

        # Check if current user has viewed this story
        has_viewed = StoryView.objects.filter(
            story=story, viewer=request.user).exists()
        if has_viewed:
            stories_by_user[story.user.id]['viewed_count'] += 1
        else:
            stories_by_user[story.user.id]['all_viewed'] = False

    # FIXED: Get user's own active stories (separate from others) - ALLOW MULTIPLE
    user_stories = Story.objects.filter(
        user=request.user,
        is_active=True,
        expires_at__gt=timezone.now()
    ).order_by('-created_at')

    # Get the latest user story for the main display
    user_story = user_stories.first()
    user_story_count = user_stories.count()

    # Use Recommendation Engine for scribes (with balanced like/dislike scoring)
    recommender = ContentRecommender(request.user)
    scribes_queryset = recommender.get_scribes(following_users, limit=20)

    # Process scribes with like/comment data
    scribes_data = []
    processed_scribe_ids = set()

    for scribe in scribes_queryset:
        if scribe.id in processed_scribe_ids:
            continue
        processed_scribe_ids.add(scribe.id)

        # Get like count and if current user liked it
        like_count = Like.objects.filter(scribe=scribe).count()
        is_liked = Like.objects.filter(
            scribe=scribe, user=request.user).exists()
        is_disliked = Dislike.objects.filter(
            scribe=scribe, user=request.user).exists()

        # Check if current user has saved this post
        is_saved = SavedPost.objects.filter(
            scribe=scribe, user=request.user).exists()

        # Get comment count
        comment_count = Comment.objects.filter(scribe=scribe).count()

        # Get recent comments (latest 3)
        recent_comments = Comment.objects.filter(
            scribe=scribe,
            parent__isnull=True
        ).select_related('user').order_by('-timestamp')[:3]

        # Check if current user has reposted this scribe
        is_reposted = Scribe.objects.filter(
            user=request.user,
            original_scribe=scribe,
            quote_source__isnull=True
        ).exists()

        # Calculate time ago
        time_diff = timezone.now() - scribe.timestamp
        if time_diff.days > 0:
            time_ago = f"{time_diff.days}d"
        elif time_diff.seconds > 3600:
            time_ago = f"{time_diff.seconds // 3600}h"
        else:
            time_ago = f"{time_diff.seconds // 60}m"

        scribes_data.append({
            'id': scribe.id,
            'content': scribe.content,
            'content_type': getattr(scribe, 'content_type', 'text'),
            'code_bundle': getattr(scribe, 'code_bundle', None),
            'code_html': getattr(scribe, 'code_html', None),
            'code_css': getattr(scribe, 'code_css', None),
            'code_js': getattr(scribe, 'code_js', None),
            'user': scribe.user,
            'user_id': scribe.user.id,
            'username': scribe.user.username,
            'fullname': scribe.user.full_name,
            'user_initials': scribe.user.initials,
            'profile_picture_url': scribe.user.profile_picture_url,
            'formatted_time': scribe.timestamp.strftime('%b %d, %Y %H:%M'),
            'time_ago': time_ago,
            'like_count': like_count,
            'comment_count': comment_count,
            'is_liked': is_liked,
            'is_disliked': is_disliked,
            'is_saved': is_saved,
            'is_reposted': is_reposted,
            'is_own': scribe.user == request.user,
            'image_url': scribe.image_url,
            'has_media': scribe.has_media,
            'recent_comments': recent_comments,
            # Repost fields
            'is_repost': scribe.is_repost,
            'original_scribe': scribe.original_scribe,
            'original_omzo': scribe.original_omzo,
            'original_story': scribe.original_story,
            'quote_source': scribe.quote_source,
        })

    # Create scribe form instance for proper rendering
    scribe_form = ScribeForm()

    # Get story inbox count (replies/likes to user's stories)
    story_inbox_count = StoryReply.objects.filter(
        story__user=request.user,
        is_read=False
    ).count() + StoryLike.objects.filter(
        story__user=request.user,
    ).exclude(user=request.user).count()

    # Get unread message count for the DM badge - count unique chats with unread messages
    unread_message_count = Chat.objects.filter(
        participants=request.user,
        messages__is_read=False
    ).exclude(messages__sender=request.user).distinct().count()

    # Combine all chats for the chats panel with additional info
    all_chats = []
    for chat in user_chats.order_by('-updated_at')[:20]:
        chat_info = {
            'id': chat.id,
            'name': chat.name,
            'is_group': chat.chat_type == 'group',
        }

        # Get other user for private chats
        if chat.chat_type == 'private':
            other_participant = chat.participants.exclude(
                id=request.user.id).first()
            chat_info['other_user'] = other_participant
            chat_info['is_following'] = other_participant.id in following_users if other_participant else False

        # Get last message
        last_message = chat.messages.order_by('-timestamp').first()
        from chat.encryption import decrypt_text
        if last_message:
            decrypted_content = decrypt_text(last_message.content)
            chat_info['last_message_preview'] = decrypted_content[:50] + \
                ('...' if len(decrypted_content) > 50 else '')
            chat_info['last_message_time'] = last_message.timestamp
        else:
            chat_info['last_message_preview'] = None
            chat_info['last_message_time'] = None

        # Get unread count
        chat_info['unread_count'] = chat.messages.filter(
            is_read=False).exclude(sender=request.user).count()

        all_chats.append(chat_info)

    context = {
        'private_chats': private_chats,
        'group_chats': group_chats,
        'chats': all_chats,  # Combined chats for the panel
        'other_users': other_users,
        'suggestion_users': suggestion_users,
        'pending_requests': pending_requests,
        'current_user': request.user,
        'stories_by_user': stories_by_user,  # Keep as dict for template iteration
        'user_story': user_story,  # Latest user story for display
        'user_stories': user_stories,  # ALL user stories for navigation
        'user_story_count': user_story_count,  # Count for display
        'scribes_data': scribes_data,
        'scribe_form': scribe_form,  # Pass form to template
        'story_inbox_count': story_inbox_count,  # Notification count
        'unread_message_count': unread_message_count,  # DM badge count
    }

    # Use Instagram-style template
    return render(request, 'chat/dashboard.html', context)


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def chat_view(request, chat_id):
    # User chats split by type, with last_message and unread_count
    user_chats = Chat.objects.filter(participants=request.user).select_related(
        'admin').order_by('-updated_at')

    # Get Manual Private List (Pinned Chats)
    pinned_chat_ids = set(PinnedChat.objects.filter(
        user=request.user).values_list('chat_id', flat=True))

    # Get chat IDs that the current user has accepted
    accepted_chat_ids = set(ChatAcceptance.objects.filter(
        user=request.user).values_list('chat_id', flat=True))

    private_chats = []
    group_chats = []
    for chat in user_chats:
        last_message_obj = chat.messages.order_by('-timestamp').first()
        if last_message_obj:
            if last_message_obj.message_type == 'text':
                last_message = last_message_obj.content
            elif last_message_obj.message_type == 'media':
                if last_message_obj.media_type == 'image':
                    last_message = 'Sent an image'
                elif last_message_obj.media_type == 'video':
                    last_message = 'Sent a video'
                elif last_message_obj.media_type == 'document':
                    last_message = 'Sent a document'
                elif last_message_obj.media_type == 'audio':
                    last_message = '🎤 Sent a voice message'
                else:
                    last_message = 'Sent a file'
            elif last_message_obj.message_type == 'system':
                last_message = '[System message]'
            else:
                last_message = last_message_obj.content
        else:
            last_message = 'No messages yet'
        unread_count = chat.messages.filter(
            is_read=False).exclude(sender=request.user).count()

        # Check if this chat is a request (not accepted by current user)
        is_request = (chat.chat_type ==
                      'private' and chat.id not in accepted_chat_ids)

        chat_dict = {
            'id': chat.id,
            'name': chat.name,
            'chat_type': chat.chat_type,
            'participants': chat.participants.all(),
            'last_message': last_message,
            'unread_count': unread_count,
            'is_private': chat.id in pinned_chat_ids,  # Manual Private List
            'is_request': is_request,  # Whether this is a DM request
        }
        if chat.chat_type == 'private':
            private_chats.append(chat_dict)
        else:
            group_chats.append(chat_dict)
    # Mark all unread messages as read when user opens the chat
    chat = get_object_or_404(Chat, id=chat_id, participants=request.user)
    chat.messages.filter(is_read=False).exclude(
        sender=request.user).update(is_read=True)
    # 🔥 NEW — clear sidebar badge for this chat
    clear_sidebar_unread(chat, request.user)

    # Update current user's online status
    request.user.last_seen = timezone.now()
    request.user.is_online = True
    request.user.save(update_fields=['last_seen', 'is_online'])

    messages_list = chat.messages.exclude(
        deletions__user=request.user
    ).order_by('timestamp')
    other_participants = chat.participants.exclude(id=request.user.id)

    # Fix stale online status for other participants
    # A user is only truly online if is_online=True AND last_seen is within 2 minutes
    for participant in other_participants:
        if participant.is_online and participant.last_seen:
            time_since_last_seen = timezone.now() - participant.last_seen
            if time_since_last_seen >= timedelta(seconds=15):
                # Mark as offline - their session is stale
                participant.is_online = False
                participant.save(update_fields=['is_online'])

    is_admin = chat.admin == request.user if chat.chat_type == 'group' else False

    join_requests = []
    if is_admin:
        join_requests = GroupJoinRequest.objects.filter(
            group=chat,
            status='pending'
        ).select_related('user').order_by('-requested_at')

    # Unread count for this chat (messages not sent by user and not read)
    chat_unread_count = chat.messages.filter(
        is_read=False).exclude(sender=request.user).count()

    # Get IDs of users the current user follows for frontend filtering
    following_ids = list(Follow.objects.filter(
        follower=request.user).values_list('following_id', flat=True))

    # --- Message Request Logic (using ChatAcceptance) ---
    is_message_request = False
    target_user_username = ''
    target_user_avatar = ''
    if chat.chat_type == 'private':
        other_user = chat.participants.exclude(id=request.user.id).first()
        if other_user:
            target_user_username = other_user.username
            target_user_avatar = other_user.profile_picture_url

            # Check if current user has accepted this chat
            has_accepted = ChatAcceptance.objects.filter(
                chat=chat, user=request.user).exists()

            # It's a request if we haven't accepted yet and they have messaged
            has_they_messaged = chat.messages.exclude(
                sender=request.user).exclude(message_type='system').exists()

            if not has_accepted and has_they_messaged:
                is_message_request = True

    context = {
        'chat': chat,
        'messages': messages_list,
        'other_participants': other_participants,
        'is_admin': is_admin,
        'join_requests': join_requests,
        'chat_unread_count': chat_unread_count,
        'private_chats': private_chats,
        'group_chats': group_chats,
        'active_chat_id': chat.id,
        'following_ids': following_ids,
        'is_message_request': is_message_request,
        'target_user_username': target_user_username,
        'target_user_avatar': target_user_avatar,
    }
    # Calls feature flags and ICE servers for WebRTC
    context['calls_enabled'] = getattr(settings, 'ENABLE_CALLS', True)
    ice_servers = getattr(settings, 'WEBRTC_ICE_SERVERS', [])
    try:
        context['ice_servers_json'] = _json.dumps(ice_servers)
    except Exception:
        context['ice_servers_json'] = '[]'
    ice_servers = getattr(settings, 'WEBRTC_ICE_SERVERS', [])
    try:
        context['ice_servers_json'] = _json.dumps(ice_servers)
    except Exception:
        context['ice_servers_json'] = '[]'

    # Use Instagram-style template
    return render(request, 'chat/chat_detail.html', context)


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def messages_page(request):
    """Dedicated messages page to pick a chat (replaces sidebar/panel)."""
    # User chats split by type, with last_message and unread_count
    user_chats = Chat.objects.filter(participants=request.user).select_related(
        'admin').order_by('-updated_at')

    # Get Manual Private List (Pinned Chats)
    pinned_chat_ids = set(PinnedChat.objects.filter(
        user=request.user).values_list('chat_id', flat=True))

    # Get chat IDs that the current user has accepted
    accepted_chat_ids = set(ChatAcceptance.objects.filter(
        user=request.user).values_list('chat_id', flat=True))

    private_chats = []
    group_chats = []
    for chat in user_chats:
        last_message_obj = chat.messages.order_by('-timestamp').first()
        if last_message_obj:
            if last_message_obj.message_type == 'text':
                last_message = last_message_obj.content
            elif last_message_obj.message_type == 'media':
                if last_message_obj.media_type == 'image':
                    last_message = 'Sent an image'
                elif last_message_obj.media_type == 'video':
                    last_message = 'Sent a video'
                elif last_message_obj.media_type == 'document':
                    last_message = 'Sent a document'
                elif last_message_obj.media_type == 'audio':
                    last_message = '🎤 Sent a voice message'
                else:
                    last_message = 'Sent a file'
            elif last_message_obj.message_type == 'system':
                last_message = '[System message]'
            else:
                last_message = last_message_obj.content
        else:
            last_message = 'No messages yet'
        unread_count = chat.messages.filter(
            is_read=False).exclude(sender=request.user).count()

        # Check if this chat is a request (not accepted by current user)
        is_request = (chat.chat_type ==
                      'private' and chat.id not in accepted_chat_ids)

        chat_dict = {
            'id': chat.id,
            'name': chat.name,
            'chat_type': chat.chat_type,
            'participants': chat.participants.all(),
            'last_message': last_message,
            'unread_count': unread_count,
            'is_private': chat.id in pinned_chat_ids,  # Manual Private List
            'is_request': is_request,  # Whether this is a DM request
        }
        if chat.chat_type == 'private':
            private_chats.append(chat_dict)
        else:
            group_chats.append(chat_dict)

    # Other users for search/help
    other_users = CustomUser.objects.exclude(
        id=request.user.id).distinct().order_by('name', 'lastname')

    # Counts for navbar badges
    story_inbox_count = (
        StoryReply.objects.filter(
            story__user=request.user, is_read=False).count()
        + StoryLike.objects.filter(story__user=request.user).exclude(user=request.user).count()
    )
    unread_message_count = Chat.objects.filter(
        participants=request.user,
        messages__is_read=False
    ).exclude(messages__sender=request.user).distinct().count()

    context = {
        'current_user': request.user,
        'private_chats': private_chats,
        'group_chats': group_chats,
        'other_users': other_users,
        'story_inbox_count': story_inbox_count,
        'unread_message_count': unread_message_count,
        'following_ids': list(Follow.objects.filter(follower=request.user).values_list('following_id', flat=True)),
    }

    # Render a chat-style messages selector (two-pane layout with empty chat area)
    return render(request, 'chat/messages.html', context)


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def get_chat_messages(request, chat_id):
    """FIXED - Get chat messages with proper API response"""
    chat = get_object_or_404(Chat, id=chat_id, participants=request.user)

    is_accepted = True
    is_message_request = False
    if chat.chat_type == 'private':
        # Check if user has already accepted
        is_accepted = ChatAcceptance.objects.filter(
            chat=chat, user=request.user).exists()

        other_user = chat.participants.exclude(id=request.user.id).first()
        if other_user:
            from chat.models import Block
            # If we've blocked them, hide the accept banner (consider it "processed")
            if Block.objects.filter(blocker=request.user, blocked=other_user).exists():
                is_accepted = True

        if not is_accepted:
            has_they_messaged = chat.messages.exclude(
                sender=request.user).exclude(message_type='system').exists()
            if has_they_messaged:
                is_message_request = True

    last_message_time = request.GET.get('last_message_time')
    after_id = request.GET.get('after_id')

    # Optimize query with select_related to avoid N+1 problems
    messages_query = chat.messages.select_related(
        'sender',
        'reply_to',
        'reply_to__sender',
        'story_reply',
        'story_reply__user',
        'shared_scribe',
        'shared_scribe__user',
        'shared_omzo',
        'shared_omzo__user'
    ).exclude(deletions__user=request.user).order_by('timestamp')

    # Filter by message ID (preferred method to avoid duplicates)
    if after_id:
        try:
            messages_query = messages_query.filter(id__gt=int(after_id))
        except Exception:
            pass
    # Fallback to time-based filtering
    elif last_message_time:
        try:
            from datetime import datetime
            last_time = datetime.fromisoformat(
                last_message_time.replace('Z', '+00:00'))
            messages_query = messages_query.filter(timestamp__gt=last_time)
        except Exception:
            pass

    messages_data = []
    for msg in messages_query:
        # Use the boolean field directly - improved performance and reliability
        is_read = msg.is_read

        message_data = {
            'id': msg.id,
            'content': decrypt_text(msg.content),
            'sender': msg.sender.username if msg.sender else 'System',
            'sender_name': msg.sender.full_name if msg.sender else 'System',
            'sender_avatar': msg.sender.profile_picture_url if msg.sender else None,
            'sender_initials': msg.sender.initials if msg.sender else 'S',
            'timestamp': msg.timestamp.strftime('%H:%M'),
            'timestamp_iso': msg.timestamp.isoformat(),
            'sender_id': msg.sender_id,
            'message_type': msg.message_type,
            'is_own': msg.sender == request.user if msg.sender else False,
            'is_read': is_read,
            'one_time': msg.one_time,
            'consumed': msg.consumed_at is not None,
            'has_media': msg.has_media,
            'media_url': msg.media_url,
            'media_type': msg.media_type,
            'media_filename': msg.media_filename,
            'reply_to': {
                'id': msg.reply_to.id if msg.reply_to else None,
                'content': decrypt_text(msg.reply_to.content) if msg.reply_to else None,
                'sender_name': msg.reply_to.sender.full_name if msg.reply_to else None,
            } if msg.reply_to else None,
            'story_reply': {
                'story_id': msg.story_reply.id,
                'story_type': msg.story_reply.story_type,
                'story_content': msg.story_reply.content if msg.story_reply.story_type == 'text' else None,
                'story_media_url': msg.story_reply.media_url if msg.story_reply.story_type in ['image', 'video'] else None,
                'story_owner': msg.story_reply.user.full_name,
            } if msg.story_reply else None,
            'shared_scribe': {
                'id': msg.shared_scribe.id,
                'content': msg.shared_scribe.content,
                'image': msg.shared_scribe.image_url,
                'user': {
                    'username': msg.shared_scribe.user.username,
                    'avatar': msg.shared_scribe.user.profile_picture_url
                }
            } if msg.shared_scribe else None,
            'shared_omzo': {
                'id': msg.shared_omzo.id,
                'caption': msg.shared_omzo.caption,
                'video_url': msg.shared_omzo.video_file.url,
                'user': {
                    'username': msg.shared_omzo.user.username,
                    'avatar': msg.shared_omzo.user.profile_picture_url
                }
            } if msg.shared_omzo else None
        }

        messages_data.append(message_data)

    is_other_blocked = False
    am_i_blocked = False
    if chat.chat_type == 'private':
        other_user = chat.participants.exclude(id=request.user.id).first()
        if other_user:
            from chat.models import Block
            is_other_blocked = Block.objects.filter(
                blocker=request.user, blocked=other_user).exists()
            am_i_blocked = Block.objects.filter(
                blocker=other_user, blocked=request.user).exists()

    return Response({
        'success': True,
        'messages': messages_data,
        'is_accepted': is_accepted,
        'is_message_request': is_message_request,
        'is_other_blocked': is_other_blocked,
        'am_i_blocked': am_i_blocked,
        'chat_updated': chat.updated_at.isoformat()
    })


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def send_message(request):
    try:
        # Standardize on request.data for both JSON and Multipart data
        chat_id = request.data.get('chat_id')
        content = request.data.get('content', '').strip()
        media_file = request.data.get('media')
        one_time = str(request.data.get('one_time', 'false')).lower() == 'true'
        shared_scribe_id = request.data.get('shared_scribe_id')
        shared_omzo_id = request.data.get('shared_omzo_id')

        # Allow empty content if sharing something
        if not content and not media_file and not shared_scribe_id and not shared_omzo_id:
            return Response({'success': False, 'error': 'Message cannot be empty'})

        chat = get_object_or_404(Chat, id=chat_id, participants=request.user)

        # 🛡️ Block check - prevent messaging if blocked
        if chat.chat_type == 'private':
            other_user = chat.participants.exclude(id=request.user.id).first()
            if other_user:
                from chat.models import Block
                if Block.objects.filter(blocker=request.user, blocked=other_user).exists():
                    return Response({'success': False, 'error': 'You have blocked this user'})
                if Block.objects.filter(blocker=other_user, blocked=request.user).exists():
                    return Response({'success': False, 'error': 'You cannot message this user'})

        # Handle reply
        reply_to_id = request.data.get('reply_to')
        reply_to_message = None
        if reply_to_id:
            try:
                reply_to_message = Message.objects.get(
                    id=reply_to_id, chat=chat)
            except Message.DoesNotExist:
                pass

        # Handle media upload
        media_url = None
        media_type = None
        media_filename = None
        media_size = None

        if media_file:
            media_url, media_type, media_filename, media_size, upload_error = handle_media_upload(
                media_file)
            if not media_url:
                return Response({'success': False, 'error': upload_error or 'Failed to upload media file'})

        message_type = 'media' if media_file else 'text'

        # Create message
        message = Message.objects.create(
            chat=chat,
            sender=request.user,
            content=encrypt_text(
                content or f'Sent {media_type}' if media_file else content or 'Shared content'),
            message_type=message_type,
            media_url=media_url,
            media_type=media_type,
            media_filename=media_filename,
            media_size=media_size,
            reply_to=reply_to_message,
            one_time=one_time,
            shared_scribe_id=shared_scribe_id,
            shared_omzo_id=shared_omzo_id
        )

        # Update chat timestamp
        chat.updated_at = timezone.now()
        chat.save()

        # 🔥 NEW — notify sidebar via WebSocket
        notify_sidebar_for_chat(
            chat=chat,
            sender=request.user,
            last_message_text='🔒 One-time message' if message.one_time else decrypt_text(
                message.content)
        )

        # 🔥 Broadcast the message to all participants via WebSocket
        broadcast_message_to_chat(chat, message, exclude_sender=True)

        return Response({
            'success': True,
            'message': {
                'id': message.id,
                'content': decrypt_text(message.content),
                'sender': message.sender.username,
                'sender_name': message.sender.full_name,
                'sender_avatar': message.sender.profile_picture_url,
                'sender_initials': message.sender.initials,
                'timestamp': message.timestamp.strftime('%H:%M'),
                'timestamp_iso': message.timestamp.isoformat(),
                'sender_id': message.sender_id,
                'message_type': message.message_type,
                'media_url': message.media_url,
                'media_type': message.media_type,
                'media_filename': message.media_filename,
                'one_time': message.one_time,
                'consumed': False,
                'is_read': False,
                'is_own': message.sender == request.user,
                'has_media': message.has_media,
                'reply_to': {
                    'id': message.reply_to.id if message.reply_to else None,
                    'content': decrypt_text(message.reply_to.content) if message.reply_to else None,
                    'sender_name': message.reply_to.sender.full_name if message.reply_to else None,
                } if message.reply_to else None,
                'shared_scribe': {
                    'id': message.shared_scribe.id,
                    'content': message.shared_scribe.content,
                    'image': message.shared_scribe.image_url,
                    'user': {
                        'username': message.shared_scribe.user.username,
                        'avatar': message.shared_scribe.user.profile_picture_url
                    }
                } if message.shared_scribe else None,
                'shared_omzo': {
                    'id': message.shared_omzo.id,
                    'caption': message.shared_omzo.caption,
                    'video_url': message.shared_omzo.video_file.url,
                    'user': {
                        'username': message.shared_omzo.user.username,
                        'avatar': message.shared_omzo.user.profile_picture_url
                    }
                } if message.shared_omzo else None
            }
        })

    except Exception as e:
        logger.error(f"Error in send_message: {str(e)}")
        return Response({'success': False, 'error': 'Failed to send message'})


@api_view(['GET'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def get_chats_api(request):
    """API endpoint to get user's chats for the slide-in panel"""

    try:
        user_chats = Chat.objects.filter(
            participants=request.user).select_related('admin')

        chats_data = []
        for chat in user_chats:
            # Get last message
            last_message = chat.messages.order_by('-timestamp').first()
            last_msg_content = None
            if last_message:
                if last_message.message_type == 'media':
                    if last_message.media_type == 'image':
                        last_msg_content = 'Sent an image'
                    elif last_message.media_type == 'audio':
                        last_msg_content = '🎤 Sent a voice message'
                    elif last_message.media_type == 'video':
                        last_msg_content = 'Sent a video'
                    else:
                        last_msg_content = 'Sent a file'
                else:
                    last_msg_content = decrypt_text(last_message.content)

            # Get unread count - messages not read by current user and not sent by current user
            unread_count = chat.messages.exclude(
                sender=request.user
            ).exclude(
                read_receipts__user=request.user
            ).count()

            # Get other participant for private chats
            other_user = None
            is_accepted = True
            is_message_request = False

            if chat.chat_type == 'private':
                other_user = chat.participants.exclude(
                    id=request.user.id).first()

                # Check acceptance
                is_accepted = ChatAcceptance.objects.filter(
                    chat=chat, user=request.user).exists()

                from chat.models import Block
                # If we've blocked them, hide the accept banner
                if other_user and Block.objects.filter(blocker=request.user, blocked=other_user).exists():
                    is_accepted = True

                # It's a request if WE haven't accepted and THEY messaged
                if not is_accepted:
                    has_they_messaged = chat.messages.exclude(
                        sender=request.user).exclude(message_type='system').exists()
                    if has_they_messaged:
                        is_message_request = True

                # Calculate actual online status based on last_seen
                if other_user:
                    is_actually_online = False
                    if other_user.is_online and other_user.last_seen:
                        time_since_last_seen = timezone.now() - other_user.last_seen
                        is_actually_online = time_since_last_seen.total_seconds() < 120

                    if other_user.is_online and not is_actually_online:
                        other_user.is_online = False
                        other_user.save(update_fields=['is_online'])

            # Build last_message payload
            last_message_data = None
            if last_message:
                is_one_time = bool(last_message.one_time)
                is_consumed = last_message.consumed_at is not None
                safe_content = '🔒 One-time message' if is_one_time else last_msg_content
                last_message_data = {
                    'id': last_message.id,
                    'content': safe_content,
                    'message_type': last_message.message_type,
                    'one_time': is_one_time,
                    'consumed_at': last_message.consumed_at.isoformat() if is_consumed else None,
                    'sender_id': last_message.sender_id,
                    'sender_name': last_message.sender.full_name if last_message.sender else None,
                }

            chat_info = {
                'id': chat.id,
                'name': chat.name if chat.chat_type == 'group' else ((other_user.full_name or other_user.username) if other_user else 'Unknown'),
                'username': other_user.username if other_user else None,
                'is_group': chat.chat_type == 'group',
                'is_accepted': is_accepted,
                'is_message_request': is_message_request,
                'last_message': last_message_data,
                'last_message_time': last_message.timestamp.isoformat() if last_message else None,
                'unread_count': unread_count,
                'avatar': other_user.profile_picture_url if other_user else (chat.group_avatar.url if chat.group_avatar else None),
                'initials': other_user.initials if other_user else (chat.name[:1].upper() if chat.name else 'G'),
                'other_user': {
                    'id': other_user.id,
                    'username': other_user.username,
                    'full_name': other_user.full_name,
                    'profile_picture': other_user.profile_picture_url,
                    'is_online': is_actually_online if other_user else False,
                    'is_verified': other_user.is_verified,
                } if other_user else None,
            }

            # Debug logging
            if other_user:
                logger.info(
                    f"Chat {chat.id}: other_user.username={other_user.username}, other_user.full_name='{other_user.full_name}', other_user.name='{other_user.name}', other_user.lastname='{other_user.lastname}'")

            chats_data.append(chat_info)

        return Response({'success': True, 'chats': chats_data})
    except Exception as e:
        logger.error(f"Error in get_chats_api: {str(e)}")
        return Response({'success': False, 'error': 'Failed to load chats'})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def create_chat(request):
    """FIXED - Universal create_chat API for private and groups"""
    try:
        data = request.data
        username = data.get('username')

        other_user = get_object_or_404(CustomUser, username=username)

        if other_user == request.user:
            return Response({'success': False, 'error': 'Cannot create chat with yourself'})

        # Check if chat already exists
        existing_chat = Chat.objects.filter(
            participants=request.user,
            chat_type='private'
        ).filter(participants=other_user).first()

        if existing_chat:
            # Make sure creator has accepted this chat
            ChatAcceptance.objects.get_or_create(
                chat=existing_chat, user=request.user)
            return Response({
                'success': True,
                'chat_id': existing_chat.id,
                'exists': True
            })

        # Create new chat
        chat = Chat.objects.create(chat_type='private')
        chat.participants.add(request.user, other_user)

        # Auto-accept for the creator (they initiated, so they've accepted)
        ChatAcceptance.objects.get_or_create(chat=chat, user=request.user)

        return Response({
            'success': True,
            'chat_id': chat.id,
            'exists': False
        })

    except Exception as e:
        logger.error(f"Error in create_chat: {str(e)}")
        return Response({'success': False, 'error': 'Failed to create chat'})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def create_group(request):
    """API endpoint to create a group chat from mobile/web"""
    try:
        data = request.data
        name = data.get('name', '').strip()
        description = data.get('description', '').strip()

        try:
            max_participants = int(data.get('max_participants', 100))
        except (ValueError, TypeError):
            max_participants = 100

        is_public_val = data.get('is_public', False)
        if isinstance(is_public_val, str):
            is_public = is_public_val.lower() == 'true'
        else:
            is_public = bool(is_public_val)

        if not name:
            return Response({'success': False, 'error': 'Group name is required'})

        group_avatar = data.get('avatar')

        chat = Chat.objects.create(
            chat_type='group',
            name=name,
            description=description,
            admin=request.user,
            max_participants=max_participants,
            is_public=is_public,
            group_avatar=group_avatar
        )
        chat.participants.add(request.user)

        participant_ids = data.get('participants', [])
        if isinstance(participant_ids, str):
            import json
            try:
                participant_ids = json.loads(participant_ids)
            except Exception:
                pass

        if participant_ids and isinstance(participant_ids, list):
            users_to_add = CustomUser.objects.filter(id__in=participant_ids)
            chat.participants.add(*users_to_add)

        Message.objects.create(
            chat=chat,
            content=f'{request.user.full_name} created the group',
            message_type='system'
        )

        return Response({'success': True, 'chat_id': chat.id})
    except Exception as e:
        logger.error(f"Error in create_group: {str(e)}")
        return Response({'success': False, 'error': 'Failed to create group'})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def manage_chat_acceptance(request):
    """Manage chat request: accept or block"""
    try:
        chat_id = request.data.get('chat_id')
        action = request.data.get('action')  # 'accept' or 'block'

        if not chat_id or not action:
            return Response({'success': False, 'error': 'chat_id and action are required'})

        chat = get_object_or_404(Chat, id=chat_id, participants=request.user)

        other_user = None
        if chat.chat_type == 'private':
            other_user = chat.participants.exclude(id=request.user.id).first()

        if action == 'accept':
            ChatAcceptance.objects.get_or_create(chat=chat, user=request.user)
            return Response({'success': True, 'message': 'Chat accepted'})

        elif action == 'block':
            if other_user:
                from chat.models import Block, Follow, FollowRequest
                Block.objects.get_or_create(
                    blocker=request.user, blocked=other_user)

                Follow.objects.filter(
                    follower=request.user, following=other_user).delete()
                Follow.objects.filter(
                    follower=other_user, following=request.user).delete()
                FollowRequest.objects.filter(
                    requester=request.user, target=other_user).delete()
                FollowRequest.objects.filter(
                    requester=other_user, target=request.user).delete()

                return Response({'success': True, 'message': 'User blocked'})

        return Response({'success': False, 'error': 'Invalid action or user'})
    except Exception as e:
        logger.error(f"Error in manage_chat_acceptance: {str(e)}")
        return Response({'success': False, 'error': str(e)})

        return Response({
            'success': True,
            'data': {
                'group': {
                    'id': chat.id,
                    'name': chat.name,
                    'invite_link': chat.invite_link,
                    'invite_code': chat.invite_code,
                    'groupAvatar': chat.group_avatar.url if chat.group_avatar else None
                }
            }
        })

    except Exception as e:
        import traceback
        logger.error(f"Error in create_group: {str(e)}")
        logger.error(traceback.format_exc())
        return Response({'success': False, 'error': f'Failed to create group: {str(e)}'})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def join_group_api(request):
    """API endpoint to join a group by ID (for public groups from discover page)"""
    try:
        data = request.data
        group_id = data.get('group_id')

        if not group_id:
            return Response({'success': False, 'error': 'Group ID is required'})

        chat = Chat.objects.filter(id=group_id, chat_type='group').first()

        if not chat:
            return Response({'success': False, 'error': 'Group not found'})

        # Check if already a member
        if chat.participants.filter(id=request.user.id).exists():
            return Response({'success': False, 'error': 'You are already a member of this group'})

        # Check if group is full
        if not chat.can_add_participants:
            return Response({'success': False, 'error': 'This group is full'})

        # For public groups, add directly
        if chat.is_public:
            chat.participants.add(request.user)

            # Create system message
            Message.objects.create(
                chat=chat,
                content=f'{request.user.full_name} joined the group',
                message_type='system'
            )

            return Response({
                'success': True,
                'chat_id': chat.id,
                'message': f'You have joined {chat.name}!'
            })
        else:
            # For private groups, create a join request
            existing_request = GroupJoinRequest.objects.filter(
                group=chat,
                user=request.user,
                status='pending'
            ).first()

            if existing_request:
                return Response({'success': False, 'error': 'You already have a pending request'})

            GroupJoinRequest.objects.create(
                group=chat,
                user=request.user,
                message=''
            )

            return Response({
                'success': True,
                'pending': True,
                'message': f'Join request sent to {chat.name}'
            })

    except Exception as e:
        logger.error(f"Error in join_group_api: {str(e)}")
        return Response({'success': False, 'error': 'Failed to join group'})


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def join_group_view(request, invite_code):
    chat = get_object_or_404(Chat, invite_code=invite_code, chat_type='group')

    # Check if already a member
    already_member = chat.participants.filter(id=request.user.id).exists()
    if already_member:
        return render(request, 'chat/join_group.html', {'chat': chat, 'already_member': True})

    if not chat.can_add_participants:
        messages.error(request, f'{chat.name} is full')
        return redirect('dashboard')

    # Handle POST - actually join or send request
    if request.method == 'POST':
        if chat.is_public:
            # Public groups - join directly
            chat.participants.add(request.user)

            # Create system message
            Message.objects.create(
                chat=chat,
                content=f'{request.user.full_name} joined the group',
                message_type='system'
            )

            messages.success(request, f'You have joined {chat.name}!')
            return redirect('chat_detail', chat_id=chat.id)
        else:
            # Private groups - send join request
            existing_request = GroupJoinRequest.objects.filter(
                group=chat,
                user=request.user,
                status='pending'
            ).first()

            if existing_request:
                messages.info(
                    request, f'You already have a pending request to join {chat.name}')
                return redirect('dashboard')

            message = request.POST.get('message', '').strip()

            GroupJoinRequest.objects.create(
                group=chat,
                user=request.user,
                message=message
            )

            messages.success(request, f'Join request sent to {chat.name}.')
            return redirect('dashboard')

    # GET request - show the join confirmation page
    return render(request, 'chat/join_group.html', {'chat': chat, 'already_member': False})


def _get_explore_content_batch(page=1, per_page=15, user=None):
    """Helper function to get a batch of explore content with pagination
    Optimized for production - only loads needed items from database
    Shows scribes from users NOT followed by current user (discovery content)"""
    from django.core.cache import cache
    import random

    # Get users that current user follows (to exclude them)
    following_ids = []
    if user:
        # Exclude following, own posts, and blocked users
        following_ids = list(Follow.objects.filter(
            follower=user).values_list('following_id', flat=True))
        following_ids.append(user.id)

        # Also exclude blocked users and users who blocked us
        from .social import Block
        blocked_ids = list(Block.objects.filter(
            blocker=user).values_list('blocked_id', flat=True))
        blocked_me_ids = list(Block.objects.filter(
            blocked=user).values_list('blocker_id', flat=True))

        following_ids = list(set(following_ids + blocked_ids + blocked_me_ids))

    # Create a cache key unique to this user (no hour component - cleared on follow/unfollow)
    cache_key = f'explore_order_{user.id if user else "anon"}'

    # Try to get cached order from Redis/Cache
    shuffled_ids = cache.get(cache_key)

    if shuffled_ids is None:
        # Cache miss - rebuild the shuffled order
        # Get scribes from users NOT followed (discovery content)
        # Exclude reposts - only show original content in explore
        scribes_query = Scribe.objects.exclude(user_id__in=following_ids).filter(
            user__is_private=False,
            original_scribe__isnull=True,
            original_omzo__isnull=True,
            original_story__isnull=True
        )

        scribes_ids = list(
            scribes_query
            .values_list('id', flat=True)
            .order_by('-timestamp'))

        omzo_query = Omzo.objects.exclude(
            user_id__in=following_ids).filter(user__is_private=False)
        omzo_ids = list(
            omzo_query.values_list('id', flat=True)
            .order_by('-created_at'))

        # Create combined list of (id, type) tuples
        shuffled_ids = [(sid, 'scribe') for sid in scribes_ids] + \
                       [(rid, 'omzo') for rid in omzo_ids]

        # Shuffle
        random.shuffle(shuffled_ids)

        # Cache for 1 hour
        cache.set(cache_key, shuffled_ids, 3600)

    # Get only the items needed for this page
    offset = (page - 1) * per_page
    page_ids = shuffled_ids[offset:offset + per_page]

    if not page_ids:
        return []

    # Fetch only the needed items from database with full data for feed display
    paginated = []
    for item_id, item_type in page_ids:
        try:
            if item_type == 'scribe':
                obj = Scribe.objects.select_related(
                    'user',
                    'original_scribe',
                    'original_scribe__user',
                    'original_omzo',
                    'original_omzo__user',
                    'original_story',
                    'original_story__user'
                ).get(id=item_id)

                # Calculate time ago
                time_diff = timezone.now() - obj.timestamp
                if time_diff.days > 0:
                    time_ago = f"{time_diff.days}d"
                elif time_diff.seconds > 3600:
                    time_ago = f"{time_diff.seconds // 3600}h"
                else:
                    time_ago = f"{time_diff.seconds // 60}m"

                # Get interaction data
                like_count = Like.objects.filter(scribe=obj).count()
                is_liked = Like.objects.filter(
                    scribe=obj, user=user).exists() if user else False
                is_disliked = Dislike.objects.filter(
                    scribe=obj, user=user).exists() if user else False
                is_saved = SavedScribeItem.objects.filter(
                    scribe=obj, user=user).exists() if user else False
                comment_count = Comment.objects.filter(scribe=obj).count()

                # Get recent comments
                recent_comments = Comment.objects.filter(
                    scribe=obj,
                    parent__isnull=True
                ).select_related('user').order_by('-timestamp')[:3]

                paginated.append({
                    'type': item_type,
                    'object': obj,
                    'id': obj.id,
                    'content': obj.content,
                    'content_type': getattr(obj, 'content_type', 'text'),
                    'code_bundle': getattr(obj, 'code_bundle', None),
                    'code_html': getattr(obj, 'code_html', None),
                    'code_css': getattr(obj, 'code_css', None),
                    'code_js': getattr(obj, 'code_js', None),
                    'user': obj.user,
                    'user_id': obj.user.id,
                    'username': obj.user.username,
                    'fullname': obj.user.full_name,
                    'user_initials': obj.user.initials,
                    'profile_picture_url': obj.user.profile_picture_url,
                    'time_ago': time_ago,
                    'like_count': like_count,
                    'comment_count': comment_count,
                    'is_liked': is_liked,
                    'is_disliked': is_disliked,
                    'is_saved': is_saved,
                    'is_own': user and obj.user.id == user.id,
                    'image_url': obj.image_url,
                    'has_media': obj.has_media,
                    'recent_comments': recent_comments,
                    # Repost data
                    'is_repost': getattr(obj, 'is_repost', False),
                    'original_scribe': obj.original_scribe,
                    'original_omzo': obj.original_omzo,
                    'original_story': obj.original_story,
                })
            else:
                obj = Omzo.objects.select_related('user').get(id=item_id)

                # Calculate time ago for omzo
                time_diff = timezone.now() - obj.created_at
                if time_diff.days > 0:
                    time_ago = f"{time_diff.days}d"
                elif time_diff.seconds > 3600:
                    time_ago = f"{time_diff.seconds // 3600}h"
                else:
                    time_ago = f"{time_diff.seconds // 60}m"

                # Get interaction data for omzo
                like_count = OmzoLike.objects.filter(omzo=obj).count()
                is_liked = OmzoLike.objects.filter(
                    omzo=obj, user=user).exists() if user else False
                is_disliked = OmzoDislike.objects.filter(
                    omzo=obj, user=user).exists() if user else False
                is_saved = SavedOmzoItem.objects.filter(
                    omzo=obj, user=user).exists() if user else False
                comment_count = OmzoComment.objects.filter(omzo=obj).count()
                # Check if user has reposted this Omzo
                is_reposted = Scribe.objects.filter(
                    user=user, original_omzo=obj).exists() if user else False

                paginated.append({
                    'type': item_type,
                    'object': obj,
                    'id': obj.id,
                    'caption': obj.caption,
                    'video_url': obj.video_file.url if obj.video_file else None,
                    'user_id': obj.user.id,
                    'username': obj.user.username,
                    'fullname': obj.user.full_name,
                    'user_initials': obj.user.initials,
                    'profile_picture_url': obj.user.profile_picture_url,
                    'time_ago': time_ago,
                    'like_count': like_count,
                    'comment_count': comment_count,
                    'is_liked': is_liked,
                    'is_disliked': is_disliked,
                    'is_saved': is_saved,
                    'is_reposted': is_reposted,
                    'is_own': user and obj.user.id == user.id,
                })
        except (Scribe.DoesNotExist, Omzo.DoesNotExist):
            continue

    return paginated


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def discover_groups_view(request):
    """Explore page: show scribes and omzo from users NOT followed (discovery feed)."""

    # Get first page (15 items) - pass user to exclude followed users
    mixed_content = _get_explore_content_batch(
        page=1, per_page=15, user=request.user)

    # If the client is a mobile browser (Android/iOS) prefer showing only scribes
    # because some mobile WebViews have trouble with autoplay/video heavy pages.
    ua = request.META.get('HTTP_USER_AGENT', '') or ''
    ua_l = ua.lower()
    is_mobile_ua = False
    try:
        if 'android' in ua_l or 'mobile' in ua_l or 'iphone' in ua_l or 'ipad' in ua_l:
            is_mobile_ua = True
    except Exception:
        is_mobile_ua = False

    if is_mobile_ua:
        mixed_content = [
            item for item in mixed_content if item.get('type') == 'scribe']

    # Get user's chats for the DM panel in navbar
    private_chats = Chat.objects.filter(
        participants=request.user,
        chat_type='private'
    ).order_by('-updated_at').distinct()

    group_chats = Chat.objects.filter(
        participants=request.user,
        chat_type='group'
    ).order_by('-updated_at').distinct()

    # Get unread message count for the DM badge
    unread_message_count = Chat.objects.filter(
        participants=request.user,
        messages__is_read=False
    ).exclude(messages__sender=request.user).distinct().count()

    # Get story inbox count
    story_inbox_count = StoryReply.objects.filter(
        story__user=request.user,
        is_read=False
    ).count()

    context = {
        'mixed_content': mixed_content,
        'current_user': request.user,
        'private_chats': private_chats,
        'group_chats': group_chats,
        'unread_message_count': unread_message_count,
        'story_inbox_count': story_inbox_count,
    }

    return render(request, 'chat/discover_groups.html', context)


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def load_more_explore_content(request):
    """API endpoint for infinite scroll on explore page"""
    try:
        page = int(request.GET.get('page', 2))
        per_page = 15

        mixed_content = _get_explore_content_batch(
            page=page, per_page=per_page, user=request.user)

        # Serialize to JSON
        data = []
        for item in mixed_content:
            item_data = {'type': item['type']}

            if item['type'] == 'scribe':
                # Serialize recent comments
                recent_comments_data = []
                for comment in item.get('recent_comments', []):
                    recent_comments_data.append({
                        'username': comment.user.username,
                        'content': comment.content,
                    })

                item_data.update({
                    'id': item['id'],
                    'content': item['content'],
                    'content_type': item['content_type'],
                    'image_url': item['image_url'],
                    'code_bundle': item['code_bundle'],
                    'code_html': item['code_html'],
                    'code_css': item['code_css'],
                    'code_js': item['code_js'],
                    'like_count': item['like_count'],
                    'comment_count': item['comment_count'],
                    'is_liked': item['is_liked'],
                    'is_disliked': item['is_disliked'],
                    'is_saved': item['is_saved'],
                    'time_ago': item['time_ago'],
                    'recent_comments': recent_comments_data,
                    'user': {
                        'id': item['user_id'],
                        'username': item['username'],
                        'full_name': item['fullname'],
                        'profile_picture_url': item['profile_picture_url'],
                        'initials': item['user_initials'],
                    }
                })
            elif item['type'] == 'omzo':
                item_data.update({
                    'id': item['id'],
                    'caption': item['caption'],
                    'video_url': item['video_url'],
                    'like_count': item['like_count'],
                    'comment_count': item['comment_count'],
                    'is_liked': item['is_liked'],
                    'is_disliked': item['is_disliked'],
                    'is_saved': item['is_saved'],
                    'time_ago': item['time_ago'],
                    'user': {
                        'id': item['user_id'],
                        'username': item['username'],
                        'full_name': item['fullname'],
                        'profile_picture_url': item['profile_picture_url'],
                        'initials': item['user_initials'],
                    }
                })

            data.append(item_data)

        has_next = len(data) >= per_page

        return Response({
            'success': True,
            'content': data,
            'has_next': has_next,
            'page': page
        })

    except Exception as e:
        logger.error(f"Error in load_more_explore_content: {str(e)}")
        return Response({'success': False, 'error': 'Failed to load content'})


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def explore(request):
    """Explore page showing a vertical list of random scribes and a user search bar."""
    query = request.GET.get('q', '').strip()

    # Use the existing explore batch helper to prepare feed items (includes scribe fields)
    mixed_content = _get_explore_content_batch(
        page=1, per_page=30, user=request.user)
    # Keep only scribes and map to the same variable name used by dashboard
    scribes_data = [
        item for item in mixed_content if item.get('type') == 'scribe']

    # Log for debugging: how many scribes were returned for this user
    try:
        logger.info(
            f"Explore: returned {len(scribes_data)} scribes for user={request.user.username}")
        if len(scribes_data) > 0:
            # Log keys of first item to verify structure
            logger.debug(
                f"Explore sample keys: {list(scribes_data[0].keys())}")
    except Exception:
        pass

    # Fallback: if personalized explore is empty (user follows everyone), show global scribes
    if not scribes_data:
        logger.info(
            f"Explore: personalized feed empty for {request.user.username}, loading global feed")
        mixed_content = _get_explore_content_batch(
            page=1, per_page=30, user=None)
        scribes_data = [
            item for item in mixed_content if item.get('type') == 'scribe']

    # Navbar/chat context reused from other views
    private_chats = Chat.objects.filter(
        participants=request.user, chat_type='private').order_by('-updated_at').distinct()
    group_chats = Chat.objects.filter(
        participants=request.user, chat_type='group').order_by('-updated_at').distinct()
    unread_message_count = Chat.objects.filter(participants=request.user, messages__is_read=False).exclude(
        messages__sender=request.user).distinct().count()
    story_inbox_count = StoryReply.objects.filter(
        story__user=request.user, is_read=False).count()

    context = {
        'scribes': scribes_data,
        'scribes_data': scribes_data,
        'current_user': request.user,
        'private_chats': private_chats,
        'group_chats': group_chats,
        'unread_message_count': unread_message_count,
        'story_inbox_count': story_inbox_count,
    }

    return render(request, 'chat/explore.html', context)


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def manage_join_request(request):
    try:
        data = request.data
        request_id = data.get('request_id')
        action = data.get('action')

        if action not in ['approve', 'reject']:
            return Response({'success': False, 'error': 'Invalid action'})

        join_request = get_object_or_404(
            GroupJoinRequest,
            id=request_id,
            group__admin=request.user,
            status='pending'
        )

        if action == 'approve':
            if not join_request.group.can_add_participants:
                return Response({'success': False, 'error': 'Group is full'})

            join_request.group.participants.add(join_request.user)
            join_request.status = 'approved'

            # Create system message
            Message.objects.create(
                chat=join_request.group,
                content=f'{join_request.user.full_name} joined the group',
                message_type='system'
            )
        else:
            join_request.status = 'rejected'

        join_request.responded_at = timezone.now()
        join_request.responded_by = request.user
        join_request.save()

        return Response({
            'success': True,
            'action': action,
            'username': join_request.user.full_name
        })

    except Exception as e:
        logger.error(f"Error in manage_join_request: {str(e)}")
        return Response({'success': False, 'error': 'Failed to manage join request'})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def delete_message_for_me(request, message_id):
    """Delete message for current user only (hide it)"""
    try:
        message = Message.objects.get(id=message_id)
        # Check if user is participant in the chat
        if not message.chat.participants.filter(id=request.user.id).exists():
            return Response({'status': 'error', 'message': 'Unauthorized'}, status=403)

        # Create deletion record for this user
        MessageDeletion.objects.get_or_create(
            message=message,
            user=request.user
        )
        return Response({'status': 'success'})
    except Message.DoesNotExist:
        return Response({'status': 'error', 'message': 'Message not found'}, status=404)


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def delete_message_for_everyone(request, message_id):
    """Delete message for everyone (only sender can do this)"""
    try:
        message = Message.objects.get(id=message_id)

        # Check if user is the sender
        if message.sender != request.user:
            return Response({'status': 'error', 'message': 'You can only delete your own messages'}, status=403)

        # Check if user is participant in the chat
        if not message.chat.participants.filter(id=request.user.id).exists():
            return Response({'status': 'error', 'message': 'Unauthorized'}, status=403)

        # Delete the message completely
        message.delete()

        return Response({'status': 'success'})
    except Message.DoesNotExist:
        return Response({'status': 'error', 'message': 'Message not found'}, status=404)


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def consume_one_time_message(request, message_id):
    """Consume a one-time message"""
    try:
        # 🚀 OPTIMIZATION: Use select_related to fetch chat and sender in one query
        message = Message.objects.select_related('chat', 'sender').get(
            id=message_id, chat__participants=request.user, one_time=True)

        # 🔥 FIX: Only the RECIPIENT can consume the message, not the sender
        # The sender should not be able to mark their own view-once message as opened
        if message.sender == request.user:
            return Response({
                'success': False,
                'error': 'Sender cannot consume their own view-once message'
            })

        # Check if already consumed
        if message.consumed_at:
            return Response({'success': False, 'error': 'Message already consumed'})

        # Mark as consumed
        message.consumed_at = timezone.now()
        message.save(update_fields=['consumed_at'])

        # 🔥 Broadcast the consumed status to all participants (including sender)
        # This ensures the sender sees the message was opened without needing to refresh
        broadcast_message_consumed(message.chat, message, request.user)

        # 🚀 OPTIMIZATION: Pre-build absolute URL for media to avoid processing delay
        media_url = message.media_url
        if media_url:
            if not media_url.startswith('http'):
                media_url = request.build_absolute_uri(media_url)

        # Return response immediately with pre-built URLs
        return Response({
            'success': True,
            'content': decrypt_text(message.content) if message.content else message.content,
            'media_url': media_url,
            'media_type': message.media_type,
            'media_filename': message.media_filename,
            'consumed_at': message.consumed_at.isoformat()
        })

    except Message.DoesNotExist:
        return Response({'success': False, 'error': 'Message not found or not accessible'})
    except Exception as e:
        logger.error(f"Error consuming message: {str(e)}")
        return Response({'success': False, 'error': 'Failed to consume message'})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def mark_message_read(request, message_id):
    """Mark a message as read"""
    try:
        message = Message.objects.get(
            id=message_id, chat__participants=request.user)

        # Mark as read
        MessageRead.objects.get_or_create(
            message=message,
            user=request.user,
            defaults={'read_at': timezone.now()}
        )
        # Update is_read flag for the main message object
        if message.sender != request.user and not message.is_read:
            message.is_read = True
            message.save(update_fields=['is_read'])

            # Broadcast read status via WebSocket
            try:
                from channels.layers import get_channel_layer
                from asgiref.sync import async_to_sync
                channel_layer = get_channel_layer()

                async_to_sync(channel_layer.group_send)(
                    f'chat_{message.chat.id}',
                    {
                        'type': 'message_read',
                        'message_id': message.id,
                        'read_by': request.user.id,
                        'read_at': timezone.now().isoformat()
                    }
                )

                # Also notify current user's sidebar to clear the badge
                from chat.utils import clear_sidebar_unread
                clear_sidebar_unread(message.chat, request.user)
            except Exception as e:
                logger.error(f"Error broadcasting read status: {e}")

        return Response({'success': True})

    except Message.DoesNotExist:
        return Response({'success': False, 'error': 'Message not found'})
    except Exception as e:
        logger.error(f"Error marking message read: {str(e)}")
        return Response({'success': False, 'error': 'Failed to mark message read'})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def react_to_message(request, message_id):
    """Add or remove emoji reaction to a message"""
    try:
        data = request.data
        emoji = data.get('emoji', '').strip()

        if not emoji:
            return Response({'status': 'error', 'message': 'Emoji is required'})

        # Get the message
        message = get_object_or_404(Message, id=message_id)

        # Check if user is participant in the chat
        if not message.chat.participants.filter(id=request.user.id).exists():
            return Response({'status': 'error', 'message': 'Unauthorized'})

        # Check if reaction already exists
        existing_reaction = MessageReaction.objects.filter(
            message=message,
            user=request.user,
            emoji=emoji
        ).first()

        if existing_reaction:
            # Remove reaction
            existing_reaction.delete()
            return Response({
                'status': 'removed',
                'emoji': emoji,
                'message_id': message_id
            })
        else:
            # Add reaction
            MessageReaction.objects.create(
                message=message,
                user=request.user,
                emoji=emoji
            )
            return Response({
                'status': 'added',
                'emoji': emoji,
                'message_id': message_id
            })

    except Exception as e:
        logger.error(f"Error reacting to message: {str(e)}")
        return Response({'status': 'error', 'message': str(e)})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def update_typing_status(request, chat_id):
    try:
        data = request.data
        is_typing = data.get('is_typing')
        if isinstance(is_typing, str):
            is_typing = is_typing.lower() == 'true'
        else:
            is_typing = bool(is_typing)

        # Store typing status in cache (simple implementation)
        cache_key = f'chat_{chat_id}_typing'

        typing_users = cache.get(cache_key, set())
        if is_typing:
            typing_users.add(request.user.id)
        else:
            typing_users.discard(request.user.id)

        # Set cache with 4 second expiry (slightly longer than 2s keep-alive to prevent flicker)
        cache.set(cache_key, typing_users, 4)

        return Response({'success': True})

    except Exception as e:
        logger.error(f"Error updating typing status: {str(e)}")
        return Response({'success': False, 'error': 'Failed to update typing status'})


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def get_typing_status(request, chat_id):
    """Get current typing users for a chat"""
    from django.core.cache import cache
    try:
        cache_key = f'chat_{chat_id}_typing'
        typing_user_ids = cache.get(cache_key, set())

        typing_users = []
        for user_id in typing_user_ids:
            try:
                user = CustomUser.objects.get(id=user_id)
                if user != request.user:  # Don't show own typing status
                    typing_users.append({
                        'id': user.id,
                        'name': user.full_name
                    })
            except CustomUser.DoesNotExist:
                pass

        return Response({'typing_users': typing_users})

    except Exception as e:
        logger.error(f"Error getting typing status: {str(e)}")
        return Response({'typing_users': []})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def edit_message(request, message_id):
    """Edit a message (within 15 minute window)"""
    try:
        message = get_object_or_404(Message, id=message_id)

        # Check if user is the sender
        if message.sender != request.user:
            return Response({'success': False, 'error': 'You can only edit your own messages'})

        # Check if message can still be edited (15 minute limit)
        if not message.can_be_edited:
            return Response({'success': False, 'error': 'Message can no longer be edited (15 minute limit exceeded)'})

        # Check if it's a media-only message
        if message.message_type == 'media' and not message.content:
            return Response({'success': False, 'error': 'Cannot edit media-only messages'})

        data = request.data
        new_content = data.get('content', '').strip()

        if not new_content:
            return Response({'success': False, 'error': 'Message content cannot be empty'})

        if len(new_content) > 5000:
            return Response({'success': False, 'error': 'Message too long (max 5000 characters)'})

        # Store original content if first edit
        if not message.is_edited:
            message.original_content = message.content

        # Update message
        message.content = encrypt_text(new_content)
        message.is_edited = True
        message.edited_at = timezone.now()
        message.save()

        return Response({
            'success': True,
            'message': {
                'id': message.id,
                'content': new_content,
                'is_edited': message.is_edited,
                'edited_at': message.edited_at.isoformat() if message.edited_at else None
            }
        })

    except json.JSONDecodeError:
        return Response({'success': False, 'error': 'Invalid JSON'})
    except Exception as e:
        logger.error(f"Error editing message: {str(e)}")
        return Response({'success': False, 'error': 'Failed to edit message'})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def pin_message(request, message_id):
    """Toggle pin/unpin a message in a chat (admin only for groups, any participant for private)"""
    try:
        message = get_object_or_404(Message, id=message_id)
        chat = message.chat

        # Check if user is participant
        if not chat.participants.filter(id=request.user.id).exists():
            return Response({'success': False, 'error': 'You are not a participant of this chat'})

        # For group chats, only admin can pin/unpin
        if chat.chat_type == 'group' and chat.admin != request.user:
            return Response({'success': False, 'error': 'Only group admin can pin/unpin messages'})

        # Toggle pin status
        if message.is_pinned:
            # Unpin the message
            message.is_pinned = False
            message.pinned_at = None
            message.pinned_by = None
            message.save()

            return Response({
                'success': True,
                'pinned': False,
                'message_id': message.id
            })
        else:
            # Pin the message
            message.is_pinned = True
            message.pinned_at = timezone.now()
            message.pinned_by = request.user
            message.save()

            return Response({
                'success': True,
                'pinned': True,
                'message_id': message.id,
                'pinned_at': message.pinned_at.isoformat(),
                'pinned_by': request.user.full_name
            })

    except Exception as e:
        logger.error(f"Error toggling pin message: {str(e)}")
        return Response({'success': False, 'error': 'Failed to toggle pin'})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def unpin_message(request, message_id):
    """Unpin a message in a chat"""
    try:
        message = get_object_or_404(Message, id=message_id)
        chat = message.chat

        # Check if user is participant
        if not chat.participants.filter(id=request.user.id).exists():
            return Response({'success': False, 'error': 'You are not a participant of this chat'})

        # For group chats, only admin can unpin
        if chat.chat_type == 'group' and chat.admin != request.user:
            return Response({'success': False, 'error': 'Only group admin can unpin messages'})

        # Unpin the message
        message.is_pinned = False
        message.pinned_at = None
        message.pinned_by = None
        message.save()

        return Response({
            'success': True,
            'message': {
                'id': message.id,
                'is_pinned': False
            }
        })

    except Exception as e:
        logger.error(f"Error unpinning message: {str(e)}")
        return Response({'success': False, 'error': 'Failed to unpin message'})


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def get_pinned_messages(request, chat_id):
    """Get all pinned messages in a chat"""
    try:
        chat = get_object_or_404(Chat, id=chat_id, participants=request.user)

        pinned_messages = Message.objects.filter(
            chat=chat,
            is_pinned=True
        ).select_related('sender', 'pinned_by').order_by('-pinned_at')

        messages_data = []
        for msg in pinned_messages:
            messages_data.append({
                'id': msg.id,
                'content': msg.content[:200] + '...' if len(msg.content) > 200 else msg.content,
                'sender': {
                    'id': msg.sender.id if msg.sender else None,
                    'username': msg.sender.username if msg.sender else 'System',
                    'full_name': msg.sender.full_name if msg.sender else 'System'
                },
                'timestamp': msg.timestamp.isoformat(),
                'pinned_at': msg.pinned_at.isoformat() if msg.pinned_at else None,
                'pinned_by': msg.pinned_by.full_name if msg.pinned_by else None,
                'media_type': msg.media_type,
                'has_media': msg.has_media
            })

        return Response({
            'success': True,
            'pinned_messages': messages_data,
            'count': len(messages_data)
        })

    except Exception as e:
        logger.error(f"Error getting pinned messages: {str(e)}")
        return Response({'success': False, 'error': 'Failed to get pinned messages'})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def pin_chat(request, chat_id):
    """Pin a chat/conversation to the top"""
    try:
        chat = get_object_or_404(Chat, id=chat_id, participants=request.user)

        # Check if already pinned
        if PinnedChat.objects.filter(user=request.user, chat=chat).exists():
            return Response({'success': False, 'error': 'Chat is already pinned'})

        # Limit pinned chats to 5
        if PinnedChat.objects.filter(user=request.user).count() >= 5:
            return Response({'success': False, 'error': 'You can only pin up to 5 chats'})

        PinnedChat.objects.create(user=request.user, chat=chat)

        return Response({'success': True, 'message': 'Chat pinned successfully'})

    except Exception as e:
        logger.error(f"Error pinning chat: {str(e)}")
        return Response({'success': False, 'error': 'Failed to pin chat'})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def unpin_chat(request, chat_id):
    """Unpin a chat/conversation"""
    try:
        chat = get_object_or_404(Chat, id=chat_id, participants=request.user)

        pinned = PinnedChat.objects.filter(user=request.user, chat=chat)
        if not pinned.exists():
            return Response({'success': False, 'error': 'Chat is not pinned'})

        pinned.delete()

        return Response({'success': True, 'message': 'Chat unpinned successfully'})

    except Exception as e:
        logger.error(f"Error unpinning chat: {str(e)}")
        return Response({'success': False, 'error': 'Failed to unpin chat'})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def toggle_star_message(request, message_id):
    """Toggle star/unstar a message for the current user"""
    try:
        message = get_object_or_404(Message, id=message_id)
        chat = message.chat

        # Verify user is participant
        if request.user not in chat.participants.all():
            return Response({'success': False, 'error': 'Not authorized'}, status=403)

        starred, created = StarredMessage.objects.get_or_create(
            user=request.user,
            message=message
        )

        if not created:
            # Already starred, so unstar it
            starred.delete()
            return Response({
                'success': True,
                'is_starred': False,
                'message': 'Message unstarred'
            })

        return Response({
            'success': True,
            'is_starred': True,
            'message': 'Message starred'
        })

    except Exception as e:
        logger.error(f"Error toggling star: {str(e)}")
        return Response({'success': False, 'error': 'Failed to toggle star'})


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def get_starred_messages(request):
    """Get all starred messages for the current user"""
    try:
        starred = StarredMessage.objects.filter(user=request.user).select_related(
            'message', 'message__sender', 'message__chat'
        )

        messages_data = []
        for star in starred:
            msg = star.message
            messages_data.append({
                'id': msg.id,
                'content': msg.content,
                'sender': {
                    'id': msg.sender.id if msg.sender else None,
                    'username': msg.sender.username if msg.sender else 'System',
                    'full_name': msg.sender.full_name if msg.sender else 'System'
                },
                'chat_id': msg.chat.id,
                'chat_name': msg.chat.name if msg.chat.chat_type == 'group' else None,
                'timestamp': msg.timestamp.strftime('%b %d, %Y %I:%M %p'),
                'starred_at': star.starred_at.strftime('%b %d, %Y %I:%M %p'),
                'media_type': msg.media_type,
                'media_url': msg.media_url
            })

        return Response({
            'success': True,
            'starred_messages': messages_data,
            'count': len(messages_data)
        })

    except Exception as e:
        logger.error(f"Error getting starred messages: {str(e)}")
        return Response({'success': False, 'error': 'Failed to get starred messages'})


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def is_message_starred(request, message_id):
    """Check if a message is starred by current user"""
    try:
        is_starred = StarredMessage.objects.filter(
            user=request.user,
            message_id=message_id
        ).exists()

        return Response({'success': True, 'is_starred': is_starred})

    except Exception as e:
        return Response({'success': False, 'error': str(e)})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def mark_messages_read(request, chat_id):
    """Mark all messages in a chat as read by current user"""
    try:
        chat = get_object_or_404(Chat, id=chat_id, participants=request.user)

        logger.info(
            f"MARK_READ: User {request.user.username} (ID {request.user.id}) calling mark_reak for chat {chat_id}")

        # Get all unread messages from other users
        unread_messages = Message.objects.filter(
            chat=chat
        ).exclude(
            sender=request.user
        ).exclude(
            read_receipts__user=request.user
        )

        # Create read receipts for each
        read_receipts = []
        for msg in unread_messages:
            read_receipts.append(MessageRead(message=msg, user=request.user))

        if read_receipts:
            MessageRead.objects.bulk_create(
                read_receipts, ignore_conflicts=True)
            # Sync the is_read flag on all messages
            unread_messages.update(is_read=True)

        # Always broadcast the latest read message status to sync clients
        # even if no new receipts were created (e.g., they were already marked as read)
        try:
            last_msg = chat.messages.exclude(
                sender=request.user).order_by('-id').first()
            if last_msg:
                from channels.layers import get_channel_layer
                from asgiref.sync import async_to_sync
                channel_layer = get_channel_layer()

                async_to_sync(channel_layer.group_send)(
                    f'chat_{chat_id}',
                    {
                        'type': 'message_read',
                        'message_id': last_msg.id,
                        'read_by': request.user.id,
                        'read_at': timezone.now().isoformat()
                    }
                )

                # Also notify current user's sidebar to clear the badge
                from chat.utils import clear_sidebar_unread
                clear_sidebar_unread(chat, request.user)
        except Exception as e:
            logger.error(f"Error broadcasting read status: {e}")

        return Response({
            'success': True,
            'marked_count': len(read_receipts)
        })

    except Exception as e:
        logger.error(f"Error marking messages read: {str(e)}")
        return Response({'success': False, 'error': 'Failed to mark messages read'})


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def get_message_read_status(request, message_id):
    """Get read receipt status for a specific message"""
    try:
        message = get_object_or_404(Message, id=message_id)

        # Only sender can see read receipts
        if message.sender != request.user:
            return Response({'success': False, 'error': 'Not authorized'}, status=403)

        read_receipts = MessageRead.objects.filter(
            message=message).select_related('user')

        readers = []
        for receipt in read_receipts:
            readers.append({
                'user_id': receipt.user.id,
                'username': receipt.user.username,
                'full_name': receipt.user.full_name,
                'read_at': receipt.read_at.strftime('%b %d, %I:%M %p')
            })

        # Get total participants (excluding sender)
        total_recipients = message.chat.participants.exclude(
            id=request.user.id).count()

        return Response({
            'success': True,
            'readers': readers,
            'read_count': len(readers),
            'total_recipients': total_recipients,
            'all_read': len(readers) >= total_recipients
        })

    except Exception as e:
        logger.error(f"Error getting read status: {str(e)}")
        return Response({'success': False, 'error': 'Failed to get read status'})


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def get_chat_read_status(request, chat_id):
    """Get read status for all messages in a chat (for current user's messages)"""
    try:
        chat = get_object_or_404(Chat, id=chat_id, participants=request.user)

        # Get user's messages that have been read
        user_messages = Message.objects.filter(
            chat=chat,
            sender=request.user
        ).annotate(
            read_count=Count('read_receipts')
        )

        total_recipients = chat.participants.exclude(
            id=request.user.id).count()

        read_status = {}
        for msg in user_messages:
            read_status[str(msg.id)] = {
                'read_count': msg.read_count,
                'total_recipients': total_recipients,
                'status': 'read' if msg.read_count >= total_recipients else ('delivered' if msg.read_count > 0 else 'sent')
            }

        return Response({
            'success': True,
            'read_status': read_status
        })

    except Exception as e:
        logger.error(f"Error getting chat read status: {str(e)}")
        return Response({'success': False, 'error': 'Failed to get read status'})


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def get_user_online_status(request, user_id):
    """Get online status of a specific user"""
    try:
        user = get_object_or_404(CustomUser, id=user_id)

        # A user is considered online only if:
        # 1. is_online flag is True AND
        # 2. last_seen is within the last 15 seconds (indicating active session)
        is_truly_online = False
        if user.is_online and user.last_seen:
            time_since_last_seen = timezone.now() - user.last_seen
            is_truly_online = time_since_last_seen < timedelta(seconds=15)

            # If is_online is True but last_seen is too old, mark them offline
            if not is_truly_online and user.is_online:
                user.is_online = False
                user.save(update_fields=['is_online'])

        # Calculate last seen display
        if is_truly_online:
            last_seen_display = "Online"
        elif user.last_seen:
            time_diff = timezone.now() - user.last_seen
            if time_diff.days > 0:
                last_seen_display = f"{time_diff.days}d ago"
            elif time_diff.seconds >= 3600:
                last_seen_display = f"{time_diff.seconds // 3600}h ago"
            elif time_diff.seconds >= 60:
                last_seen_display = f"{time_diff.seconds // 60}m ago"
            else:
                last_seen_display = "Just now"
        else:
            last_seen_display = "Unknown"

        return Response({
            'success': True,
            'user_id': user.id,
            'username': user.username,
            'is_online': is_truly_online,
            'last_seen': user.last_seen.isoformat() if user.last_seen else None,
            'last_seen_display': last_seen_display
        })

    except Exception as e:
        logger.error(f"Error getting user online status: {str(e)}")
        return Response({'success': False, 'error': 'Failed to get online status'})


@api_view(["POST"])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def user_heartbeat(request):
    """Update user's online status - heartbeat endpoint"""
    try:
        request.user.last_seen = timezone.now()
        request.user.is_online = True
        request.user.save(update_fields=['last_seen', 'is_online'])

        return Response({
            'success': True,
            'timestamp': timezone.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Heartbeat error for user {request.user.id}: {str(e)}")
        return Response({'success': False, 'error': 'Heartbeat failed'})


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def get_chat_participant_status(request, chat_id):
    """Get online status of all participants in a chat (for private chats, returns the other user's status)"""
    try:
        chat = get_object_or_404(Chat, id=chat_id, participants=request.user)

        # Update current user's last_seen to mark them as active
        request.user.last_seen = timezone.now()
        request.user.is_online = True
        request.user.save(update_fields=['last_seen', 'is_online'])

        participants_status = []
        for participant in chat.participants.exclude(id=request.user.id):
            # A user is considered online only if:
            # 1. is_online flag is True AND
            # 2. last_seen is within the last 15 seconds (indicating active session)
            is_truly_online = False
            if participant.is_online and participant.last_seen:
                time_since_last_seen = timezone.now() - participant.last_seen
                is_truly_online = time_since_last_seen < timedelta(seconds=15)

                # If is_online is True but last_seen is too old, mark them offline
                if not is_truly_online and participant.is_online:
                    participant.is_online = False
                    participant.save(update_fields=['is_online'])

            # Calculate last seen display
            if is_truly_online:
                last_seen_display = "Online"
            elif participant.last_seen:
                time_diff = timezone.now() - participant.last_seen
                if time_diff.days > 0:
                    last_seen_display = f"Last seen {time_diff.days}d ago"
                elif time_diff.seconds >= 3600:
                    last_seen_display = f"Last seen {time_diff.seconds // 3600}h ago"
                elif time_diff.seconds >= 60:
                    last_seen_display = f"Last seen {time_diff.seconds // 60}m ago"
                else:
                    last_seen_display = "Last seen just now"
            else:
                last_seen_display = "Never seen online"

            participants_status.append({
                'user_id': participant.id,
                'username': participant.username,
                'full_name': participant.full_name,
                'is_online': is_truly_online,
                'last_seen': participant.last_seen.isoformat() if participant.last_seen else None,
                'last_seen_display': last_seen_display
            })

        return Response({
            'success': True,
            'chat_id': chat_id,
            'chat_type': chat.chat_type,
            'participants': participants_status
        })

    except Exception as e:
        logger.error(f"Error getting chat participant status: {str(e)}")
        return Response({'success': False, 'error': 'Failed to get participant status'})


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def get_group_details(request, chat_id):
    """Get detailed information about a group chat"""
    try:
        chat = get_object_or_404(Chat, id=chat_id, chat_type='group')

        # Check if user is a participant
        if not chat.participants.filter(id=request.user.id).exists():
            return Response({'success': False, 'error': 'You are not a member of this group'}, status=403)

        is_admin = chat.admin == request.user

        # Get all participants with their details
        members = []
        for participant in chat.participants.all():
            # Check if truly online (with 15 second threshold)
            is_truly_online = participant.is_online and participant.last_seen and (
                timezone.now() - participant.last_seen).total_seconds() < 15

            members.append({
                'id': participant.id,
                'username': participant.username,
                'full_name': participant.full_name,
                'profile_picture': participant.profile_picture_url,
                'is_admin': participant == chat.admin,
                'is_online': is_truly_online,
            })

        # Sort: Admin first, then online users, then alphabetically
        members.sort(key=lambda x: (
            not x['is_admin'], not x['is_online'], x['full_name'].lower()))

        return Response({
            'success': True,
            'group': {
                'id': chat.id,
                'name': chat.name,
                'description': chat.description or '',
                'is_public': chat.is_public,
                'max_participants': chat.max_participants,
                'participant_count': chat.participant_count,
                'invite_code': chat.invite_code,
                'invite_link': chat.invite_link,
                'group_avatar': chat.group_avatar.url if getattr(chat, 'group_avatar', None) else None,
                'created_at': chat.created_at.strftime('%B %d, %Y'),
                'is_admin': is_admin,
            },
            'members': members
        })

    except Exception as e:
        logger.error(f"Error getting group details: {str(e)}")
        return Response({'success': False, 'error': 'Failed to get group details'})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def update_group_settings(request, chat_id):
    """Update group settings (admin only)"""
    try:
        chat = get_object_or_404(Chat, id=chat_id, chat_type='group')

        # Check if user is admin
        if chat.admin != request.user:
            return Response({'success': False, 'error': 'Only the group admin can update settings'}, status=403)

        # Use DRF request.data which handles both JSON and Multipart/form-data
        data = request.data or {}

        # Update fields if provided
        if 'name' in data:
            name = data['name'].strip()
            if not name:
                return Response({'success': False, 'error': 'Group name cannot be empty'})
            if len(name) > 100:
                return Response({'success': False, 'error': 'Group name is too long (max 100 characters)'})
            chat.name = name

        if 'description' in data:
            description = data['description'].strip()
            if len(description) > 500:
                return Response({'success': False, 'error': 'Description is too long (max 500 characters)'})
            chat.description = description

        if 'is_public' in data:
            chat.is_public = bool(data['is_public'])

        if 'max_participants' in data:
            max_participants = int(data['max_participants'])
            if max_participants < chat.participant_count:
                return Response({'success': False, 'error': f'Cannot set max lower than current member count ({chat.participant_count})'})
            if max_participants < 2 or max_participants > 500:
                return Response({'success': False, 'error': 'Max participants must be between 2 and 500'})
            chat.max_participants = max_participants

        # Handle remove avatar request
        if data.get('remove_avatar'):
            try:
                if getattr(chat, 'group_avatar', None):
                    try:
                        chat.group_avatar.delete(save=False)
                    except Exception:
                        logger.exception('Failed deleting old avatar file')
                    chat.group_avatar = None
                chat.save()
            except Exception as e:
                logger.error(f"Failed to remove group avatar: {str(e)}")
                return Response({'success': False, 'error': 'Failed to remove group avatar'})

        # Handle group avatar upload (multipart/form-data)
        avatar_file = request.data.get('group_avatar')
        if avatar_file:
            try:
                # assign uploaded file to ImageField and save
                if getattr(chat, 'group_avatar', None):
                    try:
                        chat.group_avatar.delete(save=False)
                    except Exception:
                        logger.exception('Failed deleting old avatar file')
                chat.group_avatar = avatar_file
                chat.save()
            except Exception as e:
                logger.error(f"Failed to save group avatar: {str(e)}")
                return Response({'success': False, 'error': 'Failed to upload group avatar'})

        chat.save()

        # Create system message for name change
        if 'name' in data:
            Message.objects.create(
                chat=chat,
                content=f'{request.user.full_name} changed the group name to "{chat.name}"',
                message_type='system'
            )

        return Response({
            'success': True,
            'message': 'Group settings updated successfully',
            'group': {
                'name': chat.name,
                'description': chat.description,
                'is_public': chat.is_public,
                'max_participants': chat.max_participants,
                'group_avatar': chat.group_avatar.url if getattr(chat, 'group_avatar', None) else None,
            }
        })

    except json.JSONDecodeError:
        return Response({'success': False, 'error': 'Invalid request data'})
    except Exception as e:
        logger.error(f"Error updating group settings: {str(e)}")
        return Response({'success': False, 'error': 'Failed to update group settings'})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def remove_group_member(request, chat_id):
    """Remove a member from the group (admin only)"""
    try:
        chat = get_object_or_404(Chat, id=chat_id, chat_type='group')

        # Check if user is admin
        if chat.admin != request.user:
            return Response({'success': False, 'error': 'Only the group admin can remove members'}, status=403)

        data = request.data
        user_id = data.get('user_id')

        if not user_id:
            return Response({'success': False, 'error': 'User ID is required'})

        # Cannot remove yourself (admin) - use leave group instead
        if user_id == request.user.id:
            return Response({'success': False, 'error': 'Admin cannot remove themselves. Use leave group instead.'})

        # Get the member to remove
        member = get_object_or_404(CustomUser, id=user_id)

        # Check if member is in the group
        if not chat.participants.filter(id=user_id).exists():
            return Response({'success': False, 'error': 'User is not a member of this group'})

        # Remove member
        chat.participants.remove(member)

        # Create system message
        Message.objects.create(
            chat=chat,
            content=f'{member.full_name} was removed from the group by {request.user.full_name}',
            message_type='system'
        )

        return Response({
            'success': True,
            'message': f'{member.full_name} has been removed from the group',
            'removed_user_id': user_id
        })

    except json.JSONDecodeError:
        return Response({'success': False, 'error': 'Invalid request data'})
    except Exception as e:
        logger.error(f"Error removing group member: {str(e)}")
        return Response({'success': False, 'error': 'Failed to remove member'})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def leave_group(request, chat_id):
    """Leave a group chat"""
    try:
        chat = get_object_or_404(Chat, id=chat_id, chat_type='group')

        # Check if user is a participant
        if not chat.participants.filter(id=request.user.id).exists():
            return Response({'success': False, 'error': 'You are not a member of this group'}, status=403)

        is_admin = chat.admin == request.user

        # If admin is leaving, transfer admin to another member or delete group
        if is_admin:
            other_members = chat.participants.exclude(id=request.user.id)
            if other_members.exists():
                # Transfer admin to the first other member
                new_admin = other_members.first()
                chat.admin = new_admin
                chat.save()

                # Create system message
                Message.objects.create(
                    chat=chat,
                    content=f'{request.user.full_name} left the group. {new_admin.full_name} is now the admin.',
                    message_type='system'
                )
            else:
                # No other members, delete the group
                chat.delete()
                return Response({
                    'success': True,
                    'message': 'You left and the group was deleted (no members remaining)',
                    'group_deleted': True
                })
        else:
            # Non-admin leaving
            Message.objects.create(
                chat=chat,
                content=f'{request.user.full_name} left the group',
                message_type='system'
            )

        # Remove user from participants
        chat.participants.remove(request.user)

        return Response({
            'success': True,
            'message': 'You have left the group',
            'group_deleted': False
        })

    except Exception as e:
        logger.error(f"Error leaving group: {str(e)}")
        return Response({'success': False, 'error': 'Failed to leave group'})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def regenerate_invite_code(request, chat_id):
    """Regenerate the group invite code (admin only)"""
    try:
        chat = get_object_or_404(Chat, id=chat_id, chat_type='group')

        # Check if user is admin
        if chat.admin != request.user:
            return Response({'success': False, 'error': 'Only the group admin can regenerate invite code'}, status=403)

        # Generate new invite code
        chat.invite_code = chat.generate_invite_code()
        chat.save()

        return Response({
            'success': True,
            'invite_code': chat.invite_code,
            'invite_link': chat.invite_link
        })

    except Exception as e:
        logger.error(f"Error regenerating invite code: {str(e)}")
        return Response({'success': False, 'error': 'Failed to regenerate invite code'})


def get_p2p_cache():
    """Get cache backend for P2P signals - uses Redis in production, fallback to default cache"""
    from django.core.cache import cache
    return cache


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def p2p_send_signal(request):
    """Deprecated HTTP signaling endpoint"""
    return Response({'success': False, 'message': 'Deprecated endpoints - please use WebSockets.', 'deprecated': True})


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def p2p_get_signals(request, chat_id):
    """Deprecated HTTP signaling endpoint"""
    return Response({'success': False, 'signals': [], 'message': 'Deprecated endpoints - please use WebSockets.', 'deprecated': True})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def p2p_clear_signals(request):
    """Deprecated HTTP signaling endpoint"""
    return Response({'success': False, 'message': 'Deprecated endpoints - please use WebSockets.', 'deprecated': True})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def send_call_notification(request):
    """Send call notification to other participants via HTTP (fallback if WebSocket fails)"""
    try:
        data = request.data
        chat_id = data.get('chat_id')
        audio_only = data.get('audio_only', False)

        if not chat_id:
            return Response({'success': False, 'error': 'Missing chat_id'})

        chat = get_object_or_404(Chat, id=chat_id)
        if not chat.participants.filter(id=request.user.id).exists():
            return Response({'success': False, 'error': 'Not a participant'}, status=403)

        # Get caller details
        caller_name = request.user.full_name
        caller_avatar = request.user.profile_picture_url

        # Get other participants
        others = chat.participants.exclude(id=request.user.id)

        # Send notification via channel layer (NotifyConsumer)
        channel_layer = get_channel_layer()
        for other_user in others:
            async_to_sync(channel_layer.group_send)(
                f'user_notify_{other_user.id}',
                {
                    'type': 'notify.call',
                    'from_user_id': request.user.id,
                    'chat_id': chat_id,
                    'audio_only': audio_only,
                    'from_full_name': caller_name,
                    'from_avatar': caller_avatar,
                }
            )

        logger.info(
            f"Call notification sent via HTTP for chat {chat_id} to {others.count()} users")
        return Response({'success': True, 'notified': others.count()})

    except Exception as e:
        logger.error(f"Error sending call notification: {e}", exc_info=True)
        return Response({'success': False, 'error': str(e)})


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def get_chat_participants_for_p2p(request, chat_id):
    """Get list of chat participants for P2P file sharing"""
    try:
        chat = get_object_or_404(Chat, id=chat_id)

        # Verify user is in the chat
        if not chat.participants.filter(id=request.user.id).exists():
            return Response({'success': False, 'error': 'Not a participant of this chat'}, status=403)

        # Update the requesting user's online status (heartbeat)
        request.user.last_seen = timezone.now()
        request.user.is_online = True
        request.user.save(update_fields=['last_seen', 'is_online'])

        participants = []
        for p in chat.participants.exclude(id=request.user.id):
            # Refresh from database to get latest status
            p.refresh_from_db()
            # Check if truly online
            is_online = p.is_online and p.last_seen and (
                timezone.now() - p.last_seen).total_seconds() < 15
            participants.append({
                'id': p.id,
                'username': p.username,
                'full_name': p.full_name,
                'profile_picture': p.profile_picture_url,
                'is_online': is_online
            })

        return Response({
            'success': True,
            'chat_type': chat.chat_type,
            'participants': participants
        })

    except Exception as e:
        logger.error(f"Error getting participants for P2P: {str(e)}")
        return Response({'success': False, 'error': 'Failed to get participants'})


# ================ CHAT REQUEST SYSTEM (Instagram-style) ================

@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def get_dm_requests(request):
    """
    Get chats that are pending acceptance (like Instagram DM requests).
    These are private chats where:
    1. The user is a participant
    2. The user has NOT accepted the chat (no ChatAcceptance record)
    3. There are messages from the other person
    """
    user = request.user

    # Get all private chats where user is a participant but hasn't accepted
    accepted_chat_ids = ChatAcceptance.objects.filter(
        user=user
    ).values_list('chat_id', flat=True)

    # Get private chats not accepted by user
    pending_chats = Chat.objects.filter(
        participants=user,
        chat_type='private'
    ).exclude(
        id__in=accepted_chat_ids
    ).prefetch_related('participants', 'messages').order_by('-updated_at')

    requests_data = []
    for chat in pending_chats:
        # Get the other participant
        other_user = chat.participants.exclude(id=user.id).first()
        if not other_user:
            continue

        # Check if there are messages from the other person
        has_their_messages = chat.messages.filter(sender=other_user).exists()
        if not has_their_messages:
            continue  # No messages from them, not a request

        # Get last message info
        last_msg = chat.messages.order_by('-timestamp').first()
        last_message = ''
        if last_msg:
            if last_msg.message_type == 'media':
                last_message = '📷 Sent a file'
            elif last_msg.message_type == 'system':
                last_message = '[System]'
            else:
                last_message = last_msg.content[:50] + \
                    ('...' if len(last_msg.content) > 50 else '')

        unread_count = chat.messages.filter(
            is_read=False).exclude(sender=user).count()

        requests_data.append({
            'chat_id': chat.id,
            'sender': {
                'id': other_user.id,
                'username': other_user.username,
                'full_name': other_user.full_name,
                'avatar_url': other_user.profile_picture_url,
                'is_online': other_user.is_online,
            },
            'last_message': last_message,
            'unread_count': unread_count,
            'timestamp': chat.updated_at.isoformat(),
        })

    return Response({
        'success': True,
        'requests': requests_data,
        'count': len(requests_data)
    })


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def get_dm_requests_count(request):
    """Get count of pending DM requests for badge"""
    user = request.user

    accepted_chat_ids = ChatAcceptance.objects.filter(
        user=user
    ).values_list('chat_id', flat=True)

    # Count private chats not accepted that have messages from others
    count = Chat.objects.filter(
        participants=user,
        chat_type='private'
    ).exclude(
        id__in=accepted_chat_ids
    ).filter(
        messages__sender__in=Chat.objects.filter(
            participants=user,
            chat_type='private'
        ).exclude(id__in=accepted_chat_ids).values('participants').exclude(participants=user)
    ).distinct().count()

    # Simpler count - just count non-accepted private chats with any messages
    pending_chats = Chat.objects.filter(
        participants=user,
        chat_type='private'
    ).exclude(id__in=accepted_chat_ids)

    count = 0
    for chat in pending_chats:
        other_user = chat.participants.exclude(id=user.id).first()
        if other_user and chat.messages.filter(sender=other_user).exists():
            count += 1

    return Response({'success': True, 'count': count})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def accept_dm_request(request, chat_id):
    """Accept a DM request - moves chat from Requests to All tab"""
    user = request.user
    chat = get_object_or_404(
        Chat, id=chat_id, participants=user, chat_type='private')

    # Create acceptance record
    ChatAcceptance.objects.get_or_create(chat=chat, user=user)

    # Notify frontend via WebSocket
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f"sidebar_{user.id}",
        {
            "type": "chat_accepted",
            "chat_id": chat_id,
        }
    )

    return Response({'success': True, 'message': 'Chat accepted'})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def decline_dm_request(request, chat_id):
    """Decline a DM request - removes the chat"""
    user = request.user
    chat = get_object_or_404(
        Chat, id=chat_id, participants=user, chat_type='private')

    # Delete the user from the chat (or delete the chat entirely)
    chat.participants.remove(user)

    # If no participants left, delete the chat
    if chat.participants.count() == 0:
        chat.delete()

    return Response({'success': True, 'message': 'Request declined'})


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def check_dm_request(request, chat_id):
    """Check if a chat is a DM request for the current user"""
    user = request.user
    chat = get_object_or_404(
        Chat, id=chat_id, participants=user, chat_type='private')

    # Check if user has accepted this chat
    is_accepted = ChatAcceptance.objects.filter(chat=chat, user=user).exists()

    return Response({
        'success': True,
        'is_request': not is_accepted,
        'chat_id': chat_id
    })


def auto_accept_chat_for_sender(chat, sender):
    """
    Auto-create acceptance for the sender when they send a message.
    Called when a message is sent to ensure sender has accepted the chat.
    """
    if chat.chat_type == 'private':
        ChatAcceptance.objects.get_or_create(chat=chat, user=sender)


@api_view(['GET'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def api_explore_feed(request):
    """API endpoint to get paginated explore content (scribes & omzos)"""
    print(
        f"========== API_EXPLORE_FEED CALLED!  Method: {request.method}, Path: {request.path}, User: {request.user} ==========")
    try:
        page = int(request.GET.get('page', 1))
        per_page = int(request.GET.get('per_page', 10))

        # Use personalized explore for authenticated user
        content_items = _get_explore_content_batch(
            page=page, per_page=per_page, user=request.user)

        # Fallback: if personalized explore is empty (or ended), show global content from the same page offset
        if not content_items:
            content_items = _get_explore_content_batch(
                page=page, per_page=per_page, user=None)

            # Re-check likes/dislikes for authenticated user since we fetched generic content
            if request.user.is_authenticated and content_items:
                for item in content_items:
                    obj = item['object']
                    if item['type'] == 'scribe':
                        item['is_liked'] = Like.objects.filter(
                            scribe=obj, user=request.user).exists()
                        item['is_disliked'] = Dislike.objects.filter(
                            scribe=obj, user=request.user).exists()
                        item['is_saved'] = SavedScribeItem.objects.filter(
                            scribe=obj, user=request.user).exists()
                        item['is_reposted'] = Scribe.objects.filter(
                            user=request.user, original_scribe=obj).exists()
                    elif item['type'] == 'omzo':
                        item['is_liked'] = OmzoLike.objects.filter(
                            omzo=obj, user=request.user).exists()
                        item['is_disliked'] = OmzoDislike.objects.filter(
                            omzo=obj, user=request.user).exists()
                        item['is_saved'] = SavedOmzoItem.objects.filter(
                            omzo=obj, user=request.user).exists()
                        item['is_reposted'] = Scribe.objects.filter(
                            user=request.user, original_omzo=obj).exists()

        serialized_results = []
        for item in content_items:
            obj = item['object']
            result_type = item['type']

            result = {
                'id': str(obj.id),
                'type': result_type,  # scribe or omzo
                'isLiked': item['is_liked'],
                'isDisliked': item['is_disliked'],
                'isSaved': item.get('is_saved', False),
                'likes': item['like_count'],
                'comments': item['comment_count'],
                'user': {
                    'id': str(obj.user.id),
                    'username': obj.user.username,
                    'displayName': obj.user.full_name or obj.user.username,
                    'avatar': request.build_absolute_uri(obj.user.profile_picture_url) if obj.user.profile_picture_url and not obj.user.profile_picture_url.startswith('http') else obj.user.profile_picture_url,
                    'isVerified': obj.user.is_verified,
                }
            }

            if result_type == 'scribe':
                result['createdAt'] = obj.timestamp.isoformat(
                ) if obj.timestamp else None
                result['content'] = obj.content
                result['mediaUrl'] = request.build_absolute_uri(
                    obj.image_url) if obj.image_url and not obj.image_url.startswith('http') else obj.image_url
                # Reuse simplified type logic
                ctype = getattr(obj, 'content_type', 'text')

                # Let's put Scribe-specific type inside
                result['scribeType'] = 'image' if (obj.image and (
                    not ctype or ctype == 'text')) else (ctype or 'text')

                # Add counters
                result['dislikes'] = obj.scribe_dislikes.count()
                result['reposts'] = obj.reposts.count()

                # Check if current user has reposted this scribe
                if request.user.is_authenticated:
                    result['isReposted'] = Scribe.objects.filter(
                        user=request.user,
                        original_scribe=obj,
                        quote_source__isnull=True
                    ).exists()
                else:
                    result['isReposted'] = False

                # Code content
                result['code_html'] = getattr(obj, 'code_html', '')
                result['code_css'] = getattr(obj, 'code_css', '')
                result['code_js'] = getattr(obj, 'code_js', '')

            elif result_type == 'omzo':
                result['createdAt'] = obj.created_at.isoformat(
                ) if obj.created_at else None
                # Convert relative video URL to absolute URL
                video_url = obj.video_file.url if obj.video_file else None
                result['videoUrl'] = request.build_absolute_uri(
                    video_url) if video_url and not video_url.startswith('http') else video_url
                result['videoUrl'] = obj.video_file.url if obj.video_file else None
                result['caption'] = obj.caption
                result['dislikes'] = obj.dislikes.count()
                result['shares'] = 0
                # Check if current user has reposted this omzo
                result['isReposted'] = item.get('is_reposted', False)

            serialized_results.append(result)

        return Response({
            'success': True,
            'results': serialized_results,
            'page': page,
            'has_more': len(content_items) == per_page
        })

    except Exception as e:
        logger.error(f"Error in api_explore_feed: {str(e)}")
        return Response({'success': False, 'error': str(e)}, status=500)
