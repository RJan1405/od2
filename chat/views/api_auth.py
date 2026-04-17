from django.contrib.auth import authenticate
from django.db import transaction
from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ..models import CustomUser, PhoneVerificationToken
from rest_framework.decorators import api_view, authentication_classes, permission_classes, parser_classes
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.authtoken.models import Token
from rest_framework.response import Response
from channels.db import database_sync_to_async
from rest_framework.parsers import MultiPartParser, JSONParser, FormParser

import logging
import json
import os
import firebase_admin
from firebase_admin import credentials, auth as firebase_auth

logger = logging.getLogger(__name__)

# Initialize Firebase Admin only if not already initialized
if not firebase_admin._apps:
    try:
        fb_cred = getattr(settings, 'FIREBASE_CREDENTIALS', None)
        if fb_cred:
            # credentials.Certificate handles both a dict (JSON) and a string (File Path)
            cred = credentials.Certificate(fb_cred)
            firebase_admin.initialize_app(cred)
            logger.info("FIREBASE: Admin SDK initialized successfully.")
        else:
            logger.warning(
                "FIREBASE Warning: FIREBASE_CREDENTIALS not found in settings.")
    except Exception as e:
        logger.error(f"FIREBASE Error: Failed to initialize Admin SDK: {e}")


@api_view(["POST"])
@permission_classes([AllowAny])
def api_check_availability(request):
    """
    Check if username, email, or phone number is already registered.
    """
    data = request.data
    username = data.get('username')
    email = data.get('email')
    phone_number = data.get('phone_number')

    if username and CustomUser.objects.filter(username=username).exists():
        return Response({'success': False, 'error': 'Username already exists'}, status=400)

    if email and CustomUser.objects.filter(email=email).exists():
        return Response({'success': False, 'error': 'Email already exists'}, status=400)

    if phone_number and CustomUser.objects.filter(phone_number=phone_number).exists():
        return Response({'success': False, 'error': 'Phone number already registered'}, status=400)

    return Response({'success': True})


@api_view(["POST"])
@permission_classes([AllowAny])
def api_firebase_register(request):
    """
    Verify Firebase IdToken and create user.
    Called from mobile app after Firebase verifies the SMS.
    """
    try:
        data = request.data
        id_token = data.get('idToken')
        # JSON object with user details
        reg_data = data.get('registrationData')

        if not id_token or not reg_data:
            return Response({'success': False, 'error': 'idToken and registrationData are required'}, status=400)

        # 1. Verification Bypass Logic
        use_phone_verification = getattr(
            settings, 'ENABLE_PHONE_VERIFICATION', True)

        if not use_phone_verification:
            # If set to False, we skip Firebase handshake and trust reg_data
            logger.info(
                "BYPASS: OTP verification skipped via settings. Using provided phone number.")
            firebase_phone = reg_data.get('phone_number')
            if not firebase_phone:
                return Response({'success': False, 'error': 'Phone number is required in registrationData for bypass'}, status=400)
        else:
            # Standard Secure Mode: Verify the token with Firebase
            try:
                # Allow for clock skew (up to 60 seconds) to prevent "token used too early" errors
                decoded_token = firebase_auth.verify_id_token(
                    id_token, clock_skew_seconds=60)
                firebase_phone = decoded_token.get('phone_number')

                if not firebase_phone:
                    return Response({'success': False, 'error': 'Could not extract phone number from token'}, status=400)
            except Exception as e:
                logger.error(f"Firebase Token Verification Failed: {e}")
                return Response({'success': False, 'error': f'Invalid Firebase token: {str(e)}'}, status=401)

        # 2. Extract registration details
        username = reg_data.get('username')
        email = reg_data.get('email')
        password = reg_data.get('password')
        name = reg_data.get('name', '')
        lastname = reg_data.get('lastname', '')

        # 3. Validation
        if not username or not email or not password:
            return Response({'success': False, 'error': 'Incomplete registration data'}, status=400)

        if CustomUser.objects.filter(username=username).exists():
            return Response({'success': False, 'error': 'Username already exists'}, status=400)

        if CustomUser.objects.filter(email=email).exists():
            return Response({'success': False, 'error': 'Email already exists'}, status=400)

        # 4. Create User
        with transaction.atomic():
            user = CustomUser(
                username=username,
                email=email,
                name=name,
                lastname=lastname,
                phone_number=firebase_phone,
                is_phone_verified=True,
                is_email_verified=True
            )
            user.set_password(password)
            user.save()

            # Generate DRF Token
            token_obj, _ = Token.objects.get_or_create(user=user)
            user.mark_online()

            return Response({
                'success': True,
                'auth_token': token_obj.key,
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'email': user.email,
                    'phone_number': user.phone_number
                }
            })

    except Exception as e:
        logger.error(f"Firebase Registration Error: {e}")
        return Response({'success': False, 'error': str(e)}, status=500)


