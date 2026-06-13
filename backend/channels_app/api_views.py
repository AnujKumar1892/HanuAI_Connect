from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from django.utils.text import slugify
from django.contrib.auth import get_user_model
from .models import TeamChannel
from .serializers import (
    TeamChannelSerializer, ChannelCreateSerializer,
)
from notifications.models import Notification

User = get_user_model()


class ChannelListView(generics.ListAPIView):
    serializer_class = TeamChannelSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'admin':
            return TeamChannel.objects.exclude(slug__startswith='dm-')
        elif user.role == 'management':
            return TeamChannel.objects.exclude(slug='admin').exclude(slug__startswith='dm-')
        return user.team_channels.exclude(slug__in=['admin', 'management']).exclude(slug__startswith='dm-')


class ChannelDetailView(generics.RetrieveAPIView):
    serializer_class = TeamChannelSerializer
    permission_classes = [permissions.IsAuthenticated]
    queryset = TeamChannel.objects.all()
    lookup_field = 'slug'
    lookup_url_kwarg = 'slug'


class ChannelCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if not request.user.is_active:
            return Response({'error': 'Account deactivated'}, status=status.HTTP_403_FORBIDDEN)
        if request.user.role != 'admin':
            return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)

        name = request.data.get('name', '').strip()
        if not name:
            return Response({'error': 'Name required'}, status=status.HTTP_400_BAD_REQUEST)

        description = request.data.get('description', '').strip()
        channel = TeamChannel.objects.create(name=name, slug=slugify(name), description=description)
        serializer = TeamChannelSerializer(channel, context={'request': request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class ChannelEditView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, slug):
        if not request.user.is_active:
            return Response({'error': 'Account deactivated'}, status=status.HTTP_403_FORBIDDEN)
        if request.user.role != 'admin':
            return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)

        channel = get_object_or_404(TeamChannel, slug=slug)
        if channel.slug in ['admin', 'management']:
            return Response({'error': 'Cannot edit protected channels'}, status=status.HTTP_403_FORBIDDEN)

        name = request.data.get('name', '').strip()
        if not name:
            return Response({'error': 'Name required'}, status=status.HTTP_400_BAD_REQUEST)

        channel.name = name
        channel.slug = slugify(name)
        channel.description = request.data.get('description', '').strip()
        channel.save()
        serializer = TeamChannelSerializer(channel, context={'request': request})
        return Response(serializer.data)


class ChannelDeleteView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, slug):
        if not request.user.is_active:
            return Response({'error': 'Account deactivated'}, status=status.HTTP_403_FORBIDDEN)
        if request.user.role != 'admin':
            return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)

        channel = get_object_or_404(TeamChannel, slug=slug)
        if channel.slug in ['admin', 'management']:
            return Response({'error': 'Cannot delete protected channels'}, status=status.HTTP_403_FORBIDDEN)

        channel.delete()
        return Response({'success': True})


class ChannelManageUsersView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, slug):
        if not request.user.is_active:
            return Response({'error': 'Account deactivated'}, status=status.HTTP_403_FORBIDDEN)
        if request.user.role != 'admin':
            return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)

        channel = get_object_or_404(TeamChannel, slug=slug)
        user_ids = request.data.get('user_ids', [])
        action = request.data.get('action', 'set')

        if action == 'add':
            users = User.objects.filter(id__in=user_ids)
            channel.members.add(*users)
        elif action == 'remove':
            users = User.objects.filter(id__in=user_ids)
            channel.members.remove(*users)
        else:
            channel.members.set(user_ids)

        serializer = TeamChannelSerializer(channel, context={'request': request})
        return Response(serializer.data)


class ChannelUsersView(generics.ListAPIView):
    serializer_class = TeamChannelSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, slug):
        channel = get_object_or_404(TeamChannel, slug=slug)
        members = channel.members.all()
        data = [
            {'id': u.id, 'username': u.username, 'role': u.role, 'initial': u.username[0].upper()}
            for u in members
        ]
        return Response({'members': data})


class ChannelUploadPicView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, slug):
        if not request.user.is_active:
            return Response({'error': 'Account deactivated'}, status=status.HTTP_403_FORBIDDEN)
        if request.user.role != 'admin':
            return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
        channel = get_object_or_404(TeamChannel, slug=slug)
        if request.FILES.get('profile_pic'):
            channel.profile_pic = request.FILES['profile_pic']
            channel.save()
            return Response({'success': True, 'profile_pic_url': channel.profile_pic_url})
        return Response({'error': 'No file'}, status=status.HTTP_400_BAD_REQUEST)


