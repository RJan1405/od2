from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.utils.timesince import timesince
import json
import os
import logging
from chat.models import CustomUser, Story, StoryView, StoryLike, StoryReply, Chat, Message
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import TokenAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser

logger = logging.getLogger(__name__)


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def repost_story(request):
    """
    Repost someone else's story to your own story (Instagram-style).
    Creates a new Story that references the original, auto-expires after 24hrs.
    """
    try:
        data = request.data
        original_story_id = data.get('story_id')

        if not original_story_id:
            return Response({'success': False, 'error': 'Story ID is required'})

        # Get the original story (could itself be a repost)
        original_story = get_object_or_404(
            Story,
            id=original_story_id,
            is_active=True,
            expires_at__gt=timezone.now()
        )

        # If the story is already a repost of another, always repost the root/original story.
        root_story = original_story.shared_from_story or original_story

        # Can't repost your own story
        if root_story.user == request.user:
            return Response({'success': False, 'error': "You can't repost your own story"})

        # Check if user already reposted this root story (prevent duplicates / repost-of-repost)
        existing_repost = Story.objects.filter(
            user=request.user,
            shared_from_story=root_story,
            is_active=True,
            expires_at__gt=timezone.now()
        ).exists()

        if existing_repost:
            return Response({'success': False, 'error': 'You already reposted this story'})

        # Create a new story that references the root/original story
        # The repost inherits the original's media but adds "Reposted from @username" context
        repost_story = Story.objects.create(
            user=request.user,
            content=root_story.content,  # Copy original content
            media_file=root_story.media_file.name if root_story.media_file else None,
            story_type=root_story.story_type,
            background_color=root_story.background_color,
            text_color=root_story.text_color,
            text_position=root_story.text_position,
            text_size=root_story.text_size,
            image_transform=root_story.image_transform,
            shared_from_story=root_story,  # Link to root original
            # expires_at automatically set to 24 hours from now
        )

        logger.info(
            f"Story {root_story.id} reposted by {request.user.username} as story {repost_story.id}")

        # Send chat notification to original story owner
        if root_story.user != request.user:
            # Get or create DM chat between reposter and original story owner
            chat = Chat.objects.filter(
                chat_type='private',
                participants=root_story.user
            ).filter(
                participants=request.user
            ).first()

            if not chat:
                chat = Chat.objects.create(chat_type='private')
                chat.participants.add(request.user, root_story.user)

            # Create notification message
            message_content = f"🔄 {request.user.full_name} reposted your story"
            message = Message.objects.create(
                chat=chat,
                sender=request.user,
                content=message_content,
                message_type='text'
            )

            # Update chat timestamp
            chat.updated_at = timezone.now()
            chat.save()

            # Broadcast to story owner via WebSocket
            from chat.views.chat import broadcast_message_to_chat
            broadcast_message_to_chat(chat, message, exclude_sender=True)

        return Response({
            'success': True,
            'message': 'Story reposted successfully!',
            'story': {
                'id': repost_story.id,
                'content': repost_story.content,
                'media_url': repost_story.media_url,
                'story_type': repost_story.story_type,
                'shared_from': {
                    'id': original_story.id,
                    'user': {
                        'id': root_story.user.id,
                        'username': root_story.user.username,
                        'full_name': root_story.user.full_name,
                        'profile_picture_url': root_story.user.profile_picture_url,
                    }
                }
            }
        })

    except json.JSONDecodeError:
        return Response({'success': False, 'error': 'Invalid JSON data'})
    except Exception as e:
        logger.error(f"Error reposting story: {e}")
        return Response({'success': False, 'error': str(e)})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def create_story(request):
    """FIXED - Create a new story - NOW SUPPORTS MULTIPLE STORIES PER USER AND IMAGE+TEXT COMBO"""
    try:
        story_type = request.data.get('story_type', 'text')
        content = request.data.get('content', '').strip()
        background_color = request.data.get('background_color', '#667eea')
        text_color = request.data.get('text_color', '#ffffff')
        text_position = request.data.get('text_position', 'center')
        text_size_val = request.data.get('text_size', '22')
        try:
            text_size = float(text_size_val)
        except (ValueError, TypeError):
            text_size = 22.0

        image_transform_json = request.data.get('image_transform', '{}')
        try:
            if isinstance(image_transform_json, str):
                image_transform = json.loads(image_transform_json)
            else:
                image_transform = image_transform_json
        except:
            image_transform = {}

        media_file = request.data.get('media')

        logger.info(
            f"Creating story: type={story_type}, content={content}, has_media={bool(media_file)}, text_position={text_position}")

        # Validate text_position
        if text_position not in ['top', 'center', 'bottom']:
            text_position = 'center'

        # Handle media file - determine type from file
        if media_file:
            file_extension = os.path.splitext(media_file.name)[1].lower()
            if file_extension in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
                story_type = 'image'
            elif file_extension in ['.mp4', '.mov', '.avi', '.mkv', '.webm']:
                story_type = 'video'
            else:
                return Response({'success': False, 'error': 'Invalid file type. Supported: jpg, png, gif, webp, mp4, mov, avi, mkv, webm'})

        # Validation - need either content or media
        if not content and not media_file:
            return Response({'success': False, 'error': 'Please add text or an image'})

        # Compress video if applicable
        if media_file and story_type == 'video':
            try:
                from chat.utils import compress_video
                # Compress video (crf=32 for better size)
                media_file = compress_video(media_file)
            except Exception as e:
                logger.error(f"Story video compression failed: {e}")
                # Continue with original file

        # FIXED: DON'T deactivate previous stories - allow multiple stories
        # REMOVED: Story.objects.filter(user=request.user, is_active=True).update(is_active=False)

        # Create new story WITHOUT deactivating previous ones
        story = Story.objects.create(
            user=request.user,
            content=content,  # Can be empty for image-only stories
            media_file=media_file,
            story_type=story_type,
            background_color=background_color,
            text_color=text_color,
            text_position=text_position,
            text_size=text_size,
            image_transform=image_transform,
            # is_active=True by default from model
            # expires_at set automatically by model (24 hours from now)
        )

        logger.info(f"Story created successfully: {story.id}")

        return Response({
            'success': True,
            'story': {
                'id': story.id,
                'content': story.content,
                'media_url': story.media_url,
                'story_type': story.story_type,
                'background_color': story.background_color,
                'text_color': story.text_color,
                'text_position': story.text_position,
                'text_size': story.text_size,
                'image_transform': story.image_transform,
            }
        })

    except Exception as e:
        logger.error(f"Error creating story: {e}")
        return Response({'success': False, 'error': str(e)})


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def view_story(request, story_id):
    """View a specific story"""
    try:
        story = get_object_or_404(
            Story,
            id=story_id,
            is_active=True,
            expires_at__gt=timezone.now()
        )

        # Add view if not already viewed
        if not story.story_views.filter(viewer=request.user).exists():
            StoryView.objects.create(story=story, viewer=request.user)

        # Build shared_from info if this is a repost
        shared_from = None
        if story.shared_from_story:
            original = story.shared_from_story
            shared_from = {
                'id': original.id,
                'user': {
                    'id': original.user.id,
                    'username': original.user.username,
                    'full_name': original.user.full_name,
                    'profile_picture_url': original.user.profile_picture_url,
                },
                'is_expired': original.is_expired,
            }

        return Response({
            'success': True,
            'story': {
                'id': story.id,
                'content': story.content,
                'media_url': story.media_url,
                'story_type': story.story_type,
                'background_color': story.background_color,
                'text_color': story.text_color,
                'text_position': story.text_position,
                'text_size': story.text_size,
                'image_transform': story.image_transform,
                'user': {
                    'id': story.user.id,
                    'username': story.user.username,
                    'full_name': story.user.full_name,
                    'profile_picture_url': story.user.profile_picture_url,
                },
                'created_at': story.created_at.strftime('%H:%M'),
                'view_count': story.view_count,
                'like_count': story.like_count,
                'reply_count': story.reply_count,
                'is_liked': story.story_likes.filter(user=request.user).exists(),
                'user_has_replied': story.story_replies.filter(replier=request.user).exists(),
                'shared_from': shared_from,
                'is_repost': story.shared_from_story is not None,
            }
        })

    except Exception as e:
        logger.error(f"Error viewing story: {e}")
        return Response({'success': False, 'error': str(e)})

