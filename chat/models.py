# models.py - FIXED VERSION with proper Scribe model

from django.db import models
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.utils import timezone
import uuid
import string
import secrets
import os
import logging

logger = logging.getLogger(__name__)


class CustomUser(AbstractUser):
    """Custom user model with additional fields"""
    THEME_CHOICES = [
        # Light themes
        ('light', 'Light'),
        ('lavender', 'Lavender'),
        ('rose', 'Rose'),
        ('mint', 'Mint'),
        ('peach', 'Peach'),
        ('sky', 'Sky'),
        # Dark themes
        ('dark', 'Dark'),
        ('midnight', 'Midnight'),
        ('amoled', 'AMOLED Black'),
        ('dracula', 'Dracula'),
        ('nord', 'Nord'),
        ('tokyo_night', 'Tokyo Night'),
        ('synthwave', 'Synthwave'),
        ('cyberpunk', 'Cyberpunk'),
        # Nature themes
        ('forest', 'Forest'),
        ('ocean', 'Ocean'),
        ('sunset', 'Sunset'),
        ('aurora', 'Aurora'),
        ('desert', 'Desert'),
        # Professional themes
        ('charcoal', 'Charcoal'),
        ('slate', 'Slate'),
        ('graphite', 'Graphite'),
        ('mocha', 'Mocha'),
        # Vibrant themes
        ('neon', 'Neon'),
        ('coral', 'Coral'),
        ('amber', 'Amber'),
        ('emerald', 'Emerald'),
        ('sapphire', 'Sapphire'),
    ]

    GENDER_CHOICES = [
        ('male', 'Male'),
        ('female', 'Female'),
    ]

    name = models.CharField(max_length=50)
    lastname = models.CharField(max_length=50)
    email = models.EmailField(unique=True, null=True, blank=True)
    phone_number = models.CharField(
        max_length=20, unique=True, null=True, blank=True)
    profile_picture = models.ImageField(
        upload_to='profile_pics/', blank=True, null=True)
    is_online = models.BooleanField(default=False)
    last_seen = models.DateTimeField(default=timezone.now)
    is_email_verified = models.BooleanField(default=False)
    is_phone_verified = models.BooleanField(default=False)
    # Blue tick verification flag
    is_verified = models.BooleanField(default=False)
    is_private = models.BooleanField(default=False)  # Private account feature
    theme = models.CharField(
        max_length=20, choices=THEME_CHOICES, default='ocean')  # Theme preference
    gender = models.CharField(
        max_length=10, choices=GENDER_CHOICES, default='male')  # Gender preference
    bio = models.TextField(max_length=500, blank=True, null=True)
    cover_image = models.ImageField(
        upload_to='cover_pics/', blank=True, null=True)

    def __str__(self):
        return f"{self.name} {self.lastname} (@{self.username})"

    @property
    def full_name(self):
        full = f"{self.name} {self.lastname}".strip()
        return full if full else self.username

    @property
    def initials(self):
        return f"{self.name[0] if self.name else ''}{self.lastname[0] if self.lastname else ''}".upper()

    @property
    def follower_count(self):
        """Get the number of followers"""
        return self.followers.count()

    @property
    def following_count(self):
        """Get the number of users this user is following"""
        return self.following.count()

    @property
    def profile_picture_url(self):
        """Get profile picture URL or return default placeholder"""
        if self.profile_picture and hasattr(self.profile_picture, 'url'):
            return self.profile_picture.url
        # Return a stylish gradient placeholder with user initials style
        # Rounded square with Odnix brand gradient (#667eea to #764ba2)
        return f'https://ui-avatars.com/api/?name={self.username}&background=667eea&color=fff&size=200&rounded=false&bold=true&format=svg'

    @property
    def cover_image_url(self):
        """Get cover image URL if it exists"""
        if self.cover_image and hasattr(self.cover_image, 'url'):
            return self.cover_image.url
        return None

    def mark_online(self):
        self.is_online = True
        self.last_seen = timezone.now()
        self.save(update_fields=['is_online', 'last_seen'])

    def mark_offline(self):
        self.is_online = False
        self.last_seen = timezone.now()  # Update last_seen when going offline
        self.save(update_fields=['is_online', 'last_seen'])


