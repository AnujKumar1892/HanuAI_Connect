from django.db import models
from django.utils import timezone

from accounts.models import CustomUser
from channels_app.models import TeamChannel


class ChatMessage(models.Model):

    channel = models.ForeignKey(
        TeamChannel,
        on_delete=models.CASCADE,
        related_name='messages'
    )

    sender = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='sent_messages'
    )

    reply_to = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='replies'
    )

    message = models.TextField(
        blank=True,
        null=True
    )

    file = models.FileField(
        upload_to='chat_files/',
        blank=True,
        null=True
    )

    image = models.ImageField(
        upload_to='chat_images/',
        blank=True,
        null=True
    )

    # Delete Features
    deleted_for = models.ManyToManyField(
        CustomUser,
        blank=True,
        related_name='deleted_messages'
    )

    is_deleted_for_everyone = models.BooleanField(default=False)

    # Edit Feature
    is_edited = models.BooleanField(default=False)
    original_message = models.TextField(blank=True, null=True)

    # Broadcast Feature
    is_broadcast = models.BooleanField(default=False)
    broadcast_type = models.CharField(max_length=20, blank=True, null=True)
    broadcast_channels = models.TextField(blank=True, null=True)

    # Mention Feature
    mentioned_users = models.ManyToManyField(
        CustomUser,
        blank=True,
        related_name='mentioned_in_messages'
    )

    updated_at = models.DateTimeField(auto_now=True)

    # Seen / Read Status
    is_delivered = models.BooleanField(default=False)

    is_seen = models.BooleanField(default=False)

    seen_at = models.DateTimeField(
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def mark_seen(self):
        self.is_seen = True
        self.seen_at = timezone.now()
        self.save()

    def __str__(self):
        return f"{self.sender.username} - {self.channel}"
