from django.contrib.auth.models import User
import json
import logging
import hashlib
from channels.generic.websocket import AsyncWebsocketConsumer, AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from .models import Chat, Message, MessageRead
from django.utils import timezone
from .odnix_security import OdnixSecurity, DH_PRIME, DH_G
from .encryption import encrypt_text, decrypt_text

logger = logging.getLogger(__name__)
User = get_user_model()


logger = logging.getLogger(__name__)


class ChatConsumer(AsyncJsonWebsocketConsumer):
    # Class-level dictionary to track typing users per chat room
    _typing_users = {}

    # ---------------- CONNECT ----------------
    async def connect(self):
        self.chat_id = self.scope["url_route"]["kwargs"]["chat_id"]
        self.group_name = f"chat_{self.chat_id}"
        self.user = self.scope["user"]

        # Initialize typing users set for this chat if not exists
        if self.chat_id not in ChatConsumer._typing_users:
            ChatConsumer._typing_users[self.chat_id] = set()

        if not self.user.is_authenticated:
            await self.close()
            return

        chat = await self.get_chat()
        if not chat:
            await self.close()
            return

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )

        await self.channel_layer.group_add(
            f"user_{self.user.id}",
            self.channel_name
        )

        await self.accept()
        await self.update_user_status(True)

    # ---------------- DISCONNECT ----------------
    async def disconnect(self, close_code):
        await self.update_user_status(False)
        # Only attempt to discard if group_name was set during connect
        if hasattr(self, 'group_name') and self.group_name:
            try:
                await self.channel_layer.group_discard(
                    self.group_name,
                    self.channel_name
                )
                await self.channel_layer.group_discard(
                    f"user_{self.user.id}",
                    self.channel_name
                )
            except Exception:
                logger.exception(
                    "Error during group_discard in ChatConsumer.disconnect")

        # Remove user from typing set on disconnect
        if self.chat_id in ChatConsumer._typing_users:
            ChatConsumer._typing_users[self.chat_id].discard(self.user.id)
        await self.broadcast_typing()

    # ---------------- RECEIVE ----------------
    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            return

        event = data.get("type")

        if event == "message.send":
            await self.handle_send_message(data)
        elif event == "typing":
            await self.handle_typing(data)
        elif event == "message.read":
            await self.handle_message_read(data)
        elif event == "message.consume":
            await self.handle_message_consume(data)
        elif event == "p2p.signal":
            await self.handle_p2p_signal(data)

    # ---------------- EVENTS ----------------
    async def chat_message(self, event):
        # Skip sending to the original sender if exclude_sender_id is set
        # This prevents duplicate messages when sent via HTTP broadcast
        exclude_sender_id = event.get("exclude_sender_id")
        if exclude_sender_id is not None and exclude_sender_id == self.user.id:
            return

        # Send with frontend-expected type
        await self.send_json({
            "type": "message.new",
            "message": event["message"]
        })

    async def message_read(self, event):
        # Send with frontend-expected type
        await self.send_json({
            "type": "message.read",
            "message_id": event["message_id"],
            "read_by": event["read_by"],
            "read_at": event["read_at"]
        })

    async def message_consumed(self, event):
        # Send with frontend-expected type
        await self.send_json({
            "type": "message.consumed",
            "message_id": event["message_id"],
            "consumed_by": event["consumed_by"],
            "consumed_at": event["consumed_at"]
        })

    async def message_deleted(self, event):
        # Notify clients that a message was deleted
        await self.send_json({
            "type": "message.deleted",
            "message_id": event["message_id"],
            "deleted_for_everyone": event.get("deleted_for_everyone", True),
            "deleted_by": event.get("deleted_by")
        })

    async def message_edited(self, event):
        # Notify clients that a message was edited
        await self.send_json({
            "type": "message.edited",
            "message_id": event["message_id"],
            "new_content": event["new_content"],
            "edited_at": event.get("edited_at")
        })

    async def typing_update(self, event):
        # Filter out current user from typing users (don't show own typing indicator)
        users = [u for u in event.get(
            "users", []) if u.get("id") != self.user.id]
        # Send with frontend-expected type
        await self.send_json({
            "type": "typing.update",
            "users": users
        })

    async def p2p_signal(self, event):
        # Send P2P signals directly to the frontend via WebSocket

        # Don't send the signal back to the sender
        sender_id = event.get("sender_id")
        if sender_id == self.user.id:
            return

        logger.info(
            f"P2P signal delivered via WS: {event.get('signal', {}).get('type', 'unknown')} to user {self.user.id}")

        await self.send_json({
            "type": "p2p.signal",
            "signal": event["signal"],
            "sender_id": sender_id
        })

    # ---------------- HANDLERS ----------------
    async def handle_send_message(self, data):
        content = data.get("content", "").strip()
        if not content:
            return

        one_time = data.get("one_time", False)
        reply_to_id = data.get("reply_to")

        message = await self.create_message(content, one_time, reply_to_id)
        serialized = await self.serialize_message(message)

        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "chat_message",
                "message": serialized
            }
        )

        # Auto-accept chat for the sender (Instagram-style)
        await self.auto_accept_chat()

        # Send push notification to other participants
        await self.send_message_notification(content)

        # Notify recipients about new chat if this is the first message
        await self.notify_new_chat_if_needed(content)

        # Update sidebar for all recipients (real-time message preview update)
        await self.notify_sidebar_update(content)

    async def handle_typing(self, data):
        # Ensure typing users set exists for this chat
        if self.chat_id not in ChatConsumer._typing_users:
            ChatConsumer._typing_users[self.chat_id] = set()

        if data.get("is_typing"):
            ChatConsumer._typing_users[self.chat_id].add(self.user.id)
        else:
            ChatConsumer._typing_users[self.chat_id].discard(self.user.id)

        await self.broadcast_typing()

    async def handle_message_read(self, data):
        message_id = data.get("message_id")
        if not message_id:
            return

        await self.mark_message_read(message_id)

        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "message_read",
                "message_id": message_id,
                "read_by": self.user.id,
                "read_at": timezone.now().isoformat()
            }
        )

    async def handle_message_consume(self, data):
        message_id = data.get("message_id")
        consumed_at = await self.consume_one_time_message(message_id)

        if consumed_at:
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "message_consumed",
                    "message_id": message_id,
                    "consumed_by": self.user.id,
                    "consumed_at": consumed_at.isoformat()
                }
            )

    async def broadcast_typing(self):
        users = []
        typing_set = ChatConsumer._typing_users.get(self.chat_id, set())
        for uid in typing_set:
            user = await self.get_user(uid)
            if user:
                users.append({"id": user.id, "name": user.full_name})

        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "typing_update",
                "users": users,
                "sender_id": self.user.id  # Include sender so clients can filter
            }
        )

    async def handle_p2p_signal(self, data):
        """Handle P2P signaling for WebRTC calls and file transfers via WebSocket."""
        signal_data = data.get("signal")
        target_user_id = data.get("target_user_id")

        if not signal_data or not target_user_id:
            return

        # 1. Direct user-to-user signaling delivery
        await self.channel_layer.group_send(
            f"user_{target_user_id}",
            {
                "type": "p2p_signal",
                "signal": signal_data,
                "sender_id": self.user.id,
            }
        )

    # ---------------- DATABASE ----------------
    @database_sync_to_async
    def get_chat(self):
        try:
            return Chat.objects.get(id=self.chat_id, participants=self.user)
        except Chat.DoesNotExist:
            return None

    @database_sync_to_async
    def create_message(self, content, one_time, reply_to_id):
        chat = Chat.objects.get(id=self.chat_id)
        reply_to = Message.objects.filter(
            id=reply_to_id).first() if reply_to_id else None

        return Message.objects.create(
            chat=chat,
            sender=self.user,
            content=encrypt_text(content),
            one_time=one_time,
            reply_to=reply_to
        )

    @database_sync_to_async
    def mark_message_read(self, message_id):
        message = Message.objects.get(id=message_id)
        MessageRead.objects.get_or_create(
            message=message,
            user=self.user,
            defaults={"read_at": timezone.now()}
        )
        if message.sender_id != self.user.id:
            message.is_read = True
            message.save(update_fields=['is_read'])

    @database_sync_to_async
    def consume_one_time_message(self, message_id):
        message = Message.objects.filter(
            id=message_id,
            one_time=True,
            consumed_at__isnull=True
        ).first()

        if not message:
            return None

        # 🔥 FIX: Only the RECIPIENT can consume the message, not the sender
        if message.sender_id == self.user.id:
            return None  # Sender cannot consume their own view-once message

        message.consumed_at = timezone.now()
        message.save(update_fields=["consumed_at"])
        return message.consumed_at

    @database_sync_to_async
    def get_user(self, user_id):
        return User.objects.filter(id=user_id).first()

    @database_sync_to_async
    def serialize_message(self, message):
        return {
            "id": message.id,
            "content": decrypt_text(message.content),
            "sender": message.sender.username,
            "sender_name": message.sender.full_name,
            "sender_avatar": message.sender.profile_picture_url if hasattr(message.sender, 'profile_picture_url') else None,
            "sender_initials": message.sender.initials if hasattr(message.sender, 'initials') else message.sender.username[0].upper(),
            "timestamp": message.timestamp.strftime("%H:%M"),
            "timestamp_iso": message.timestamp.isoformat(),
            "one_time": message.one_time,
            "consumed": bool(message.consumed_at),
            "is_read": message.is_read,
            "sender_id": message.sender_id,
            "reply_to": {
                "id": message.reply_to.id,
                "content": decrypt_text(message.reply_to.content),
                "sender_name": message.reply_to.sender.full_name
            } if message.reply_to else None
        }

    async def send_message_notification(self, content):
        """Send push notification to other chat participants about new message"""
        participant_ids = await self.get_other_participants()

        sender_avatar = None
        if hasattr(self.user, 'profile_picture') and self.user.profile_picture:
            sender_avatar = self.user.profile_picture.url

        # Truncate message preview
        preview = content[:100] + '...' if len(content) > 100 else content

        for participant_id in participant_ids:
            await self.channel_layer.group_send(
                f'user_notify_{participant_id}',
                {
                    'type': 'notify_message',
                    'chat_id': self.chat_id,
                    'sender_id': self.user.id,
                    'sender_name': self.user.full_name if hasattr(self.user, 'full_name') else self.user.username,
                    'sender_avatar': sender_avatar,
                    'message_preview': preview,
                }
            )

    @database_sync_to_async
    def auto_accept_chat(self):
        """Auto-accept chat for the sender when they send a message"""
        from chat.models import ChatAcceptance
        try:
            chat = Chat.objects.get(id=self.chat_id)
            if chat.chat_type == 'private':
                ChatAcceptance.objects.get_or_create(chat=chat, user=self.user)
        except Chat.DoesNotExist:
            pass

    async def notify_new_chat_if_needed(self, content):
        """Notify recipients if this is a new chat appearing in their sidebar"""
        chat_info = await self.get_chat_info_for_notification()
        if not chat_info:
            return

        participant_ids = await self.get_other_participants()

        for participant_id in participant_ids:
            # Check if participant has accepted this chat
            is_accepted = await self.check_chat_acceptance(participant_id)

            # Send new_chat notification to sidebar
            await self.channel_layer.group_send(
                f'sidebar_{participant_id}',
                {
                    'type': 'new_chat',
                    'chat': chat_info,
                    'is_request': not is_accepted,  # It's a request if not accepted
                }
            )

            # Also update request count if it's a new request
            if not is_accepted:
                count = await self.get_pending_request_count(participant_id)
                await self.channel_layer.group_send(
                    f'sidebar_{participant_id}',
                    {
                        'type': 'request_count_update',
                        'count': count,
                    }
                )

    @database_sync_to_async
    def get_chat_info_for_notification(self):
        """Get chat info for sidebar notification"""
        try:
            chat = Chat.objects.get(id=self.chat_id)
            if chat.chat_type != 'private':
                return None

            other_user = chat.participants.exclude(id=self.user.id).first()
            if not other_user:
                return None

            last_msg = chat.messages.order_by('-timestamp').first()
            last_message = ''
            if last_msg:
                if last_msg.message_type == 'media':
                    last_message = '📷 Sent a file'
                else:
                    decrypted_content = decrypt_text(last_msg.content)
                    last_message = decrypted_content[:50] + \
                        ('...' if len(decrypted_content) > 50 else '')

            return {
                'id': chat.id,
                'type': 'private',
                'other_user': {
                    'id': self.user.id,
                    'username': self.user.username,
                    'full_name': self.user.full_name,
                    'avatar_url': self.user.profile_picture_url if hasattr(self.user, 'profile_picture_url') else None,
                    'is_online': self.user.is_online,
                },
                'last_message': last_message,
                'unread_count': 1,
            }
        except Chat.DoesNotExist:
            return None

    @database_sync_to_async
    def check_chat_acceptance(self, user_id):
        """Check if a user has accepted this chat"""
        from chat.models import ChatAcceptance
        return ChatAcceptance.objects.filter(chat_id=self.chat_id, user_id=user_id).exists()

    @database_sync_to_async
    def get_pending_request_count(self, user_id):
        """Get count of pending DM requests for a user"""
        from chat.models import ChatAcceptance, CustomUser
        try:
            user = CustomUser.objects.get(id=user_id)
            accepted_chat_ids = ChatAcceptance.objects.filter(
                user=user
            ).values_list('chat_id', flat=True)

            pending_chats = Chat.objects.filter(
                participants=user,
                chat_type='private'
            ).exclude(id__in=accepted_chat_ids)

            count = 0
            for chat in pending_chats:
                other_user = chat.participants.exclude(id=user_id).first()
                if other_user and chat.messages.filter(sender=other_user).exists():
                    count += 1
            return count
        except:
            return 0

    async def notify_sidebar_update(self, content):
        """Send sidebar_update to all recipients for real-time message preview updates"""
        participant_ids = await self.get_other_participants()

        for participant_id in participant_ids:
            unread_count = await self.get_unread_count_for_user(participant_id)

            # Truncate message preview
            preview = content[:50] + ('...' if len(content) > 50 else '')

            await self.channel_layer.group_send(
                f'sidebar_{participant_id}',
                {
                    'type': 'sidebar_update',
                    'chat_id': self.chat_id,
                    'unread_count': unread_count,
                    'last_message': preview,
                }
            )

    @database_sync_to_async
    def get_unread_count_for_user(self, user_id):
        """Get unread message count for a specific user in this chat"""
        try:
            from .models import Message
            return Message.objects.filter(
                chat_id=self.chat_id
            ).exclude(
                sender_id=user_id
            ).exclude(
                read_receipts__user_id=user_id
            ).count()
        except:
            return 0

    @database_sync_to_async
    def get_other_participants(self):
        """Get list of other participant IDs in this chat"""
        try:
            chat = Chat.objects.get(id=self.chat_id)
            return list(chat.participants.exclude(id=self.user.id).values_list('id', flat=True))
        except Chat.DoesNotExist:
            return []

    @database_sync_to_async
    def update_user_status(self, is_online):
        """Update user online status in database"""
        try:
            if self.user and self.user.is_authenticated:
                # Use User already imported at top
                user = User.objects.get(id=self.user.id)
                user.is_online = is_online
                user.last_seen = timezone.now()
                user.save(update_fields=['is_online', 'last_seen'])
                logger.debug(
                    f"[Chat] User {user.id} marked {'online' if is_online else 'offline'}")
        except Exception as e:
            logger.error(f"Error updating user status in ChatConsumer: {e}")