class Chat(models.Model):
    """Model for chats with enhanced group functionality"""
    CHAT_TYPE_CHOICES = [
        ('private', 'Private'),
        ('group', 'Group'),
    ]

    participants = models.ManyToManyField(
        CustomUser, related_name='chats', blank=True)
    chat_type = models.CharField(
        max_length=10, choices=CHAT_TYPE_CHOICES, default='private')
    name = models.CharField(max_length=100, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    group_avatar = models.ImageField(
        upload_to='group_avatars/', blank=True, null=True)
    admin = models.ForeignKey(CustomUser, on_delete=models.CASCADE,
                              related_name='admin_chats', null=True, blank=True)
    invite_code = models.CharField(
        max_length=20, unique=True, blank=True, null=True)
    is_public = models.BooleanField(default=False)
    max_participants = models.IntegerField(default=100)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def save(self, *args, **kwargs):
        if self.chat_type == 'group' and not self.invite_code:
            self.invite_code = self.generate_invite_code()
        super().save(*args, **kwargs)

    def generate_invite_code(self):
        """Generate a unique invite code"""
        while True:
            code = ''.join(secrets.choice(
                string.ascii_letters + string.digits) for _ in range(10))
            if not Chat.objects.filter(invite_code=code).exists():
                return code

    @property
    def invite_link(self):
        """Get the full invite link for this group"""
        if self.invite_code:
            from django.conf import settings
            domain = getattr(settings, 'SITE_DOMAIN', 'https://odnix.org')
            return f"{domain}/join-group/{self.invite_code}/"
        return None

    @property
    def participant_count(self):
        """Get current participant count"""
        return self.participants.count()

    @property
    def can_add_participants(self):
        """Check if more participants can be added"""
        return self.participant_count < self.max_participants

    def __str__(self):
        if self.chat_type == 'group':
            return self.name or f"Group Chat {self.id}"
        else:
            participants = self.participants.all()[:2]
            return f"Chat between {' and '.join([p.username for p in participants])}"


class ChatAcceptance(models.Model):
    """
    Tracks whether a user has accepted a chat (like Instagram DM requests).

    When a new user sends a DM:
    1. Chat is created with both participants
    2. ChatAcceptance is created ONLY for the sender (they auto-accept by initiating)
    3. Recipient sees chat in "Requests" tab
    4. When recipient replies or clicks "Accept", ChatAcceptance is created for them
    5. Chat moves to "All" tab for recipient
    """
    chat = models.ForeignKey(
        Chat, on_delete=models.CASCADE, related_name='acceptances')
    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='chat_acceptances')
    accepted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['chat', 'user']
        ordering = ['-accepted_at']

    def __str__(self):
        return f"{self.user.username} accepted chat {self.chat.id}"


class GroupJoinRequest(models.Model):
    """Model for group join requests"""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    group = models.ForeignKey(
        Chat, on_delete=models.CASCADE, related_name='join_requests')
    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='join_requests')
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default='pending')
    message = models.TextField(blank=True, null=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    responded_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='handled_requests')

    class Meta:
        unique_together = ('group', 'user')
        ordering = ['-requested_at']

    def __str__(self):
        return f"{self.user.username} wants to join {self.group.name} ({self.status})"


class Message(models.Model):
    """Model for chat messages with media support"""
    MESSAGE_TYPE_CHOICES = [
        ('text', 'Text'),
        ('system', 'System'),
        ('media', 'Media'),
    ]

    MEDIA_TYPE_CHOICES = [
        ('image', 'Image'),
        ('video', 'Video'),
        ('document', 'Document'),
    ]

    chat = models.ForeignKey(
        Chat, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, null=True, blank=True)
    content = models.TextField()
    message_type = models.CharField(
        max_length=10, choices=MESSAGE_TYPE_CHOICES, default='text')
    media_url = models.URLField(blank=True, null=True)
    media_type = models.CharField(
        max_length=10, choices=MEDIA_TYPE_CHOICES, blank=True, null=True)
    media_filename = models.CharField(max_length=255, blank=True, null=True)
    media_size = models.BigIntegerField(blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)
    reactions = models.JSONField(default=dict, blank=True)
    reply_to = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True, related_name='replies')
    one_time = models.BooleanField(default=False)  # For one-time messages
    # When one-time message was consumed
    consumed_at = models.DateTimeField(null=True, blank=True)

    # Message Editing feature
    is_edited = models.BooleanField(default=False)
    edited_at = models.DateTimeField(null=True, blank=True)
    # Store original content before edit
    original_content = models.TextField(blank=True, null=True)

    # Pinned Messages feature
    is_pinned = models.BooleanField(default=False)
    pinned_at = models.DateTimeField(null=True, blank=True)
    pinned_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='pinned_messages')

    # Story Reply - Reference to story if this message is a reply to a story
    story_reply = models.ForeignKey(
        'Story', on_delete=models.SET_NULL, null=True, blank=True, related_name='chat_replies',
        help_text="Story that this message is replying to"
    )

    # NEW: Shared Content Support
    shared_scribe = models.ForeignKey(
        'Scribe', on_delete=models.SET_NULL, null=True, blank=True, related_name='shared_messages',
        help_text="Scribe shared in this message"
    )
    shared_omzo = models.ForeignKey(
        'Omzo', on_delete=models.SET_NULL, null=True, blank=True, related_name='shared_messages',
        help_text="Omzo shared in this message"
    )

    class Meta:
        ordering = ['timestamp']
        indexes = [
            models.Index(fields=['one_time', 'consumed_at'],
                         name='msg_onetime_idx'),
            models.Index(fields=['chat', 'one_time'],
                         name='msg_chat_onetime_idx'),
        ]

    def __str__(self):
        sender_name = self.sender.username if self.sender else "System"
        if self.media_url:
            return f"{sender_name}: [Media: {self.media_type}]"
        return f"{sender_name}: {self.content[:50]}..."

    @property
    def has_media(self):
        """Check if message has media attachment"""
        return bool(self.media_url)

    @property
    def is_image(self):
        """Check if message contains an image"""
        return self.media_type == 'image'

    @property
    def is_video(self):
        """Check if message contains a video"""
        return self.media_type == 'video'

    @property
    def can_be_edited(self):
        """Check if message can still be edited (within 15 minutes)"""
        from django.utils import timezone
        if not self.timestamp:
            return False
        time_diff = timezone.now() - self.timestamp
        return time_diff.total_seconds() < 900  # 15 minutes = 900 seconds

    @property
    def is_read_by_recipient(self):
        """Check if message has been read by anyone other than the sender (for read receipts)"""
        if not self.sender:
            return False
        return self.read_receipts.exclude(user=self.sender).exists()


