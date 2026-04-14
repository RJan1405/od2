"""
Django settings for odnix project.
"""

import os
from pathlib import Path
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent


# ---------------------------Production starts----------------------------

"""



# Load environment variables from .env if it exists
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / '.env')
except ImportError:
    pass

SECRET_KEY = os.environ.get('SECRET_KEY', 'django-insecure-change-this-key-in-production-123456789')

DEBUG = os.environ.get('DEBUG', 'True') == 'True'

# Security settings for production
if not DEBUG:
    # Use HTTPS for cookies and redirects
    SECURE_SSL_REDIRECT = os.environ.get('SECURE_SSL_REDIRECT', 'True') == 'True'
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    # SECURE_HSTS_SECONDS = 31536000 # 1 year
    # SECURE_HSTS_PRELOAD = True
    # SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Fixed ALLOWED_HOSTS for local + production
ALLOWED_HOSTS = ['localhost', '127.0.0.1', '*']

# Render specific
RENDER_EXTERNAL_HOSTNAME = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)

# Site domain for clean invite links (defaults to production if not in env)
# SITE_DOMAIN = os.environ.get('SITE_DOMAIN', 'https://odnixdeploy.onrender.com')
# SITE_DOMAIN = os.environ.get('SITE_DOMAIN', 'https://odnixdeploy.onrender.com')
SITE_DOMAIN = 'http://192.168.104.187:8000'

# CORS settings for React frontend
# Defaults to localhost + production URL
DEFAULT_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:8080",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:8080",
    "https://odnixdeploy.onrender.com",
]

env_cors = os.environ.get('CORS_ALLOWED_ORIGINS')
if env_cors:
    CORS_ALLOWED_ORIGINS = [origin.strip() for origin in env_cors.split(',')]
else:
    CORS_ALLOWED_ORIGINS = DEFAULT_CORS_ORIGINS
CORS_ALLOW_CREDENTIALS = True  # Required for session-based auth
CORS_ALLOW_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
]

# CSRF trusted origins for POST requests
env_csrf = os.environ.get('CSRF_TRUSTED_ORIGINS')
if env_csrf:
    CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in env_csrf.split(',')]
    # Add Cloudflare tunnel pattern if not present
    if "https://*.trycloudflare.com" not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append("https://*.trycloudflare.com")
else:
    CSRF_TRUSTED_ORIGINS = DEFAULT_CORS_ORIGINS + ["https://*.trycloudflare.com"]
    



"""
# ---------------------------Production Ends----------------------------

# ---------------------------Local Starts----------------------------

# Load environment variables from .env if it exists
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / '.env')
except ImportError:
    pass

SECRET_KEY = os.environ.get(
    'SECRET_KEY', 'django-insecure-change-this-key-in-production-123456789')

DEBUG = os.environ.get('DEBUG', 'True') == 'True'
ALLOWED_HOSTS = ['localhost', '127.0.0.1', '*']

# Render specific
RENDER_EXTERNAL_HOSTNAME = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)

# FIXED: Site domain for clean invite links
# SITE_DOMAIN = 'http://192.168.104.187:8000'
SITE_DOMAIN = "https://odnixdeploy.onrender.com"

# CORS settings for React frontend
CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",  # Vite dev server (default)
    "http://localhost:8080",  # Vite dev server (configured)
    "http://localhost:3000",  # Alternative React dev server
    "http://127.0.0.1:5173",
    "http://127.0.0.1:8080",
    "http://192.168.104.187:8080",
    "http://192.168.104.187:8000",
    "http://192.168.0.104:8080",
    "http://127.0.0.1:3000",
    "https://api.odnix.org",
    "https://odnixdeploy.onrender.com",
]
CORS_ALLOW_CREDENTIALS = True  # Required for Django admin session
CORS_ALLOW_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
    'https://api.odnix.org',
    "https://odnixdeploy.onrender.com",
]

