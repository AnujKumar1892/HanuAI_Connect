from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import Notification
from .serializers import NotificationSerializer


class NotificationListView(generics.ListAPIView):
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Notification.objects.filter(
            user=self.request.user
        ).select_related('channel', 'message__sender', 'sender')[:50]

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        unread_count = Notification.objects.filter(
            user=request.user, is_read=False
        ).count()
        unread_mentions = Notification.objects.filter(
            user=request.user, type='mention', is_read=False
        ).count()
        return Response({
            'notifications': serializer.data,
            'unread_count': unread_count,
            'unread_mentions': unread_mentions,
        })


class MarkNotificationsReadView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        nid = request.data.get('notification_id')
        if nid:
            Notification.objects.filter(id=nid, user=request.user).update(is_read=True)
        else:
            Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
        return Response({'success': True})
