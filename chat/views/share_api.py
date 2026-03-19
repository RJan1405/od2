from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.db.models import Q, Case, When, Value, IntegerField, Count
from django.utils import timezone
import json
import logging

from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import TokenAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from chat.models import (
    CustomUser, Chat, Message, Scribe, Omzo, Story, ChatRequest, ChatAcceptance
)

logger = logging.getLogger(__name__)

@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def search_users_for_share(request):
    """
    Search users for sharing content.
    Prioritizes:
    1. Users with existing private chats (most recent first)
    2. Users the current user follows
    3. Other users matching the query
    
    Excludes blocked users.
    """
    query = request.GET.get('q', '').strip()
    
    # Base query for users
    users = CustomUser.objects.filter(is_active=True).exclude(id=request.user.id)
    
    # Exclude blocked users (both ways)
    # Users blocked by me
    blocked_by_me = request.user.blocking.values_list('blocked_id', flat=True)
    # Users blocking me
    blocking_me = request.user.blocked_by.values_list('blocker_id', flat=True)
    
    users = users.exclude(id__in=blocked_by_me).exclude(id__in=blocking_me)
    
    if query:
        users = users.filter(
            Q(username__icontains=query) | 
            Q(name__icontains=query) | 
            Q(lastname__icontains=query)
        )
    
    # Get IDs of users with existing private chats
    existing_chat_partner_ids = Chat.objects.filter(
        chat_type='private',
        participants=request.user
    ).values_list('participants__id', flat=True)
    
    # Get IDs of users I follow
    following_ids = request.user.following.values_list('following_id', flat=True)
    
    # Annotate with priority
    # Priority: 3 = Existing Chat, 2 = Following, 1 = Others
    users = users.annotate(
        priority=Case(
            When(id__in=existing_chat_partner_ids, then=Value(3)),
            When(id__in=following_ids, then=Value(2)),
            default=Value(1),
            output_field=IntegerField(),
        )
    ).order_by('-priority', 'username')  # Secondary sort by username
    
    # Pagination
    page = int(request.GET.get('page', 1))
    per_page = 20
    start = (page - 1) * per_page
    end = start + per_page
    
    results = users[start:end]
    
    data = []
    for user in results:
        # Determine specific relationship status for UI hints
        status_label = ""
        if user.id in existing_chat_partner_ids:
            # Check if it's strictly the *other* participant, though logic above helps
            # Filter ensures we are looking at participants of my chats
            status_label = "Recent Chat"
        elif user.id in following_ids:
            status_label = "Following"
            
        data.append({
            'id': user.id,
            'username': user.username,
            'full_name': user.full_name,
            'avatar_url': user.profile_picture_url,
            'status_label': status_label,
            'priority': user.priority,
            # Add some privacy info if needed
            'is_private': user.is_private
        })
        
    return Response({
        'success': True,
        'results': data,
        'has_more': len(data) == per_page
    })