class Story(models.Model):
    """Model for user stories - Instagram-like"""
    STORY_TYPE_CHOICES = [
        ('image', 'Image'),
        ('video', 'Video'),
        ('text', 'Text'),
    ]

    TEXT_POSITION_CHOICES = [
        ('top', 'Top'),
        ('center', 'Center'),
        ('bottom', 'Bottom'),
    ]

    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='stories')
    # For text stories or captions
    content = models.TextField(blank=True, null=True)
    media_file = models.FileField(
        upload_to='story_media/', blank=True, null=True)  # For image/video stories
    story_type = models.CharField(
        max_length=10, choices=STORY_TYPE_CHOICES, default='text')
    background_color = models.CharField(
        max_length=7, default='#667eea')  # For text stories
    text_color = models.CharField(
        max_length=7, default='#ffffff')  # For text stories
    text_position = models.CharField(
        max_length=10, choices=TEXT_POSITION_CHOICES, default='center')  # Text position
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()  # Stories expire after 24 hours
    is_active = models.BooleanField(default=True)
    image_transform = models.JSONField(
        default=dict, blank=True)  # Store scale, x, y, rotation
    text_size = models.FloatField(default=22.0)  # Text font size
    # Removed old views ManyToManyField - now using StoryView model

    # Story Repost - For sharing someone's story to your own story (Instagram-style)
    shared_from_story = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='story_reposts', help_text="Original story if this is a repost"
    )

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + timezone.timedelta(hours=24)
        super().save(*args, **kwargs)

    @property
    def is_expired(self):
        """Check if story has expired"""
        return timezone.now() > self.expires_at

    @property
    def view_count(self):
        """Get story view count"""
        return self.story_views.count()

    @property
    def like_count(self):
        """Get story like count"""
        return self.story_likes.count()

    @property
    def reply_count(self):
        """Get story reply count"""
        return self.story_replies.count()

    @property
    def is_liked_by_user(self, user):
        """Check if story is liked by a specific user"""
        if not user or user.is_anonymous:
            return False
        return self.story_likes.filter(user=user).exists()

    @property
    def media_url(self):
        """Get media URL if exists"""
        if self.media_file and hasattr(self.media_file, 'url'):
            return self.media_file.url
        return None

    def __str__(self):
        return f"{self.user.username}'s story - {self.story_type}"


class StoryView(models.Model):
    """Model to track detailed story views with timestamps"""
    story = models.ForeignKey(
        Story, on_delete=models.CASCADE, related_name='story_views')
    viewer = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='story_views_made')
    viewed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['story', 'viewer']  # One view per user per story
        ordering = ['-viewed_at']

    def __str__(self):
        return f"{self.viewer.username} viewed {self.story.user.username}'s story"


class StoryLike(models.Model):
    """Model for story likes"""
    story = models.ForeignKey(
        Story, on_delete=models.CASCADE, related_name='story_likes')
    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='story_likes_given')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['story', 'user']  # One like per user per story
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} liked {self.story.user.username}'s story"


class StoryReply(models.Model):
    """Model for story replies - only visible to story poster"""
    story = models.ForeignKey(
        Story, on_delete=models.CASCADE, related_name='story_replies')
    replier = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='story_replies_made')
    content = models.TextField(max_length=500)  # Reply content
    created_at = models.DateTimeField(auto_now_add=True)
    # Track if story poster has read the reply
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Reply to {self.story.user.username}'s story by {self.replier.username}"


