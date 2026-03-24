import os
import subprocess
import tempfile
import logging
from django.core.files.base import ContentFile
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from .models import Message

logger = logging.getLogger(__name__)

from django.core.cache import cache
from .encryption import decrypt_text

def should_send_call_notification(chat_id, sender_id):
    """
    Debounce call notifications to prevent duplicates when both WS and HTTP 
    fallback trigger the notification simultaneously.
    """
    cache_key = f"call_notify_debounced_{chat_id}_{sender_id}"
    if cache.get(cache_key):
        return False
    # Set timeout for 10 seconds to prevent dual-notification
    cache.set(cache_key, True, timeout=10)
    return True

def notify_sidebar_for_chat(chat, sender, last_message_text):
    channel_layer = get_channel_layer()

    recipients = chat.participants.exclude(id=sender.id)

    for user in recipients:
        unread_count = Message.objects.filter(
            chat=chat
        ).exclude(
            sender=user
        ).exclude(
            read_receipts__user=user
        ).count()

        async_to_sync(channel_layer.group_send)(
            f"sidebar_{user.id}",
            {
                "type": "sidebar_update",
                "chat_id": chat.id,
                "unread_count": unread_count,
                "last_message": decrypt_text(last_message_text),
            }
        )


def broadcast_message_to_chat(chat, message, exclude_sender=True):
    """
    Broadcast a new message to all participants in the chat via WebSocket.
    This is used when messages are sent via HTTP (e.g., media uploads).
    """
    channel_layer = get_channel_layer()
    
    # Safely get sender details
    sender_avatar = None
    if hasattr(message.sender, 'profile_picture_url'):
        sender_avatar = message.sender.profile_picture_url
    elif hasattr(message.sender, 'avatar'):
        sender_avatar = message.sender.avatar.url if message.sender.avatar else None

    sender_initials = message.sender.initials if hasattr(message.sender, 'initials') else message.sender.username[0].upper()

    message_data = {
        "id": message.id,
        "content": decrypt_text(message.content),
        "sender": message.sender.username,
        "sender_name": message.sender.full_name,
        "sender_avatar": sender_avatar,
        "sender_initials": sender_initials,
        "timestamp": message.timestamp.strftime("%H:%M"),
        "timestamp_iso": message.timestamp.isoformat(),
        "is_read": False,
        "one_time": message.one_time,
        "consumed": bool(message.consumed_at) if hasattr(message, 'consumed_at') else False,
        "sender_id": message.sender_id,
        "message_type": message.message_type,
        "media_url": message.media_url if hasattr(message, 'media_url') else None,
        "media_type": message.media_type if hasattr(message, 'media_type') else None,
        "media_filename": message.media_filename if hasattr(message, 'media_filename') else None,
        "has_media": message.has_media if hasattr(message, 'has_media') else False,
        "reply_to": {
            "id": message.reply_to.id,
            "content": decrypt_text(message.reply_to.content),
            "sender_name": message.reply_to.sender.full_name
        } if message.reply_to else None
    }
    
    # Send to the chat group - the consumer will handle distribution
    async_to_sync(channel_layer.group_send)(
        f"chat_{chat.id}",
        {
            "type": "chat_message",
            "message": message_data,
            "exclude_sender_id": message.sender_id if exclude_sender else None
        }
    )


def broadcast_message_consumed(chat, message, consumed_by_user):
    """
    Broadcast that a one-time message has been consumed to all participants.
    This ensures the sender sees the updated status immediately.
    """
    channel_layer = get_channel_layer()
    
    async_to_sync(channel_layer.group_send)(
        f"chat_{chat.id}",
        {
            "type": "message_consumed",
            "message_id": message.id,
            "consumed_by": consumed_by_user.id,
            "consumed_at": message.consumed_at.isoformat() if message.consumed_at else None
        }
    )


def clear_sidebar_unread(chat, user):
    channel_layer = get_channel_layer()

    async_to_sync(channel_layer.group_send)(
        f"sidebar_{user.id}",
        {
            "type": "sidebar_update",
            "chat_id": chat.id,
            "unread_count": 0,
            "last_message": chat.messages.order_by('-timestamp').first().content if chat.messages.exists() else ''
        }
    )

