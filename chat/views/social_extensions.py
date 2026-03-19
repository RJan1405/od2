from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
import logging
from chat.models import Omzo, OmzoLike, OmzoDislike, SavedOmzoItem
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import TokenAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes

logger = logging.getLogger(__name__)

@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def get_omzo_detail(request, omzo_id):
    """Get a single Omzo by ID (API)"""
    try:
        from django.utils.timesince import timesince
        omzo_item = get_object_or_404(Omzo, id=omzo_id)

        # Check interaction status
        is_liked = OmzoLike.objects.filter(user=request.user, omzo=omzo_item).exists()
        is_disliked = OmzoDislike.objects.filter(user=request.user, omzo=omzo_item).exists()
        is_saved = SavedOmzoItem.objects.filter(user=request.user, omzo=omzo_item).exists()

        omzo_data = {
            'id': omzo_item.id,
            'caption': omzo_item.caption,
            'videoUrl': omzo_item.video_file.url,
            'user': {
                'id': omzo_item.user.id,
                'username': omzo_item.user.username,
                'displayName': omzo_item.user.full_name or omzo_item.user.username,
                'avatar': omzo_item.user.profile_picture.url if (omzo_item.user.profile_picture and omzo_item.user.profile_picture.name) else '',
                'isOnline': omzo_item.user.is_online,
                'isVerified': omzo_item.user.is_verified,
            },
            'likes': omzo_item.like_count,
            'dislikes': omzo_item.dislikes.count() if hasattr(omzo_item, 'dislikes') else 0,
            'views': omzo_item.views_count,
            'comments': omzo_item.comment_count,
            'shares': 0, # Sharing not tracked in DB yet
            'isLiked': is_liked,
            'isDisliked': is_disliked,
            'isSaved': is_saved,
            'audioName': 'Original Sound', # Field doesn't exist yet
            'createdAt': omzo_item.created_at.isoformat(),
            'feedType': 'omzo'
        }

        return Response({
            'success': True,
            'omzo': omzo_data
        })

    except Exception as e:
        import traceback
        logger.error(f"Error in get_omzo_detail: {str(e)}")
        logger.error(traceback.format_exc())
        return Response({'success': False, 'error': f'Failed to get Omzo: {str(e)}'})