class Scribe(models.Model):
    """Model for user scribes/posts with FIXED image support"""
    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='scribes')
    # Allow blank content for image-only scribes
    content = models.TextField(max_length=280, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    # FIXED: Enhanced media support for scribes
    image = models.ImageField(
        upload_to='scribe_images/', blank=True, null=True)  # Direct image upload

    # Code Scribe fields (optional)
    content_type = models.CharField(max_length=32, default='text')
    code_html = models.TextField(blank=True, null=True)
    code_css = models.TextField(blank=True, null=True)
    code_js = models.TextField(blank=True, null=True)
    code_bundle = models.TextField(blank=True, null=True)

    # REPOST FIELDS
    original_scribe = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True, related_name='reposts')
    original_omzo = models.ForeignKey(
        'Omzo', on_delete=models.SET_NULL, null=True, blank=True, related_name='reposts')
    original_story = models.ForeignKey(
        'Story', on_delete=models.SET_NULL, null=True, blank=True, related_name='reposts')
    quote_source = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True, related_name='quotes')

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.user.username}: {self.content[:50]}..." if self.content else f"{self.user.username}: [Image Scribe]"

    @property
    def like_count(self):
        """Get the count of likes for this scribe"""
        return self.scribe_likes.count()

    @property
    def comment_count(self):
        """Get the count of comments for this scribe"""
        return self.comments.count()

    def is_liked_by(self, user):
        """Check if a specific user has liked this scribe"""
        if not user.is_authenticated:
            return False
        return self.scribe_likes.filter(user=user).exists()

    @property
    def has_media(self):
        """Check if scribe has media attachment"""
        return bool(self.image)

    @property
    def image_url(self):
        """Get scribe image URL"""
        if self.image and hasattr(self.image, 'url'):
            return self.image.url
        return None

    @property
    def is_repost(self):
        """Check if this scribe is a repost of other content"""
        return bool(self.original_scribe or self.original_omzo or self.original_story)


class Comment(models.Model):
    """Model for scribe comments"""
    scribe = models.ForeignKey(
        Scribe, on_delete=models.CASCADE, related_name='comments')
    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='user_comments')
    content = models.TextField(max_length=500)
    timestamp = models.DateTimeField(auto_now_add=True)
    parent = models.ForeignKey(
        'self', on_delete=models.CASCADE, null=True, blank=True, related_name='replies')

    class Meta:
        ordering = ['timestamp']

    def __str__(self):
        return f"{self.user.username} commented on {self.scribe.user.username}'s scribe"

    @property
    def reply_count(self):
        """Get the count of replies to this comment"""
        return self.replies.count()

    @property
    def like_count(self):
        """Get the count of likes on this comment"""
        return self.comment_likes.count()


class CommentLike(models.Model):
    """Model for comment likes"""
    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='user_comment_likes')
    comment = models.ForeignKey(
        Comment, on_delete=models.CASCADE, related_name='comment_likes')
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'comment')
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.user.full_name} liked a comment"


class Like(models.Model):
    """Model for scribe likes"""
    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='user_likes')
    scribe = models.ForeignKey(
        Scribe, on_delete=models.CASCADE, related_name='scribe_likes')
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'scribe')
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.user.full_name} liked {self.scribe.user.full_name}'s scribe"


class Dislike(models.Model):
    """Model for scribe dislikes"""
    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='user_dislikes')
    scribe = models.ForeignKey(
        Scribe, on_delete=models.CASCADE, related_name='scribe_dislikes')
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'scribe')
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.user.full_name} disliked {self.scribe.user.full_name}'s scribe"


class SavedPost(models.Model):
    """Model for saved/bookmarked posts"""
    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='saved_posts')
    scribe = models.ForeignKey(
        Scribe, on_delete=models.CASCADE, related_name='saved_by')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'scribe')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} saved {self.scribe.user.username}'s post"


class PostReport(models.Model):
    """Model for reported posts"""
    COPYRIGHT_TYPE_CHOICES = [
        ('audio', 'Audio Copyright'),
        ('content', 'Content Copyright'),
        ('both', 'Both Audio and Content Copyright'),
    ]

    REPORT_REASONS = [
        ('copyright', 'Copyright Infringement'),
        ('spam', 'Spam'),
        ('inappropriate', 'Inappropriate Content'),
        ('harassment', 'Harassment or Bullying'),
        ('violence', 'Violence or Threats'),
        ('hate_speech', 'Hate Speech'),
        ('false_info', 'False Information'),
        ('other', 'Other'),
    ]

    reporter = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='reports_made')
    scribe = models.ForeignKey(
        Scribe, on_delete=models.CASCADE, related_name='reports')
    reason = models.CharField(max_length=20, choices=REPORT_REASONS)
    description = models.TextField(blank=True, null=True)
    # Copyright-specific fields
    copyright_description = models.TextField(
        blank=True, null=True, help_text="Description of copyright infringement (optional)")
    copyright_type = models.CharField(
        max_length=10,
        choices=COPYRIGHT_TYPE_CHOICES,
        blank=True,
        null=True,
        help_text="Whether the copyright is for audio or content"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed = models.BooleanField(default=False)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('reporter', 'scribe')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.reporter.username} reported {self.scribe.user.username}'s post for {self.reason}"

    @property
    def copyright_info(self):
        """Return copyright type info for notifications"""
        if self.reason == 'copyright' and self.copyright_type:
            return self.get_copyright_type_display()
        return None


class Follow(models.Model):
    """Model for user following relationships"""
    follower = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='following')
    following = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='followers')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('follower', 'following')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.follower.full_name} follows {self.following.full_name}"


class Block(models.Model):
    """Model for user blocking relationships"""
    blocker = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='blocking')
    blocked = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='blocked_by')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('blocker', 'blocked')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.blocker.full_name} blocks {self.blocked.full_name}"