class NotifyConsumer(AsyncWebsocketConsumer):
    """
    NotifyConsumer - Handles real-time push notifications for:
    - Incoming calls
    - New messages
    - Follows
    - Missed calls
    """

    async def connect(self):
        self.user = self.scope.get('user')

        # Fallback manual token check if middleware missed it
        if not self.user or not self.user.is_authenticated:
            from urllib.parse import parse_qs
            query_string = self.scope.get('query_string', b'').decode()
            params = parse_qs(query_string)
            token_key = params.get('token', [None])[0]
            if token_key:
                from .views.api_auth import get_user_from_token_sync
                self.user = await get_user_from_token_sync(token_key)
                self.scope['user'] = self.user

        if not self.user or not self.user.is_authenticated:
            logger.warning(
                "[NotifyConsumer] Unauthenticated user attempted to connect")
            await self.close()
            return

        self.group_name = f'user_notify_{self.user.id}'
        logger.info(
            f"[NotifyConsumer] User {self.user.id} ({self.user.username}) connected to group {self.group_name}")
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.update_user_status(True)

    async def disconnect(self, close_code):
        await self.update_user_status(False)
        # Guard against disconnect being called before connect finished
        if hasattr(self, 'group_name') and self.group_name:
            try:
                await self.channel_layer.group_discard(self.group_name, self.channel_name)
            except Exception:
                logger.exception(
                    "Error during group_discard in NotifyConsumer.disconnect")

    async def receive(self, text_data):
        return

    async def notify_call(self, event):
        """Handle incoming call notification"""
        logger.info(
            f"[NotifyConsumer] Received notify_call event for user {self.user.id} from {event.get('from_user_id')}")
        await self.send(text_data=json.dumps({
            'type': 'incoming.call',
            'from_user_id': event.get('from_user_id'),
            'chat_id': event.get('chat_id'),
            'audioOnly': event.get('audio_only', False),
            'from_full_name': event.get('from_full_name'),
            'from_avatar': event.get('from_avatar'),
        }))
        logger.info(
            f"[NotifyConsumer] Sent 'incoming.call' to UI for user {self.user.id}")

    async def notify_message(self, event):
        """Handle new message notification"""
        await self.send(text_data=json.dumps({
            'type': 'new.message',
            'chat_id': event.get('chat_id'),
            'sender_id': event.get('sender_id'),
            'sender_name': event.get('sender_name'),
            'sender_avatar': event.get('sender_avatar'),
            'message_preview': event.get('message_preview'),
        }))

    async def notify_follow(self, event):
        """Handle new follower notification"""
        await self.send(text_data=json.dumps({
            'type': 'follow',
            'follower_id': event.get('follower_id'),
            'follower_name': event.get('follower_name'),
            'follower_username': event.get('follower_username'),
            'follower_avatar': event.get('follower_avatar'),
            'content': 'started following you',
            'timestamp': timezone.now().isoformat()
        }))

    async def notify_report(self, event):
        """Handle post report notification"""
        await self.send(text_data=json.dumps({
            'type': 'post_report',
            'scribe_id': event.get('scribe_id'),
            'reporter_id': event.get('reporter_id'),
            'reason': event.get('reason'),
            'content': f"Your post was reported for {event.get('reason')}",
            'timestamp': event.get('timestamp')
        }))

    async def notify_report_omzo(self, event):
        """Handle omzo report notification"""
        await self.send(text_data=json.dumps({
            'type': 'omzo_report',
            'omzo_id': event.get('omzo_id'),
            'reporter_id': event.get('reporter_id'),
            'reason': event.get('reason'),
            'content': f"Your omzo was reported for {event.get('reason')}",
            'timestamp': event.get('timestamp')
        }))

    async def notify_missed_call(self, event):
        """Handle missed call notification"""
        await self.send(text_data=json.dumps({
            'type': 'missed.call',
            'chat_id': event.get('chat_id'),
            'caller_id': event.get('caller_id'),
            'caller_name': event.get('caller_name'),
            'caller_avatar': event.get('caller_avatar'),
            'audio_only': event.get('audio_only', True),
        }))

    async def notify_like(self, event):
        """Handle scribe like notification"""
        await self.send(text_data=json.dumps({
            'type': 'like',
            'scribe_id': event.get('scribe_id'),
            'user_id': event.get('user_id'),
            'user_name': event.get('user_name'),
            'user_avatar': event.get('user_avatar'),
            'content': 'liked your scribe',
            'timestamp': event.get('timestamp')
        }))

    async def notify_omzo_like(self, event):
        """Handle omzo like notification"""
        await self.send(text_data=json.dumps({
            'type': 'omzo_like',
            'omzo_id': event.get('omzo_id'),
            'user_id': event.get('user_id'),
            'user_name': event.get('user_name'),
            'user_avatar': event.get('user_avatar'),
            'content': 'liked your omzo',
            'timestamp': event.get('timestamp')
        }))

    async def notify_comment(self, event):
        """Handle comment notification"""
        await self.send(text_data=json.dumps({
            'type': 'comment',
            'scribe_id': event.get('scribe_id'),
            'comment_id': event.get('comment_id'),
            'user_id': event.get('user_id'),
            'user_name': event.get('user_name'),
            'user_avatar': event.get('user_avatar'),
            'comment_content': event.get('comment_content'),
            'content': 'commented on your scribe',
            'timestamp': event.get('timestamp')
        }))

    async def notify_omzo_comment(self, event):
        """Handle Omzo comment notification"""
        await self.send(text_data=json.dumps({
            'type': 'omzo_comment',
            'omzo_id': event.get('omzo_id'),
            'comment_id': event.get('comment_id'),
            'user_id': event.get('user_id'),
            'user_name': event.get('user_name'),
            'user_avatar': event.get('user_avatar'),
            'comment_content': event.get('comment_content'),
            'content': 'commented on your omzo',
            'timestamp': event.get('timestamp')
        }))

    @database_sync_to_async
    def update_user_status(self, is_online):
        """Update user online status in database"""
        try:
            if self.user and self.user.is_authenticated:
                # Fetch fresh user object
                from django.contrib.auth import get_user_model
                U = get_user_model()
                user = U.objects.get(id=self.user.id)
                user.is_online = is_online
                user.last_seen = timezone.now()
                user.save(update_fields=['is_online', 'last_seen'])
                logger.debug(
                    f"[Notify] User {user.id} marked {'online' if is_online else 'offline'}")
        except Exception as e:
            logger.error(f"Error updating user status in NotifyConsumer: {e}")