@api_view(["POST"])
@permission_classes([AllowAny])
def api_login(request):
    """API endpoint for React frontend login"""
    try:
        data = request.data
        username = data.get('username')
        password = data.get('password')

        if not username or not password:
            return Response({
                'success': False,
                'error': 'Username and password are required'
            }, status=400)

        user = authenticate(username=username, password=password)

        if user is not None:
            user.mark_online()

            # Get or create a DRF token for WebSocket authentication (mobile clients)
            try:
                token_obj, _ = Token.objects.get_or_create(user=user)
                auth_token = token_obj.key
            except Exception:
                auth_token = None

            if not auth_token:
                return Response({
                    'success': False,
                    'error': 'Token generation failed'
                }, status=500)

            return Response({
                'success': True,
                'auth_token': auth_token,  # Used by mobile for WS auth via ?token=xxx
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'email': user.email,
                    'name': user.name,
                    'lastname': user.lastname,
                    'full_name': user.full_name,
                    'profile_picture': user.profile_picture.url if user.profile_picture else '',
                    'profile_picture_url': user.profile_picture_url,
                    'cover_image_url': user.cover_image_url,
                    'bio': getattr(user, 'bio', ''),
                    'is_verified': user.is_verified,
                    'is_private': user.is_private,
                    'is_online': True,
                    'last_seen': user.last_seen.isoformat() if user.last_seen else '',
                    'theme': user.theme,
                    'gender': user.gender,
                    'follower_count': user.follower_count,
                    'following_count': user.following_count,
                    'post_count': user.scribes.count(),
                }
            })
        else:
            return Response({
                'success': False,
                'error': 'Invalid username or password'
            }, status=401)

    except Exception as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=500)


@api_view(["POST"])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def api_logout(request):
    """API endpoint for React frontend logout"""
    if request.user.is_authenticated:
        request.user.mark_offline()
        Token.objects.filter(user=request.user).delete()
    return Response({'success': True}, status=200)


@api_view(["POST"])
@permission_classes([AllowAny])
def api_register(request):
    """API endpoint for user registration (mobile/frontend) with optional Twilio OTP"""
    try:
        data = request.data
        username = data.get('username')
        email = data.get('email')
        password = data.get('password')
        name = data.get('name', '')
        lastname = data.get('lastname', '')
        phone_number = data.get('phone_number', '').strip()

        if not username or not email or not password:
            return Response({
                'success': False,
                'error': 'Username, email, and password are required'
            }, status=400)

        if CustomUser.objects.filter(username=username).exists():
            return Response({'success': False, 'error': 'Username already exists'}, status=400)

        if CustomUser.objects.filter(email=email).exists():
            return Response({'success': False, 'error': 'Email already exists'}, status=400)

        if phone_number and CustomUser.objects.filter(phone_number=phone_number).exists():
            return Response({'success': False, 'error': 'Phone number already registered'}, status=400)

        # Store all registration data JSON-encoded to create user later
        reg_data = {
            'username': username,
            'email': email,
            'password': password,
            'name': name,
            'lastname': lastname,
            'phone_number': phone_number
        }

        # Delete any existing registration tokens for this email
        from chat.models import EmailVerificationToken
        import json
        EmailVerificationToken.objects.filter(email=email, user=None).delete()

        # Create token with registration data
        token_obj = EmailVerificationToken.objects.create(
            email=email,
            registration_data=json.dumps(reg_data)
        )

        # Send Email
        from django.core.mail import send_mail
        from django.conf import settings
        subject = 'Your Odnix Verification Code'
        html_content = f"""<h2>Hello {name}!</h2><p>Your Odnix account verification code:</p><h3>{token_obj.token}</h3>"""
        try:
            send_mail(subject, html_content, settings.DEFAULT_FROM_EMAIL, [
                      email], html_message=html_content, fail_silently=False)
        except Exception as e:
            return Response({'success': False, 'error': f'Failed to send email: {str(e)}'}, status=500)

        return Response({
            'success': True,
            'requires_otp': True,
            'email': email,
            'message': 'OTP sent to email. Your account will be created upon verification.'
        })

    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=500)