# CSRF trusted origins for POST requests (includes localhost + Cloudflare tunnel)
CSRF_TRUSTED_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:8080",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
    "http://192.168.104.187:8080",
    "http://192.168.104.187:8000",
    "http://192.168.0.104:8080",
    "http://127.0.0.1:8080",
    "http://127.0.0.1:3000",
    "https://*.trycloudflare.com",  # Allow all Cloudflare tunnels
    "https://api.odnix.org",
    "https://odnixdeploy.onrender.com",
]

# ---------------------------Local Ends----------------------------

# ENVIRONMENT SETUP
ENV = os.environ.get('ENV', 'development')  # development, staging, production

# ANALYTICS CONFIGURATION
# Strictly enable analytics only in production to prevent test data pollution
ENABLE_ANALYTICS = os.environ.get(
    'ENABLE_ANALYTICS', str(ENV == 'production')).lower() == 'true'
POSTHOG_API_KEY = os.environ.get('POSTHOG_API_KEY', '')
POSTHOG_HOST = os.environ.get('POSTHOG_HOST', 'https://app.posthog.com')

# CELERY SETTINGS (Basic Configuration)
CELERY_BROKER_URL = os.environ.get(
    'CELERY_BROKER_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.environ.get(
    'CELERY_RESULT_BACKEND', 'redis://localhost:6379/0')

INSTALLED_APPS = [
    'jazzmin',  # Must be before django.contrib.admin
    'daphne',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'channels',
    'corsheaders',  # Enable CORS for React frontend
    'rest_framework',
    'rest_framework.authtoken',
    'chat',
    'analytics',
]

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.TokenAuthentication',
    ],
}

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',  # Must be at the top
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'analytics.middleware.PostHogAPIMiddleware',
]

ROOT_URLCONF = 'odnix.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'odnix.wsgi.application'

# ASGI application for channels
ASGI_APPLICATION = 'odnix.asgi.application'

# Channel layers configuration
# Use Redis if USE_REDIS_CHANNELS env var is set, otherwise use in-memory for development
if os.environ.get("USE_REDIS_CHANNELS", "").lower() == "true":
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {
                "hosts": [os.environ.get("REDIS_URL", "redis://127.0.0.1:6379")]
            }
        }
    }
else:
    # In-memory channel layer for development (no Redis required)
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer"
        }
    }