class FollowRequest(models.Model):
    """Model for follow requests to private accounts"""
    requester = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='sent_requests')
    target = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='received_requests')
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=[
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('declined', 'Declined')
    ], default='pending')

    class Meta:
        unique_together = ('requester', 'target')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.requester.full_name} → {self.target.full_name} ({self.status})"


class DismissedSuggestion(models.Model):
    """Model for tracking dismissed user suggestions"""
    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='dismissed_suggestions')
    dismissed_user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='dismissed_by')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'dismissed_user')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} dismissed {self.dismissed_user.username}"


class EmailVerificationToken(models.Model):
    """Model for email verification tokens (OTP)"""
    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='verification_tokens', null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    registration_data = models.TextField(null=True, blank=True)
    # Changed to 6 chars for OTP, removed unique=True
    token = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        if not self.token:
            # Generate 6-digit OTP
            import random
            self.token = ''.join([str(random.randint(0, 9)) for _ in range(6)])
        if not self.expires_at:
            # OTP expires in 10 minutes (shorter than link)
            self.expires_at = timezone.now() + timezone.timedelta(minutes=10)
        super().save(*args, **kwargs)

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    def __str__(self):
        if self.user:
            return f"OTP for {self.user.username}: {self.token}"
        return f"OTP for {self.email}: {self.token}"


class PhoneVerificationToken(models.Model):
    """Model for phone verification tokens (OTP)"""
    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='phone_verification_tokens', null=True, blank=True)
    phone_number = models.CharField(max_length=20, null=True, blank=True)
    # JSON encoded data to store registration info
    registration_data = models.TextField(null=True, blank=True)
    token = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        if not self.token:
            # Generate 6-digit OTP
            import random
            self.token = ''.join([str(random.randint(0, 9)) for _ in range(6)])
        if not self.expires_at:
            # OTP expires in 10 minutes
            self.expires_at = timezone.now() + timezone.timedelta(minutes=10)
        super().save(*args, **kwargs)

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    def __str__(self):
        if self.user:
            return f"OTP for user {self.user.username}: {self.token}"
        return f"OTP for {self.phone_number}: {self.token}"


class EmojiSet(models.Model):
    """Model for storing custom emoji sets"""
    name = models.CharField(max_length=50)
    description = models.TextField(blank=True, null=True)
    emojis = models.JSONField(default=list)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class MessageReaction(models.Model):
    """Model for emoji reactions to messages"""
    message = models.ForeignKey(
        Message, on_delete=models.CASCADE, related_name='message_reactions')
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    emoji = models.CharField(max_length=10)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('message', 'user', 'emoji')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} reacted {self.emoji} to message {self.message.id}"


class MessageDeletion(models.Model):
    """Model to track messages deleted for specific users (delete for me functionality)"""
    message = models.ForeignKey(
        Message, on_delete=models.CASCADE, related_name='deletions')
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    deleted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('message', 'user')
        ordering = ['-deleted_at']

    def __str__(self):
        return f"Message {self.message.id} deleted for {self.user.username}"


class MessageRead(models.Model):
    """Model for tracking message read receipts per recipient"""
    message = models.ForeignKey(
        Message, on_delete=models.CASCADE, related_name='read_receipts')
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('message', 'user')
        ordering = ['-read_at']

    def __str__(self):
        return f"Message {self.message.id} read by {self.user.username} at {self.read_at}"


class Hashtag(models.Model):
    """Model for hashtags used in scribes"""
    name = models.CharField(
        max_length=100, unique=True)  # Hashtag without the # symbol
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"#{self.name}"

    @property
    def scribe_count(self):
        """Get count of scribes using this hashtag"""
        return self.scribes.count()


class ScribeHashtag(models.Model):
    """Model for linking scribes to hashtags (many-to-many)"""
    scribe = models.ForeignKey(
        Scribe, on_delete=models.CASCADE, related_name='scribe_hashtags')
    hashtag = models.ForeignKey(
        Hashtag, on_delete=models.CASCADE, related_name='scribes')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('scribe', 'hashtag')
        ordering = ['-created_at']

    def __str__(self):
        return f"#{self.hashtag.name} in scribe {self.scribe.id}"


class Mention(models.Model):
    """Model for @mentions in scribes"""
    scribe = models.ForeignKey(
        Scribe, on_delete=models.CASCADE, related_name='mentions')
    mentioned_user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='scribe_mentions')
    created_at = models.DateTimeField(auto_now_add=True)
    # Track if mentioned user has seen the mention
    is_read = models.BooleanField(default=False)

    class Meta:
        unique_together = ('scribe', 'mentioned_user')
        ordering = ['-created_at']

    def __str__(self):
        return f"@{self.mentioned_user.username} mentioned in scribe {self.scribe.id}"


class PinnedChat(models.Model):
    """Model for pinned conversations per user"""
    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='pinned_chats')
    chat = models.ForeignKey(
        Chat, on_delete=models.CASCADE, related_name='pinned_by_users')
    pinned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'chat')
        ordering = ['-pinned_at']

    def __str__(self):
        return f"{self.user.username} pinned chat {self.chat.id}"


