from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_GET
from chat.models import Chat, Message, MessageRead, CustomUser
from django.db.models import Prefetch
import logging
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import TokenAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from chat.encryption import decrypt_text

logger = logging.getLogger(__name__)

@require_GET
@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def get_chat_details_api(request, chat_id):
    """
    API to get full details of a chat including messages and metadata.
    Used for AJAX navigation to prevent full page refresh.
    """
    user = request.user
    
    # Get chat and verify participation
    chat = get_object_or_404(
        Chat.objects.prefetch_related(
            'participants',
            Prefetch('messages', queryset=Message.objects.order_by('timestamp'))
        ),
        id=chat_id, 
        participants=user
    )

    logger.info(f"GET_CHAT_DETAILS: User {user.username} (ID {user.id}) accessing chat {chat_id}")

    # Mark unread messages as read
    unread_messages = chat.messages.exclude(sender=user).exclude(read_receipts__user=user)
    if unread_messages.exists():
        # Create read receipts in bulk
        read_receipts = []
        for msg in unread_messages:
            read_receipts.append(MessageRead(message=msg, user=user))
        MessageRead.objects.bulk_create(read_receipts, ignore_conflicts=True)
        # Sync the is_read flag on all messages
        unread_messages.update(is_read=True)

    # Determine chat metadata (name, avatar, etc.)
    chat_name = chat.name
    chat_avatar = None
    chat_is_online = False
    chat_last_seen = None
    chat_initials = "G"
    
    other_user = None
    if chat.chat_type == 'private':
        other_user = chat.participants.exclude(id=user.id).first()
        if other_user:
            chat_name = other_user.full_name
            chat_avatar = other_user.profile_picture_url
            chat_is_online = other_user.is_online
            chat_last_seen = other_user.last_seen.isoformat() if other_user.last_seen else None
            chat_initials = other_user.initials
    else:
        chat_initials = chat.name[:1].upper() if chat.name else "G"
        if chat.group_avatar:
            chat_avatar = chat.group_avatar.url

    # Serialize messages
    messages_data = []
    # Use the prefetched messages to avoid N+1, but we need to re-fetch to include related data if not prefetched enough
    # Actually, let's just use the relationship. 
    # To be safe and performant, we might want to select_related sender. 
    # But for now, let's iterate.
    
    # Re-query with select_related for performance
    messages_qs = chat.messages.select_related('sender', 'reply_to', 'reply_to__sender').prefetch_related('read_receipts').exclude(deletions__user=user).order_by('timestamp')
    
    for msg in messages_qs:
        sender_name = 'System'
        sender_username = 'system'
        sender_avatar = None
        sender_initials = 'S'
        is_own = False
        
        if msg.sender:
            sender_name = msg.sender.full_name
            sender_username = msg.sender.username
            sender_avatar = msg.sender.profile_picture_url
            sender_initials = msg.sender.initials
            is_own = msg.sender.id == user.id

        # Determine read status (if own message, check if others read it)
        is_read = False
        if is_own:
             is_read = msg.read_receipts.exclude(user=user).exists()
        
        # Reply info
        reply_to_data = None
        if msg.reply_to:
            reply_sender_name = msg.reply_to.sender.full_name if msg.reply_to.sender else 'System'
            reply_to_data = {
                'id': msg.reply_to.id,
                'content': decrypt_text(msg.reply_to.content),
                'sender_name': reply_sender_name
            }

        messages_data.append({
            'id': msg.id,
            'content': decrypt_text(msg.content),
            'sender': {
                'id': msg.sender_id,
                'username': sender_username,
                'name': sender_name,
                'avatar': sender_avatar,
                'initials': sender_initials,
            },
            'timestamp': msg.timestamp.strftime('%H:%M'),
            'timestamp_iso': msg.timestamp.isoformat(),
            'is_own': is_own,
            'is_read': is_read,
            'message_type': msg.message_type,
            'has_media': msg.has_media,
            'media_url': msg.media_url,
            'media_type': msg.media_type,
            'media_filename': msg.media_filename,
            'one_time': msg.one_time,
            'consumed': msg.consumed_at is not None,
            'reply_to': reply_to_data,
            'is_pinned': msg.is_pinned
        })

    return Response({
        'success': True,
        'chat': {
            'id': chat.id,
            'name': chat_name,
            'avatar': chat_avatar,
            'initials': chat_initials,
            'type': chat.chat_type,
            'is_online': chat_is_online,
            'last_seen': chat_last_seen,
            'is_group': chat.chat_type == 'group',
            'admin_id': chat.admin_id if chat.chat_type == 'group' else None,
            'description': chat.description if chat.chat_type == 'group' else None,
            'participant_count': chat.participants.count(),
            'participants': [{
                'id': p.id,
                'username': p.username,
                'full_name': p.full_name,
                'profile_picture': p.profile_picture_url,
                'is_online': p.is_online
            } for p in chat.participants.all()] if chat.chat_type == 'group' else [],
            'other_user': {
                'id': other_user.id,
                'username': other_user.username,
                'full_name': other_user.full_name,
                'first_name': other_user.first_name,
                'profile_picture': other_user.profile_picture_url,
                'is_online': other_user.is_online,
                'is_verified': getattr(other_user, 'is_verified', False)
            } if other_user else None
        },
        'messages': messages_data,
        'current_user_id': user.id
    })