def compress_video(video_file, max_size_mb=8, crf=32):
    """
    Compress video using ffmpeg.
    
    Args:
        video_file: InMemoryUploadedFile or TemporaryUploadedFile
        max_size_mb: Target size mostly handled by CRF, but included for API consistency
        crf: Constant Rate Factor (18-28 is good range, 32 = smaller size, decent quality)
    
    Returns:
        ContentFile (compressed) or original video_file if compression fails
    """
    if not video_file:
        return None

    # Skip very small files (< 512KB)
    if video_file.size < 512 * 1024:
        logger.info(f"Skipping compression for small file: {video_file.size} bytes")
        return video_file

    try:
        # Create temp input file
        temp_in = tempfile.NamedTemporaryFile(suffix=os.path.splitext(video_file.name)[1], delete=False)
        try:
            for chunk in video_file.chunks():
                temp_in.write(chunk)
            temp_in.flush()
            temp_in.close()  # Close file handle so ffmpeg can read it (impt on Windows)
            
            temp_in_path = temp_in.name
            
            # Create temp output file path
            temp_out_path = os.path.join(tempfile.gettempdir(), f"compressed_{os.path.basename(temp_in_path)}")
            # Enforce .mp4 for compatibility
            temp_out_path = os.path.splitext(temp_out_path)[0] + ".mp4"
            
            # Remove previous if exists
            if os.path.exists(temp_out_path):
                os.remove(temp_out_path)

            # Get FFmpeg executable path from imageio-ffmpeg
            import imageio_ffmpeg
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
            
            # Build ffmpeg command
            # -i input
            # -vcodec libx264 (H.264)
            # -crf 32 (Quality/Size balance)
            # -preset fast (Encoding speed)
            # -vf scale=-2:720 (Resize to 720p height, width auto-scaled)
            # -acodec aac (Audio)
            # -b:a 128k (Audio bitrate)
            # -movflags +faststart (Web optimization)
            command = [
                ffmpeg_exe,
                '-y', # Overwrite output
                '-i', temp_in_path,
                '-vcodec', 'libx264',
                '-crf', str(crf),
                '-preset', 'fast',
                '-vf', 'scale=-2:720',
                '-acodec', 'aac',
                '-b:a', '128k',
                '-movflags', '+faststart',
                temp_out_path
            ]
            
            # Run ffmpeg
            # Use shell=True for Windows might be needed if ffmpeg is in PATH but not directly executable
            # But normally subprocess finds it if in PATH
            # subprocess.run check=True ensures we catch errors
            # Capture output to avoid spamming console, but log error
            
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            if result.returncode != 0:
                logger.error(f"FFmpeg compression failed: {result.stderr.decode('utf-8')}")
                # Return original on failure
                if os.path.exists(temp_in_path):
                    os.remove(temp_in_path)
                return video_file
            
            # Check if output exists and is smaller (or reasonable)
            if os.path.exists(temp_out_path):
                new_size = os.path.getsize(temp_out_path)
                logger.info(f"Video compressed: {video_file.size} -> {new_size}")
                
                # If compression actually made it bigger (rare with CRF 28), keep original
                # Unless original was huge uncompressed avi or something
                if new_size > video_file.size and video_file.size > 50 * 1024 * 1024:
                     # Only accept bigger file if original was massive (likely raw) and we want mp4 compatibility
                     pass
                elif new_size > video_file.size:
                     logger.info("Compressed file larger than original, keeping original.")
                     os.remove(temp_out_path)
                     os.remove(temp_in_path)
                     return video_file

                # Read compressed data
                with open(temp_out_path, 'rb') as f:
                    compressed_data = f.read()
                
                # Cleanup
                os.remove(temp_out_path)
                os.remove(temp_in_path)
                
                # Create ContentFile
                new_name = os.path.splitext(video_file.name)[0] + ".mp4"
                return ContentFile(compressed_data, name=new_name)
                
            else:
                logger.error("FFmpeg did not produce output file")
                if os.path.exists(temp_in_path):
                    os.remove(temp_in_path)
                return video_file

        except Exception as e:
            logger.error(f"Error during video compression: {e}")
            if os.path.exists(temp_in.name):
                try:
                    os.remove(temp_in.name)
                except:
                    pass
            return video_file
            
    except Exception as e:
        logger.error(f"General error in video compression wrapper: {e}")
        return video_file
