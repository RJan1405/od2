from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import json
import logging

from chat.models import Message, StarredMessage, MessageDeletion, MessageRead
from chat.encryption import encrypt_text, decrypt_text
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import TokenAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes

logger = logging.getLogger(__name__)


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def get_message_context_menu(request, message_id):
    """Get context menu options for a specific message"""
    try:
        message = get_object_or_404(Message, id=message_id)
        chat = message.chat
        
        # Verify user is a participant
        if not chat.participants.filter(id=request.user.id).exists():
            return Response({'success': False, 'error': 'Unauthorized'}, status=403)
        
        is_own = message.sender == request.user
        is_starred = StarredMessage.objects.filter(user=request.user, message=message).exists()
        
        options = []
        
        # Reply option (always available)
        options.append({
            'id': 'reply',
            'label': 'Reply',
            'icon': 'reply',
            'action': 'reply'
        })
        
        # Copy option (for text messages)
        if message.message_type == 'text' and message.content:
            options.append({
                'id': 'copy',
                'label': 'Copy Text',
                'icon': 'copy',
                'action': 'copy'
            })
        
        # Forward option
        options.append({
            'id': 'forward',
            'label': 'Forward',
            'icon': 'forward',
            'action': 'forward'
        })
        
        # Star/Unstar option
        options.append({
            'id': 'star',
            'label': 'Unstar' if is_starred else 'Star',
            'icon': 'star',
            'action': 'unstar' if is_starred else 'star'
        })
        
        # Download option (for media messages)
        if message.message_type == 'media' and message.media_url:
            options.append({
                'id': 'download',
                'label': 'Download',
                'icon': 'download',
                'action': 'download',
                'divider': True
            })
        
        # Select option (for bulk actions)
        options.append({
            'id': 'select',
            'label': 'Select',
            'icon': 'select',
            'action': 'select',
            'divider': not is_own
        })
        
        # Own message options
        if is_own:
            # Edit option (only for text messages, within 15 minutes)
            if message.message_type == 'text':
                time_since_sent = timezone.now() - message.timestamp
                if time_since_sent.total_seconds() < 900:  # 15 minutes
                    options.append({
                        'id': 'edit',
                        'label': 'Edit',
                        'icon': 'edit',
                        'action': 'edit',
                        'divider': True
                    })
            
            # Delete option
            options.append({
                'id': 'delete',
                'label': 'Delete for Everyone',
                'icon': 'delete',
                'action': 'delete_everyone',
                'destructive': True
            })
            options.append({
                'id': 'delete_me',
                'label': 'Delete for Me',
                'icon': 'delete',
                'action': 'delete_me',
                'destructive': True
            })
        else:
            # Message info option
            options.append({
                'id': 'info',
                'label': 'Message Info',
                'icon': 'info',
                'action': 'info'
            })
            
            # Delete for me option
            options.append({
                'id': 'delete_me',
                'label': 'Delete for Me',
                'icon': 'delete',
                'action': 'delete_me',
                'destructive': True,
                'divider': True
            })
        
        return Response({
            'success': True,
            'options': options
        })
        
    except Exception as e:
        logger.error(f"Error in get_message_context_menu: {str(e)}")
        return Response({'success': False, 'error': str(e)}, status=500)


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def message_context_action(request):
    """Handle context menu actions on messages"""
    try:
        data = request.data
        message_id = data.get('message_id')
        action = data.get('action')
        
        if not message_id or not action:
            return Response({'success': False, 'error': 'Missing required fields'})
        
        message = get_object_or_404(Message, id=message_id)
        chat = message.chat
        
        # Verify user is a participant
        if not chat.participants.filter(id=request.user.id).exists():
            return Response({'success': False, 'error': 'Unauthorized'}, status=403)
        
        is_own = message.sender == request.user
        
        # Handle different actions
        if action == 'star':
            StarredMessage.objects.get_or_create(user=request.user, message=message)
            return Response({'success': True, 'message': 'Message starred'})
        
        elif action == 'unstar':
            StarredMessage.objects.filter(user=request.user, message=message).delete()
            return Response({'success': True, 'message': 'Message unstarred'})
        
        elif action == 'copy':
            # Frontend handles the actual copying
            return Response({'success': True, 'content': decrypt_text(message.content)})
        
        elif action == 'delete_me':
            # Delete for current user only
            MessageDeletion.objects.get_or_create(message=message, user=request.user)
            return Response({'success': True, 'message': 'Message deleted for you'})
        
        elif action == 'delete_everyone':
            # Only owner can delete for everyone
            if not is_own:
                return Response({'success': False, 'error': 'Unauthorized'}, status=403)
            
            # Mark message as deleted for everyone
            message.content = encrypt_text('This message was deleted')
            message.media_url = None
            message.save()
            
            # Broadcast deletion to all participants
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f'chat_{chat.id}',
                {
                    'type': 'message.deleted',
                    'message_id': message.id,
                    'deleted_by': request.user.username
                }
            )
            
            return Response({'success': True, 'message': 'Message deleted for everyone'})
        
        elif action == 'edit':
            # Only owner can edit, and only text messages within 15 minutes
            if not is_own:
                return Response({'success': False, 'error': 'Unauthorized'}, status=403)
            
            if message.message_type != 'text':
                return Response({'success': False, 'error': 'Can only edit text messages'})
            
            time_since_sent = timezone.now() - message.timestamp
            if time_since_sent.total_seconds() >= 900:  # 15 minutes
                return Response({'success': False, 'error': 'Edit time expired'})
            
            new_content = data.get('new_content', '').strip()
            if not new_content:
                return Response({'success': False, 'error': 'Content cannot be empty'})
            
            message.content = encrypt_text(new_content)
            message.is_edited = True
            message.edited_at = timezone.now()
            message.save()
            
            # Broadcast edit to all participants
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f'chat_{chat.id}',
                {
                    'type': 'message.edited',
                    'message_id': message.id,
                    'new_content': new_content,
                    'edited_at': message.edited_at.isoformat()
                }
            )
            
            return Response({
                'success': True,
                'message': 'Message edited',
                'new_content': new_content
            })
        
        elif action == 'info':
            # Get message info
            read_by = MessageRead.objects.filter(message=message).select_related('user')
            read_info = [{
                'username': read.user.username,
                'full_name': read.user.full_name,
                'read_at': read.read_at.isoformat()
            } for read in read_by]
            
            return Response({
                'success': True,
                'info': {
                    'sender': message.sender.full_name if message.sender else 'System',
                    'sent_at': message.timestamp.isoformat(),
                    'is_edited': message.is_edited,
                    'edited_at': message.edited_at.isoformat() if message.edited_at else None,
                    'read_by': read_info
                }
            })
        
        else:
            return Response({'success': False, 'error': 'Unknown action'})
        
    except Exception as e:
        logger.error(f"Error in message_context_action: {str(e)}")
        return Response({'success': False, 'error': str(e)}, status=500)