class StarredMessage(models.Model):
    """Model for starred/saved messages per user"""
    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='starred_messages')
    message = models.ForeignKey(
        Message, on_delete=models.CASCADE, related_name='starred_by')
    starred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'message')
        ordering = ['-starred_at']

    def __str__(self):
        return f"{self.user.username} starred message {self.message.id}"


class TypingStatus(models.Model):
    """Model for tracking typing status in chats"""
    chat = models.ForeignKey(
        Chat, on_delete=models.CASCADE, related_name='typing_statuses')
    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='typing_in_chats')
    started_typing_at = models.DateTimeField(auto_now=True)
    is_typing = models.BooleanField(default=False)

    class Meta:
        unique_together = ('chat', 'user')

    def __str__(self):
        status = "typing" if self.is_typing else "not typing"
        return f"{self.user.username} is {status} in chat {self.chat.id}"

    @property
    def is_still_typing(self):
        """Check if user is still typing (within last 3 seconds)"""
        if not self.is_typing:
            return False
        time_diff = timezone.now() - self.started_typing_at
        return time_diff.total_seconds() < 3  # 3 second timeout


class P2PSignal(models.Model):
    """
    Store P2P WebRTC signaling data for both file transfers and video/audio calls

    This model serves as a fallback mechanism when WebSocket connections fail:
    1. Signals are always stored in DB first (dual-path strategy)
    2. WebSocket provides real-time P2P signaling (preferred)
    3. HTTP polling retrieves signals from DB if WebSocket fails (fallback)

    Signal types:
    - webrtc.offer: Initial call offer with SDP
    - webrtc.answer: Answer to call offer with SDP
    - webrtc.ice: ICE candidates for connection negotiation
    - webrtc.end: Call termination signal
    """
    chat = models.ForeignKey(
        'Chat', on_delete=models.CASCADE, related_name='p2p_signals')
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sent_p2p_signals')
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='received_p2p_signals')
    # Contains type, sdp/candidate, audioOnly, etc.
    signal_data = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    is_consumed = models.BooleanField(default=False)

    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['chat', 'target_user', 'is_consumed']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        signal_type = self.signal_data.get('type', 'unknown') if isinstance(
            self.signal_data, dict) else 'unknown'
        return f"P2P Signal ({signal_type}) from {self.sender.username} to {self.target_user.username}"

    @classmethod
    def cleanup_old_signals(cls):
        """
        Remove old signals to prevent database bloat
        - Consumed signals older than 1 minute
        - Unconsumed signals older than 5 minutes (stale)
        """
        from datetime import timedelta

        # Remove consumed signals older than 1 minute
        consumed_cutoff = timezone.now() - timedelta(minutes=1)
        deleted_consumed = cls.objects.filter(
            is_consumed=True,
            created_at__lt=consumed_cutoff
        ).delete()[0]

        # Remove unconsumed signals older than 5 minutes (stale/abandoned)
        unconsumed_cutoff = timezone.now() - timedelta(minutes=5)
        deleted_stale = cls.objects.filter(
            is_consumed=False,
            created_at__lt=unconsumed_cutoff
        ).delete()[0]

        if deleted_consumed > 0 or deleted_stale > 0:
            logger.info(
                f"[P2PSignal] Cleaned up {deleted_consumed} consumed and {deleted_stale} stale signals")

        return deleted_consumed + deleted_stale


class Omzo(models.Model):
    """Model for short video omzo"""
    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='omzos')
    video_file = models.FileField(upload_to='omzos/')
    caption = models.TextField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    views_count = models.PositiveIntegerField(default=0)
    is_muted = models.BooleanField(
        default=False, help_text="If True, audio will be disabled for all users")

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Omzo by {self.user.username} at {self.created_at}"

    @property
    def like_count(self):
        return self.likes.count()

    @property
    def dislike_count(self):
        return self.dislikes.count()

    @property
    def comment_count(self):
        return self.comments.count()

    def is_liked_by(self, user):
        if not user.is_authenticated:
            return False
        return self.likes.filter(user=user).exists()


class OmzoLike(models.Model):
    """Model for omzo likes"""
    omzo = models.ForeignKey(
        Omzo, on_delete=models.CASCADE, related_name='likes')
    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='liked_omzos')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('omzo', 'user')


class OmzoDislike(models.Model):
    """Model for omzo dislikes"""
    omzo = models.ForeignKey(
        Omzo, on_delete=models.CASCADE, related_name='dislikes')
    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='disliked_omzos')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('omzo', 'user')


class OmzoComment(models.Model):
    """Model for omzo comments"""
    omzo = models.ForeignKey(
        Omzo, on_delete=models.CASCADE, related_name='comments')
    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='omzo_comments')
    content = models.TextField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)
    parent = models.ForeignKey(
        'self', on_delete=models.CASCADE, null=True, blank=True, related_name='replies')