@api_view(["POST"])
@permission_classes([AllowAny])
def api_verify_email_otp(request):
    """Verify email OTP for mobile users. Creates the user if verification is successful."""
    try:
        data = request.data
        email = data.get('email')
        otp = data.get('otp')

        if not email or not otp:
            return Response({'success': False, 'error': 'email and otp are required'}, status=400)

        from chat.models import EmailVerificationToken
        token_obj = EmailVerificationToken.objects.filter(
            email=email, token=otp, is_used=False).first()

        if not token_obj or token_obj.is_expired:
            return Response({'success': False, 'error': 'Invalid or expired OTP'}, status=400)

        with transaction.atomic():
            import json
            # If the token contains registration data, create the user NOW
            if token_obj.registration_data:
                reg_data = json.loads(token_obj.registration_data)

                # Check if someone else took the username or email while waiting
                if CustomUser.objects.filter(username=reg_data['username']).exists():
                    return Response({'success': False, 'error': 'Username already taken'}, status=400)
                if CustomUser.objects.filter(email=reg_data['email']).exists():
                    return Response({'success': False, 'error': 'Email already registered'}, status=400)

                user = CustomUser(
                    username=reg_data['username'],
                    email=reg_data['email'],
                    name=reg_data['name'],
                    lastname=reg_data['lastname'],
                    phone_number=reg_data.get('phone_number'),
                    is_email_verified=True,
                    is_phone_verified=True
                )
                user.set_password(reg_data['password'])
                user.save()
            else:
                return Response({'success': False, 'error': 'No registration data found for this token'}, status=400)

            # Mark token as used
            token_obj.is_used = True
            token_obj.save()

            # Log the user in
            auth_token, _ = Token.objects.get_or_create(user=user)
            user.mark_online()

            return Response({
                'success': True,
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'email': user.email,
                    'phone_number': user.phone_number,
                },
                'auth_token': auth_token.key
            })
    except Exception as e:
        logger.error(f"OTP verification error: {e}")
        return Response({'success': False, 'error': str(e)}, status=500)


@api_view(["GET", "POST"])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def api_profile(request):
    """API endpoint to get or update current user profile"""
    user = request.user

    if request.method == 'POST':
        try:
            # Handle file uploads from request.data (MultiPartParser puts them there)
            if 'avatar' in request.data:
                user.profile_picture = request.data['avatar']

            if 'cover_image' in request.data:
                user.cover_image = request.data['cover_image']

            # Handle text fields from request.data
            display_name = request.data.get('displayName')
            first_name = request.data.get('first_name')
            last_name = request.data.get('last_name')

            if display_name:
                # Map mobile displayName to name and lastname
                names = display_name.split(' ', 1)
                user.name = names[0]
                user.lastname = names[1] if len(names) > 1 else ""
            else:
                # Map web first_name/last_name to name and lastname
                if first_name:
                    user.name = first_name
                if last_name:
                    user.lastname = last_name

            username = request.data.get('username')
            if username:
                user.username = username

            bio = request.data.get('bio')
            if bio is not None:
                user.bio = bio

            user.save()

            user_data = {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'name': user.name,
                'lastname': user.lastname,
                'full_name': user.full_name,
                'profile_picture': user.profile_picture.url if user.profile_picture else '',
                'profile_picture_url': user.profile_picture_url,
                'cover_image_url': user.cover_image_url,
                'bio': getattr(user, 'bio', ''),
                'is_verified': user.is_verified,
                'is_private': user.is_private,
                'is_online': user.is_online,
                'last_seen': user.last_seen.isoformat() if user.last_seen else '',
                'theme': user.theme,
                'gender': user.gender,
                'follower_count': user.follower_count,
                'following_count': user.following_count,
                'post_count': user.scribes.count(),
            }

            user.save()

            return Response({
                'success': True,
                'user': user_data,
                'data': user_data
            }, status=200)
        except Exception as e:
            return Response({'success': False, 'error': str(e)}, status=500)

    user_response = {
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'name': user.name,
        'lastname': user.lastname,
        'full_name': user.full_name,
        'profile_picture': user.profile_picture.url if user.profile_picture else '',
        'profile_picture_url': user.profile_picture_url,
        'cover_image_url': user.cover_image_url,
        'bio': getattr(user, 'bio', ''),
        'is_verified': user.is_verified,
        'is_private': user.is_private,
        'is_online': user.is_online,
        'last_seen': user.last_seen.isoformat() if user.last_seen else '',
        'theme': user.theme,
        'gender': user.gender,
        'follower_count': user.follower_count,
        'following_count': user.following_count,
        'post_count': user.scribes.count(),
    }

    return Response({
        'success': True,
        'user': user_response,
        'data': user_response
    }, status=200)

# Deprecated: Not used in token-based auth


def get_csrf_token(request):
    return Response({'success': True}, status=200)