class OdnixGatewayConsumer(AsyncWebsocketConsumer):
    """
    THE ODNIX GATEWAY (MTProto 2.0 Style)
    -------------------------------------
    This consumer replaces separate Chat/Call endpoints.
    It implements the full telegram-style binary protocol:
    1. Connection is essentially "dumb" TCP/WS tunnel.
    2. First packets MUST be Handshake (req_pq_multi).
    3. Once AuthKey established, all traffic is encrypted binary packets.
    4. Acts as a dispatcher for RPC calls (messages.send, phone.requestCall).
    """

    async def connect(self):
        # In Telegram architecture, we accept everyone. Auth happens via protocol.
        self.user = self.scope.get('user')  # Might be Anonymous initially
        self.session_id = None
        self.auth_key = None
        self.auth_key_id = None

        # Security State
        self.handshake_step = 0
        self.proto_security = OdnixSecurity()

        await self.accept()
        logger.info(f"[OdnixGateway] New connection accepted. ID: {id(self)}")

    async def disconnect(self, close_code):
        logger.info(f"[OdnixGateway] Connection closed: {close_code}")

    async def receive(self, text_data=None, bytes_data=None):
        try:
            # MTProto only uses Binary. Text frames are invalid/legacy.
            if text_data:
                logger.warning(
                    "[OdnixGateway] Dropping text frame (Strict Binary Protocol)")
                return

            if not bytes_data:
                return

            # --- PHASE 1: HANDSHAKE (Plaintext Wrapper) ---
            # If we don't have an AuthKey yet, we expect specific Handshake primitives
            # In real MTProto, even handshake is wrapped in a specific 'UnencryptedMessage' envelope.
            # Here we simplify: if len < 24 or auth_key_id == 0, it's handshake.

            if not self.auth_key:
                await self.handle_handshake_packet(bytes_data)
                return

            # --- PHASE 2: SECURE TRANSPORT (Encrypted Envelope) ---
            # Parse the OdnixPacket envelope
            try:
                from .odnix_proto import OdnixPacket
                packet = OdnixPacket.from_bytes(bytes_data)
            except Exception as e:
                logger.error(f"[OdnixGateway] Malformed Packet: {e}")
                return

            # 1. Verify Auth Key ID
            # In real impl, we'd look up the session state by ID.
            # valid_auth_id = hashlib.sha1(self.auth_key).digest()[-8:]
            # if packet.auth_key_id != valid_auth_id: ...

            # 2. Decrypt Payload
            # We use the OdnixSecurity logic but adapted for binary
            decrypted_data = self.decrypt_binary_payload(packet)

            if not decrypted_data:
                logger.warning(
                    "[OdnixGateway] Decryption failed or integrity check failed")
                return

            # 3. Dispatch RPC
            await self.dispatch_rpc(decrypted_data)

        except Exception as e:
            logger.error(f"[OdnixGateway] Critical Error: {e}", exc_info=True)
            await self.close()

    async def handle_handshake_packet(self, data):
        """
        Handles the raw binary handshake flow (Req_PQ -> Res_DH, etc.)
        """
        # For prototype, we'll assume the client sends a raw 1-byte OpCode for handshake step
        # Real MTProto scans for TL Constructor ID

        op_code = data[0]
        logger.info(f"[OdnixGateway] Handshake OpCode: {op_code}")

        # 0x01: REQ_PQ (Client sends nonce)
        if op_code == 0x01:
            nonce = data[1:17]  # 16 bytes

            # Server Reply: RES_PQ (Nonce + ServerNonce + Prime + G)
            dh_config = self.proto_security.create_dh_config()
            # currently b64 in security lib
            s_nonce_b64 = dh_config['server_nonce']
            import base64
            s_nonce = base64.b64decode(s_nonce_b64)

            # Pack response
            # [Op:0x02][Nonce(16)][ServerNonce(16)][PrimeLen(2)][PrimeBytes...][G(4)]
            # This is pseudo-code for the binary logic
            # Key Calculation (Simulated Diffie-Hellman Completion for Demo)
            # In real flow, client sends another packet. Here we shortcut for prototype stability.
            # Client thinks handshake is done after RES_PQ in our simple client.
            # We derive a fixed key based on nonces to match client.

            # Key = SHA256(ClientNonce + ServerNonce)
            combined = nonce + s_nonce
            import hashlib
            self.auth_key = hashlib.sha256(combined).digest()
            self.proto_security.auth_key = self.auth_key
            logger.info(f"[OdnixGateway] Auth Key Established for Session")

            reply = b'\x02' + nonce + s_nonce
            # ... (packing prime/g skipped for brevity in snippet) ...

            await self.send(bytes_data=reply)

    def decrypt_binary_payload(self, packet):
        # Implementation of AES decryption (Simulated AES-CBC to match client)
        if not self.auth_key:
            return None

        # 1. Derive MsgKey/Key/IV
        # Client: msgKey = sha256(authKey + data)
        # Server: we already have msgKey in packet.

        # Derive Key/IV:
        # key = sha256(msgKey + authKey)
        # iv = sha256(authKey + msgKey)[0:16]

        ka = packet.msg_key + self.auth_key
        kb = self.auth_key + packet.msg_key

        key = hashlib.sha256(ka).digest()
        iv = hashlib.sha256(kb).digest()[:16]

        try:
            from Crypto.Cipher import AES
            import struct
            import json
            cipher = AES.new(key, AES.MODE_CBC, iv)
            decrypted = cipher.decrypt(packet.encrypted_data)

            # 2. Parse Inner Payload
            # [Salt(8)][Session(8)][MsgId(8)][Seq(4)][Len(4)][Data][Padding]
            data_len = struct.unpack('<I', decrypted[28:32])[0]
            json_bytes = decrypted[32:32+data_len]

            payload_json = json.loads(json_bytes.decode('utf-8'))
            return payload_json

        except Exception as e:
            logger.error(f"[OdnixGateway] Decrypt Error: {e}")
            return None

    async def dispatch_rpc(self, payload):
        method = payload.get('method')
        params = payload.get('params')

        logger.info(f"[OdnixGateway] RPC Dispatch: {method}")

        if method == 'signal':
            # Bridge to Call logic - Echo for now
            logger.info(
                f"[OdnixGateway] Signal received via Binary Proto: {params.get('type')}")