class OmzoReport(models.Model):
    """Model for reported omzos"""
    COPYRIGHT_TYPE_CHOICES = [
        ('audio', 'Audio Copyright'),
        ('content', 'Content Copyright'),
        ('both', 'Both Audio and Content Copyright'),
    ]

    REPORT_REASONS = [
        ('spam', 'Spam'),
        ('inappropriate', 'Inappropriate Content'),
        ('harassment', 'Harassment or Bullying'),
        ('violence', 'Violence or Threats'),
        ('hate_speech', 'Hate Speech'),
        ('false_info', 'False Information'),
        ('copyright', 'Copyright Infringement'),
        ('other', 'Other'),
    ]

    reporter = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='omzo_reports_made')
    omzo = models.ForeignKey(
        Omzo, on_delete=models.CASCADE, related_name='reports')
    reason = models.CharField(max_length=20, choices=REPORT_REASONS)
    description = models.TextField(blank=True, null=True)
    # Copyright-specific fields
    copyright_description = models.TextField(
        blank=True, null=True, help_text="Description of copyright infringement (optional)")
    copyright_type = models.CharField(
        max_length=10,
        choices=COPYRIGHT_TYPE_CHOICES,
        blank=True,
        null=True,
        help_text="Whether the copyright is for audio or content"
    )
    disable_audio = models.BooleanField(
        default=False, help_text="If checked, audio will be disabled for this omzo")
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed = models.BooleanField(default=False)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('reporter', 'omzo')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.reporter.username} reported omzo {self.omzo.id} for {self.reason}"

    @property
    def copyright_info(self):
        """Return copyright type info for notifications"""
        if self.reason == 'copyright' and self.copyright_type:
            return self.get_copyright_type_display()
        return None


class ProfileView(models.Model):
    """Model to track user profile views"""
    viewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile_views_made')
    viewed_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile_views_received')
    # Update timestamp on each view
    viewed_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('viewer', 'viewed_user')
        ordering = ['-viewed_at']

    def __str__(self):
        return f"{self.viewer.username} viewed {self.viewed_user.username}"


