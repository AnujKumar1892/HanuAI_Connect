from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from django.utils import timezone
import os
from .models import ChatMessage
from .serializers import ChatMessageSerializer
from channels_app.models import TeamChannel
from notifications.models import Notification
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync


class IsChannelMemberPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        channel_slug = view.kwargs.get('slug')
        if not channel_slug:
            return True
        try:
            channel = TeamChannel.objects.get(slug=channel_slug)
            if request.user.role == 'admin':
                return True
            return channel.members.filter(id=request.user.id).exists()
        except TeamChannel.DoesNotExist:
            return False


class MessageListView(generics.ListAPIView):
    serializer_class = ChatMessageSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        slug = self.kwargs['slug']
        channel = get_object_or_404(TeamChannel, slug=slug)
        user = self.request.user

        if user.role != 'admin' and not channel.members.filter(id=user.id).exists():
            return ChatMessage.objects.none()

        return ChatMessage.objects.filter(
            channel=channel,
            is_deleted_for_everyone=False
        ).exclude(deleted_for=user).select_related('sender', 'channel', 'reply_to__sender').order_by('created_at')


class MessageCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, slug):
        if not request.user.is_active:
            return Response({'error': 'Account deactivated'}, status=status.HTTP_403_FORBIDDEN)

        channel = get_object_or_404(TeamChannel, slug=slug)
        user = request.user

        if channel.is_archived:
            return Response({'error': 'Cannot send messages in an archived channel'}, status=status.HTTP_403_FORBIDDEN)

        if user.role == 'employee' and not channel.members.filter(id=user.id).exists():
            return Response({'error': 'Not a member'}, status=status.HTTP_403_FORBIDDEN)

        if slug.startswith('dm-'):
            parts = slug.split('-')
            if len(parts) == 3:
                try:
                    uid1, uid2 = int(parts[1]), int(parts[2])
                except (ValueError, IndexError):
                    return Response({'error': 'Invalid DM'}, status=status.HTTP_400_BAD_REQUEST)
                other_id = uid2 if uid1 == user.id else uid1
                from accounts.models import CustomUser
                try:
                    other_user = CustomUser.objects.get(id=other_id)
                except CustomUser.DoesNotExist:
                    return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)
                if user.role == 'employee':
                    emp_dept = (other_user.department or '').lower()
                    if emp_dept not in ('hr', 'finance', 'human resources'):
                        return Response({'error': 'Employees can only send messages to HR and Finance'}, status=status.HTTP_403_FORBIDDEN)
                elif user.role == 'admin' and other_user.role != 'management':
                    return Response({'error': 'Admins can only DM management users'}, status=status.HTTP_403_FORBIDDEN)
                elif user.role == 'management' and other_user.role not in ('employee', 'admin'):
                    return Response({'error': 'Management can only DM employees and admins'}, status=status.HTTP_403_FORBIDDEN)

        message = request.data.get('message', '').strip()
        if not message:
            return Response({'error': 'Message required'}, status=status.HTTP_400_BAD_REQUEST)

        chat_message = ChatMessage.objects.create(
            channel=channel,
            sender=user,
            message=message,
            is_delivered=True,
        )
        serializer = ChatMessageSerializer(chat_message)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class MessageEditView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, message_id):
        if not request.user.is_active:
            return Response({'error': 'Account deactivated'}, status=status.HTTP_403_FORBIDDEN)

        message = get_object_or_404(ChatMessage, id=message_id)
        if message.sender != request.user:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
        if message.is_deleted_for_everyone:
            return Response({'error': 'Message deleted'}, status=status.HTTP_400_BAD_REQUEST)
        if message.is_broadcast:
            return Response({'error': 'Broadcast messages cannot be edited'}, status=status.HTTP_403_FORBIDDEN)

        elapsed = timezone.now() - message.created_at
        if elapsed.total_seconds() > 900:  # 15 minutes
            return Response({'error': 'Edit window expired (15 minutes)'}, status=status.HTTP_403_FORBIDDEN)

        new_text = request.data.get('message', '').strip()
        if not new_text:
            return Response({'error': 'Message required'}, status=status.HTTP_400_BAD_REQUEST)

        if not message.original_message:
            message.original_message = message.message

        message.message = new_text
        message.is_edited = True
        message.save()

        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f'chat_{message.channel_id}',
            {
                'type': 'msg_edited',
                'message_id': message.id,
                'new_text': new_text,
                'sender_id': message.sender_id,
            }
        )

        serializer = ChatMessageSerializer(message)
        return Response(serializer.data)


