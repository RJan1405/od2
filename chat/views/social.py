from django.shortcuts import render, redirect, get_object_or_404
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.utils import timezone
from django.db.models import Count, Q, Max
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.exceptions import ValidationError
import json
import hashlib
import logging
import re
from django.db import models as db_models
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

from chat.models import (
    CustomUser, Chat, Scribe, Comment, CommentLike, Like, Dislike, Follow, Block, FollowRequest,
    Hashtag, ScribeHashtag, Mention, StoryReply, StoryLike, Story,
    SavedPost, PostReport, Omzo, OmzoLike, OmzoDislike, OmzoComment, OmzoReport,
    ProfileView, PinnedChat, DismissedSuggestion, SavedScribeItem, SavedOmzoItem
)
from chat.forms import ScribeForm, ProfileUpdateForm
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import TokenAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes

logger = logging.getLogger(__name__)


def handle_repost_action(user, repost_type, repost_id, content=''):
    """
    Shared helper to implement Instagram-like repost behaviour:
    - Reposting creates a new Scribe that points to the original content
      (flattening any existing repost chain).
    - Reposting again the same original by the same user UNDOES the repost
      by deleting the existing repost scribe (toggle behaviour).
    - Supports reposting Scribes, Omzos, Stories, and quote posts.
    """
    repost_type = (repost_type or '').lower()
    if not repost_type or not repost_id:
        raise ValueError('repost_type and repost_id are required')

    # Convert repost_id to int if it's a string
    try:
        repost_id = int(repost_id)
    except (ValueError, TypeError):
        raise ValueError(f'Invalid repost_id: {repost_id}')

    # Resolve the original object based on type
    original = None
    try:
        if repost_type in ['scribe', 'post']:
            original = Scribe.objects.get(id=repost_id)
        elif repost_type == 'omzo':
            original = Omzo.objects.get(id=repost_id)
        elif repost_type == 'story':
            original = Story.objects.get(id=repost_id)
        elif repost_type == 'quote':
            original = Scribe.objects.get(id=repost_id)
        else:
            raise ValueError('Invalid repost type')
    except Scribe.DoesNotExist:
        raise ValueError(f'Scribe with id {repost_id} not found')
    except Omzo.DoesNotExist:
        raise ValueError(f'Omzo with id {repost_id} not found')
    except Story.DoesNotExist:
        raise ValueError(f'Story with id {repost_id} not found')

    # Quote reposts behave like Instagram's "quote tweet":
    # always create a new post with reference to the original, no toggle.
    if repost_type == 'quote':
        scribe = Scribe.objects.create(
            user=user,
            quote_source=original,
            content=content,
        )
        process_scribe_hashtags_mentions(scribe)
        return {
            'is_reposted': True,
            'action': 'quote_created',
            'scribe_id': scribe.id,
        }

    # Prevent reposting own content (UI should also normally hide this)
    owner = getattr(original, 'user', None)
    if owner and owner == user:
        raise ValueError("You can't repost your own content")

    # Compute the root/original target to avoid chaining repost-of-repost
    root_scribe = None
    root_omzo = None
    root_story = None

    if isinstance(original, Scribe):
        # If the scribe is itself a repost of something else, follow that
        root_scribe = original.original_scribe
        root_omzo = original.original_omzo
        root_story = original.original_story

        if not (root_scribe or root_omzo or root_story):
            # Plain scribe – repost this one
            root_scribe = original
    elif isinstance(original, Omzo):
        root_omzo = original
    elif isinstance(original, Story):
        root_story = original

    # Find any existing repost by this user for the same underlying content
    existing_qs = Scribe.objects.filter(
        user=user,
        original_scribe=root_scribe,
        original_omzo=root_omzo,
        original_story=root_story,
        quote_source__isnull=True,
    )

    if existing_qs.exists():
        # Toggle OFF: undo repost by deleting existing repost scribe(s)
        deleted_count, _ = existing_qs.delete()
        logger.info(
            f"User {user.id} removed {deleted_count} repost(s) for type={repost_type}, id={repost_id}"
        )
        return {
            'is_reposted': False,
            'action': 'removed',
        }

    # Toggle ON: create new repost scribe that points to the root content
    scribe = Scribe.objects.create(
        user=user,
        original_scribe=root_scribe,
        original_omzo=root_omzo,
        original_story=root_story,
        content=content,
    )
    process_scribe_hashtags_mentions(scribe)

    logger.info(
        f"User {user.id} created repost scribe {scribe.id} for type={repost_type}, id={repost_id}"
    )

    return {
        'is_reposted': True,
        'action': 'created',
        'scribe_id': scribe.id,
    }


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def api_repost(request):
    """
    Lightweight JSON API for repost/undo repost from the (React) frontend.
    Accepts JSON body: {"type": "scribe|omzo|story|quote", "id": <int>, "content": "<optional caption>"}.
    """
    try:
        data = json.loads(request.body or '{}')
        repost_type = data.get('type')
        repost_id = data.get('id')
        content = (data.get('content') or '').strip()

        logger.info(
            f"api_repost called: type={repost_type}, id={repost_id}, user={request.user.id}")

        if not repost_type or not repost_id:
            logger.warning(
                f"Missing required fields: type={repost_type}, id={repost_id}")
            return Response(
                {'success': False, 'error': 'type and id are required'},
                status=400,
            )

        result = handle_repost_action(
            user=request.user,
            repost_type=repost_type,
            repost_id=repost_id,
            content=content,
        )

        response = {'success': True}
        response.update(result)
        # Mirror Instagram-style UX: backend tells if it's now reposted or undone
        if 'message' not in response:
            if response.get('is_reposted'):
                response['message'] = 'Reposted to your profile'
            else:
                response['message'] = 'Repost removed from your profile'

        logger.info(f"api_repost success: {response}")
        return Response(response)
    except ValueError as e:
        logger.warning(f"ValueError in api_repost: {e}")
        return Response({'success': False, 'error': str(e)}, status=400)
    except Exception as e:
        logger.error(f"Error in api_repost: {e}", exc_info=True)
        return Response(
            {'success': False, 'error': 'Failed to process repost'},
            status=500,
        )


# Global cache for preventing duplicate scribes
SCRIBE_CACHE_PREFIX = "prevent_duplicate_scribe_"
SCRIBE_COOLDOWN = 5  # 5 seconds between identical scribes