DATABASES = {
    'default': dj_database_url.config(
        default=f'sqlite:///{BASE_DIR / "db.sqlite3"}',
        conn_max_age=600
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATICFILES_DIRS = [
    BASE_DIR / "static",
]
STATIC_ROOT = BASE_DIR / "staticfiles"

# WhiteNoise for serving static files with ASGI/Daphne
WHITENOISE_USE_FINDERS = True

# FIXED: Media files configuration with profile pics support
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Ensure media directories exist
os.makedirs(MEDIA_ROOT, exist_ok=True)
os.makedirs(MEDIA_ROOT / 'profile_pics', exist_ok=True)
os.makedirs(MEDIA_ROOT / 'chat_media', exist_ok=True)

# FIXED: File upload settings - PREVENTS CORRUPTION & ALLOWS LARGER VIDEOS
FILE_UPLOAD_MAX_MEMORY_SIZE = 100 * 1024 * \
    1024  # 100MB (Stream larger to disk)
DATA_UPLOAD_MAX_MEMORY_SIZE = 100 * 1024 * \
    1024  # 100MB (Max request body size)
FILE_UPLOAD_PERMISSIONS = 0o644

# Allowed file types for uploads
ALLOWED_MEDIA_TYPES = {
    'image': ['.jpg', '.jpeg', '.png', '.gif', '.webp'],
    'video': ['.mp4', '.mov', '.avi', '.mkv', '.webm'],
    'document': ['.pdf', '.doc', '.docx', '.txt']
}

# Maximum file sizes (in bytes)
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Custom user model
AUTH_USER_MODEL = 'chat.CustomUser'

# Login URLs
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/'  # Redirect to landing page after logout

# FIXED: Email settings for verification using provided credentials
# FIXED: Email settings for verification using Gmail
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
# TODO: Replace with your actual Gmail address
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', 'optinal46@gmail.com')
EMAIL_HOST_PASSWORD = os.environ.get(
    'EMAIL_HOST_PASSWORD', 'qxeo wtqn xpsn jvuv')
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER

# For development/testing - uncomment to see emails in console
# EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# PHONE VERIFICATION CONFIGURATION
# Set to True to require phone verification (Now using Firebase instead of Twilio)
ENABLE_PHONE_VERIFICATION = True
# Twilio keys removed as requested

# FIREBASE CONFIGURATION (Production Safe)
ENABLE_FIREBASE_AUTH = True

# We can load credentials from an environment variable (JSON string) for production (Render/AWS/etc.)
# or from a local file for development.
FIREBASE_CRED_JSON = os.getenv("FIREBASE_CREDENTIALS")
if FIREBASE_CRED_JSON:
    try:
        import json
        FIREBASE_CREDENTIALS = json.loads(FIREBASE_CRED_JSON)
    except Exception:
        FIREBASE_CREDENTIALS = os.path.join(
            BASE_DIR, 'firebase-service-account.json')
else:
    FIREBASE_CREDENTIALS = os.path.join(
        BASE_DIR, 'firebase-service-account.json')

# Session settings
SESSION_COOKIE_AGE = 86400  # 1 day
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = False

# Security settings for media files
SECURE_CROSS_ORIGIN_OPENER_POLICY = None
X_FRAME_OPTIONS = 'DENY'

# Logging configuration
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': BASE_DIR / 'django_errors.log',
        },
        'console': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
        },
    },
    # Ensure everything goes to console so you can see call/WS logs in the runserver terminal
    'root': {
        'handlers': ['console'],
        'level': 'DEBUG',
    },
    'loggers': {
        'django': {
            'handlers': ['file', 'console'],
            'level': 'INFO',
            'propagate': True,
        },
        'chat': {
            'handlers': ['file', 'console'],
            'level': 'DEBUG',
            'propagate': True,
        },
    },
}

# --- Omzo Compression Settings ---
# Tunable knobs for server-side omzo compression. You can override via env vars
# or directly edit here per environment.
OMZO_MAX_WIDTH = int(os.getenv('OMZO_MAX_WIDTH', 480))           # px
OMZO_MAX_DURATION = 120      # seconds (Maximum 2 minutes)
# frames per second (cap)
OMZO_MAX_FPS = int(os.getenv('OMZO_MAX_FPS', 30))
# 18-32 (lower=better quality)
OMZO_CRF = int(os.getenv('OMZO_CRF', 28))
# ultrafast..veryslow
OMZO_PRESET = os.getenv('OMZO_PRESET', 'veryfast')
OMZO_AUDIO_BITRATE = os.getenv(
    'OMZO_AUDIO_BITRATE', '96k')      # e.g. '96k', '128k'
OMZO_SMART_FALLBACK = os.getenv(
    'OMZO_SMART_FALLBACK', '1') in ('1', 'true', 'True')
OMZO_FORCE_MP4 = os.getenv('OMZO_FORCE_MP4', '1') in ('1', 'true', 'True')

# ============================================================================
# JAZZMIN ADMIN THEME CONFIGURATION
# ============================================================================

