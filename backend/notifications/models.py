from django.db import models
from accounts.models import CustomUser
from channels_app.models import TeamChannel
from chat.models import ChatMessage


class Notification(models.Model):
    NOTIFICATION_TYPES = (
        ('message', 'New Message'),
        ('broadcast', 'Broadcast'),
        ('mention', 'Mention'),
        ('system', 'System'),
    )

    PRIORITIES = (
        (1, 'Broadcast'),
        (2, 'Mention'),
        (3, 'Direct Message'),
        (4, 'Channel Message'),
    )

    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='notifications'
    )
    sender = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='sent_notifications'
    )
    type = models.CharField(max_length=20, choices=NOTIFICATION_TYPES, default='message')
    priority = models.PositiveSmallIntegerField(choices=PRIORITIES, default=4)
    channel = models.ForeignKey(
        TeamChannel,
        on_delete=models.SET_NULL,
        null=True, blank=True
    )
    message = models.ForeignKey(
        ChatMessage,
        on_delete=models.SET_NULL,
        null=True, blank=True
    )
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['priority', '-created_at']

    def __str__(self):
        return f"[{self.type}] {self.title} -> {self.user.username}"