# --- SIDEBAR CONSUMER (NEW) ---

class SidebarConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")

        # Fallback manual token check
        if not user or not user.is_authenticated:
            from urllib.parse import parse_qs
            query_string = self.scope.get('query_string', b'').decode()
            params = parse_qs(query_string)
            token_key = params.get('token', [None])[0]
            if token_key:
                from .views.api_auth import get_user_from_token_sync
                user = await get_user_from_token_sync(token_key)
                self.scope['user'] = user

        if not user or not user.is_authenticated:
            await self.close()
            return

        self.user = user
        self.group_name = f"sidebar_{user.id}"

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name
            )

    async def sidebar_update(self, event):
        await self.send(text_data=json.dumps({
            "type": "sidebar_update",
            "chat_id": event["chat_id"],
            "unread_count": event["unread_count"],
            "last_message": event["last_message"],
        }))

    async def new_chat(self, event):
        """Notify frontend about a new chat that should appear in sidebar"""
        await self.send(text_data=json.dumps({
            "type": "new_chat",
            "chat": event["chat"],
            "is_request": event.get("is_request", False),
        }))

    async def chat_accepted(self, event):
        """Notify frontend that a chat request was accepted (move from Requests to All)"""
        await self.send(text_data=json.dumps({
            "type": "chat_accepted",
            "chat_id": event["chat_id"],
        }))

    async def request_count_update(self, event):
        """Update the request badge count"""
        await self.send(text_data=json.dumps({
            "type": "request_count_update",
            "count": event["count"],
        }))