class ClearChatView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsChannelMemberPermission]

    def post(self, request, slug):
        channel = get_object_or_404(TeamChannel, slug=slug)
        messages = ChatMessage.objects.filter(
            channel=channel, is_deleted_for_everyone=False
        ).exclude(deleted_for=request.user)
        for msg in messages:
            msg.deleted_for.add(request.user)
        return Response({'success': True, 'cleared': messages.count()})


class MessageDeleteForMeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, message_id):
        message = get_object_or_404(ChatMessage, id=message_id)
        if message.is_broadcast:
            return Response({'error': 'Broadcast messages cannot be deleted'}, status=status.HTTP_403_FORBIDDEN)
        message.deleted_for.add(request.user)
        return Response({'success': True})


class MessageDeleteForEveryoneView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, message_id):
        if not request.user.is_active:
            return Response({'error': 'Account deactivated'}, status=status.HTTP_403_FORBIDDEN)

        message = get_object_or_404(ChatMessage, id=message_id)
        if message.sender != request.user and request.user.role != 'admin':
            return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
        if message.is_broadcast:
            return Response({'error': 'Broadcast messages cannot be deleted'}, status=status.HTTP_403_FORBIDDEN)

        elapsed = timezone.now() - message.created_at
        if elapsed.total_seconds() > 900:  # 15 minutes
            return Response({'error': 'Delete for everyone window expired (15 minutes)'}, status=status.HTTP_403_FORBIDDEN)

        message.is_deleted_for_everyone = True
        message.message = "This message was deleted."
        message.file = None
        message.image = None
        message.save()
        return Response({'success': True})


class MessageHistoryView(generics.ListAPIView):
    serializer_class = ChatMessageSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        channel_slug = self.request.query_params.get('channel')
        search = self.request.query_params.get('search', '')
        days = self.request.query_params.get('days', '')

        qs = ChatMessage.objects.filter(
            is_deleted_for_everyone=False
        ).exclude(deleted_for=user).select_related('sender', 'channel', 'reply_to__sender')

        if user.role == 'admin':
            pass
        elif user.role == 'management':
            qs = qs.exclude(channel__slug='admin')
        else:
            qs = qs.filter(channel__in=user.team_channels.all())

        if channel_slug and channel_slug != 'all':
            qs = qs.filter(channel__slug=channel_slug)
        if search:
            qs = qs.filter(message__icontains=search)
        if days:
            try:
                from datetime import timedelta
                qs = qs.filter(created_at__gte=timezone.now() - timedelta(days=int(days)))
            except ValueError:
                pass

        return qs.order_by('-created_at')[:100]


class UploadFileView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, slug):
        if not request.user.is_active:
            return Response({'error': 'Account deactivated'}, status=status.HTTP_403_FORBIDDEN)

        channel = get_object_or_404(TeamChannel, slug=slug)
        user = request.user

        if user.role == 'employee' and not channel.members.filter(id=user.id).exists():
            return Response({'error': 'Not a member'}, status=status.HTTP_403_FORBIDDEN)

        uploaded_file = request.FILES.get('file')
        if not uploaded_file:
            return Response({'error': 'File required'}, status=status.HTTP_400_BAD_REQUEST)

        ext = os.path.splitext(uploaded_file.name)[1].lower()
        allowed_exts = {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
                        '.png', '.jpg', '.jpeg', '.gif',
                        '.mp4', '.mov'}
        if ext not in allowed_exts:
            return Response({'error': f'File type {ext} is not supported'}, status=status.HTTP_400_BAD_REQUEST)

        message_text = request.data.get('message', '').strip()

        msg = ChatMessage.objects.create(
            channel=channel, sender=user,
            message=message_text or '', is_delivered=True
        )

        image_exts = {'.jpg', '.jpeg', '.png', '.gif'}
        if ext in image_exts:
            msg.image = uploaded_file
        else:
            msg.file = uploaded_file
        msg.save()

        file_url = msg.file.url if msg.file else msg.image.url
        async_to_sync(get_channel_layer().group_send)(
            f'chat_{channel.id}',
            {
                'type': 'chat_message',
                'message': message_text or '',
                'sender': user.username,
                'sender_id': user.id,
                'message_id': msg.id,
                'file_url': file_url,
                'file_name': uploaded_file.name,
                'is_image': ext in image_exts,
            }
        )

        member_ids = list(channel.members.exclude(id=user.id).values_list('id', flat=True))
        Notification.objects.bulk_create([
            Notification(
                user_id=mid, type='message',
                title=f"File from {user.username}",
                body=message_text[:200] if message_text else uploaded_file.name,
                channel=channel, message=msg
            )
            for mid in member_ids
        ], ignore_conflicts=True)

        return Response({
            'success': True,
            'message_id': msg.id,
            'file_url': file_url,
            'file_name': uploaded_file.name,
            'is_image': ext in image_exts,
        })