JAZZMIN_SETTINGS = {
    # Title on the login screen (19 chars max)
    "site_title": "Odnix Admin",

    # Title on the brand (19 chars max)
    "site_header": "Odnix",

    # Title on the brand in sidebar
    "site_brand": "Odnix",

    # Logo to use for your site, must be present in static files
    "site_logo": "img/logo.png",

    # Logo to use for your site on login page
    "login_logo": "img/logo.png",

    # Logo to use for login form in dark themes
    "login_logo_dark": "img/logo.png",

    # CSS classes applied to the logo
    "site_logo_classes": "rounded-circle shadow-sm",

    # Relative path to a favicon, will default to site_logo if absent
    "site_icon": "img/logo.png",

    # Welcome text on the login screen
    "welcome_sign": "Welcome to Odnix Admin Panel",

    # Copyright on the footer
    "copyright": "Odnix Social Platform",

    # List of model admins to search from the search bar
    "search_model": ["chat.CustomUser", "chat.Chat", "chat.Scribe", "chat.Omzo"],

    # Field name on user model that contains avatar ImageField/URLField/Charfield
    "user_avatar": "profile_picture",

    ############
    # Top Menu #
    ############
    "topmenu_links": [
        # Url that gets reversed (Alarm those those those names are valid)
        {"name": "Home", "url": "admin:index",
            "permissions": ["auth.view_user"]},

        # External url that opens in a new window
        {"name": "View Site", "url": "/dashboard/", "new_window": True},

        # Model admin to link to (Alarm those names to valid ones)
        {"model": "chat.CustomUser"},

        # App with dropdown menu to all its models pages
        {"app": "chat"},
    ],

    #############
    # User Menu #
    #############
    "usermenu_links": [
        {"name": "View Site", "url": "/dashboard/",
            "new_window": True, "icon": "fas fa-globe"},
        {"model": "chat.customuser"},
    ],

    #############
    # Side Menu #
    #############
    # Whether to display the side menu
    "show_sidebar": True,

    # Whether to auto expand the menu
    "navigation_expanded": True,

    # Hide these apps when generating side menu
    "hide_apps": [],

    # Hide these models when generating side menu
    "hide_models": [],

    # List of apps (and/or models) to base side menu ordering off of
    "order_with_respect_to": [
        "chat",
        "chat.CustomUser",
        "chat.Follow",
        "chat.Chat",
        "chat.Message",
        "chat.GroupJoinRequest",
        "chat.Scribe",
        "chat.Like",
        "chat.Dislike",
        "chat.Comment",
        "chat.SavedPost",
        "chat.Story",
        "chat.Omzo",
        "chat.OmzoLike",
        "chat.OmzoDislike",
        "chat.OmzoComment",
        "chat.PostReport",
        "chat.OmzoReport",
        "chat.EmailVerificationToken",
        "auth",
        "auth.Group",
    ],

    # Custom links to append to app groups
    # Note: Commented out - "Analytics Dashboard" pointed to /admin/ (same as main Dashboard)
    # "custom_links": {
    #     "chat": [{
    #         "name": "Analytics Dashboard",
    #         "url": "/admin/",
    #         "icon": "fas fa-chart-line",
    #         "permissions": ["chat.view_customuser"]
    #     }]
    # },
    "custom_links": {},

    #############
    # Icons     #
    #############
    # Icons that are used when one is not manually specified
    "default_icon_parents": "fas fa-chevron-circle-right",
    "default_icon_children": "fas fa-circle",

    # Custom icons for apps/models
    "icons": {
        # Auth app
        "auth": "fas fa-users-cog",
        "auth.user": "fas fa-user",
        "auth.Group": "fas fa-users",

        # Chat app - Users & Auth
        "chat.CustomUser": "fas fa-user-circle",
        "chat.EmailVerificationToken": "fas fa-envelope-open-text",
        "chat.Follow": "fas fa-user-friends",

        # Chat app - Messaging
        "chat.Chat": "fas fa-comments",
        "chat.Message": "fas fa-envelope",
        "chat.GroupJoinRequest": "fas fa-user-plus",

        # Chat app - Posts/Scribes
        "chat.Scribe": "fas fa-feather-alt",
        "chat.Like": "fas fa-heart",
        "chat.Dislike": "fas fa-thumbs-down",
        "chat.Comment": "fas fa-comment-dots",
        "chat.SavedPost": "fas fa-bookmark",

        # Chat app - Stories
        "chat.Story": "fas fa-book-open",
        "chat.StoryView": "fas fa-eye",
        "chat.StoryLike": "fas fa-star",
        "chat.StoryReply": "fas fa-reply",

        # Chat app - Omzos (Reels/Videos)
        "chat.Omzo": "fas fa-video",
        "chat.OmzoLike": "fas fa-heart",
        "chat.OmzoDislike": "fas fa-thumbs-down",
        "chat.OmzoComment": "fas fa-comment",

        # Chat app - Reports & Moderation
        "chat.PostReport": "fas fa-flag",
        "chat.OmzoReport": "fas fa-exclamation-triangle",

        # Other models
        "chat.Hashtag": "fas fa-hashtag",
        "chat.P2PSignal": "fas fa-phone",
        "chat.ProfileView": "fas fa-eye",
        "chat.TypingStatus": "fas fa-keyboard",
        "chat.StarredMessage": "fas fa-star",
    },

    #################
    # Related Modal #
    #################
    # Use modals instead of popups for related objects
    "related_modal_active": True,

    #############
    # UI Tweaks #
    #############
    # Disable the live UI customizer to lock premium theme
    "show_ui_builder": False,

    ###############
    # Change view #
    ###############
    # Render out the change view as a single form, or in tabs (horizontal/vertical/collapsible/carousel)
    "changeform_format": "horizontal_tabs",

    # Override change forms on a per model basis
    "changeform_format_overrides": {
        "chat.customuser": "collapsible",
        "chat.chat": "horizontal_tabs",
        "chat.scribe": "vertical_tabs",
        "chat.omzo": "vertical_tabs",
        "chat.postreport": "collapsible",
        "chat.omzoreport": "collapsible",
    },

    # Language chooser (if i18n is enabled)
    "language_chooser": False,

    #################
    # Custom CSS/JS #
    #################
    # Add custom CSS for professional styling
    "custom_css": "css/admin-custom.css",
    # Add custom JS for theme switcher
    "custom_js": "js/admin-theme-switcher.js",
}