# NEW: API endpoint to get all stories for a user (for multiple story viewing)


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def get_user_stories(request, username):
    """Get all active stories for a specific user"""
    try:
        if username == 'me':
            user = request.user
        else:
            user = get_object_or_404(CustomUser, username=username)

        # Get all active stories for this user
        stories = Story.objects.filter(
            user=user,
            is_active=True,
            expires_at__gt=timezone.now()
        ).order_by('-created_at')

        stories_data = []
        for story in stories:
            # Mark as viewed if not already
            if not story.story_views.filter(viewer=request.user).exists():
                StoryView.objects.create(story=story, viewer=request.user)

            # Build shared_from info if this is a repost
            shared_from = None
            if story.shared_from_story:
                original = story.shared_from_story
                shared_from = {
                    'id': original.id,
                    'user': {
                        'id': original.user.id,
                        'username': original.user.username,
                        'full_name': original.user.full_name,
                        'profile_picture_url': original.user.profile_picture_url,
                    },
                    'is_expired': original.is_expired,
                }

            stories_data.append({
                'id': story.id,
                'content': story.content,
                'media_url': story.media_url,
                'story_type': story.story_type,
                'background_color': story.background_color,
                'text_color': story.text_color,
                'text_position': story.text_position,
                'text_size': story.text_size,
                'image_transform': story.image_transform,
                'user': {
                    'id': story.user.id,
                    'username': story.user.username,
                    'full_name': story.user.full_name,
                    'profile_picture_url': story.user.profile_picture_url,
                },
                'created_at': story.created_at.isoformat(),
                'view_count': story.view_count,
                'like_count': story.like_count,
                'reply_count': story.reply_count,
                'is_liked': story.story_likes.filter(user=request.user).exists(),
                'user_has_replied': story.story_replies.filter(replier=request.user).exists(),
                'shared_from': shared_from,
                'is_repost': story.shared_from_story is not None,
            })

        return Response({
            'success': True,
            'stories': stories_data
        })

    except Exception as e:
        logger.error(f"Error getting user stories: {e}")
        return Response({'success': False, 'error': str(e)})