def generate_scribe_hash(user_id, content, has_image):
    """Generate unique hash for duplicate detection"""
    content_hash = hashlib.md5(
        f"{user_id}_{content.strip()}_{has_image}".encode()).hexdigest()
    return content_hash


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def profile_view(request, username=None):
    if username:
        profile_user = get_object_or_404(CustomUser, username=username)
        is_own_profile = False
    else:
        profile_user = request.user
        is_own_profile = True

    # Check if profile is accessible
    can_view_profile = True
    is_blocked = False
    follow_request_status = None

    if not is_own_profile and request.user.is_authenticated:
        # Check if blocked
        is_blocked_by_me = Block.objects.filter(
            blocker=request.user,
            blocked=profile_user
        ).exists()
        is_blocked_by_them = Block.objects.filter(
            blocker=profile_user,
            blocked=request.user
        ).exists()

        if is_blocked_by_me or is_blocked_by_them:
            is_blocked = True
            can_view_profile = False
        elif profile_user.is_private:
            # Check if current user follows the private account
            is_following = Follow.objects.filter(
                follower=request.user,
                following=profile_user
            ).exists()

            if not is_following:
                can_view_profile = False
                # Check if there's a pending follow request
                follow_request = FollowRequest.objects.filter(
                    requester=request.user,
                    target=profile_user
                ).first()
                if follow_request:
                    follow_request_status = follow_request.status
        else:
            # Public account - auto-accept any pending follow requests
            follow_request = FollowRequest.objects.filter(
                requester=request.user,
                target=profile_user,
                status='pending'
            ).first()
            if follow_request:
                Follow.objects.get_or_create(
                    follower=request.user,
                    following=profile_user
                )
                follow_request.status = 'accepted'
                follow_request.save()

    # Track profile view if allowed
    if not is_own_profile and request.user.is_authenticated and can_view_profile:
        # Update or create to allow "latest view" tracking, preventing duplicates
        ProfileView.objects.update_or_create(
            viewer=request.user,
            viewed_user=profile_user,
            defaults={'viewed_at': timezone.now()}
        )

    # Get user's scribes (only if profile is accessible)
    posts = []
    reposts = []
    if can_view_profile:
        scribes_queryset = Scribe.objects.filter(user=profile_user).select_related(
            'user',
            'original_scribe', 'original_scribe__user',
            'original_omzo', 'original_omzo__user',
            'original_story', 'original_story__user'
        ).distinct().order_by('-id', '-timestamp')
        processed_scribe_ids = set()

        for scribe in scribes_queryset:
            if scribe.id in processed_scribe_ids:
                continue
            processed_scribe_ids.add(scribe.id)

            like_count = Like.objects.filter(scribe=scribe).count()
            is_liked = Like.objects.filter(scribe=scribe, user=request.user).exists(
            ) if request.user.is_authenticated else False
            is_disliked = Dislike.objects.filter(scribe=scribe, user=request.user).exists(
            ) if request.user.is_authenticated else False

            # Get comment count
            comment_count = Comment.objects.filter(scribe=scribe).count()

            # Get recent comments (latest 3)
            recent_comments = Comment.objects.filter(
                scribe=scribe,
                parent__isnull=True
            ).select_related('user').order_by('-timestamp')[:3]

            scribe_data = {
                'id': scribe.id,
                'content': scribe.content,
                'timestamp': scribe.timestamp,
                'user': scribe.user,
                'like_count': like_count,
                'is_liked': is_liked,
                'is_disliked': is_disliked,
                'comment_count': comment_count,
                'image_url': scribe.image_url,
                'has_media': scribe.has_media,
                'recent_comments': recent_comments,
                # Repost fields
                'is_repost': scribe.is_repost,
                'original_scribe': scribe.original_scribe,
                'original_omzo': scribe.original_omzo,
                'original_story': scribe.original_story,
                'quote_source': scribe.quote_source,
                # Code Scribe fields
                'content_type': getattr(scribe, 'content_type', ''),
                'code_bundle': getattr(scribe, 'code_bundle', ''),
                'code_html': getattr(scribe, 'code_html', ''),
                'code_css': getattr(scribe, 'code_css', ''),
                'code_js': getattr(scribe, 'code_js', ''),
            }
            if scribe.is_repost:
                reposts.append(scribe_data)
            else:
                posts.append(scribe_data)

    # Check if there's an existing chat
    existing_chat = None
    if not is_own_profile and not is_blocked:
        existing_chat = Chat.objects.filter(
            participants=request.user,
            chat_type='private'
        ).filter(participants=profile_user).first()

    # Check following status
    is_following = False
    if not is_own_profile and request.user.is_authenticated and not is_blocked:
        is_following = Follow.objects.filter(
            follower=request.user,
            following=profile_user
        ).exists()

    # Get follow request counts for own profile
    pending_requests_count = 0
    if is_own_profile:
        pending_requests_count = FollowRequest.objects.filter(
            target=request.user,
            status='pending'
        ).count()

    other_users = CustomUser.objects.exclude(
        id=request.user.id).distinct().order_by('name', 'lastname')

    # Create scribe form for profile page
    scribe_form = ScribeForm()

    # Get user's chats for mobile bottom nav (same as dashboard)
    private_chats = Chat.objects.filter(
        participants=request.user,
        chat_type='private'
    ).annotate(
        last_message_time=Max('messages__timestamp')
    ).order_by('-last_message_time').distinct()

    group_chats = Chat.objects.filter(
        participants=request.user,
        chat_type='group'
    ).annotate(
        last_message_time=Max('messages__timestamp')
    ).order_by('-last_message_time').distinct()

    # Combine chats for the chats panel modal
    user_chats = Chat.objects.filter(
        participants=request.user).order_by('-updated_at')[:20]
    all_chats = []
    for chat in user_chats:
        chat_info = {
            'id': chat.id,
            'name': chat.name,
            'is_group': chat.chat_type == 'group',
        }
        if chat.chat_type == 'private':
            other_participant = chat.participants.exclude(
                id=request.user.id).first()
            chat_info['other_user'] = other_participant
        last_message = chat.messages.order_by('-timestamp').first()
        if last_message:
            chat_info['last_message_preview'] = last_message.content[:50] + \
                ('...' if len(last_message.content) > 50 else '')
        else:
            chat_info['last_message_preview'] = None
        all_chats.append(chat_info)

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

    # Get user's active stories for highlights section
    user_stories = []
    if can_view_profile:
        # stored globally

        stories = Story.objects.filter(
            user=profile_user,
            is_active=True,
            expires_at__gt=timezone.now()
        ).order_by('-created_at')[:10]  # Get up to 10 recent stories

        for story in stories:
            user_stories.append({
                'id': story.id,
                'content': story.content,
                'media_url': story.media_url,
                'story_type': story.story_type,
                'background_color': story.background_color,
                'text_color': story.text_color,
                'created_at': story.created_at,
                'view_count': story.view_count,
            })

    # Get saved posts (only for own profile)
    saved_posts = []
    if is_own_profile:
        saved_items = SavedPost.objects.filter(user=request.user).select_related(
            'scribe', 'scribe__user').order_by('-created_at')
        for saved in saved_items:
            scribe = saved.scribe
            like_count = Like.objects.filter(scribe=scribe).count()
            is_liked = Like.objects.filter(
                scribe=scribe, user=request.user).exists()
            comment_count = Comment.objects.filter(scribe=scribe).count()

            saved_posts.append({
                'id': scribe.id,
                'content': scribe.content,
                'timestamp': scribe.timestamp,
                'user': scribe.user,
                'like_count': like_count,
                'is_liked': is_liked,
                'comment_count': comment_count,
                'image_url': scribe.image_url,
                'has_media': scribe.has_media,
                'content_type': scribe.content_type,
                'code_bundle': scribe.code_bundle,
                'code_html': scribe.code_html,
                'code_css': scribe.code_css,
                'code_js': scribe.code_js,
                'saved_at': saved.created_at,
            })

    # Get omzo if profile is viewable
    omzo = []
    if can_view_profile:
        omzo = Omzo.objects.filter(user=profile_user).order_by('-created_at')

    context = {
        'profile_user': profile_user,
        'scribes': posts,  # Main tab only shows original posts
        'reposts': reposts,
        'omzo': omzo,
        'is_own_profile': is_own_profile,
        'existing_chat': existing_chat,
        'is_following': is_following,
        'other_users': other_users,
        'scribe_form': scribe_form,
        'can_view_profile': can_view_profile,
        'is_blocked': is_blocked,
        'follow_request_status': follow_request_status,
        'pending_requests_count': pending_requests_count,
        'private_chats': private_chats,
        'group_chats': group_chats,
        'chats': all_chats,  # Combined chats for the panel
        'current_user': request.user,
        'unread_message_count': unread_message_count,
        'story_inbox_count': story_inbox_count,
        'user_stories': user_stories,  # Add stories for highlights
        'saved_posts': saved_posts,  # Add saved posts for own profile
    }

    # Use Instagram-style template
    return render(request, 'chat/profile.html', context)


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def toggle_private_chat(request):
    """Toggle whether a chat is in the user's manual 'Private' list (using PinnedChat model)"""
    try:
        data = json.loads(request.body)
        username = data.get('username')

        target_user = get_object_or_404(CustomUser, username=username)

        # Find the private chat between these users
        chat = Chat.objects.filter(
            chat_type='private',
            participants=request.user
        ).filter(participants=target_user).first()

        if not chat:
            # If no chat exists, create one?
            # Ideally frontend only calls this on existing chats.
            # But "Add to Private" logic implies we can do it even if we haven't chatted?
            # Creating a chat just to pin it seems fine.
            chat = Chat.objects.create(chat_type='private')
            chat.participants.add(request.user, target_user)

        # Toggle PinnedChat
        pinned, created = PinnedChat.objects.get_or_create(
            user=request.user, chat=chat)

        if not created:
            # If it existed, delete it (Unpin/Remove from Private)
            pinned.delete()
            is_private = False
        else:
            is_private = True

        return Response({'success': True, 'is_private': is_private})

    except Exception as e:
        logger.error(f"Error in toggle_private_chat: {str(e)}")
        return Response({'success': False, 'error': str(e)})


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def update_profile(request):
    """Update user profile with cropped image support"""
    if request.method == 'POST':
        form = ProfileUpdateForm(
            request.POST, request.FILES, instance=request.user)

        # Check for cropped image data (base64)
        cropped_image_data = request.POST.get('profile_picture_cropped', '')

        # Capture old profile picture path safely
        old_profile_pic_path = None
        if request.user.profile_picture:
            try:
                old_profile_pic_path = request.user.profile_picture.path
            except:
                pass

        if form.is_valid():
            user = form.save(commit=False)

            # Handle cropped image if provided
            if cropped_image_data and cropped_image_data.startswith('data:image'):
                try:
                    import base64
                    import os
                    from django.core.files.base import ContentFile
                    import uuid

                    # Parse the base64 data
                    format_part, imgstr = cropped_image_data.split(';base64,')
                    ext = format_part.split('/')[-1]
                    if ext == 'jpeg':
                        ext = 'jpg'

                    # Decode and save
                    image_data = base64.b64decode(imgstr)
                    filename = f"profile_{request.user.id}_{uuid.uuid4().hex[:8]}.{ext}"

                    # Delete old profile picture if exists on disk
                    if old_profile_pic_path and os.path.exists(old_profile_pic_path):
                        try:
                            os.remove(old_profile_pic_path)
                        except Exception as e:
                            logger.warning(
                                f"Failed to delete old profile pic: {e}")

                    # Save new cropped image
                    # Compress before saving
                    try:
                        from PIL import Image
                        from io import BytesIO

                        img = Image.open(ContentFile(image_data))

                        # Resize if > 900px (Aggressive optimization)
                        if img.width > 900:
                            img.thumbnail(
                                (900, 900), Image.Resampling.LANCZOS)

                        # Re-compress as WebP
                        out_io = BytesIO()

                        if img.mode != 'RGB':
                            img = img.convert('RGB')

                        # Save as WebP with 70% quality
                        # This typically yields files < 100KB
                        img.save(out_io, format='WEBP',
                                 quality=70, optimize=True)

                        # Change filename extension to .webp
                        filename_base = filename.rsplit('.', 1)[0]
                        filename = f"{filename_base}.webp"

                        user.profile_picture.save(
                            filename, ContentFile(out_io.getvalue()), save=False)
                    except Exception as e:
                        logger.error(f"Profile pic compression failed: {e}")
                        # Fallback to uncompressed
                        user.profile_picture.save(
                            filename, ContentFile(image_data), save=False)

                except Exception as e:
                    logger.error(f"Error processing cropped image: {e}")
                    messages.error(
                        request, 'Error processing image. Please try again.')
                    return redirect('update_profile')

            user.save()
            messages.success(request, 'Profile updated successfully!')
            return redirect('profile')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
    else:
        form = ProfileUpdateForm(instance=request.user)

    context = {
        'form': form,
    }
    # Use Instagram-style template
    return render(request, 'chat/update_profile.html', context)


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def post_scribe(request):
    """Post a scribe with proper duplicate prevention and validation"""
    logger.info(f"Scribe post attempt by user {request.user.id}")

    try:
        # Parse form data properly
        content = request.POST.get('content', '').strip()
        image_file = request.FILES.get('image')
        content_type = request.POST.get('content_type', 'text')
        code_html = request.POST.get('code_html')
        code_css = request.POST.get('code_css')
        code_js = request.POST.get('code_js')
        code_bundle = request.POST.get('code_bundle')

        repost_type = request.POST.get('repost_type')
        repost_id = request.POST.get('repost_id')

        # Handle Reposts (including toggle + repost-of-repost flattening)
        if repost_type and repost_id:
            try:
                result = handle_repost_action(
                    user=request.user,
                    repost_type=repost_type,
                    repost_id=repost_id,
                    content=content,
                )
                # Keep backwards-compatible shape: always at least {success: True}
                response = {'success': True}
                response.update(result)
                return Response(response)
            except ValueError as e:
                return Response({'success': False, 'error': str(e)}, status=400)
            except Exception as e:
                logger.error(f"Error creating repost: {str(e)}", exc_info=True)
                return Response({'success': False, 'error': str(e)}, status=400)

        logger.info(
            f"Content: {content[:50]}..., Has image: {bool(image_file)}")

        # Basic validation
        if content_type == 'code_scribe':
            # Allow code-only posts as long as at least one code field is present
            has_code = any([(code_html and code_html.strip()), (code_css and code_css.strip(
            )), (code_js and code_js.strip()), (code_bundle and code_bundle.strip())])
            if not has_code and not content:
                return Response({'success': False, 'error': 'Code scribe cannot be empty. Add HTML, CSS, JS, or a caption.'})
        else:
            if not content and not image_file:
                return Response({'success': False, 'error': 'Scribe cannot be empty. Please add text or an image.'})

        if content and len(content) > 280:
            return Response({'success': False, 'error': 'Scribe must be 280 characters or less.'})

        # Duplicate prevention (only for brand new posts, not repost toggles)
        scribe_hash = generate_scribe_hash(
            request.user.id, (content or code_bundle or ''), bool(image_file))
        cache_key = f"{SCRIBE_CACHE_PREFIX}{scribe_hash}"

        # Check cache for recent duplicate
        if cache.get(cache_key):
            logger.warning(
                f"Duplicate scribe attempt blocked for user {request.user.id}")
            return Response({'success': False, 'error': f'Please wait {SCRIBE_COOLDOWN} seconds before posting the same scribe again.'})

        # Check database for recent duplicates (last 3 minutes)
        three_minutes_ago = timezone.now() - timezone.timedelta(minutes=3)
        recent_duplicate = Scribe.objects.filter(
            user=request.user,
            content=content or '',
            timestamp__gte=three_minutes_ago
        )

        if image_file:
            recent_duplicate = recent_duplicate.exclude(
                image__isnull=True).exclude(image='')
        else:
            recent_duplicate = recent_duplicate.filter(
                Q(image__isnull=True) | Q(image=''))

        if recent_duplicate.exists():
            logger.warning(
                f"Recent duplicate found in database for user {request.user.id}")
            return Response({'success': False, 'error': 'You already posted this scribe recently. Please wait before posting again.'})

        # For code scribe posts, skip ScribeForm and construct manually
        if content_type == 'code_scribe':
            scribe = Scribe(
                user=request.user,
                content=content or '',
                content_type='code_scribe',
                code_html=code_html or None,
                code_css=code_css or None,
                code_js=code_js or None,
                code_bundle=code_bundle or None,
            )
            # image_file is ignored for code scribe unless provided
            if image_file:
                scribe.image = image_file
            scribe.save()
            process_scribe_hashtags_mentions(scribe)
            cache.set(cache_key, True, timeout=SCRIBE_COOLDOWN)
            logger.info(
                f"Code Scribe {scribe.id} created successfully by user {request.user.id}")
            return Response({
                'success': True,
                'message': 'Code scribe posted successfully!',
                'scribe': {
                    'id': scribe.id,
                    'content': scribe.content,
                    'timestamp': scribe.timestamp.strftime('%B %d, %Y at %H:%M'),
                    'time_ago': 'now',
                    'like_count': 0,
                    'comment_count': 0,
                    'image_url': scribe.image_url,
                    'has_media': scribe.has_media,
                    'content_type': scribe.content_type,
                    'code_bundle': scribe.code_bundle,
                }
            })

        # Use Django form for proper validation for standard posts
        form_data = {'content': content} if content else {}
        files_data = {'image': image_file} if image_file else {}

        form = ScribeForm(form_data, files_data)
        if form.is_valid():
            # Create scribe using form
            scribe = form.save(commit=False)

            # Compress image if present
            if image_file:
                try:
                    from PIL import Image, ImageOps
                    from io import BytesIO
                    from django.core.files.base import ContentFile
                    import os

                    # Open image
                    img = Image.open(image_file)
                    img = ImageOps.exif_transpose(img)

                    # Resize if > 900px (Aggressive optimization for 100KB target)
                    if img.width > 900 or img.height > 900:
                        img.thumbnail((900, 900), Image.Resampling.LANCZOS)

                    # Compress - Force WebP for maximum storage efficiency
                    output_io = BytesIO()

                    if img.mode != 'RGB':
                        img = img.convert('RGB')

                    # Save as WebP with 70% quality
                    img.save(output_io, format='WEBP',
                             quality=70, optimize=True)

                    # Update the file in the model instance with .webp extension
                    original_name = os.path.splitext(image_file.name)[0]
                    new_filename = f"{original_name}_opt.webp"

                    if output_io.tell() > 0:
                        scribe.image = ContentFile(
                            output_io.getvalue(), name=new_filename)
                except Exception as e:
                    logger.error(f"Scribe image compression failed: {e}")
                    # If compression fails, it will just use the original file from form.save logic (managed by Django)

            scribe.user = request.user
            scribe.save()

            # Process hashtags and mentions
            process_scribe_hashtags_mentions(scribe)

            # Set cache to prevent immediate duplicates
            cache.set(cache_key, True, timeout=SCRIBE_COOLDOWN)

            logger.info(
                f"Scribe {scribe.id} created successfully by user {request.user.id}")

            return Response({
                'success': True,
                'message': 'Scribe posted successfully!',
                'scribe': {
                    'id': scribe.id,
                    'content': scribe.content,
                    'timestamp': scribe.timestamp.strftime('%B %d, %Y at %H:%M'),
                    'time_ago': 'now',
                    'like_count': 0,
                    'comment_count': 0,
                    'image_url': scribe.image_url,
                    'has_media': scribe.has_media,
                    'user': {
                        'username': request.user.username,
                        'fullname': request.user.full_name,
                        'initials': request.user.initials,
                        'profile_picture_url': request.user.profile_picture_url,
                    }
                }
            })
        else:
            # Form validation errors
            error_messages = []
            for field, errors in form.errors.items():
                for error in errors:
                    error_messages.append(f"{error}")
            logger.warning(f"Form validation failed: {error_messages}")
            return Response({'success': False, 'error': '. '.join(error_messages)})

    except Exception as e:
        logger.error(f"Error in post_scribe: {str(e)}", exc_info=True)
        return Response({'success': False, 'error': 'An unexpected error occurred. Please try again.'})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def toggle_like(request):
    try:
        data = json.loads(request.body)
        scribe_id = data.get('scribe_id') or data.get(
            'tweet_id')  # Support both for backward compatibility

        if not scribe_id:
            return Response({'success': False, 'error': 'Scribe ID is required'})

        try:
            scribe = Scribe.objects.get(id=scribe_id)
        except Scribe.DoesNotExist:
            return Response({'success': False, 'error': 'Scribe not found'})

        # Remove dislike if exists
        Dislike.objects.filter(user=request.user, scribe=scribe).delete()

        # Toggle like
        like_obj = Like.objects.filter(
            user=request.user, scribe=scribe).first()

        if like_obj:
            like_obj.delete()
            is_liked = False
        else:
            Like.objects.create(user=request.user, scribe=scribe)
            is_liked = True

            # Send Notification if not self-like
            if request.user.id != scribe.user.id:
                channel_layer = get_channel_layer()
                async_to_sync(channel_layer.group_send)(
                    f'user_notify_{scribe.user.id}',
                    {
                        'type': 'notify.like',
                        'scribe_id': scribe.id,
                        'user_id': request.user.id,
                        'user_name': request.user.full_name or request.user.username,
                        'user_avatar': request.user.profile_picture.url if request.user.profile_picture else None,
                        'timestamp': timezone.now().isoformat()
                    }
                )

        like_count = Like.objects.filter(scribe=scribe).count()
        dislike_count = Dislike.objects.filter(scribe=scribe).count()

        return Response({
            'success': True,
            'is_liked': is_liked,
            'is_disliked': False,  # Always false since we removed dislike
            'like_count': like_count,
            'dislike_count': dislike_count
        })

    except Exception as e:
        logger.error(f"Error in toggle_like: {str(e)}")
        return Response({'success': False, 'error': 'Failed to toggle like'})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def toggle_dislike(request):
    """Toggle dislike on a scribe"""
    try:
        data = json.loads(request.body)
        scribe_id = data.get('scribe_id') or data.get(
            'tweet_id')  # Support both for backward compatibility

        if not scribe_id:
            return Response({'success': False, 'error': 'Scribe ID is required'})

        try:
            scribe = Scribe.objects.get(id=scribe_id)
        except Scribe.DoesNotExist:
            return Response({'success': False, 'error': 'Scribe not found'})

        # Remove like if exists
        Like.objects.filter(user=request.user, scribe=scribe).delete()

        # Toggle dislike
        dislike_obj = Dislike.objects.filter(
            user=request.user, scribe=scribe).first()

        if dislike_obj:
            dislike_obj.delete()
            is_disliked = False
        else:
            Dislike.objects.create(user=request.user, scribe=scribe)
            is_disliked = True

        like_count = Like.objects.filter(scribe=scribe).count()
        dislike_count = Dislike.objects.filter(scribe=scribe).count()

        return Response({
            'success': True,
            'is_liked': False,  # Always false since we removed like
            'is_disliked': is_disliked,
            'like_count': like_count,
            'dislike_count': dislike_count
        })

    except Exception as e:
        logger.error(f"Error in toggle_dislike: {str(e)}")
        return Response({'success': False, 'error': 'Failed to toggle dislike'})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def toggle_save_post(request):
    """Toggle save/bookmark a post"""
    try:
        data = json.loads(request.body)
        scribe_id = data.get('scribe_id') or data.get(
            'tweet_id')  # Support both for backward compatibility

        if not scribe_id:
            return Response({'success': False, 'error': 'Scribe ID is required'})

        try:
            scribe = Scribe.objects.get(id=scribe_id)
        except Scribe.DoesNotExist:
            return Response({'success': False, 'error': 'Post not found'})

        # Toggle save
        saved_obj = SavedPost.objects.filter(
            user=request.user, scribe=scribe).first()

        if saved_obj:
            saved_obj.delete()
            is_saved = False
            message = 'Post removed from saved'
        else:
            SavedPost.objects.create(user=request.user, scribe=scribe)
            is_saved = True
            message = 'Post saved'

        return Response({
            'success': True,
            'is_saved': is_saved,
            'message': message
        })

    except Exception as e:
        logger.error(f"Error in toggle_save_post: {str(e)}")
        return Response({'success': False, 'error': 'Failed to save post'})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def delete_post(request):
    """Delete a user's own post"""
    try:
        data = json.loads(request.body)
        scribe_id = data.get('scribe_id') or data.get(
            'tweet_id')  # Support both for backward compatibility

        if not scribe_id:
            return Response({'success': False, 'error': 'Scribe ID is required'})

        try:
            scribe = Scribe.objects.get(id=scribe_id)
        except Scribe.DoesNotExist:
            return Response({'success': False, 'error': 'Post not found'})

        # Only allow owner to delete
        if scribe.user != request.user:
            return Response({'success': False, 'error': 'You can only delete your own posts'})

        # Delete the image file if it exists
        if scribe.image:
            try:
                scribe.image.delete(save=False)
            except Exception:
                pass

        scribe.delete()

        return Response({
            'success': True,
            'message': 'Post deleted successfully'
        })

    except Exception as e:
        logger.error(f"Error in delete_post: {str(e)}")
        return Response({'success': False, 'error': 'Failed to delete scribe'})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def report_post(request):
    """Report a post for inappropriate content"""
    try:
        data = json.loads(request.body)
        scribe_id = data.get('scribe_id') or data.get(
            'tweet_id')  # Support both for backward compatibility
        reason = data.get('reason')
        description = data.get('description', '').strip()
        copyright_description = data.get('copyright_description', '').strip()
        copyright_type = data.get('copyright_type', '').strip()

        if not scribe_id or not reason:
            return Response({'success': False, 'error': 'Scribe ID and reason are required'})

        valid_reasons = ['spam', 'inappropriate', 'harassment',
                         'violence', 'hate_speech', 'false_info', 'copyright', 'other']
        if reason not in valid_reasons:
            return Response({'success': False, 'error': 'Invalid report reason'})

        try:
            scribe = Scribe.objects.get(id=scribe_id)
        except Scribe.DoesNotExist:
            return Response({'success': False, 'error': 'Post not found'})

        # Can't report your own posts
        if scribe.user == request.user:
            return Response({'success': False, 'error': 'You cannot report your own post'})

        # Check if already reported by this user
        existing_report = PostReport.objects.filter(
            reporter=request.user, scribe=scribe).first()
        if existing_report:
            return Response({'success': False, 'error': 'You have already reported this post'})

        # Validate copyright_type if reason is copyright
        if reason == 'copyright':
            valid_copyright_types = ['audio', 'content', 'both']
            if copyright_type and copyright_type not in valid_copyright_types:
                return Response({'success': False, 'error': 'Invalid copyright type'})

        PostReport.objects.create(
            reporter=request.user,
            scribe=scribe,
            reason=reason,
            description=description,
            copyright_description=copyright_description if reason == 'copyright' else None,
            copyright_type=copyright_type if reason == 'copyright' else None
        )

        # Send Notification to the reported user
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f'user_notify_{scribe.user.id}',
            {
                'type': 'notify.report',  # New type
                'scribe_id': scribe.id,
                'reporter_id': request.user.id,  # Often hidden, but backend sends it
                'reason': reason,
                'timestamp': timezone.now().isoformat()
            }
        )

        return Response({
            'success': True,
            'message': 'Thank you for your report. We will review it shortly.'
        })

    except Exception as e:
        logger.error(f"Error in report_post: {str(e)}")
        return Response({'success': False, 'error': 'Failed to report post'})


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def get_saved_posts(request):
    """Get all saved posts for the current user"""
    try:
        saved = SavedPost.objects.filter(
            user=request.user).select_related('scribe', 'scribe__user')

        posts = []
        for saved_post in saved:
            scribe = saved_post.scribe
            posts.append({
                'id': scribe.id,
                'content': scribe.content,
                'image_url': scribe.image_url,
                'user_username': scribe.user.username,
                'user_full_name': scribe.user.full_name,
                'user_profile_picture': scribe.user.profile_picture_url,
                'like_count': scribe.like_count,
                'comment_count': scribe.comment_count,
                'timestamp': scribe.timestamp.strftime('%b %d, %Y'),
                'saved_at': saved_post.created_at.strftime('%b %d, %Y'),
            })

        return Response({
            'success': True,
            'saved_posts': posts
        })

    except Exception as e:
        logger.error(f"Error in get_saved_posts: {str(e)}")
        return Response({'success': False, 'error': 'Failed to get saved posts'})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def copy_post_link(request):
    """Get the shareable link for a post"""
    try:
        data = json.loads(request.body)
        scribe_id = data.get('scribe_id') or data.get(
            'tweet_id')  # Support both for backward compatibility

        if not scribe_id:
            return Response({'success': False, 'error': 'Scribe ID is required'})

        try:
            scribe = Scribe.objects.get(id=scribe_id)
        except Scribe.DoesNotExist:
            return Response({'success': False, 'error': 'Post not found'})

        # Generate the post link using the request's host
        scheme = 'https' if request.is_secure() else 'http'
        host = request.get_host()
        post_link = f"{scheme}://{host}/post/{scribe_id}/"

        return Response({
            'success': True,
            'link': post_link,
            'message': 'Link copied to clipboard'
        })

    except Exception as e:
        logger.error(f"Error in copy_post_link: {str(e)}")
        return Response({'success': False, 'error': 'Failed to get post link'})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def add_comment(request):
    """Add a comment to a scribe"""
    try:
        data = json.loads(request.body)
        scribe_id = data.get('scribe_id') or data.get(
            'tweet_id')  # Support both for backward compatibility
        content = data.get('content', '').strip()
        parent_id = data.get('parent_id')  # For replies

        if not scribe_id or not content:
            return Response({'success': False, 'error': 'Scribe ID and content are required'})

        if len(content) > 500:
            return Response({'success': False, 'error': 'Comment too long (max 500 characters)'})

        try:
            scribe = Scribe.objects.get(id=scribe_id)
        except Scribe.DoesNotExist:
            return Response({'success': False, 'error': 'Scribe not found'})

        parent_comment = None
        if parent_id:
            try:
                parent_comment = Comment.objects.get(
                    id=parent_id, scribe=scribe)
            except Comment.DoesNotExist:
                return Response({'success': False, 'error': 'Parent comment not found'})

        comment = Comment.objects.create(
            scribe=scribe,
            user=request.user,
            content=content,
            parent=parent_comment
        )

        # Send Notification if not self-comment
        if request.user.id != scribe.user.id:
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f'user_notify_{scribe.user.id}',
                {
                    'type': 'notify.comment',
                    'scribe_id': scribe.id,
                    'comment_id': comment.id,
                    'user_id': request.user.id,
                    'user_name': request.user.full_name or request.user.username,
                    'user_avatar': request.user.profile_picture.url if request.user.profile_picture else None,
                    'comment_content': content[:100],
                    'timestamp': timezone.now().isoformat()
                }
            )

        return Response({
            'success': True,
            'comment': {
                'id': comment.id,
                'content': comment.content,
                'user_id': comment.user.id,
                'user_full_name': comment.user.full_name,
                'user_username': comment.user.username,
                'user_initials': comment.user.initials,
                'user_profile_picture': comment.user.profile_picture_url,
                'timestamp': comment.timestamp.strftime('%b %d, %Y %H:%M'),
                'is_own': comment.user == request.user,
            }
        })

    except Exception as e:
        logger.error(f"Error in add_comment: {str(e)}")
        return Response({'success': False, 'error': 'Failed to add comment'})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def toggle_comment_like(request):
    """Toggle like on a comment"""
    try:
        data = json.loads(request.body)
        comment_id = data.get('comment_id')

        if not comment_id:
            return Response({'success': False, 'error': 'Comment ID is required'})

        try:
            comment = Comment.objects.get(id=comment_id)
        except Comment.DoesNotExist:
            return Response({'success': False, 'error': 'Comment not found'})

        # Toggle like
        like_obj = CommentLike.objects.filter(
            user=request.user, comment=comment).first()

        if like_obj:
            like_obj.delete()
            is_liked = False
        else:
            CommentLike.objects.create(user=request.user, comment=comment)
            is_liked = True

        return Response({
            'success': True,
            'is_liked': is_liked,
            'like_count': comment.like_count
        })

    except Exception as e:
        logger.error(f"Error in toggle_comment_like: {str(e)}")
        return Response({'success': False, 'error': 'Failed to toggle like'})


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def get_scribe(request, scribe_id):
    """Get a single scribe by ID"""
    try:
        from django.utils.timesince import timesince
        scribe = get_object_or_404(Scribe, id=scribe_id)

        # Check if user has liked this scribe
        is_liked = Like.objects.filter(
            user=request.user, scribe=scribe).exists()

        # Check if user has saved this scribe
        is_saved = SavedPost.objects.filter(
            user=request.user, scribe=scribe).exists()

        scribe_data = {
            'id': scribe.id,
            'content': scribe.content,
            'image_url': scribe.image_url,
            'username': scribe.user.username,
            'avatar': scribe.user.profile_picture_url,
            'full_name': scribe.user.full_name,
            'like_count': scribe.scribe_likes.count(),
            'comment_count': scribe.comments.count(),
            'is_liked': is_liked,
            'is_saved': is_saved,
            'time_ago': timesince(scribe.timestamp) + ' ago',
            'timestamp': scribe.timestamp.isoformat(),
            'code_html': getattr(scribe, 'code_html', ''),
            'code_css': getattr(scribe, 'code_css', ''),
            'code_js': getattr(scribe, 'code_js', ''),
        }

        return Response({
            'success': True,
            'scribe': scribe_data
        })

    except Exception as e:
        logger.error(f"Error in get_scribe: {str(e)}")
        return Response({'success': False, 'error': 'Failed to get scribe'})