# ============================================================================
# JAZZMIN UI TWEAKS - DARK & LIGHT THEME OPTIONS
# ============================================================================

JAZZMIN_UI_TWEAKS = {
    # ===== DARK THEME (Default) =====
    # Uncomment below for DARK theme

    "navbar_small_text": False,
    "footer_small_text": False,
    "body_small_text": False,
    "brand_small_text": False,
    "brand_colour": "navbar-light",
    "accent": "accent-primary",
    "navbar": "navbar-light navbar-white",
    "no_navbar_border": False,
    "navbar_fixed": True,
    "layout_boxed": False,
    "footer_fixed": False,
    "sidebar_fixed": True,
    "sidebar": "sidebar-light-primary",
    "sidebar_nav_small_text": False,
    "sidebar_disable_expand": False,
    "sidebar_nav_child_indent": True,
    "sidebar_nav_compact_style": False,
    "sidebar_nav_legacy_style": False,
    "sidebar_nav_flat_style": False,
    "theme": "flatly",  # Professional light theme from Bootswatch
    "dark_mode_theme": None,
    "sidebar_nav_compact_style": True,
    "sidebar_nav_flat_style": False,

    # ===== LIGHT THEME (Alternative) =====
    # Comment out the DARK theme above and uncomment below for LIGHT theme

    # "navbar_small_text": False,
    # "footer_small_text": False,
    # "body_small_text": False,
    # "brand_small_text": False,
    # "brand_colour": "navbar-light",
    # "accent": "accent-primary",
    # "navbar": "navbar-light navbar-white",
    # "no_navbar_border": False,
    # "navbar_fixed": True,
    # "layout_boxed": False,
    # "footer_fixed": False,
    # "sidebar_fixed": True,
    # "sidebar": "sidebar-light-primary",
    # "sidebar_nav_small_text": False,
    # "sidebar_disable_expand": False,
    # "sidebar_nav_child_indent": True,
    # "sidebar_nav_compact_style": False,
    # "sidebar_nav_legacy_style": False,
    # "sidebar_nav_flat_style": False,
    # "theme": "flatly",  # Light theme from bootswatch
    # "dark_mode_theme": None,
}
