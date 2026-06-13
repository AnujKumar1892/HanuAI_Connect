from django.urls import path
from .api_views import NotificationListView, MarkNotificationsReadView

urlpatterns = [
    path('notifications/', NotificationListView.as_view(), name='api_notifications'),
    path('notifications/mark-read/', MarkNotificationsReadView.as_view(), name='api_notifications_mark_read'),
]