def view_post(request, post_id):
    """View a single post - accessible without login for sharing"""
    try:
        scribe = get_object_or_404(Scribe, id=post_id)

        # If user is logged in, redirect to dashboard with the post highlighted
        if request.user.is_authenticated:
            return redirect(f'/dashboard/?post={post_id}')

        # If not logged in, redirect to login with next parameter
        return redirect(f'/login/?next=/post/{post_id}/')

    except Exception as e:
        logger.error(f"Error in view_post: {str(e)}")
        return redirect('/login/')


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def get_scribe_comments(request, scribe_id):
    """Get comments for a scribe"""
    try:
        scribe = get_object_or_404(Scribe, id=scribe_id)

        comments = Comment.objects.filter(
            scribe=scribe,
            parent__isnull=True
        ).select_related('user').prefetch_related('replies__user', 'comment_likes', 'replies__comment_likes').order_by('timestamp')

        # Get all comment IDs the current user has liked
        user_liked_comment_ids = set(
            CommentLike.objects.filter(user=request.user).values_list(
                'comment_id', flat=True)
        )

        comments_data = []
        for comment in comments:
            comment_data = {
                'id': comment.id,
                'content': comment.content,
                'user_id': comment.user.id,
                'user_full_name': comment.user.full_name,
                'user_username': comment.user.username,
                'user_initials': comment.user.initials,
                'user_profile_picture': comment.user.profile_picture_url,
                'timestamp': comment.timestamp.strftime('%b %d, %Y %H:%M'),
                'is_own': comment.user == request.user,
                'is_liked': comment.id in user_liked_comment_ids,
                'like_count': comment.like_count,
                'replies': []
            }

            # Add replies
            for reply in comment.replies.all():
                reply_data = {
                    'id': reply.id,
                    'content': reply.content,
                    'user_full_name': reply.user.full_name,
                    'user_username': reply.user.username,
                    'user_initials': reply.user.initials,
                    'user_profile_picture': reply.user.profile_picture_url,
                    'timestamp': reply.timestamp.strftime('%b %d, %Y %H:%M'),
                    'is_own': reply.user == request.user,
                    'is_liked': reply.id in user_liked_comment_ids,
                    'like_count': reply.like_count,
                }
                comment_data['replies'].append(reply_data)

            comments_data.append(comment_data)

        return Response({
            'success': True,
            'comments': comments_data
        })

    except Exception as e:
        logger.error(f"Error in get_scribe_comments: {str(e)}")
        return Response({'success': False, 'error': 'Failed to load comments'})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def toggle_follow(request):
    try:
        data = json.loads(request.body)
        username = data.get('username')

        if not username:
            return Response({'success': False, 'error': 'Username is required'})

        try:
            target_user = CustomUser.objects.get(username=username)
        except CustomUser.DoesNotExist:
            return Response({'success': False, 'error': 'User not found'})

        if target_user == request.user:
            return Response({'success': False, 'error': 'Cannot follow yourself'})

        # Check if target user is blocked by current user
        if Block.objects.filter(blocker=request.user, blocked=target_user).exists():
            return Response({'success': False, 'error': 'You have blocked this user'})

        # Check if current user is blocked by target user
        if Block.objects.filter(blocker=target_user, blocked=request.user).exists():
            return Response({'success': False, 'error': 'This user has blocked you'})

        follow_obj = Follow.objects.filter(
            follower=request.user,
            following=target_user
        ).first()

        if follow_obj:
            # Unfollow
            follow_obj.delete()
            is_following = False
            follow_request_status = None
        else:
            # Check if there's a pending follow request
            existing_request = FollowRequest.objects.filter(
                requester=request.user,
                target=target_user,
                status='pending'
            ).first()

            if existing_request:
                # Cancel the pending request
                existing_request.delete()
                is_following = False
                follow_request_status = None
            elif target_user.is_private:
                # Send new follow request for private account
                # Clear any old declined requests first
                FollowRequest.objects.filter(
                    requester=request.user,
                    target=target_user
                ).delete()

                FollowRequest.objects.create(
                    requester=request.user,
                    target=target_user
                )
                is_following = False
                follow_request_status = 'pending'
            else:
                # Public account - follow directly
                Follow.objects.create(
                    follower=request.user,
                    following=target_user
                )
                is_following = True
                follow_request_status = None

                # Send Notification
                channel_layer = get_channel_layer()
                async_to_sync(channel_layer.group_send)(
                    f'user_notify_{target_user.id}',
                    {
                        'type': 'notify.follow',
                        'follower_id': request.user.id,
                        'follower_name': request.user.full_name,
                        'follower_username': request.user.username,
                        'follower_avatar': request.user.profile_picture.url if request.user.profile_picture else None,
                    }
                )

        # Clear explore cache when follow status changes
        from django.core.cache import cache
        cache_key = f'explore_order_{request.user.id}'
        cache.delete(cache_key)

        return Response({
            'success': True,
            'is_following': is_following,
            'follow_request_status': follow_request_status,
            'username': username,
            'follower_count': target_user.follower_count
        })

    except Exception as e:
        logger.error(f"Error in toggle_follow: {str(e)}")
        return Response({'success': False, 'error': 'Failed to toggle follow'})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def dismiss_suggestion(request):
    """Dismiss a user suggestion so they don't appear again"""
    try:
        data = json.loads(request.body)
        username = data.get('username')

        if not username:
            return Response({'success': False, 'error': 'Username is required'})

        try:
            target_user = CustomUser.objects.get(username=username)
        except CustomUser.DoesNotExist:
            return Response({'success': False, 'error': 'User not found'})

        if target_user == request.user:
            return Response({'success': False, 'error': 'Cannot dismiss yourself'})

        # Create dismissed suggestion record (or get if exists)
        DismissedSuggestion.objects.get_or_create(
            user=request.user,
            dismissed_user=target_user
        )

        return Response({
            'success': True,
            'message': f'{username} will no longer appear in suggestions'
        })

    except Exception as e:
        logger.error(f"Error in dismiss_suggestion: {str(e)}")
        return Response({'success': False, 'error': 'Failed to dismiss suggestion'})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def toggle_block(request):
    """Block or unblock a user"""
    try:
        data = json.loads(request.body)
        username = data.get('username')

        if not username:
            return Response({'success': False, 'error': 'Username is required'})

        try:
            target_user = CustomUser.objects.get(username=username)
        except CustomUser.DoesNotExist:
            return Response({'success': False, 'error': 'User not found'})

        if target_user == request.user:
            return Response({'success': False, 'error': 'Cannot block yourself'})

        # Check if already blocked
        block_obj = Block.objects.filter(
            blocker=request.user,
            blocked=target_user
        ).first()

        if block_obj:
            # Unblock
            block_obj.delete()
            is_blocked = False

            # Remove follow relationship if it exists
            Follow.objects.filter(
                follower=request.user,
                following=target_user
            ).delete()
            Follow.objects.filter(
                follower=target_user,
                following=request.user
            ).delete()
        else:
            # Block
            Block.objects.create(
                blocker=request.user,
                blocked=target_user
            )
            is_blocked = True

            # Remove follow relationship if it exists
            Follow.objects.filter(
                follower=request.user,
                following=target_user
            ).delete()
            Follow.objects.filter(
                follower=target_user,
                following=request.user
            ).delete()

            # Remove any pending follow requests
            FollowRequest.objects.filter(
                requester=request.user,
                target=target_user
            ).delete()
            FollowRequest.objects.filter(
                requester=target_user,
                target=request.user
            ).delete()

        return Response({
            'success': True,
            'is_blocked': is_blocked,
            'username': username
        })

    except Exception as e:
        logger.error(f"Error in toggle_block: {str(e)}")
        return Response({'success': False, 'error': 'Failed to toggle block'})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def manage_follow_request(request):
    """Accept or decline a follow request"""
    try:
        data = json.loads(request.body)
        username = data.get('username')
        action = data.get('action')  # 'accept' or 'decline'

        if not username:
            return Response({'success': False, 'error': 'Username is required'})

        if action not in ['accept', 'decline']:
            return Response({'success': False, 'error': 'Invalid action'})

        try:
            sender_user = CustomUser.objects.get(username=username)
        except CustomUser.DoesNotExist:
            return Response({'success': False, 'error': 'User not found'})

        # Find the follow request
        follow_request = FollowRequest.objects.filter(
            requester=sender_user,
            target=request.user,
            status='pending'
        ).first()

        if not follow_request:
            return Response({'success': False, 'error': 'No pending follow request found'})

        if action == 'accept':
            # Create follow relationship
            Follow.objects.get_or_create(
                follower=sender_user,
                following=request.user
            )
            follow_request.status = 'accepted'
            follow_request.save()
            message = 'Follow request accepted'

            # Send Notification to the requester
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f'user_notify_{sender_user.id}',
                {
                    'type': 'notify.follow',
                    'follower_id': request.user.id,
                    'follower_name': request.user.full_name,
                    'follower_username': request.user.username,
                    'follower_avatar': request.user.profile_picture.url if request.user.profile_picture else None,
                }
            )
        else:  # decline
            follow_request.status = 'declined'
            follow_request.save()
            message = 'Follow request declined'

        return Response({
            'success': True,
            'action': action,
            'username': username,
            'message': message
        })

    except Exception as e:
        logger.error(f"Error in manage_follow_request: {str(e)}")
        return Response({'success': False, 'error': 'Failed to manage follow request'})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def toggle_account_privacy(request):
    """Toggle account privacy setting"""
    try:
        old_privacy = request.user.is_private
        request.user.is_private = not request.user.is_private
        request.user.save()

        # Handle existing follow requests when changing privacy
        if not old_privacy and request.user.is_private:
            # User is making account private - existing follows remain
            pass
        elif old_privacy and not request.user.is_private:
            # User is making account public - accept all pending follow requests
            pending_requests = FollowRequest.objects.filter(
                target=request.user,
                status='pending'
            )

            for follow_request in pending_requests:
                # Create follow relationship
                Follow.objects.get_or_create(
                    follower=follow_request.requester,
                    following=request.user
                )
                # Mark request as accepted
                follow_request.status = 'accepted'
                follow_request.save()

        return Response({
            'success': True,
            'is_private': request.user.is_private
        })

    except Exception as e:
        logger.error(f"Error in toggle_account_privacy: {str(e)}")
        return Response({'success': False, 'error': 'Failed to toggle account privacy'})


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def get_follow_requests(request):
    """Get pending follow requests for the current user"""
    try:
        follow_requests = FollowRequest.objects.filter(
            target=request.user,
            status='pending'
        ).select_related('requester').order_by('-created_at')

        requests_data = []
        for req in follow_requests:
            requests_data.append({
                'username': req.requester.username,
                'full_name': req.requester.name + ' ' + req.requester.lastname if req.requester.name and req.requester.lastname else req.requester.username,
                'profile_pic': req.requester.profile_picture.url if req.requester.profile_picture else None,
                'requested_at': req.created_at.strftime('%b %d, %Y')
            })

        return Response({
            'success': True,
            'requests': requests_data
        })

    except Exception as e:
        logger.error(f"Error in get_follow_requests: {str(e)}")
        return Response({'success': False, 'error': 'Failed to get follow requests'})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def follow_states(request):
    try:
        data = json.loads(request.body)
        usernames = data.get('usernames', [])

        if not usernames:
            return Response({'success': True, 'follow_states': {}})

        follow_states_dict = {}
        for username in usernames:
            try:
                target_user = CustomUser.objects.get(username=username)

                # Check if blocked
                is_blocked_by_me = Block.objects.filter(
                    blocker=request.user,
                    blocked=target_user
                ).exists()
                is_blocked_by_them = Block.objects.filter(
                    blocker=target_user,
                    blocked=request.user
                ).exists()

                if is_blocked_by_me or is_blocked_by_them:
                    follow_states_dict[username] = {
                        'is_following': False,
                        'is_blocked': True,
                        'follow_request_status': None,
                        'can_follow': False
                    }
                    continue

                # Check follow status
                is_following = Follow.objects.filter(
                    follower=request.user,
                    following=target_user
                ).exists()

                # Check follow request status
                follow_request = FollowRequest.objects.filter(
                    requester=request.user,
                    target=target_user
                ).first()

                follow_request_status = None
                if follow_request:
                    if follow_request.status == 'pending' and not target_user.is_private:
                        # Auto-accept pending request for public accounts
                        Follow.objects.get_or_create(
                            follower=request.user,
                            following=target_user
                        )
                        follow_request.status = 'accepted'
                        follow_request.save()
                        is_following = True
                        follow_request_status = None
                    else:
                        follow_request_status = follow_request.status

                follow_states_dict[username] = {
                    'is_following': is_following,
                    'is_blocked': False,
                    'follow_request_status': follow_request_status,
                    'can_follow': True,
                    'is_private': target_user.is_private
                }

            except CustomUser.DoesNotExist:
                follow_states_dict[username] = {
                    'is_following': False,
                    'is_blocked': False,
                    'follow_request_status': None,
                    'can_follow': False
                }

        return Response({
            'success': True,
            'follow_states': follow_states_dict
        })

    except Exception as e:
        logger.error(f"Error in follow_states: {str(e)}")
        return Response({'success': False, 'error': 'Failed to get follow states'})


