from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate, get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.urls import reverse
from django.conf import settings
from django.core.mail import send_mail
import logging
from chat.models import CustomUser, EmailVerificationToken
from chat.forms import CustomUserCreationForm
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import TokenAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes

User = get_user_model()
logger = logging.getLogger(__name__)

def home(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    return render(request, 'chat/landing.html')

def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        if not username or not password:
            messages.error(request, 'Username and password are required')
            return render(request, 'chat/login.html')
        
        user = authenticate(request, username=username, password=password)
        if user is not None:
            # if user.is_email_verified:
            login(request, user)
            user.mark_online()
            messages.success(request, f'Welcome back, {user.full_name}!')
            return redirect('dashboard')
            # else:
            #     messages.error(request, 'Please verify your email before logging in.')
        else:
            try:
                existing_user = CustomUser.objects.get(username=username)
                messages.error(request, 'Invalid password. Please try again.')
            except CustomUser.DoesNotExist:
                # User doesn't exist - redirect to signup with a message
                messages.info(request, f'No account found with username "{username}". Please create an account to get started.')
                return redirect('register')
    
    return render(request, 'chat/login.html')

def register_view(request):
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                user = form.save(commit=False)
                # Ensure email is not verified initially
                user.is_email_verified = False
                user.save()

                # Send verification email with OTP
                send_verification_email(user, request)

                # Store user ID in session for the verification step
                request.session['verification_user_id'] = user.id

                messages.success(request, f'Account created! A verification code has been sent to {user.email}.')
                return redirect('verify_email_otp')

            except Exception as e:
                logger.error(f"Error creating account: {str(e)}")
                messages.error(request, f'Error creating account: {str(e)}')
        else:
            # Display form errors
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')

    return render(request, 'chat/register.html')

def send_verification_email(user, request):
    try:
        # Delete any existing tokens for this user
        EmailVerificationToken.objects.filter(user=user).delete()

        # Create new OTP token (auto-generated 6 digits by model save method)
        token = EmailVerificationToken.objects.create(user=user)

        subject = 'Your Odnix Verification Code'
        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <div style="background: #667eea; color: white; padding: 20px; text-align: center;">
                    <h1>Verify your email</h1>
                </div>
                <div style="padding: 20px; text-align: center;">
                    <h2>Hello {user.full_name}!</h2>
                    <p>Use the following code to verify your Odnix account:</p>
                    <div style="font-size: 32px; letter-spacing: 5px; font-weight: bold; color: #667eea; margin: 20px 0; padding: 10px; background: #f0f4ff; display: inline-block; border-radius: 8px;">
                        {token.token}
                    </div>
                    <p>This code expires in 10 minutes.</p>
                </div>
            </div>
        </body>
        </html>
        """

        plain_message = f"""
        Hello {user.full_name}!

        Your verification code is: {token.token}

        This code expires in 10 minutes.
        """

        send_mail(
            subject,
            plain_message,
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            html_message=html_content,
            fail_silently=False,
        )
        return True
    except Exception as e:
        logger.error(f"Email error: {e}")
        return False

def verify_otp_view(request):
    # Get user ID from session
    user_id = request.session.get('verification_user_id')
    if not user_id:
        messages.error(request, 'Session expired. Please sign up again.')
        return redirect('register')

    user = get_object_or_404(User, id=user_id)

    if request.method == 'POST':
        otp = request.POST.get('otp')
        if not otp:
            messages.error(request, 'Please enter the verification code.')
            return render(request, 'chat/verify_otp.html', {'email': user.email})

        # Verify OTP
        try:
            # Check for valid, unexpired, unused token for this user
            token_obj = EmailVerificationToken.objects.filter(
                user=user,
                token=otp,
                is_used=False
            ).latest('created_at')

            if token_obj.is_expired:
                messages.error(request, 'Verification code has expired.')
                return render(request, 'chat/verify_otp.html', {'email': user.email})

            # Success!
            user.is_email_verified = True
            user.save()

            token_obj.is_used = True
            token_obj.save()

            # Clean up session
            del request.session['verification_user_id']

            # Log the user in directly
            login(request, user)
            user.mark_online()

            messages.success(request, 'Email verified successfully! Welcome to Odnix.')
            return redirect('dashboard')

        except EmailVerificationToken.DoesNotExist:
            messages.error(request, 'Invalid verification code. Please try again.')

    return render(request, 'chat/verify_otp.html', {'email': user.email})

# Kept for backward compatibility if needed, or redirect to Login
def verify_email(request, token):
    messages.error(request, 'Invalid verification link.')
    return redirect('login')

@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def logout_view(request):
    request.user.mark_offline()
    logout(request)
    return redirect('login')