class ChatRequest(models.Model):
    """Model for pending chat/message requests.

    When a user shares content to someone they don't have an existing chat with,
    it creates a request that the recipient must accept before the message
    appears in their regular chat inbox.

    Flow:
    1. User A shares Scribe/Omzo/Story to User B (no existing chat)
    2. ChatRequest is created with status='pending'
    3. User B sees request in their "Requests" tab
    4. User B accepts -> Chat created, message sent, status='accepted'
       OR User B declines -> status='declined'
    """

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('declined', 'Declined'),
    ]

    CONTENT_TYPE_CHOICES = [
        ('scribe', 'Scribe'),
        ('omzo', 'Omzo'),
        ('story', 'Story'),
        ('text', 'Text Message'),
    ]

    sender = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='sent_chat_requests',
        help_text="User who initiated the share")
    recipient = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='received_chat_requests',
        help_text="User receiving the shared content")

    # Shared content - only ONE of these should be set based on content_type
    shared_scribe = models.ForeignKey(
        'Scribe', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='share_requests', help_text="Shared scribe if content_type='scribe'")
    shared_omzo = models.ForeignKey(
        'Omzo', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='share_requests', help_text="Shared omzo if content_type='omzo'")
    shared_story = models.ForeignKey(
        'Story', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='share_requests', help_text="Shared story if content_type='story'")

    # Request metadata
    message = models.TextField(
        max_length=500, blank=True, default='',
        help_text="Optional message sent with the shared content")
    content_type = models.CharField(
        max_length=10, choices=CONTENT_TYPE_CHOICES, default='scribe')
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default='pending',
        db_index=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(
        null=True, blank=True, help_text="When request was accepted/declined")

    # Chat created after acceptance (for reference)
    created_chat = models.ForeignKey(
        'Chat', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='origin_request', help_text="Chat created when request was accepted")

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', 'status', '-created_at']),
            models.Index(fields=['sender', '-created_at']),
        ]
        # Prevent duplicate pending requests for same sender->recipient->content
        constraints = [
            models.UniqueConstraint(
                fields=['sender', 'recipient', 'shared_scribe'],
                condition=models.Q(status='pending') & ~models.Q(
                    shared_scribe=None),
                name='unique_pending_scribe_share_request'
            ),
            models.UniqueConstraint(
                fields=['sender', 'recipient', 'shared_omzo'],
                condition=models.Q(status='pending') & ~models.Q(
                    shared_omzo=None),
                name='unique_pending_omzo_share_request'
            ),
            models.UniqueConstraint(
                fields=['sender', 'recipient', 'shared_story'],
                condition=models.Q(status='pending') & ~models.Q(
                    shared_story=None),
                name='unique_pending_story_share_request'
            ),
        ]

    def __str__(self):
        content_preview = ''
        if self.shared_scribe:
            content_preview = f"Scribe #{self.shared_scribe_id}"
        elif self.shared_omzo:
            content_preview = f"Omzo #{self.shared_omzo_id}"
        elif self.shared_story:
            content_preview = f"Story #{self.shared_story_id}"
        return f"{self.sender.username} → {self.recipient.username}: {content_preview} ({self.status})"

    @property
    def shared_content(self):
        """Get the actual shared content object"""
        return self.shared_scribe or self.shared_omzo or self.shared_story

    @property
    def shared_content_preview(self):
        """Get a preview of the shared content for UI display"""
        if self.shared_scribe:
            scribe = self.shared_scribe
            return {
                'type': 'scribe',
                'id': scribe.id,
                'content': scribe.content[:100] if scribe.content else '',
                'has_image': scribe.has_media,
                'image_url': scribe.image_url,
                'author_username': scribe.user.username,
                'author_name': scribe.user.full_name,
                'author_avatar': scribe.user.profile_picture_url,
            }
        elif self.shared_omzo:
            omzo = self.shared_omzo
            return {
                'type': 'omzo',
                'id': omzo.id,
                'caption': omzo.caption[:100] if omzo.caption else '',
                'video_url': omzo.video_file.url if omzo.video_file else None,
                'author_username': omzo.user.username,
                'author_name': omzo.user.full_name,
                'author_avatar': omzo.user.profile_picture_url,
            }
        elif self.shared_story:
            story = self.shared_story
            return {
                'type': 'story',
                'id': story.id,
                'content': story.content[:100] if story.content else '',
                'media_url': story.media_url,
                'author_username': story.user.username,
                'author_name': story.user.full_name,
                'author_avatar': story.user.profile_picture_url,
            }
        return None

    def accept(self):
        """Accept the request and create/return the chat"""
        from django.utils import timezone

        if self.status != 'pending':
            return self.created_chat

        # Find or create private chat between sender and recipient
        existing_chat = Chat.objects.filter(
            chat_type='private',
            participants=self.sender
        ).filter(participants=self.recipient).first()

        if existing_chat:
            chat = existing_chat
        else:
            chat = Chat.objects.create(chat_type='private')
            chat.participants.add(self.sender, self.recipient)

        # Create message with shared content
        from chat.models import Message
        message_content = self.message if self.message else "Shared content"

        # Build shared content reference in message
        shared_data = {
            'type': self.content_type,
        }
        if self.shared_scribe:
            shared_data['scribe_id'] = self.shared_scribe_id
        elif self.shared_omzo:
            shared_data['omzo_id'] = self.shared_omzo_id
        elif self.shared_story:
            shared_data['story_id'] = self.shared_story_id

        Message.objects.create(
            chat=chat,
            sender=self.sender,
            content=message_content,
            message_type='text',
            # Store shared ref in reactions JSON
            reactions={'shared_content': shared_data}
        )

        # Update request status
        self.status = 'accepted'
        self.responded_at = timezone.now()
        self.created_chat = chat
        self.save(update_fields=['status', 'responded_at', 'created_chat'])

        return chat

    def decline(self):
        """Decline the request"""
        from django.utils import timezone

        if self.status != 'pending':
            return

        self.status = 'declined'
        self.responded_at = timezone.now()
        self.save(update_fields=['status', 'responded_at'])


class Notification(models.Model):

    """Model to store and persist user notifications"""
    NOTIFICATION_TYPES = [
        ('message', 'New Message'),
        ('call', 'Incoming Call'),
        ('missed_call', 'Missed Call'),
        ('follow', 'New Follower'),
        ('like', 'Post Liked'),
        ('comment', 'New Comment'),
        ('mention', 'Mentioned You'),
        ('story_view', 'Story Viewed'),
        ('story_reply', 'Story Reply'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sent_notifications',
        null=True, blank=True)
    notification_type = models.CharField(
        max_length=20, choices=NOTIFICATION_TYPES)
    title = models.CharField(max_length=100)
    message = models.TextField(max_length=500)
    # Extra data (chat_id, post_id, etc.)
    data = models.JSONField(default=dict, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_read', '-created_at']),
        ]

    def __str__(self):
        return f"{self.notification_type}: {self.title} -> {self.user.username}"

    def mark_read(self):
        self.is_read = True
        self.save(update_fields=['is_read'])


class SavedScribeItem(models.Model):
    """Model for saved scribes (posts)"""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='saved_scribe_items'
    )
    scribe = models.ForeignKey(
        'Scribe',
        on_delete=models.CASCADE,
        related_name='saved_by_users'
    )
    saved_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'scribe')
        ordering = ['-saved_at']
        indexes = [
            models.Index(fields=['user', '-saved_at']),
        ]

    def __str__(self):
        return f"{self.user.username} saved scribe {self.scribe.id}"


class SavedOmzoItem(models.Model):
    """Model for saved omzos (videos)"""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='saved_omzo_items'
    )
    omzo = models.ForeignKey(
        'Omzo',
        on_delete=models.CASCADE,
        related_name='saved_by_users'
    )
    saved_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'omzo')
        ordering = ['-saved_at']
        indexes = [
            models.Index(fields=['user', '-saved_at']),
        ]

    def __str__(self):
        return f"{self.user.username} saved omzo {self.omzo.id}"