def extract_hashtags(content):
    """Extract hashtags from content"""
    hashtag_pattern = r'#(\w+)'
    return list(set(re.findall(hashtag_pattern, content.lower())))


def extract_mentions(content):
    """Extract @mentions from content"""
    mention_pattern = r'@(\w+)'
    return list(set(re.findall(mention_pattern, content.lower())))


def process_scribe_hashtags_mentions(scribe):
    """Process hashtags and mentions in a scribe after creation"""

    if not scribe.content:
        return

    # Process hashtags
    hashtags = extract_hashtags(scribe.content)
    for tag_name in hashtags:
        hashtag, _ = Hashtag.objects.get_or_create(name=tag_name.lower())
        ScribeHashtag.objects.get_or_create(scribe=scribe, hashtag=hashtag)

    # Process mentions
    mentions = extract_mentions(scribe.content)
    for username in mentions:
        try:
            mentioned_user = CustomUser.objects.get(username__iexact=username)
            if mentioned_user != scribe.user:  # Don't mention yourself
                Mention.objects.get_or_create(
                    scribe=scribe, mentioned_user=mentioned_user)
        except CustomUser.DoesNotExist:
            pass  # User doesn't exist, skip


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def get_hashtag_scribes(request, hashtag):
    """Get all scribes with a specific hashtag"""
    try:
        # Clean hashtag (remove # if present)
        hashtag_name = hashtag.lower().lstrip('#')

        hashtag_obj = Hashtag.objects.filter(name=hashtag_name).first()

        if not hashtag_obj:
            return Response({
                'success': True,
                'hashtag': hashtag_name,
                'scribes': [],
                'count': 0
            })

        scribe_links = ScribeHashtag.objects.filter(
            hashtag=hashtag_obj
        ).select_related('scribe__user').order_by('-scribe__timestamp')[:50]

        scribes_data = []
        for link in scribe_links:
            scribe = link.scribe
            scribes_data.append({
                'id': scribe.id,
                'content': scribe.content,
                'user': {
                    'id': scribe.user.id,
                    'username': scribe.user.username,
                    'full_name': scribe.user.full_name,
                    'profile_picture_url': scribe.user.profile_picture_url
                },
                'timestamp': scribe.timestamp.isoformat(),
                'like_count': scribe.like_count,
                'comment_count': scribe.comment_count,
                'image_url': scribe.image_url,
                'is_liked': scribe.is_liked_by(request.user),
                'code_html': getattr(scribe, 'code_html', ''),
                'code_css': getattr(scribe, 'code_css', ''),
                'code_js': getattr(scribe, 'code_js', ''),
            })

        return Response({
            'success': True,
            'hashtag': hashtag_name,
            'scribes': scribes_data,
            'count': len(scribes_data)
        })

    except Exception as e:
        logger.error(f"Error getting hashtag scribes: {str(e)}")
        return Response({'success': False, 'error': 'Failed to get hashtag scribes'})


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def get_trending_hashtags(request):
    """Get trending hashtags (most used in last 24 hours)"""
    try:
        # Get hashtags from scribes in last 24 hours
        yesterday = timezone.now() - timezone.timedelta(days=1)

        trending = ScribeHashtag.objects.filter(
            created_at__gte=yesterday
        ).values('hashtag__name').annotate(
            count=Count('id')
        ).order_by('-count')[:10]

        hashtags_data = []
        for item in trending:
            hashtags_data.append({
                'name': item['hashtag__name'],
                'scribe_count': item['count']
            })

        return Response({
            'success': True,
            'trending': hashtags_data
        })

    except Exception as e:
        logger.error(f"Error getting trending hashtags: {str(e)}")
        return Response({'success': False, 'error': 'Failed to get trending hashtags'})


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def get_user_mentions(request):
    """Get mentions of the current user"""
    try:
        mentions = Mention.objects.filter(
            mentioned_user=request.user
        ).select_related('scribe__user').order_by('-created_at')[:50]

        mentions_data = []
        for mention in mentions:
            scribe = mention.scribe
            mentions_data.append({
                'id': mention.id,
                'scribe': {
                    'id': scribe.id,
                    'content': scribe.content,
                    'user': {
                        'id': scribe.user.id,
                        'username': scribe.user.username,
                        'full_name': scribe.user.full_name,
                        'profile_picture_url': scribe.user.profile_picture_url
                    },
                    'timestamp': scribe.timestamp.isoformat(),
                    'like_count': scribe.like_count,
                    'image_url': scribe.image_url
                },
                'is_read': mention.is_read,
                'created_at': mention.created_at.isoformat()
            })

        # Mark mentions as read
        Mention.objects.filter(mentioned_user=request.user,
                               is_read=False).update(is_read=True)

        return Response({
            'success': True,
            'mentions': mentions_data,
            'count': len(mentions_data)
        })

    except Exception as e:
        logger.error(f"Error getting user mentions: {str(e)}")
        return Response({'success': False, 'error': 'Failed to get mentions'})


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def search_users_for_mention(request):
    """Search users for @mention autocomplete"""
    try:
        query = request.GET.get('q', '').strip().lower()

        if len(query) < 1:
            return Response({'success': True, 'users': []})

        users = CustomUser.objects.filter(
            db_models.Q(username__icontains=query) |
            db_models.Q(name__icontains=query) |
            db_models.Q(lastname__icontains=query)
        ).exclude(id=request.user.id)[:10]

        users_data = []
        for user in users:
            is_following = Follow.objects.filter(
                follower=request.user,
                following=user
            ).exists()

            users_data.append({
                'id': user.id,
                'username': user.username,
                'full_name': user.full_name,
                'profile_picture_url': user.profile_picture_url,
                'is_following': is_following
            })

        return Response({
            'success': True,
            'users': users_data
        })

    except Exception as e:
        logger.error(f"Error searching users: {str(e)}")
        return Response({'success': False, 'error': 'Failed to search users'})


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def global_search(request):
    """Global search across Users, Groups, Scribes, and Omzo"""
    try:
        query = request.GET.get('q', '').strip()
        page = int(request.GET.get('page', 1))
        per_page = 15
        offset = (page - 1) * per_page

        if len(query) < 1:
            return Response({'success': True, 'results': [], 'has_more': False})

        # Search QuerySets
        results = []

        # 1. Users
        # 1. Users
        users_qs = CustomUser.objects.filter(
            db_models.Q(username__icontains=query) |
            db_models.Q(name__icontains=query) |
            db_models.Q(lastname__icontains=query)
        )

        # 2. Groups
        groups_qs = Chat.objects.filter(
            chat_type='group',
            name__icontains=query
        )

        # 3. Scribes
        scribes_qs = Scribe.objects.filter(
            db_models.Q(content__icontains=query) |
            db_models.Q(code_html__icontains=query) |
            db_models.Q(code_css__icontains=query) |
            db_models.Q(code_js__icontains=query)
        ).select_related('user')

        # 4.Omzo
        omzo_qs = Omzo.objects.filter(
            caption__icontains=query
        ).select_related('user')

        # Combine results (naively for now, interleaving could be better but simple list extension is request)
        # We will fetch a batch of each and combine, or search all.
        # Given pagination complexity across mixed models, we'll fetch a slice of each and merge,
        # or prioritze categories.
        # Let's simple combine lists and paginate in memory for this MVP as data volume is distinct.
        # Optimized: perform limit on each query to avoid huge memory usage, then merge.

        # Fetch top N matches from each category
        # Using a limit slightly higher than per_page to ensure we have mixed content
        limit = per_page + offset

        users = list(users_qs[:limit])
        groups = list(groups_qs[:limit])
        scribes = list(scribes_qs[:limit])
        omzos = list(omzo_qs[:limit])

        # Normalize to standard dict format
        combined = []

        for u in users:
            combined.append({
                'type': 'person',
                'id': u.id,
                'title': u.full_name or u.username,
                'subtitle': f"@{u.username}",
                'image_url': u.profile_picture_url,
                'data': {'username': u.username},
                # Sort weight? Users match usually high relevance
                'score': 100
            })

        for g in groups:
            combined.append({
                'type': 'group',
                'id': g.id,
                'title': g.name,
                'subtitle': f"{g.participant_count} members",
                # Placeholder for group icon
                'image_url': None,
                'data': {'id': g.id},
                'score': 90
            })

        for s in scribes:
            # Determine if scribe or post
            is_code_scribe = s.content_type == 'code_scribe' or s.code_bundle or s.code_html
            combined.append({
                'type': 'scribe' if is_code_scribe else 'post',
                'id': s.id,
                'title': s.user.full_name or s.user.username,
                'subtitle': s.content[:50] if s.content else 'Media content',
                'image_url': s.image_url if s.image_url else None,
                'data': {
                    'content': s.content,
                    'has_code': is_code_scribe,
                    'time_ago': s.timestamp.strftime('%b %d')
                },
                'score': 80
            })

        for r in omzos:
            combined.append({
                'type': 'omzo',
                'id': r.id,
                'title': r.user.full_name or r.user.username,
                'subtitle': r.caption[:50] if r.caption else 'Omzo content',
                # Not a thumbnail, but browser might handle
                'image_url': r.video_file.url if r.video_file else None,
                'data': {'id': r.id},
                'score': 70
            })

        # Sort by vague relevance/type or just mix?
        # Let's shuffle since "score" is static per type
        # Ideally we'd sort by some match quality, but DB 'icontains' is simple.
        # For stable pagination, we MUST sort deterministically or cache.
        # Simplified: Just slice the combined list.
        # WARNING: In-memory pagination of combined lists is tricky across requests without state.
        # Hack: Return all reasonable matches up to a hard limit (e.g. 100) and let client paginate?
        # Or just paginate the combined result:
        combined.sort(key=lambda x: str(x['id']))  # Stable sort
        # Then reverse so newer IDs (roughly) are first? no, IDs are mixed types.
        # Let's just return the slice requested.

        has_more = len(combined) > (offset + per_page)
        paginated_results = combined[offset:offset + per_page]

        return Response({
            'success': True,
            'results': paginated_results,
            'has_more': has_more
        })

    except Exception as e:
        logger.error(f"Error in global search: {str(e)}")
        return Response({'success': False, 'error': 'Search failed'})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def update_theme(request):
    """Update user theme preference"""
    try:
        data = json.loads(request.body)
        theme = data.get('theme')

        # Validate theme
        valid_themes = [choice[0] for choice in CustomUser.THEME_CHOICES]
        if theme not in valid_themes:
            return Response({'success': False, 'error': 'Invalid theme'})

        request.user.theme = theme
        request.user.save(update_fields=['theme'])

        return Response({'success': True, 'theme': theme})
    except Exception as e:
        logger.error(f"Error updating theme: {str(e)}")
        return Response({'success': False, 'error': 'Failed to update theme'})


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def get_all_activity(request):
    """Get all activity for the current user - likes, comments, follows, story activity"""
    try:
        from django.utils.timesince import timesince
        from chat.models import Story, StoryView

        activity_items = []

        # 1. Post likes - people who liked MY posts (excluding my own likes)
        post_likes = Like.objects.filter(
            scribe__user=request.user
        ).exclude(user=request.user).select_related('user', 'scribe').order_by('-timestamp')[:20]

        for like in post_likes:
            activity_items.append({
                'type': 'like',
                'timestamp': like.timestamp,
                'user': {
                    'id': like.user.id,
                    'username': like.user.username,
                    'full_name': like.user.full_name,
                    'profile_picture_url': like.user.profile_picture_url,
                },
                'scribe': {
                    'id': like.scribe.id,
                    'content': like.scribe.content[:50] + '...' if len(like.scribe.content) > 50 else like.scribe.content,
                    'image_url': like.scribe.image_url,
                }
            })

        # 2. Post comments - people who commented on MY posts (excluding my own comments)
        post_comments = Comment.objects.filter(
            scribe__user=request.user
        ).exclude(user=request.user).select_related('user', 'scribe').order_by('-timestamp')[:20]

        for comment in post_comments:
            activity_items.append({
                'type': 'comment',
                'timestamp': comment.timestamp,
                'user': {
                    'id': comment.user.id,
                    'username': comment.user.username,
                    'full_name': comment.user.full_name,
                    'profile_picture_url': comment.user.profile_picture_url,
                },
                'scribe': {
                    'id': comment.scribe.id,
                    'content': comment.scribe.content[:50] + '...' if len(comment.scribe.content) > 50 else comment.scribe.content,
                },
                'comment_content': comment.content[:80] + '...' if len(comment.content) > 80 else comment.content,
            })

        # 3. New followers
        new_followers = Follow.objects.filter(
            following=request.user
        ).select_related('follower').order_by('-created_at')[:20]

        for follow in new_followers:
            activity_items.append({
                'type': 'follow',
                'timestamp': follow.created_at,
                'user': {
                    'id': follow.follower.id,
                    'username': follow.follower.username,
                    'full_name': follow.follower.full_name,
                    'profile_picture_url': follow.follower.profile_picture_url,
                }
            })

        # 4. Story likes
        story_likes = StoryLike.objects.filter(
            story__user=request.user
        ).exclude(user=request.user).select_related('user', 'story').order_by('-created_at')[:20]

        for like in story_likes:
            activity_items.append({
                'type': 'story_like',
                'timestamp': like.created_at,
                'user': {
                    'id': like.user.id,
                    'username': like.user.username,
                    'full_name': like.user.full_name,
                    'profile_picture_url': like.user.profile_picture_url,
                },
                'story': {
                    'id': like.story.id,
                    'story_type': like.story.story_type,
                }
            })

        # 5. Story replies
        story_replies = StoryReply.objects.filter(
            story__user=request.user
        ).exclude(replier=request.user).select_related('replier', 'story').order_by('-created_at')[:20]

        for reply in story_replies:
            activity_items.append({
                'type': 'story_reply',
                'timestamp': reply.created_at,
                'is_read': reply.is_read,
                'user': {
                    'id': reply.replier.id,
                    'username': reply.replier.username,
                    'full_name': reply.replier.full_name,
                    'profile_picture_url': reply.replier.profile_picture_url,
                },
                'story': {
                    'id': reply.story.id,
                    'story_type': reply.story.story_type,
                },
                'content': reply.content[:80] + '...' if len(reply.content) > 80 else reply.content,
            })

        # 6. Omzo (Omzo) likes - people who liked MY Omzo
        omzo_likes = OmzoLike.objects.filter(
            omzo__user=request.user
        ).exclude(user=request.user).select_related('user', 'omzo').order_by('-created_at')[:20]

        for like in omzo_likes:
            activity_items.append({
                'type': 'omzo_like',
                'timestamp': like.created_at,
                'user': {
                    'id': like.user.id,
                    'username': like.user.username,
                    'full_name': like.user.full_name,
                    'profile_picture_url': like.user.profile_picture_url,
                },
                'omzo': {
                    'id': like.omzo.id,
                    'caption': like.omzo.caption[:50] + '...' if like.omzo.caption and len(like.omzo.caption) > 50 else (like.omzo.caption or 'Omzo'),
                }
            })

        # 7. Omzo (Omzo) comments - people who commented on MY Omzo
        omzo_comments = OmzoComment.objects.filter(
            omzo__user=request.user
        ).exclude(user=request.user).select_related('user', 'omzo').order_by('-created_at')[:20]

        for comment in omzo_comments:
            activity_items.append({
                'type': 'omzo_comment',
                'timestamp': comment.created_at,
                'user': {
                    'id': comment.user.id,
                    'username': comment.user.username,
                    'full_name': comment.user.full_name,
                    'profile_picture_url': comment.user.profile_picture_url,
                },
                'omzo': {
                    'id': comment.omzo.id,
                    'caption': comment.omzo.caption[:50] + '...' if comment.omzo.caption and len(comment.omzo.caption) > 50 else (comment.omzo.caption or 'Omzo'),
                },
                'comment_content': comment.content[:80] + '...' if len(comment.content) > 80 else comment.content,
            })

        # 8. Post Reports - Notify the user that they have been reported
        post_reports = PostReport.objects.filter(
            scribe__user=request.user
        ).select_related('reporter', 'scribe').order_by('-created_at')[:20]

        for report in post_reports:
            reason_display = report.get_reason_display()
            # Add copyright type info if applicable
            if report.reason == 'copyright' and report.copyright_type:
                reason_display = f"{reason_display} ({report.get_copyright_type_display()})"

            activity_items.append({
                'type': 'post_report',
                'timestamp': report.created_at,
                'user': {
                    'id': report.reporter.id,
                    'username': report.reporter.username,
                    'full_name': report.reporter.full_name,
                    'profile_picture_url': report.reporter.profile_picture_url,
                },
                'scribe': {
                    'id': report.scribe.id,
                    'content': report.scribe.content[:50] + '...' if len(report.scribe.content) > 50 else report.scribe.content,
                },
                'reason': reason_display,
            })

        # 9. Omzo Reports - Notify the user that they have been reported
        omzo_reports = OmzoReport.objects.filter(
            omzo__user=request.user
        ).select_related('reporter', 'omzo').order_by('-created_at')[:20]

        for report in omzo_reports:
            reason_display = report.get_reason_display()
            # Add copyright type info if applicable
            if report.reason == 'copyright' and report.copyright_type:
                reason_display = f"{reason_display} ({report.get_copyright_type_display()})"

            activity_items.append({
                'type': 'omzo_report',
                'timestamp': report.created_at,
                'user': {
                    'id': report.reporter.id,
                    'username': report.reporter.username,
                    'full_name': report.reporter.full_name,
                    'profile_picture_url': report.reporter.profile_picture_url,
                },
                'omzo': {
                    'id': report.omzo.id,
                    'caption': report.omzo.caption[:50] + '...' if len(report.omzo.caption) > 50 else report.omzo.caption,
                },
                'reason': reason_display,
            })

        # 10. My Reports - Content the current user reported (show for reporter)
        my_post_reports = PostReport.objects.filter(
            reporter=request.user
        ).select_related('scribe', 'scribe__user').order_by('-created_at')[:20]

        for report in my_post_reports:
            activity_items.append({
                'type': 'my_post_report',
                'timestamp': report.created_at,
                'user': {  # target content owner
                    'id': report.scribe.user.id,
                    'username': report.scribe.user.username,
                    'full_name': report.scribe.user.full_name,
                    'profile_picture_url': report.scribe.user.profile_picture_url,
                },
                'scribe': {
                    'id': report.scribe.id,
                    'content': report.scribe.content[:50] + '...' if len(report.scribe.content) > 50 else report.scribe.content,
                },
                'reason': report.get_reason_display(),
            })

        my_omzo_reports = OmzoReport.objects.filter(
            reporter=request.user
        ).select_related('omzo', 'omzo__user').order_by('-created_at')[:20]

        for report in my_omzo_reports:
            activity_items.append({
                'type': 'my_omzo_report',
                'timestamp': report.created_at,
                'user': {  # target content owner
                    'id': report.omzo.user.id,
                    'username': report.omzo.user.username,
                    'full_name': report.omzo.user.full_name,
                    'profile_picture_url': report.omzo.user.profile_picture_url,
                },
                'omzo': {
                    'id': report.omzo.id,
                    'caption': report.omzo.caption[:50] + '...' if len(report.omzo.caption) > 50 else report.omzo.caption,
                },
                'reason': report.get_reason_display(),
            })

        # 11. Profile Views (People who viewed MY profile)
        profile_views = ProfileView.objects.filter(
            viewed_user=request.user
        ).select_related('viewer').order_by('-viewed_at')[:20]

        for view in profile_views:
            activity_items.append({
                'type': 'profile_view',
                'timestamp': view.viewed_at,
                'user': {
                    'id': view.viewer.id,
                    'username': view.viewer.username,
                    'full_name': view.viewer.full_name,
                    'profile_picture_url': view.viewer.profile_picture_url,
                }
            })

        # Sort all activity by timestamp (newest first)
        activity_items.sort(key=lambda x: x['timestamp'], reverse=True)

        # Take top 50 items
        activity_items = activity_items[:50]

        # Add time_ago to each item
        now = timezone.now()
        for item in activity_items:
            item['time_ago'] = timesince(item['timestamp']) + ' ago'
            item['timestamp'] = item['timestamp'].isoformat()

        return Response({
            'success': True,
            'activity_items': activity_items
        })

    except Exception as e:
        logger.error(f"Error getting all activity: {str(e)}")
        import traceback
        traceback.print_exc()
        return Response({'success': False, 'error': 'Failed to get activity'})


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def get_profile_followers(request, username):
    """Get list of followers for a user profile"""
    try:
        user = get_object_or_404(CustomUser, username=username)

        # Get followers (people who follow this user)
        followers = Follow.objects.filter(
            following=user).select_related('follower')

        followers_data = []
        for follow in followers:
            follower = follow.follower
            followers_data.append({
                'id': follower.id,
                'username': follower.username,
                'full_name': follower.full_name,
                'avatar': follower.profile_picture_url,
                'is_following': Follow.objects.filter(
                    follower=request.user, following=follower
                ).exists() if request.user.is_authenticated else False
            })

        return Response({
            'success': True,
            'followers': followers_data
        })

    except Exception as e:
        logger.error(f"Error getting followers: {str(e)}")
        return Response({'success': False, 'error': 'Failed to get followers'})


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def get_profile_following(request, username):
    """Get list of users that a profile is following"""
    try:
        user = get_object_or_404(CustomUser, username=username)

        # Get following (people this user follows)
        following = Follow.objects.filter(
            follower=user).select_related('following')

        following_data = []
        for follow in following:
            followed_user = follow.following
            following_data.append({
                'id': followed_user.id,
                'username': followed_user.username,
                'full_name': followed_user.full_name,
                'avatar': followed_user.profile_picture_url,
                'is_following': Follow.objects.filter(
                    follower=request.user, following=followed_user
                ).exists() if request.user.is_authenticated else False
            })

        return Response({
            'success': True,
            'following': following_data
        })

    except Exception as e:
        logger.error(f"Error getting following: {str(e)}")
        return Response({'success': False, 'error': 'Failed to get following'})


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def omzo_view(request):
    """View to watch and scroll through omzo"""
    from chat.recommendations import ContentRecommender

    # Check if a specific omzo_id is requested
    specific_omzo_id = request.GET.get('omzo_id')

    # Use Recommendation Engine
    recommender = ContentRecommender(request.user)
    omzos = recommender.get_omzo(limit=50)

    # If specific omzo requested, move it to the front
    if specific_omzo_id:
        try:
            specific_omzo_id = int(specific_omzo_id)
            # Find and move the specific omzo to front
            specific_omzo = None
            remaining_omzos = []
            for omzo in omzos:
                if omzo.id == specific_omzo_id:
                    specific_omzo = omzo
                else:
                    remaining_omzos.append(omzo)

            # If specific omzo not in recommended list, fetch it separately
            if specific_omzo is None:
                try:
                    specific_omzo = Omzo.objects.get(id=specific_omzo_id)
                except Omzo.DoesNotExist:
                    pass

            # Put specific omzo first
            if specific_omzo:
                omzos = [specific_omzo] + remaining_omzos
            else:
                omzos = remaining_omzos
        except (ValueError, TypeError):
            pass

    # Process omzo for the frontend
    omzo_data = []
    for omzo in omzos:
        repost_count = Scribe.objects.filter(original_omzo=omzo).count()
        is_reposted = Scribe.objects.filter(
            user=request.user, original_omzo=omzo, quote_source__isnull=True).exists()
        is_saved = SavedOmzoItem.objects.filter(user=request.user, omzo=omzo).exists(
        ) if request.user.is_authenticated else False
        omzo_data.append({
            'id': omzo.id,
            'url': omzo.video_file.url,
            'caption': omzo.caption,
            'user': omzo.user,
            'likes': omzo.like_count,
            'comments_count': omzo.comment_count,
            'is_liked': omzo.is_liked_by(request.user),
            'views': omzo.views_count,
            'views': omzo.views_count,
            'timestamp': omzo.created_at,
            'reposts': repost_count,
            'is_reposted': is_reposted,
            'is_saved': is_saved,
            'is_following': Follow.objects.filter(follower=request.user, following=omzo.user).exists(),
        })

    return render(request, 'chat/Omzo.html', {
        'omzos': omzo_data,
        'initial_omzo_id': specific_omzo_id,
    })