class BroadcastView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if not request.user.is_active:
            return Response({'error': 'Account deactivated'}, status=status.HTTP_403_FORBIDDEN)
        if request.user.role not in ('admin', 'management'):
            return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)

        message_text = request.data.get('message', '').strip()
        target = request.data.get('target', 'all')
        channel_slugs = request.data.get('channels', [])
        user_ids = request.data.get('user_ids', [])

        if not message_text:
            return Response({'error': 'Message required'}, status=status.HTTP_400_BAD_REQUEST)

        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync
        channel_layer = get_channel_layer()
        created_messages = []

        if target == 'all':
            channels = TeamChannel.objects.filter(is_archived=False, is_deleted=False)
        elif target == 'selected' and channel_slugs:
            channels = TeamChannel.objects.filter(slug__in=channel_slugs, is_archived=False, is_deleted=False)
        else:
            channels = TeamChannel.objects.none()

        for ch in channels:
            from chat.models import ChatMessage
            msg = ChatMessage.objects.create(
                channel=ch, sender=request.user,
                message=message_text, is_delivered=True,
                is_broadcast=True,
                broadcast_type='all' if target == 'all' else 'selected',
                broadcast_channels=','.join(channel_slugs) if target == 'selected' else None
            )
            created_messages.append({'id': msg.id, 'channel': ch.slug, 'channel_name': ch.name})
            async_to_sync(channel_layer.group_send)(
                f'chat_{ch.id}',
                {
                    'type': 'chat_message',
                    'message': message_text,
                    'sender': request.user.username,
                    'sender_id': request.user.id,
                    'message_id': msg.id,
                    'is_broadcast': True,
                }
            )
            for member in ch.members.exclude(id=request.user.id):
                Notification.objects.create(
                    user=member, type='broadcast',
                    title=f"Broadcast from {request.user.username}",
                    body=message_text[:200], channel=ch, message=msg
                )
                async_to_sync(channel_layer.group_send)(
                    f'user_notifications_{member.id}',
                    {
                        'type': 'notification_event',
                        'ntype': 'broadcast',
                        'title': f"Broadcast from {request.user.username}",
                        'body': message_text[:200],
                        'channel': ch.name,
                        'channel_slug': ch.slug,
                        'sender': request.user.username,
                        'message_id': msg.id,
                    }
                )

        if target == 'user' and user_ids:
            from chat.models import ChatMessage
            for uid in user_ids:
                ch_slug = f'dm-{min(request.user.id, uid)}-{max(request.user.id, uid)}'
                ch, _ = TeamChannel.objects.get_or_create(
                    slug=ch_slug, defaults={'name': f'DM-{min(request.user.id, uid)}-{max(request.user.id, uid)}'}
                )
                msg = ChatMessage.objects.create(
                    channel=ch, sender=request.user,
                    message=message_text, is_delivered=True,
                    is_broadcast=True, broadcast_type='user'
                )
                ch.members.add(request.user.id, uid)
                created_messages.append({'id': msg.id, 'channel': ch.slug, 'channel_name': ch.name})
                async_to_sync(channel_layer.group_send)(
                    f'chat_{ch.id}',
                    {
                        'type': 'chat_message',
                        'message': message_text,
                        'sender': request.user.username,
                        'sender_id': request.user.id,
                        'message_id': msg.id,
                    }
                )
                target_user = User.objects.filter(id=uid).first()
                if target_user and target_user.id != request.user.id:
                    Notification.objects.create(
                        user=target_user, type='message',
                        title=f"Message from {request.user.username}",
                        body=message_text[:200], channel=ch, message=msg
                    )
                    async_to_sync(channel_layer.group_send)(
                        f'user_notifications_{target_user.id}',
                        {
                            'type': 'notification_event',
                            'ntype': 'message',
                            'title': f"Message from {request.user.username}",
                            'body': message_text[:200],
                            'channel': ch.name,
                            'channel_slug': ch.slug,
                            'sender': request.user.username,
                            'message_id': msg.id,
                        }
                    )

        return Response({'success': True, 'messages': created_messages})