@api_view(['GET'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def get_following_stories(request):
    """Get stories from all users that the current user follows (Instagram-style feed)"""
    if not request.user.is_authenticated:
        return Response({'success': True, 'users': []})

    try:
        from chat.models import Follow

        # Get all users the current user is following
        following_users = Follow.objects.filter(
            follower=request.user
        ).values_list('following', flat=True)

        # Get all active stories from followed users AND the current user's own stories
        user_ids = list(following_users)
        user_ids.append(request.user.id)  # Include current user's own stories

        stories = Story.objects.filter(
            user_id__in=user_ids,
            is_active=True,
            expires_at__gt=timezone.now()
        ).select_related('user').order_by('user', '-created_at')

        # Group stories by user
        users_with_stories = {}
        for story in stories:
            user_id = story.user.id
            if user_id not in users_with_stories:
                # Check if user has any unviewed stories
                has_unviewed = not story.story_views.filter(
                    viewer=request.user).exists()

                users_with_stories[user_id] = {
                    'user': {
                        'id': story.user.id,
                        'username': story.user.username,
                        'full_name': story.user.full_name,
                        'profile_picture_url': story.user.profile_picture_url,
                        'is_verified': story.user.is_verified,
                    },
                    'stories': [],
                    'has_unviewed': has_unviewed,
                    'story_count': 0
                }

            # Build shared_from info if this is a repost
            shared_from = None
            if story.shared_from_story:
                original = story.shared_from_story
                shared_from = {
                    'id': original.id,
                    'user': {
                        'id': original.user.id,
                        'username': original.user.username,
                        'full_name': original.user.full_name,
                        'profile_picture_url': original.user.profile_picture_url,
                    },
                    'is_expired': original.is_expired,
                }

            users_with_stories[user_id]['stories'].append({
                'id': story.id,
                'content': story.content,
                'media_url': story.media_url,
                'story_type': story.story_type,
                'background_color': story.background_color,
                'text_color': story.text_color,
                'text_position': story.text_position,
                'text_size': story.text_size,
                'image_transform': story.image_transform,
                'created_at': story.created_at.isoformat(),
                'view_count': story.view_count,
                'like_count': story.like_count,
                'reply_count': story.reply_count,
                'is_liked': story.story_likes.filter(user=request.user).exists(),
                'is_viewed': story.story_views.filter(viewer=request.user).exists(),
                'shared_from': shared_from,
                'is_repost': story.shared_from_story is not None,
            })
            users_with_stories[user_id]['story_count'] += 1

        # Convert to list
        stories_feed = []
        for user_id, data in users_with_stories.items():
            is_own = user_id == request.user.id
            stories_feed.append({
                **data,
                'is_own': is_own
            })

        # Ensure current user is always in the feed (for the "Add Story" button)
        if request.user.id not in users_with_stories:
            stories_feed.append({
                'user': {
                    'id': request.user.id,
                    'username': request.user.username,
                    'full_name': request.user.full_name,
                    'profile_picture_url': request.user.profile_picture_url,
                    'is_verified': getattr(request.user, 'is_verified', False),
                },
                'stories': [],
                'has_unviewed': False,
                'story_count': 0,
                'is_own': True
            })

        # Sort: own stories first, then unviewed, then viewed
        stories_feed.sort(key=lambda x: (
            not x.get('is_own', False), not x.get('has_unviewed', False)))

        return Response({
            'success': True,
            'users_with_stories': stories_feed,
            'total_users': len(stories_feed)
        })

    except Exception as e:
        logger.error(f"Error getting following stories: {e}")
        return Response({'success': False, 'error': str(e)})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def mark_story_viewed(request):
    """Mark a story as viewed by the current user"""
    try:
        data = request.data
        story_id = data.get('story_id')

        if not story_id:
            return Response({'success': False, 'error': 'Story ID is required'})

        story = get_object_or_404(Story, id=story_id)

        # Create or update view record
        view, created = StoryView.objects.get_or_create(
            story=story,
            viewer=request.user,
            defaults={'viewed_at': timezone.now()}
        )

        if not created:
            # Update timestamp if already viewed
            view.viewed_at = timezone.now()
            view.save()

        return Response({
            'success': True,
            'view_count': story.view_count
        })

    except Exception as e:
        logger.error(f"Error in mark_story_viewed: {str(e)}")
        return Response({'success': False, 'error': 'Failed to mark story as viewed'})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def toggle_story_like(request):
    """Toggle like on a story"""
    try:
        data = request.data
        story_id = data.get('story_id')

        if not story_id:
            return Response({'success': False, 'error': 'Story ID is required'})

        story = get_object_or_404(Story, id=story_id)

        # Toggle like
        like_obj, created = StoryLike.objects.get_or_create(
            story=story,
            user=request.user
        )

        if not created:
            # Unlike if already liked
            like_obj.delete()
            is_liked = False
        else:
            is_liked = True

            # Send chat notification to story owner (only when liking, not unliking)
            if story.user != request.user:
                try:
                    # Get or create DM chat between liker and story owner
                    chat = Chat.objects.filter(
                        chat_type='private',
                        participants=story.user
                    ).filter(
                        participants=request.user
                    ).first()

                    if not chat:
                        chat = Chat.objects.create(chat_type='private')
                        chat.participants.add(request.user, story.user)

                    # Create notification message
                    message = Message.objects.create(
                        chat=chat,
                        sender=request.user,
                        content="❤️",
                        message_type='text',
                        story_reply=story
                    )

                    # Update chat timestamp
                    chat.updated_at = timezone.now()
                    chat.save()

                    # Broadcast to story owner via WebSocket
                    from chat.views.chat import broadcast_message_to_chat
                    broadcast_message_to_chat(
                        chat, message, exclude_sender=True)
                except Exception as e:
                    # Log error but DON'T fail the like action
                    print(f"ERROR sending like notification: {e}")
                    logger.error(f"Failed to send like notification: {e}")

        like_count = story.like_count

        return Response({
            'success': True,
            'is_liked': is_liked,
            'like_count': like_count
        })

    except Exception as e:
        logger.error(f"Error in toggle_story_like: {str(e)}")
        # Force print to console
        print(f"DEBUG ERROR in toggle_story_like: {str(e)}")
        return Response({'success': False, 'error': f'Failed to toggle story like: {str(e)}'})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def add_story_reply(request):
    """Add a reply to a story (only visible to story poster)"""
    try:
        data = request.data
        story_id = data.get('story_id')
        content = data.get('content', '').strip()

        if not story_id:
            return Response({'success': False, 'error': 'Story ID is required'}, status=400)

        if not content:
            return Response({'success': False, 'error': 'Reply content is required'})

        if len(content) > 500:
            return Response({'success': False, 'error': 'Reply content too long (max 500 characters)'})

        story = get_object_or_404(Story, id=story_id)

        # Create the reply
        reply = StoryReply.objects.create(
            story=story,
            replier=request.user,
            content=content
        )

        # Send reply as chat message to story owner (best effort)
        if story.user != request.user:
            try:
                # Get or create DM chat between replier and story owner
                chat = Chat.objects.filter(
                    chat_type='private',
                    participants=story.user
                ).filter(
                    participants=request.user
                ).first()

                if not chat:
                    chat = Chat.objects.create(chat_type='private')
                    chat.participants.add(request.user, story.user)

                # Create message with story context
                message = Message.objects.create(
                    chat=chat,
                    sender=request.user,
                    content=content,
                    message_type='text',
                    story_reply=story  # Link to the story
                )

                # Update chat timestamp
                chat.updated_at = timezone.now()
                chat.save()

                # Broadcast to story owner via WebSocket with story metadata
                from chat.views.chat import broadcast_message_to_chat
                from channels.layers import get_channel_layer
                from asgiref.sync import async_to_sync

                channel_layer = get_channel_layer()
                async_to_sync(channel_layer.group_send)(
                    f'chat_{chat.id}',
                    {
                        'type': 'message.new',
                        'message': {
                            'id': message.id,
                            'content': message.content,
                            'sender_id': message.sender_id,
                            'sender_name': message.sender.full_name,
                            'sender_avatar': message.sender.profile_picture_url,
                            'timestamp': message.timestamp.strftime('%H:%M'),
                            'timestamp_iso': message.timestamp.isoformat(),
                            'message_type': message.message_type,
                            'is_read': message.is_read,
                            'is_own': False,  # For the receiver
                            # Story metadata for reply context
                            'story_reply': {
                                'story_id': story.id,
                                'story_type': story.story_type,
                                'story_content': story.content if story.story_type == 'text' else None,
                                'story_media_url': story.media_url if story.story_type in ['image', 'video'] else None,
                                'story_owner': story.user.full_name,
                            }
                        }
                    }
                )
            except Exception as e:
                # Log error but don't fail the reply creation
                logger.error(f"Failed to send chat message for reply: {e}")
                # Return the error to the frontend so we know what happened
                return Response({
                    'success': True,
                    'reply_id': reply.id,
                    'reply_count': story.reply_count,
                    'message_error': str(e)  # Pass the error back
                })

        return Response({
            'success': True,
            'reply_id': reply.id,
            'reply_count': story.reply_count
        })

    except Exception as e:
        logger.error(f"Error in add_story_reply: {str(e)}")
        print(f"DEBUG ERROR in add_story_reply: {str(e)}")
        return Response({'success': False, 'error': f'Failed to add story reply: {str(e)}'})


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def get_story_replies(request, story_id):
    """Get replies for a story (for story poster or reply author)"""
    try:
        story = get_object_or_404(Story, id=story_id)

        # Allow story poster OR users who have replied to see replies
        if story.user != request.user and not story.story_replies.filter(replier=request.user).exists():
            return Response({'success': False, 'error': 'Unauthorized'})

        replies = story.story_replies.select_related(
            'replier').order_by('created_at')

        replies_data = []
        for reply in replies:
            replies_data.append({
                'id': reply.id,
                'replier': {
                    'id': reply.replier.id,
                    'username': reply.replier.username,
                    'full_name': reply.replier.full_name,
                    'profile_picture_url': reply.replier.profile_picture_url
                },
                'content': reply.content,
                'created_at': reply.created_at.isoformat(),
                'is_read': reply.is_read,
            })        # Mark replies as read
        story.story_replies.filter(is_read=False).update(is_read=True)

        return Response({
            'success': True,
            'replies': replies_data
        })

    except Exception as e:
        logger.error(f"Error in get_story_replies: {str(e)}")
        return Response({'success': False, 'error': 'Failed to get story replies'})


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def get_story_viewers(request, story_id):
    """Get viewers for a story (only for story poster)"""
    try:
        story = get_object_or_404(Story, id=story_id)

        # Only story poster can see viewers
        if story.user != request.user:
            return Response({'success': False, 'error': 'Unauthorized'})

        viewers = story.story_views.select_related(
            'viewer').order_by('-viewed_at')

        viewers_data = []
        for view in viewers:
            viewers_data.append({
                'id': view.viewer.id,
                'username': view.viewer.username,
                'full_name': view.viewer.full_name,
                'profile_picture_url': view.viewer.profile_picture_url,
                'viewed_at': view.viewed_at.isoformat()
            })

        return Response({
            'success': True,
            'viewers': viewers_data,
            'view_count': len(viewers_data)
        })

    except Exception as e:
        logger.error(f"Error in get_story_viewers: {str(e)}")
        return Response({'success': False, 'error': 'Failed to get story viewers'})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def delete_reply(request, reply_id):
    """Delete a story reply (only by reply author)"""
    try:
        reply = get_object_or_404(StoryReply, id=reply_id)

        # Only reply author or story owner can delete
        if reply.replier != request.user and reply.story.user != request.user:
            return Response({'success': False, 'error': 'Unauthorized'})

        reply.delete()

        return Response({'success': True})

    except Exception as e:
        logger.error(f"Error in delete_reply: {str(e)}")
        return Response({'success': False, 'error': 'Failed to delete reply'})


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def get_story_inbox(request):
    """Get all replies to the current user's stories - Story Inbox"""
    try:
        # Get all replies to stories owned by the current user
        replies = StoryReply.objects.filter(
            story__user=request.user
        ).select_related('replier', 'story').order_by('-created_at')

        replies_data = []
        for reply in replies:
            replies_data.append({
                'id': reply.id,
                'content': reply.content,
                'created_at': reply.created_at.isoformat(),
                'time_ago': timesince(reply.created_at) + ' ago',
                'is_read': reply.is_read,
                'replier': {
                    'id': reply.replier.id,
                    'username': reply.replier.username,
                    'full_name': reply.replier.full_name,
                    'profile_picture_url': reply.replier.profile_picture_url,
                },
                'story': {
                    'id': reply.story.id,
                    'story_type': reply.story.story_type,
                    'content': reply.story.content,
                    'media_url': reply.story.media_url,
                    'background_color': reply.story.background_color,
                    'text_color': reply.story.text_color,
                    'text_position': reply.story.text_position,
                    'text_size': reply.story.text_size,
                    'image_transform': reply.story.image_transform,
                    'created_at': reply.story.created_at.isoformat(),
                }
            })

        # Mark all as read after fetching
        replies.filter(is_read=False).update(is_read=True)

        return Response({
            'success': True,
            'replies': replies_data
        })

    except Exception as e:
        logger.error(f"Error in get_story_inbox: {str(e)}")
        return Response({'success': False, 'error': 'Failed to get story inbox'})


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def get_story_inbox_count(request):
    """Get the count of unread story replies"""
    try:
        unread_count = StoryReply.objects.filter(
            story__user=request.user,
            is_read=False
        ).count()

        return Response({
            'success': True,
            'unread_count': unread_count
        })

    except Exception as e:
        logger.error(f"Error in get_story_inbox_count: {str(e)}")
        return Response({'success': False, 'error': 'Failed to get count'})