def view_omzo(request, omzo_id):
    """
    View a single Omzo - accessible without login for sharing (like Instagram).
    Shows the Omzo in a proper UI with branding instead of just the raw video.
    """
    try:
        omzo = get_object_or_404(Omzo, id=omzo_id)

        # Get comments for this Omzo
        comments = omzo.comments.select_related(
            'user').order_by('-created_at')[:20]
        comments_data = [{
            'id': comment.id,
            'username': comment.user.username,
            'user_avatar': comment.user.profile_picture_url,
            'content': comment.content,
            'timestamp': comment.created_at,
        } for comment in comments]

        # For non-authenticated users, show a standalone Omzo detail page
        omzo_data = {
            'id': omzo.id,
            'url': omzo.video_file.url,
            'caption': omzo.caption,
            'user': omzo.user,
            'username': omzo.user.username,
            'user_avatar': omzo.user.profile_picture_url,
            'likes': omzo.like_count,
            'comments_count': omzo.comment_count,
            'views': omzo.views_count,
            'timestamp': omzo.created_at,
            'is_muted': omzo.is_muted,
        }

        # Get more Omzos from same user
        more_from_user = Omzo.objects.filter(
            user=omzo.user
        ).exclude(id=omzo_id).order_by('-created_at')[:6]

        more_from_user_data = [{
            'id': o.id,
            'url': o.video_file.url,
            'thumbnail': o.video_file.url,
            'caption': o.caption[:50] if o.caption else '',
            'likes': o.like_count,
            'comments_count': o.comment_count,
            'views': o.views_count,
        } for o in more_from_user]

        # Get suggested/explore Omzos (random popular ones)
        explore_omzos = Omzo.objects.exclude(
            id=omzo_id
        ).exclude(
            user=omzo.user
        ).order_by('-views_count', '-created_at')[:12]

        explore_data = [{
            'id': o.id,
            'url': o.video_file.url,
            'thumbnail': o.video_file.url,
            'caption': o.caption[:50] if o.caption else '',
            'username': o.user.username,
            'likes': o.like_count,
            'views': o.views_count,
        } for o in explore_omzos]

        # Check if authenticated safely
        is_authenticated = False
        try:
            is_authenticated = request.user.is_authenticated
        except:
            is_authenticated = False

        return render(request, 'chat/omzo_detail.html', {
            'omzo': omzo_data,
            'omzo_id': omzo_id,
            'comments': comments_data,
            'more_from_user': more_from_user_data,
            'explore_omzos': explore_data,
            'is_authenticated': is_authenticated,
        })

    except Omzo.DoesNotExist:
        # Omzo not found - redirect to home
        logger.error(f"Omzo {omzo_id} does not exist")
        return redirect('/')
    except Exception as e:
        import traceback
        logger.error(f"Error in view_omzo: {str(e)}")
        logger.error(traceback.format_exc())
        # On error, show a simple error page or redirect home
        return redirect('/')