@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def share_content_to_user(request):
    """
    Share content to a list of users.
    
    Unified approach:
    - Always find or create a chat
    - Send message directly
    - For NEW chats: sender gets ChatAcceptance, recipient sees in-chat banner
    """
    try:
        data = json.loads(request.body)
        recipient_ids = data.get('recipient_ids', [])
        content_type = data.get('content_type')
        content_id = data.get('content_id')
        message_text = data.get('message', '').strip()
        
        if not recipient_ids or not content_type or not content_id:
            return Response({'success': False, 'error': 'Missing required fields'})
            
        # Get content object
        content_obj = None
        if content_type == 'scribe':
            content_obj = get_object_or_404(Scribe, id=content_id)
        elif content_type == 'omzo':
            content_obj = get_object_or_404(Omzo, id=content_id)
        elif content_type == 'story':
            content_obj = get_object_or_404(Story, id=content_id)
        else:
             return Response({'success': False, 'error': 'Invalid content type'})

        results = {
            'sent': 0,
            'failed': 0,
            'details': []
        }

        for user_id in recipient_ids:
            try:
                recipient = CustomUser.objects.get(id=user_id)
                
                # Check blocking
                if request.user.blocking.filter(id=user_id).exists() or \
                   request.user.blocked_by.filter(id=user_id).exists():
                    results['failed'] += 1
                    results['details'].append({'id': user_id, 'status': 'blocked'})
                    continue
                
                # Find or create private chat
                chat = Chat.objects.filter(
                    chat_type='private',
                    participants=request.user
                ).filter(participants=recipient).first()
                
                is_new_chat = False
                if not chat:
                    # Create new chat
                    chat = Chat.objects.create(chat_type='private')
                    chat.participants.add(request.user, recipient)
                    is_new_chat = True
                    
                    # Sender auto-accepts the chat they initiated
                    ChatAcceptance.objects.get_or_create(
                        chat=chat,
                        user=request.user
                    )
                    # Recipient does NOT get ChatAcceptance - they will see the in-chat banner
                
                # Build shared content data for message
                shared_data = {
                    'type': content_type,
                    f'{content_type}_id': content_id
                }
                
                # Create the message
                Message.objects.create(
                    chat=chat,
                    sender=request.user,
                    content=message_text or '',
                    message_type='text',
                    reactions={'shared_content': shared_data}
                )
                
                # Update chat timestamp
                chat.updated_at = timezone.now()
                chat.save(update_fields=['updated_at'])
                
                results['sent'] += 1
                status = 'sent_new_chat' if is_new_chat else 'sent'
                results['details'].append({'id': user_id, 'status': status, 'chat_id': chat.id})

            except CustomUser.DoesNotExist:
                results['failed'] += 1
                results['details'].append({'id': user_id, 'status': 'user_not_found'})
            except Exception as e:
                logger.error(f"Error sharing to user {user_id}: {str(e)}")
                results['failed'] += 1
                results['details'].append({'id': user_id, 'status': 'error'})
                
        return Response({'success': True, 'results': results})
        
    except Exception as e:
        logger.error(f"Share API Error: {str(e)}")
        return Response({'success': False, 'error': str(e)})

@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def get_chat_requests(request):
    """Get pending chat requests received by current user"""
    requests = ChatRequest.objects.filter(
        recipient=request.user,
        status='pending'
    ).select_related('sender', 'shared_scribe', 'shared_omzo', 'shared_story')
    
    data = []
    for req in requests:
        data.append({
            'id': req.id,
            'sender': {
                'username': req.sender.username,
                'full_name': req.sender.full_name,
                'avatar_url': req.sender.profile_picture_url,
            },
            'message': req.message,
            'content_type': req.content_type,
            'preview': req.shared_content_preview,
            'timestamp': req.created_at.strftime('%Y-%m-%d %H:%M'),
            'time_ago': req.created_at  # Can use humanize on client or server
        })
        
    return Response({'success': True, 'requests': data})

@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def get_chat_requests_count(request):
    """Get count of pending requests for badge"""
    count = ChatRequest.objects.filter(
        recipient=request.user,
        status='pending'
    ).count()
    return Response({'success': True, 'count': count})

@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def accept_chat_request(request, request_id):
    """Accept a chat request"""
    chat_request = get_object_or_404(ChatRequest, id=request_id, recipient=request.user)
    
    try:
        chat = chat_request.accept()
        return Response({
            'success': True, 
            'chat_id': chat.id,
            'message': 'Request accepted'
        })
    except Exception as e:
        logger.error(f"Error accepting request: {str(e)}")
        return Response({'success': False, 'error': str(e)})

@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def decline_chat_request(request, request_id):
    """Decline a chat request"""
    chat_request = get_object_or_404(ChatRequest, id=request_id, recipient=request.user)
    
    try:
        chat_request.decline()
        return Response({'success': True, 'message': 'Request declined'})
    except Exception as e:
         logger.error(f"Error declining request: {str(e)}")
         return Response({'success': False, 'error': str(e)})
