"""
Read Receipt Management Views
Handles marking messages as read and tracking read receipts
"""
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_GET
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404
from django.utils import timezone
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from chat.models import Chat, Message, MessageRead
import json
import logging
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import TokenAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes

logger = logging.getLogger(__name__)


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def mark_messages_read(request):
    """
    Mark multiple messages as read for the current user.
    Can mark all messages in a chat or specific message IDs.

    POST data:
    - chat_id: ID of the chat
    - message_ids: (optional) Array of specific message IDs to mark as read

    Returns:
    - marked_count: Number of messages marked as read
    - unread_count: Remaining unread count for the chat
    """
    try:
        data = request.data
        chat_id = data.get('chat_id')
        message_ids = data.get('message_ids')  # Optional: specific messages

        if not chat_id:
            return Response({'success': False, 'error': 'chat_id required'}, status=400)

        # Verify user is participant in chat
        chat = get_object_or_404(Chat, id=chat_id, participants=request.user)

        # Get unread messages (not sent by user, not already read)
        unread_messages = Message.objects.filter(
            chat=chat
        ).exclude(
            sender=request.user
        ).exclude(
            read_receipts__user=request.user
        )

        # Filter by specific message IDs if provided
        if message_ids:
            unread_messages = unread_messages.filter(id__in=message_ids)

        # Create read receipts in bulk
        read_receipts = []
        marked_messages = []

        for msg in unread_messages:
            read_receipts.append(MessageRead(
                message=msg,
                user=request.user,
                read_at=timezone.now()
            ))
            marked_messages.append(msg.id)

        if read_receipts:
            MessageRead.objects.bulk_create(
                read_receipts, ignore_conflicts=True)

            # Update is_read flag on messages
            unread_messages.update(is_read=True)

            # Broadcast read receipts via WebSocket
            channel_layer = get_channel_layer()
            for message_id in marked_messages:
                async_to_sync(channel_layer.group_send)(
                    f'chat_{chat_id}',
                    {
                        'type': 'message_read',
                        'message_id': message_id,
                        'read_by': request.user.id,
                        'read_at': timezone.now().isoformat()
                    }
                )

            logger.info(
                f"User {request.user.id} marked {len(marked_messages)} messages as read in chat {chat_id}")

        # Calculate remaining unread count
        remaining_unread = Message.objects.filter(
            chat=chat
        ).exclude(
            sender=request.user
        ).exclude(
            read_receipts__user=request.user
        ).count()

        return Response({
            'success': True,
            'marked_count': len(marked_messages),
            'unread_count': remaining_unread,
            'marked_message_ids': marked_messages
        })

    except json.JSONDecodeError:
        return Response({'success': False, 'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(
            f"Error marking messages as read: {str(e)}", exc_info=True)
        return Response({'success': False, 'error': str(e)}, status=500)


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def get_unread_counts(request):
    """
    Get unread message counts for all chats the user participates in.

    Returns:
    - counts: Dictionary mapping chat_id to unread count
    - total_unread: Total unread messages across all chats
    """
    try:
        user_chats = Chat.objects.filter(participants=request.user)

        counts = {}
        total_unread = 0

        for chat in user_chats:
            unread_count = Message.objects.filter(
                chat=chat
            ).exclude(
                sender=request.user
            ).exclude(
                read_receipts__user=request.user
            ).count()

            counts[str(chat.id)] = unread_count
            total_unread += unread_count

        return Response({
            'success': True,
            'counts': counts,
            'total_unread': total_unread
        })

    except Exception as e:
        logger.error(f"Error getting unread counts: {str(e)}", exc_info=True)
        return Response({'success': False, 'error': str(e)}, status=500)


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def mark_chat_read(request, chat_id):
    """
    Mark all messages in a chat as read for the current user.
    Convenience endpoint that marks all unread messages.

    Returns:
    - marked_count: Number of messages marked as read
    """
    try:
        # Verify user is participant in chat
        chat = get_object_or_404(Chat, id=chat_id, participants=request.user)

        # Get all unread messages
        unread_messages = Message.objects.filter(
            chat=chat
        ).exclude(
            sender=request.user
        ).exclude(
            read_receipts__user=request.user
        )

        # Create read receipts in bulk
        read_receipts = []
        marked_messages = []

        for msg in unread_messages:
            read_receipts.append(MessageRead(
                message=msg,
                user=request.user,
                read_at=timezone.now()
            ))
            marked_messages.append(msg.id)

        if read_receipts:
            MessageRead.objects.bulk_create(
                read_receipts, ignore_conflicts=True)
            unread_messages.update(is_read=True)

            # Broadcast read receipts via WebSocket
            channel_layer = get_channel_layer()
            for message_id in marked_messages:
                async_to_sync(channel_layer.group_send)(
                    f'chat_{chat_id}',
                    {
                        'type': 'message_read',
                        'message_id': message_id,
                        'read_by': request.user.id,
                        'read_at': timezone.now().isoformat()
                    }
                )

            logger.info(
                f"User {request.user.id} marked entire chat {chat_id} as read ({len(marked_messages)} messages)")

        return Response({
            'success': True,
            'marked_count': len(marked_messages),
            'unread_count': 0
        })

    except Exception as e:
        logger.error(f"Error marking chat as read: {str(e)}", exc_info=True)
        return Response({'success': False, 'error': str(e)}, status=500)