def get_omzo_batch(request):
    """
    API endpoint for batch fetching omzos with cursor-based pagination.
    Used for preloading and infinite scroll.

    Query params:
        - cursor: ID of the last omzo seen (for pagination)
        - limit: Number of omzos to fetch (default 10, max 20)
        - exclude: Comma-separated list of omzo IDs to exclude (already loaded)

    Returns:
        - omzos: List of omzo data
        - next_cursor: ID to use for next batch (null if no more)
        - has_more: Boolean indicating if more omzos exist
        - total_available: Approximate count of remaining omzos
    """
    from chat.recommendations import ContentRecommender

    if not request.user.is_authenticated:
        return Response({
            'success': True,
            'omzos': [],
            'next_cursor': None,
            'has_more': False,
            'total_available': 0
        })

    try:
        cursor = request.GET.get('cursor')
        limit = min(int(request.GET.get('limit', 10)),
                    20)  # Max 20 per request
        exclude_ids_str = request.GET.get('exclude', '')

        # Parse excluded IDs
        exclude_ids = set()
        if exclude_ids_str:
            try:
                exclude_ids = set(int(x)
                                  for x in exclude_ids_str.split(',') if x.strip())
            except ValueError:
                pass

        # Use recommendation engine
        recommender = ContentRecommender(request.user)
        all_omzos = list(recommender.get_omzo(limit=100))  # Get larger pool

        # Filter out excluded omzos
        filtered_omzos = [o for o in all_omzos if o.id not in exclude_ids]

        # Apply cursor pagination
        if cursor:
            try:
                cursor_id = int(cursor)
                # Find position after cursor
                cursor_found = False
                temp_list = []
                for omzo in filtered_omzos:
                    if cursor_found:
                        temp_list.append(omzo)
                    elif omzo.id == cursor_id:
                        cursor_found = True
                filtered_omzos = temp_list if cursor_found else filtered_omzos
            except ValueError:
                pass

        # Get batch with limit
        batch = filtered_omzos[:limit]
        remaining = filtered_omzos[limit:]

        # Prepare response data
        omzo_data = []
        for omzo in batch:
            repost_count = Scribe.objects.filter(original_omzo=omzo).count()
            is_reposted = Scribe.objects.filter(
                user=request.user, original_omzo=omzo, quote_source__isnull=True).exists()
            is_saved = SavedOmzoItem.objects.filter(
                user=request.user, omzo=omzo).exists()

            # Build absolute URL for video
            video_url = request.build_absolute_uri(
                omzo.video_file.url) if omzo.video_file else None

            omzo_data.append({
                'id': omzo.id,
                'url': video_url,
                'video_url': video_url,
                'thumbnail_url': video_url,  # Use video URL as thumbnail
                'caption': omzo.caption,
                'username': omzo.user.username,
                'user_avatar': omzo.user.profile_picture_url,
                'likes': omzo.like_count,
                'comments_count': omzo.comment_count,
                'is_liked': omzo.is_liked_by(request.user),
                'is_disliked': OmzoDislike.objects.filter(user=request.user, omzo=omzo).exists(),
                'views': omzo.views_count,
                'is_muted': omzo.is_muted,
                'is_saved': is_saved,
                'is_following': Follow.objects.filter(follower=request.user, following=omzo.user).exists(),
                'reposts': repost_count,
                'is_reposted': is_reposted,
            })

        # Determine next cursor and has_more
        next_cursor = batch[-1].id if batch and remaining else None
        has_more = len(remaining) > 0

        return Response({
            'success': True,
            'data': omzo_data,
            'next_cursor': next_cursor,
            'has_more': has_more,
            'total_available': len(remaining),
            'batch_size': len(batch)
        })

    except Exception as e:
        logger.error(f"Error in get_omzo_batch: {str(e)}")
        return Response({
            'success': False,
            'error': 'Failed to fetch omzos',
            'omzos': [],
            'has_more': False
        })


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def track_omzo_view(request):
    """API endpoint to track when a user watches a specific omzo"""
    try:
        data = json.loads(request.body)

        omzo_id = data.get('omzo_id') or data.get('omzo_id')
        if not omzo_id:
            return Response({'error': 'omzo_id required'}, status=400)
        omzo = get_object_or_404(Omzo, id=omzo_id)

        # Increment view count only for this omzo
        omzo.views_count += 1
        omzo.save(update_fields=['views_count'])

        return Response({
            'status': 'success',
            'views': omzo.views_count
        })
    except json.JSONDecodeError:
        return Response({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Error tracking omzo view: {str(e)}")
        return Response({'error': str(e)}, status=500)


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def upload_omzo(request):
    """API to upload a new omzo with compression"""
    # CHECK DAILY LIMIT (5 Omzo per day)
    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_count = Omzo.objects.filter(
        user=request.user,
        created_at__gte=today_start
    ).count()

    if today_count >= 5:
        return Response({
            'success': False,
            'error': 'Daily omzo limit reached. You can upload up to 5 Omzo per day. Try again tomorrow!'
        })

    try:
        video_file = request.FILES.get('video')
        caption = request.POST.get('caption', '')

        if not video_file:
            return Response({'success': False, 'error': 'No video provided'})

        # SECURITY CHECK (Magic Bytes)
        try:
            from chat.security import validate_media_file
            if video_file:
                validate_media_file(video_file)
        except ValidationError as e:
            return Response({'success': False, 'error': str(e)})

        # Use new FFmpeg compression utility
        from chat.utils import compress_video

        # Compress the video (returns original if fails or is small enough)
        # We target CRF 32 for good balance of size/quality
        compressed_video = compress_video(video_file)

        # Create Omzo
        omzo = Omzo.objects.create(
            user=request.user,
            video_file=compressed_video,
            caption=caption
        )

        return Response({'success': True, 'message': 'Omzo uploaded successfully'})

    except Exception as e:
        logger.error(f"Error uploading omzo: {str(e)}")
        return Response({'success': False, 'error': str(e)}, status=500)
    except Exception as e:
        logger.error(f"Error uploading omzo: {str(e)}")
        return Response({'success': False, 'error': f'Failed to upload omzo: {str(e)}'})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def toggle_omzo_like(request):
    """API to like/unlike a omzo"""
    try:
        data = json.loads(request.body)
        omzo_id = data.get('omzo_id')
        omzo = get_object_or_404(Omzo, id=omzo_id)

        # Remove dislike if exists
        OmzoDislike.objects.filter(omzo=omzo, user=request.user).delete()

        like = OmzoLike.objects.filter(omzo=omzo, user=request.user).first()
        if like:
            like.delete()
            is_liked = False
        else:
            OmzoLike.objects.create(omzo=omzo, user=request.user)
            is_liked = True

            # Send Notification if not self-like
            if request.user.id != omzo.user.id:
                channel_layer = get_channel_layer()
                async_to_sync(channel_layer.group_send)(
                    f'user_notify_{omzo.user.id}',
                    {
                        'type': 'notify.omzo_like',
                        'omzo_id': omzo.id,
                        'user_id': request.user.id,
                        'user_name': request.user.full_name or request.user.username,
                        'user_avatar': request.user.profile_picture.url if request.user.profile_picture else None,
                        'timestamp': timezone.now().isoformat()
                    }
                )

        return Response({
            'success': True,
            'is_liked': is_liked,
            'is_disliked': False,  # Always false since we removed dislike
            'like_count': omzo.like_count,
            'dislike_count': omzo.dislike_count
        })
    except Exception as e:
        logger.error(f"Error toggling omzo like: {str(e)}")
        return Response({'success': False, 'error': 'Action failed'})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def toggle_omzo_dislike(request):
    """API to dislike/undislike a omzo"""
    try:
        data = json.loads(request.body)
        omzo_id = data.get('omzo_id')
        omzo = get_object_or_404(Omzo, id=omzo_id)

        # Remove like if exists
        OmzoLike.objects.filter(omzo=omzo, user=request.user).delete()

        dislike = OmzoDislike.objects.filter(
            omzo=omzo, user=request.user).first()
        if dislike:
            dislike.delete()
            is_disliked = False
        else:
            OmzoDislike.objects.create(omzo=omzo, user=request.user)
            is_disliked = True

        return Response({
            'success': True,
            'is_liked': False,  # Always false since we removed like
            'is_disliked': is_disliked,
            'like_count': omzo.like_count,
            'dislike_count': omzo.dislike_count
        })
    except Exception as e:
        logger.error(f"Error toggling omzo dislike: {str(e)}")
        return Response({'success': False, 'error': 'Action failed'})


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def get_omzo_comments(request, omzo_id):
    """Return comments for a omzo (latest first)."""
    try:
        omzo = get_object_or_404(Omzo, id=omzo_id)
        limit = int(request.GET.get('limit', 20))
        offset = int(request.GET.get('offset', 0))

        qs = OmzoComment.objects.filter(omzo=omzo).select_related(
            'user').order_by('-created_at')
        total = qs.count()
        comments = []
        for rc in qs[offset:offset+limit]:
            comments.append({
                'id': rc.id,
                'content': rc.content,
                'created_at': rc.created_at.isoformat(),
                'user': {
                    'id': rc.user.id,
                    'username': rc.user.username,
                    'full_name': rc.user.full_name,
                    'avatar': rc.user.profile_picture_url,
                    'initials': rc.user.initials,
                }
            })

        return Response({
            'success': True,
            'total': total,
            'comments': comments,
        })
    except Exception as e:
        logger.error(f"Error getting omzo comments: {str(e)}")
        return Response({'success': False, 'error': 'Failed to load comments'})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def add_omzo_comment(request):
    """Add a comment to a omzo."""
    try:
        data = json.loads(request.body)
        omzo_id = data.get('omzo_id') or data.get('omzo_id')
        content = (data.get('content') or '').strip()

        if not omzo_id:
            return Response({'success': False, 'error': 'omzo_id required'}, status=400)
        if not content:
            return Response({'success': False, 'error': 'Comment cannot be empty'}, status=400)
        if len(content) > 500:
            return Response({'success': False, 'error': 'Comment too long (max 500)'}, status=400)

        omzo = get_object_or_404(Omzo, id=omzo_id)
        rc = OmzoComment.objects.create(
            omzo=omzo, user=request.user, content=content)

        # Send Notification if not self-comment
        if request.user.id != omzo.user.id:
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f'user_notify_{omzo.user.id}',
                {
                    'type': 'notify.omzo_comment',
                    'omzo_id': omzo.id,
                    'comment_id': rc.id,
                    'user_id': request.user.id,
                    'user_name': request.user.full_name or request.user.username,
                    'user_avatar': request.user.profile_picture.url if request.user.profile_picture else None,
                    'comment_content': content[:100],
                    'timestamp': timezone.now().isoformat()
                }
            )

        return Response({
            'success': True,
            'comment': {
                'id': rc.id,
                'content': rc.content,
                'created_at': rc.created_at.isoformat(),
                'user': {
                    'id': request.user.id,
                    'username': request.user.username,
                    'full_name': request.user.full_name,
                    'avatar': request.user.profile_picture_url,
                    'initials': request.user.initials,
                }
            },
            'comments_count': omzo.comment_count,
        })
    except json.JSONDecodeError:
        return Response({'success': False, 'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Error adding omzo comment: {str(e)}")
        return Response({'success': False, 'error': 'Failed to add comment'})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def report_omzo(request):
    """Report a omzo for inappropriate content"""
    try:
        data = json.loads(request.body)
        omzo_id = data.get('omzo_id') or data.get('omzo_id')
        reason = data.get('reason')
        description = data.get('description', '').strip()
        copyright_description = data.get('copyright_description', '').strip()
        copyright_type = data.get('copyright_type', '').strip()
        disable_audio = data.get('disable_audio', False)

        if not omzo_id or not reason:
            return Response({'success': False, 'error': 'Omzo ID and reason are required'})

        valid_reasons = ['spam', 'inappropriate', 'harassment',
                         'violence', 'hate_speech', 'false_info', 'copyright', 'other']
        if reason not in valid_reasons:
            return Response({'success': False, 'error': 'Invalid report reason'})

        try:
            omzo = Omzo.objects.get(id=omzo_id)
        except Omzo.DoesNotExist:
            return Response({'success': False, 'error': 'Omzo not found'})

        # Can't report your own Omzo
        if omzo.user == request.user:
            return Response({'success': False, 'error': 'You cannot report your own Omzo'})

        # Check if already reported by this user
        existing_report = OmzoReport.objects.filter(
            reporter=request.user, omzo=omzo).first()
        if existing_report:
            return Response({'success': False, 'error': 'You have already reported this Omzo'})

        # Validate copyright_type if reason is copyright
        if reason == 'copyright':
            valid_copyright_types = ['audio', 'content', 'both']
            if copyright_type and copyright_type not in valid_copyright_types:
                return Response({'success': False, 'error': 'Invalid copyright type'})

        # Create the report
        report = OmzoReport.objects.create(
            reporter=request.user,
            omzo=omzo,
            reason=reason,
            description=description,
            copyright_description=copyright_description if reason == 'copyright' else None,
            copyright_type=copyright_type if reason == 'copyright' else None,
            disable_audio=disable_audio
        )

        # Send Notification to the reported user
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f'user_notify_{omzo.user.id}',
            {
                'type': 'notify.report_omzo',  # New type
                'omzo_id': omzo.id,
                'reporter_id': request.user.id,
                'reason': reason,
                'timestamp': timezone.now().isoformat()
            }
        )

        # If disable_audio is checked, mute the omzo
        if disable_audio:
            omzo.is_muted = True
            omzo.save()

        return Response({
            'success': True,
            'message': 'Thank you for your report. We will review it shortly.'
        })

    except Exception as e:
        logger.error(f"Error in report_omzo: {str(e)}")
        return Response({'success': False, 'error': 'Failed to report omzo'})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def toggle_save_scribe(request):
    """Toggle save status for a scribe"""
    try:
        data = json.loads(request.body)
        scribe_id = data.get('scribe_id')

        if not scribe_id:
            return Response({'success': False, 'error': 'Scribe ID is required'})

        try:
            scribe = Scribe.objects.get(id=scribe_id)
        except Scribe.DoesNotExist:
            return Response({'success': False, 'error': 'Scribe not found'})

        from chat.models import SavedScribeItem
        saved_obj = SavedScribeItem.objects.filter(
            user=request.user, scribe=scribe).first()

        if saved_obj:
            saved_obj.delete()
            is_saved = False
        else:
            SavedScribeItem.objects.create(user=request.user, scribe=scribe)
            is_saved = True

        return Response({
            'success': True,
            'is_saved': is_saved
        })

    except Exception as e:
        logger.error(f"Error in toggle_save_scribe: {str(e)}")
        return Response({'success': False, 'error': 'Failed to toggle save'})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def toggle_save_omzo(request):
    """Toggle save status for an omzo"""
    try:
        data = json.loads(request.body)
        omzo_id = data.get('omzo_id')

        if not omzo_id:
            return Response({'success': False, 'error': 'Omzo ID is required'})

        try:
            omzo = Omzo.objects.get(id=omzo_id)
        except Omzo.DoesNotExist:
            return Response({'success': False, 'error': 'Omzo not found'})

        from chat.models import SavedOmzoItem
        saved_obj = SavedOmzoItem.objects.filter(
            user=request.user, omzo=omzo).first()

        if saved_obj:
            saved_obj.delete()
            is_saved = False
        else:
            SavedOmzoItem.objects.create(user=request.user, omzo=omzo)
            is_saved = True

        return Response({
            'success': True,
            'is_saved': is_saved
        })

    except Exception as e:
        logger.error(f"Error in toggle_save_omzo: {str(e)}")
        return Response({'success': False, 'error': 'Failed to toggle save'})


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def get_saved_items(request):
    """Get all saved items (scribes and omzos) for the current user"""
    try:
        from chat.models import SavedScribeItem, SavedOmzoItem

        # Get saved scribes
        saved_scribes = SavedScribeItem.objects.filter(
            user=request.user).select_related('scribe__user')
        scribes_data = []

        for saved in saved_scribes:
            scribe = saved.scribe
            # Detect type correctly
            ctype = scribe.content_type
            detected_type = 'image' if (scribe.image and (
                not ctype or ctype == 'text')) else (ctype or 'text')

            scribes_data.append({
                'id': scribe.id,
                'type': 'scribe',
                'content': scribe.content,
                'media_type': detected_type,
                'image_url': scribe.image_url,
                'user': {
                    'id': scribe.user.id,
                    'username': scribe.user.username,
                    'full_name': scribe.user.full_name,
                    'profile_picture_url': scribe.user.profile_picture_url,
                    'is_verified': scribe.user.is_verified,
                },
                'likes': scribe.scribe_likes.count(),
                'dislikes': scribe.scribe_dislikes.count(),
                'comments': scribe.comments.count(),
                'reposts': scribe.reposts.count(),
                'code_html': getattr(scribe, 'code_html', ''),
                'code_css': getattr(scribe, 'code_css', ''),
                'code_js': getattr(scribe, 'code_js', ''),
                'saved_at': saved.saved_at.isoformat(),
                'created_at': scribe.timestamp.isoformat(),
            })

        # Get saved omzos
        saved_omzos = SavedOmzoItem.objects.filter(
            user=request.user).select_related('omzo__user')
        omzos_data = []

        for saved in saved_omzos:
            omzo = saved.omzo
            repost_count = Scribe.objects.filter(original_omzo=omzo).count()
            is_reposted = Scribe.objects.filter(
                user=request.user, original_omzo=omzo, quote_source__isnull=True).exists()

            # Build absolute URL for video
            video_url = None
            if omzo.video_file:
                video_url = request.build_absolute_uri(omzo.video_file.url)

            omzos_data.append({
                'id': omzo.id,
                'type': 'omzo',
                'caption': omzo.caption,
                'video_url': video_url,
                'thumbnail_url': video_url,  # Use video URL as thumbnail
                'user': {
                    'id': omzo.user.id,
                    'username': omzo.user.username,
                    'full_name': omzo.user.full_name,
                    'profile_picture_url': omzo.user.profile_picture_url,
                    'is_verified': omzo.user.is_verified,
                },
                'likes': omzo.likes.count(),
                'dislikes': omzo.dislikes.count(),
                'views': omzo.views_count,
                'comments': omzo.comments.count(),
                'shares': 0,  # Omzo model doesn't seem to have shares?
                'saved_at': saved.saved_at.isoformat(),
                'reposts': repost_count,
                'is_reposted': is_reposted,
                'created_at': omzo.created_at.isoformat(),
            })

        # Combine and sort by saved_at
        all_saved = scribes_data + omzos_data
        all_saved.sort(key=lambda x: x['saved_at'], reverse=True)

        return Response({
            'success': True,
            'saved_items': all_saved,
            'count': len(all_saved)
        })

    except Exception as e:
        logger.error(f"Error in get_saved_items: {str(e)}")
        return Response({'success': False, 'error': f'Failed to fetch saved items: {str(e)}'})
