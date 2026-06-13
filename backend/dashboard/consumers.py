import json
import logging
import re
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.db.models import Count

logger = logging.getLogger(__name__)

from chat.models import ChatMessage
from channels_app.models import TeamChannel
from notifications.models import Notification

User = get_user_model()

online_users = {}


@database_sync_to_async
def get_channel_by_slug(slug):
    if slug.startswith('dm-'):
        parts = slug.split('-')
        if len(parts) == 3:
            try:
                uid1, uid2 = int(parts[1]), int(parts[2])
                norm_slug = f'dm-{min(uid1, uid2)}-{max(uid1, uid2)}'
                return TeamChannel.objects.get(slug=norm_slug)
            except (ValueError, TeamChannel.DoesNotExist):
                pass
    return TeamChannel.objects.get(slug=slug)


@database_sync_to_async
def get_unread_count(user_id):
    return Notification.objects.filter(user_id=user_id, is_read=False).count()


@database_sync_to_async
def get_unread_mentions_count(user_id):
    return Notification.objects.filter(user_id=user_id, type='mention', is_read=False).count()


@database_sync_to_async
def get_user_by_id(user_id):
    try:
        return User.objects.get(id=user_id)
    except User.DoesNotExist:
        return None


@database_sync_to_async
def check_membership(channel_obj, user):
    if user.role == 'admin':
        return True
    return channel_obj.members.filter(id=user.id).exists()


@database_sync_to_async
def save_message(channel_obj, user, message, file_url=None, file_name=None, is_image=False):
    msg = ChatMessage.objects.create(
        channel=channel_obj,
        sender=user,
        message=message,
        is_delivered=True
    )
    if file_url:
        if is_image:
            msg.image.name = file_url.split('/media/')[-1] if '/media/' in file_url else file_url
        else:
            msg.file.name = file_url.split('/media/')[-1] if '/media/' in file_url else file_url
        msg.save()
    return msg


@database_sync_to_async
def check_user_active(user_id):
    try:
        return User.objects.get(id=user_id).is_active
    except User.DoesNotExist:
        return False


@database_sync_to_async
def get_online_users_for_channel(channel_id):
    return list(online_users.get(channel_id, set()))


class ChatConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        user = self.scope['user']
        if not user.is_active or not await check_user_active(user.id):
            await self.close()
            return

        self.slug = self.scope['url_route']['kwargs']['slug']
        self.channel_obj = await get_channel_by_slug(self.slug)
        self.channel_id = self.channel_obj.id
        self.room_group_name = f'chat_{self.channel_id}'
        self.user_notification_group = f'user_notifications_{user.id}'
        self.user_id = user.id
        self.username = user.username

        await self.channel_layer.group_add(
            self.room_group_name, self.channel_name
        )
        await self.channel_layer.group_add(
            self.user_notification_group, self.channel_name
        )

        await self.accept()
        logger.info(f"[ChatConsumer] Connected: user={self.username}, slug={self.slug}, room={self.room_group_name}, channel_name={self.channel_name}")

        await self.update_last_seen()

        if self.channel_id not in online_users:
            online_users[self.channel_id] = set()
        online_users[self.channel_id].add(self.user_id)

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'presence_update',
                'user_id': self.user_id,
                'username': self.username,
                'action': 'online',
            }
        )

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.room_group_name, self.channel_name
        )
        await self.channel_layer.group_discard(
            self.user_notification_group, self.channel_name
        )

        await self.update_last_seen()

        if self.channel_id in online_users:
            online_users[self.channel_id].discard(self.user_id)
            if not online_users[self.channel_id]:
                del online_users[self.channel_id]

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'presence_update',
                'user_id': self.user_id,
                'username': self.username,
                'action': 'offline',
            }
        )

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Invalid message format',
            }))
            return

        event_type = data.get('type')
        logger.info(f"[ChatConsumer] receive: type={event_type}, data={data}")

        if event_type == 'typing':
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'typing_status',
                    'sender': data.get('sender'),
                    'sender_id': data.get('sender_id'),
                    'is_typing': data.get('is_typing'),
                }
            )
            return

        if event_type == 'seen':
            message_id = data.get('message_id')
            if message_id:
                await self.mark_message_seen(message_id)
                await self.channel_layer.group_send(
                    self.room_group_name, {'type': 'message_seen', 'message_id': message_id}
                )
            return

        if event_type == 'msg_deleted':
            message_id = data.get('message_id')
            if message_id:
                await self.channel_layer.group_send(
                    self.room_group_name, {'type': 'msg_deleted', 'message_id': message_id}
                )
            return

        if not await check_user_active(self.user_id):
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Account deactivated',
            }))
            return

        message = data.get('message')
        if message:
            try:
                is_member = await check_membership(self.channel_obj, self.scope['user'])
                if not is_member:
                    await self.send(text_data=json.dumps({
                        'type': 'error',
                        'message': 'You are not a member of this channel',
                    }))
                    return

                if self.channel_obj.is_archived:
                    await self.send(text_data=json.dumps({
                        'type': 'error',
                        'message': 'Cannot send messages in an archived channel',
                    }))
                    return

                if self.slug.startswith('dm-'):
                    parts = self.slug.split('-')
                    if len(parts) == 3:
                        try:
                            uid1, uid2 = int(parts[1]), int(parts[2])
                        except (ValueError, IndexError):
                            await self.send(text_data=json.dumps({'type': 'error', 'message': 'Invalid DM'}))
                            return
                        other_id = uid2 if uid1 == self.user_id else uid1
                        other_user = await get_user_by_id(other_id)
                        if other_user is None:
                            await self.send(text_data=json.dumps({'type': 'error', 'message': 'User not found'}))
                            return
                        urole = self.scope['user'].role
                        if urole == 'employee':
                            other_dept = (other_user.department or '').lower()
                            if other_dept not in ('hr', 'finance', 'human resources'):
                                await self.send(text_data=json.dumps({'type': 'error', 'message': 'Employees can only send messages to HR and Finance'}))
                                return
                        elif urole == 'admin' and other_user.role != 'management':
                            await self.send(text_data=json.dumps({'type': 'error', 'message': 'Admins can only DM management users'}))
                            return
                        elif urole == 'management' and other_user.role not in ('employee', 'admin'):
                            await self.send(text_data=json.dumps({'type': 'error', 'message': 'Management can only DM employees and admins'}))
                            return

                reply_to_id = data.get('reply_to')
                saved_message = await self.save_message_helper(message, reply_to_id)
                logger.info(f"[ChatConsumer] message saved: id={saved_message.id}, text='{saved_message.message}'")

                # Build reply data
                reply_to_id = 0
                reply_to_text = ''
                reply_to_sender = ''
                if saved_message.reply_to and not saved_message.reply_to.is_deleted_for_everyone:
                    reply_to_id = saved_message.reply_to.id
                    reply_to_text = saved_message.reply_to.message or ''
                    reply_to_sender = saved_message.reply_to.sender.username

                created_at_iso = saved_message.created_at.isoformat() if saved_message.created_at else ''

                # Echo back to sender directly (guaranteed delivery)
                echo_payload = {
                    'type': 'message',
                    'message': saved_message.message or '',
                    'sender': saved_message.sender.username,
                    'sender_id': saved_message.sender.id,
                    'message_id': saved_message.id,
                    'created_at': created_at_iso,
                    'reply_to_id': reply_to_id,
                    'reply_to_text': reply_to_text,
                    'reply_to_sender': reply_to_sender,
                }
                await self.send(text_data=json.dumps(echo_payload))
                logger.info(f"[ChatConsumer] direct echo sent to sender for msg_id={saved_message.id}")

                # Broadcast to all group members (including sender, frontend deduplicates)
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        'type': 'chat_message',
                        'message': saved_message.message or '',
                        'sender': saved_message.sender.username,
                        'sender_id': saved_message.sender.id,
                        'message_id': saved_message.id,
                        'created_at': created_at_iso,
                        'reply_to_id': reply_to_id,
                        'reply_to_text': reply_to_text,
                        'reply_to_sender': reply_to_sender,
                    }
                )
                logger.info(f"[ChatConsumer] group_send chat_message done for msg_id={saved_message.id}")

                await self.notify_channel_members(saved_message)
            except Exception as e:
                logger.error(f"[ChatConsumer] Error in receive: {e}", exc_info=True)
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'message': f'Server error: {str(e)}',
                }))

    @database_sync_to_async
    def save_message_helper(self, message, reply_to_id=None):
        reply_to_msg = None
        if reply_to_id:
            try:
                reply_to_msg = ChatMessage.objects.get(id=reply_to_id)
            except ChatMessage.DoesNotExist:
                pass
        msg = ChatMessage.objects.create(
            channel=self.channel_obj,
            sender=self.scope['user'],
            message=message,
            reply_to=reply_to_msg,
            is_delivered=True
        )
        if reply_to_msg:
            msg = ChatMessage.objects.select_related('sender', 'reply_to__sender').get(id=msg.id)
        return msg

    @database_sync_to_async
    def mark_message_seen(self, message_id):
        ChatMessage.objects.filter(
            id=message_id, is_seen=False
        ).exclude(
            sender=self.scope['user']
        ).update(
            is_seen=True, is_delivered=True, seen_at=timezone.now()
        )

    async def notify_channel_members(self, msg):
        sender = self.scope['user']
        channel_name = self.channel_obj.name
        is_dm = self.slug.startswith('dm-')

        member_ids = await self.get_channel_member_ids()
        admin_ids = await self.get_admin_user_ids()
        target_ids = set(member_ids) | set(admin_ids)
        target_ids.discard(sender.id)
        if not target_ids:
            return

        # Detect @mentions in message text (users, roles, @all)
        text = msg.message or ''
        mentioned_users = await self.parse_mentions(text, target_ids)
        mentioned_ids = set(u.id for u in mentioned_users)

        # Detect role mentions (@Management, @Admin, @Employee)
        role_mention_ids = await self.parse_role_mentions(text, target_ids)
        # Detect @all
        all_mention = await self.detect_all_mention(text, sender)

        # Combine all mentioned user IDs
        all_mentioned_ids = mentioned_ids | role_mention_ids
        if all_mention:
            all_mentioned_ids.update(target_ids)

        # Store mentioned users on the message
        all_mentioned_users = await self.get_users_by_ids(all_mentioned_ids)
        if all_mentioned_users:
            await self.store_mentioned_users(msg, all_mentioned_users)

        # Determine base notification type and priority
        if is_dm:
            base_type = 'message'
            base_priority = 3
            base_title = f"DM from {sender.username}"
        elif msg.is_broadcast:
            base_type = 'broadcast'
            base_priority = 1
            base_title = f"Broadcast in #{channel_name}"
        else:
            base_type = 'message'
            base_priority = 4
            base_title = f"New message in #{channel_name}"

        # Exclude archived channels from generating notifications
        if self.channel_obj.is_archived:
            return

        notifications = []
        for uid in target_ids:
            if uid in all_mentioned_ids:
                ntype = 'mention'
                priority = 2
                if all_mention:
                    title = f"{sender.username} @all in #{channel_name}"
                elif uid in role_mention_ids and uid not in mentioned_ids:
                    role_name = await self.get_user_role_label(uid)
                    title = f"{sender.username} @{role_name} in #{channel_name}"
                else:
                    title = f"{sender.username} mentioned you in #{channel_name}"
            else:
                ntype = base_type
                priority = base_priority
                title = base_title

            notifications.append(Notification(
                user_id=uid, sender=sender, type=ntype, priority=priority,
                title=title,
                body=text[:200] if text else '',
                channel=self.channel_obj, message=msg
            ))

        await self.bulk_create_notifications(notifications)

        for uid in target_ids:
            if uid in all_mentioned_ids:
                ntype = 'mention'
                priority = 2
                if all_mention:
                    title = f"{sender.username} @all in #{channel_name}"
                elif uid in role_mention_ids and uid not in mentioned_ids:
                    role_name = await self.get_user_role_label(uid)
                    title = f"{sender.username} @{role_name} in #{channel_name}"
                else:
                    title = f"{sender.username} mentioned you in #{channel_name}"
            else:
                ntype = base_type
                priority = base_priority
                title = base_title

            await self.channel_layer.group_send(
                f'user_notifications_{uid}',
                {
                    'type': 'notification_event',
                    'ntype': ntype,
                    'priority': priority,
                    'title': title,
                    'body': text[:200] if text else '',
                    'channel': channel_name,
                    'channel_slug': self.slug,
                    'sender': sender.username,
                    'sender_id': sender.id,
                    'message_id': msg.id,
                }
            )

        # Send unread_mentions updates for all mentioned users
        if all_mentioned_ids:
            for uid in all_mentioned_ids:
                um_count = await get_unread_mentions_count(uid)
                await self.channel_layer.group_send(
                    f'user_notifications_{uid}',
                    {'type': 'unread_mentions', 'count': um_count}
                )

    @database_sync_to_async
    def parse_mentions(self, text, target_ids):
        """Extract @username mentions from message text, filtered to accessible users."""
        if not text:
            return []
        matches = re.findall(r'(?<!\w)@(\w+)(?!\w)', text)
        if not matches:
            return []
        # Filter out role keywords and @all
        role_keywords = {'management', 'admin', 'employee', 'all'}
        username_matches = [m for m in matches if m.lower() not in role_keywords]
        if not username_matches:
            return []
        return list(User.objects.filter(
            username__in=username_matches, id__in=target_ids
        ))

    @database_sync_to_async
    def parse_role_mentions(self, text, target_ids):
        """Detect @Management, @Admin, @Employee and return all matching user IDs."""
        if not text:
            return set()
        lower = text.lower()
        result = set()
        if '@management' in lower:
            result.update(User.objects.filter(
                role='management', id__in=target_ids
            ).values_list('id', flat=True))
        if '@admin' in lower:
            result.update(User.objects.filter(
                role='admin', id__in=target_ids
            ).values_list('id', flat=True))
        if '@employee' in lower:
            result.update(User.objects.filter(
                role='employee', id__in=target_ids
            ).values_list('id', flat=True))
        return result

    @database_sync_to_async
    def detect_all_mention(self, text, sender):
        """Check if @all is used. Only Admin/Management can use @all."""
        if not text:
            return False
        if '@all' not in text.lower():
            return False
        if sender.role in ('admin', 'management'):
            return True
        return False

    @database_sync_to_async
    def get_users_by_ids(self, user_ids):
        if not user_ids:
            return []
        return list(User.objects.filter(id__in=user_ids))

    @database_sync_to_async
    def get_user_role_label(self, user_id):
        try:
            u = User.objects.get(id=user_id)
            return u.role.capitalize()
        except User.DoesNotExist:
            return 'User'

    @database_sync_to_async
    def store_mentioned_users(self, msg, users):
        msg.mentioned_users.add(*users)

    @database_sync_to_async
    def get_channel_member_ids(self):
        return list(self.channel_obj.members.values_list('id', flat=True))

    @database_sync_to_async
    def get_admin_user_ids(self):
        return list(User.objects.filter(role__in=['admin', 'management']).values_list('id', flat=True))

    @database_sync_to_async
    def bulk_create_notifications(self, notifications):
        Notification.objects.bulk_create(notifications, ignore_conflicts=True)

    @database_sync_to_async
    def update_last_seen(self):
        User.objects.filter(id=self.user_id).update(last_seen=timezone.now())

    async def chat_message(self, event):
        payload = {
            'type': 'message',
            'message': event['message'],
            'sender': event['sender'],
            'sender_id': event['sender_id'],
            'message_id': event['message_id'],
            'created_at': event.get('created_at', ''),
            'reply_to_id': event.get('reply_to_id', 0),
            'reply_to_text': event.get('reply_to_text', ''),
            'reply_to_sender': event.get('reply_to_sender', ''),
        }
        if event.get('file_url'):
            payload['file_url'] = event['file_url']
            payload['file_name'] = event['file_name']
            payload['is_image'] = event['is_image']
        if event.get('is_broadcast'):
            payload['is_broadcast'] = True
        logger.info(f"[ChatConsumer] chat_message handler: sending to ws, msg_id={event.get('message_id')}")
        await self.send(text_data=json.dumps(payload))

    async def typing_status(self, event):
        await self.send(text_data=json.dumps({
            'type': 'typing',
            'sender': event['sender'],
            'sender_id': event['sender_id'],
            'is_typing': event['is_typing'],
        }))

    async def message_seen(self, event):
        await self.send(text_data=json.dumps({
            'type': 'seen',
            'message_id': event['message_id'],
        }))

    async def msg_edited(self, event):
        await self.send(text_data=json.dumps({
            'type': 'msg_edited',
            'message_id': event['message_id'],
            'new_text': event['new_text'],
            'sender_id': event['sender_id'],
        }))

    async def msg_deleted(self, event):
        await self.send(text_data=json.dumps({
            'type': 'msg_deleted',
            'message_id': event['message_id'],
        }))

    async def presence_update(self, event):
        await self.send(text_data=json.dumps({
            'type': 'presence',
            'user_id': event['user_id'],
            'username': event['username'],
            'action': event['action'],
        }))

    async def notification_event(self, event):
        logger.info(f"[ChatConsumer] notification_event for {self.username}: {event.get('title')}")
        await self.send(text_data=json.dumps({
            'type': 'notification',
            'ntype': event['ntype'],
            'priority': event.get('priority', 4),
            'title': event['title'],
            'body': event['body'],
            'channel': event['channel'],
            'channel_slug': event['channel_slug'],
            'sender': event['sender'],
            'sender_id': event.get('sender_id'),
            'message_id': event['message_id'],
        }))


class NotificationConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        self.user = self.scope['user']
        if self.user.is_anonymous or not self.user.is_active or not await check_user_active(self.user.id):
            await self.close()
            return

        self.notification_group = f'user_notifications_{self.user.id}'
        await self.channel_layer.group_add(
            self.notification_group, self.channel_name
        )
        await self.accept()
        logger.info(f"[NotificationConsumer] Connected: user={self.user.username}, group={self.notification_group}")

        unread_count = await get_unread_count(self.user.id)
        await self.send(text_data=json.dumps({
            'type': 'unread_count',
            'count': unread_count,
        }))

        unread_mentions = await get_unread_mentions_count(self.user.id)
        if unread_mentions > 0:
            await self.send(text_data=json.dumps({
                'type': 'unread_mentions',
                'count': unread_mentions,
            }))

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.notification_group, self.channel_name
        )

    async def receive(self, text_data):
        if not await check_user_active(self.user.id):
            return
        data = json.loads(text_data)
        if data.get('type') == 'mark_read':
            nid = data.get('notification_id')
            await self.mark_notifications_read(nid)
            count = await get_unread_count(self.user.id)
            await self.send(text_data=json.dumps({
                'type': 'unread_count',
                'count': count,
            }))
            mention_count = await get_unread_mentions_count(self.user.id)
            await self.send(text_data=json.dumps({
                'type': 'unread_mentions',
                'count': mention_count,
            }))

    @database_sync_to_async
    def mark_notifications_read(self, notification_id=None):
        qs = Notification.objects.filter(user=self.user, is_read=False)
        if notification_id:
            qs = qs.filter(id=notification_id)
        qs.update(is_read=True)

    async def notification_event(self, event):
        logger.info(f"[NotificationConsumer] notification_event for {self.user.username}: {event.get('title')}")
        await self.send(text_data=json.dumps({
            'type': 'notification',
            'ntype': event['ntype'],
            'priority': event.get('priority', 4),
            'title': event['title'],
            'body': event['body'],
            'channel': event['channel'],
            'channel_slug': event['channel_slug'],
            'sender': event['sender'],
            'sender_id': event.get('sender_id'),
            'message_id': event['message_id'],
        }))

    async def unread_mentions(self, event):
        await self.send(text_data=json.dumps({
            'type': 'unread_mentions',
            'count': event['count'],
        }))

    async def unread_count(self, event):
        await self.send(text_data=json.dumps({
            'type': 'unread_count',
            'count': event['count'],
        }))