@api_view(["GET"])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def api_user_profile(request, username):
    """API endpoint to get user profile by username"""
    from django.shortcuts import get_object_or_404
    from ..models import CustomUser, Follow, FollowRequest

    # Get the user by username or 'me' for current user
    if username == 'me':
        user = request.user
    else:
        user = get_object_or_404(CustomUser, username=username)

    # Determine if current user can see this profile's content
    is_following = False
    if not user == request.user and request.user.is_authenticated:
        is_following = Follow.objects.filter(
            follower=request.user, following=user).exists()

    can_view_content = True
    if not user == request.user:
        if user.is_private and not is_following:
            can_view_content = False

    # Get user's scribes
    from ..models import Scribe, Omzo, Like, Dislike, SavedScribeItem, SavedOmzoItem

    if can_view_content:
        scribes_queryset = Scribe.objects.filter(user=user).select_related(
            'user',
            'original_scribe', 'original_scribe__user',
            'original_omzo', 'original_omzo__user',
            'original_story', 'original_story__user'
        ).order_by('-timestamp')
    else:
        scribes_queryset = Scribe.objects.none()

    scribes_data = []
    reposts_data = []

    for scribe in scribes_queryset:
        is_liked = Like.objects.filter(scribe=scribe, user=request.user).exists(
        ) if request.user.is_authenticated else False
        is_disliked = Dislike.objects.filter(scribe=scribe, user=request.user).exists(
        ) if request.user.is_authenticated else False
        is_saved = SavedScribeItem.objects.filter(scribe=scribe, user=request.user).exists(
        ) if request.user.is_authenticated else False

        # Determine type correctly: if it has an image and type is text (default), it's an image scribe
        scribe_type = getattr(scribe, 'content_type', 'text')
        if scribe.image and (not scribe_type or scribe_type == 'text'):
            scribe_type = 'image'

        # Check if this is a repost
        is_repost = bool(
            scribe.original_scribe or scribe.original_omzo or scribe.original_story)

        # Build scribe data
        scribe_obj = {
            'id': scribe.id,
            'content': scribe.content,
            'timestamp': scribe.timestamp,
            'type': scribe_type,
            'media_url': scribe.image.url if scribe.image else None,
            'like_count': scribe.scribe_likes.count(),
            'dislike_count': scribe.scribe_dislikes.count(),
            'comment_count': scribe.comments.count(),
            'repost_count': scribe.reposts.count(),
            'is_liked': is_liked,
            'is_disliked': is_disliked,
            'is_saved': is_saved,
            'code_html': getattr(scribe, 'code_html', ''),
            'code_css': getattr(scribe, 'code_css', ''),
            'code_js': getattr(scribe, 'code_js', ''),
            'is_repost': is_repost,
            'user': {
                'id': scribe.user.id,
                'username': scribe.user.username,
                'full_name': scribe.user.full_name,
                'profile_picture': scribe.user.profile_picture.url if scribe.user.profile_picture else '',
                'profile_picture_url': scribe.user.profile_picture_url,
                'is_verified': scribe.user.is_verified,
            },
        }

        # If it's a repost, add original content information
        if is_repost:
            original_data = None
            original_type = None

            if scribe.original_scribe:
                original = scribe.original_scribe
                original_type = 'scribe'

                # Copy code fields from original to top level for better visibility in feeds
                scribe_obj['code_html'] = getattr(original, 'code_html', '')
                scribe_obj['code_css'] = getattr(original, 'code_css', '')
                scribe_obj['code_js'] = getattr(original, 'code_js', '')

                original_data = {
                    'id': original.id,
                    'content': original.content,
                    'timestamp': original.timestamp,
                    'type': getattr(original, 'content_type', 'text'),
                    'media_url': original.image.url if original.image else None,
                    'like_count': original.scribe_likes.count(),
                    'comment_count': original.comments.count(),
                    'repost_count': original.reposts.count(),
                    'code_html': getattr(original, 'code_html', ''),
                    'code_css': getattr(original, 'code_css', ''),
                    'code_js': getattr(original, 'code_js', ''),
                    'user': {
                        'id': str(original.user.id),
                        'username': original.user.username,
                        'display_name': original.user.full_name or original.user.username,
                        'avatar': original.user.profile_picture.url if original.user.profile_picture else '',
                        'is_verified': original.user.is_verified,
                    },
                    'likes': original.scribe_likes.count(),
                    'comments': original.comments.count(),
                    'reposts': original.reposts.count(),
                }
            elif scribe.original_omzo:
                original = scribe.original_omzo
                original_type = 'omzo'
                original_data = {
                    'id': original.id,
                    'caption': original.caption,
                    'video_url': original.video_file.url if original.video_file else None,
                    'timestamp': original.created_at,
                    'like_count': original.likes.count(),
                    'comment_count': original.comments.count(),
                    'likes': original.likes.count(),
                    'comments': original.comments.count(),
                    'views': original.views_count,
                    'user': {
                        'id': str(original.user.id),
                        'username': original.user.username,
                        'display_name': original.user.full_name or original.user.username,
                        'avatar': original.user.profile_picture.url if original.user.profile_picture else '',
                        'is_verified': original.user.is_verified,
                    }
                }
            elif scribe.original_story:
                original = scribe.original_story
                original_type = 'story'
                original_data = {
                    'id': original.id,
                    'timestamp': original.created_at,
                    'user': {
                        'id': str(original.user.id),
                        'username': original.user.username,
                        'display_name': original.user.full_name or original.user.username,
                        'avatar': original.user.profile_picture.url if original.user.profile_picture else '',
                        'is_verified': original.user.is_verified,
                    }
                }

            scribe_obj['original_type'] = original_type
            scribe_obj['original_data'] = original_data

            # Add to reposts list
            reposts_data.append(scribe_obj)
        else:
            # Add to regular scribes list
            scribes_data.append(scribe_obj)

    # Get user's omzos
    if can_view_content:
        omzos_queryset = Omzo.objects.filter(user=user).order_by('-created_at')
    else:
        omzos_queryset = Omzo.objects.none()
    omzos_data = []

    for omzo in omzos_queryset:
        is_liked = omzo.is_liked_by(
            request.user) if request.user.is_authenticated else False
        is_saved = SavedOmzoItem.objects.filter(omzo=omzo, user=request.user).exists(
        ) if request.user.is_authenticated else False
        repost_count = Scribe.objects.filter(original_omzo=omzo).count()
        is_reposted = Scribe.objects.filter(user=request.user, original_omzo=omzo, quote_source__isnull=True).exists(
        ) if request.user.is_authenticated else False

        # Build absolute URL for video
        video_url = None
        if omzo.video_file:
            video_url = request.build_absolute_uri(omzo.video_file.url)

        omzos_data.append({
            'id': omzo.id,
            'caption': omzo.caption,
            'video_url': video_url,
            'thumbnail_url': video_url,  # Use video URL as thumbnail
            'timestamp': omzo.created_at,
            'like_count': omzo.likes.count(),
            'dislike_count': omzo.dislikes.count(),
            'likes': omzo.likes.count(),
            'dislikes': omzo.dislikes.count(),
            'shares': 0,  # Placeholder
            'views': omzo.views_count,
            'comment_count': omzo.comments.count(),
            'is_liked': is_liked,
            'is_saved': is_saved,
            'repost_count': repost_count,
            'reposts': repost_count,
            'is_reposted': is_reposted,
        })

    # Follow request status (from ME to THEM)
    follow_request_status = None
    if not user == request.user and request.user.is_authenticated:
        req = FollowRequest.objects.filter(
            requester=request.user, target=user).first()
        if req:
            follow_request_status = req.status

    # Check if THEY have requested to follow ME
    is_requesting_follow = False
    if not user == request.user and request.user.is_authenticated:
        is_requesting_follow = FollowRequest.objects.filter(
            requester=user,
            target=request.user,
            status='pending'
        ).exists()

    return Response({
        'success': True,
        'user': {
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'name': user.name,
            'lastname': user.lastname,
            'full_name': user.full_name,
            'profile_picture': user.profile_picture.url if user.profile_picture else '',
            'profile_picture_url': user.profile_picture_url,
            'cover_image_url': user.cover_image_url,
            'bio': getattr(user, 'bio', ''),
            'is_verified': user.is_verified,
            'is_private': user.is_private,
            'is_online': user.is_online,
            'last_seen': user.last_seen.isoformat() if user.last_seen else '',
            'theme': user.theme,
            'gender': user.gender,
            'follower_count': user.follower_count,
            'following_count': user.following_count,
            'post_count': user.scribes.count(),
            'is_following': is_following,
            'follow_request_status': follow_request_status,
            'is_requesting_follow': is_requesting_follow,
        },
        'scribes': scribes_data,
        'reposts': reposts_data,
        'omzos': omzos_data
    }, status=200)


@database_sync_to_async
def get_user_from_token_sync(token_key):
    """Bridge for WebSocket authentication."""
    try:
        from rest_framework.authtoken.models import Token
        token = Token.objects.select_related('user').get(key=token_key)
        return token.user
    except Exception:
        from django.contrib.auth.models import AnonymousUser
        return AnonymousUser()
