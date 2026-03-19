from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.contrib.auth.decorators import login_required
from chat.models import Chat
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import TokenAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def unread_counts(request):
    user = request.user
    chats = Chat.objects.filter(participants=user)
    data = {}
    for chat in chats:
        unread = chat.messages.exclude(
            sender=user
        ).exclude(
            read_receipts__user=user
        ).count()
        data[chat.id] = unread
    return Response({'counts': data})


@require_GET
def chat_partial(request, chat_id):
    # Dummy implementation for AJAX chat partial
    # Replace with your actual logic
    return Response({'success': True, 'chat_id': chat_id, 'html': '<div>Chat partial for chat_id {}</div>'.format(chat_id)})
