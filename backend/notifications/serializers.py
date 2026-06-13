from rest_framework import serializers
from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    channel_slug = serializers.CharField(source='channel.slug', read_only=True)
    channel_name = serializers.CharField(source='channel.name', read_only=True)
    sender_username = serializers.SerializerMethodField()
    sender_id = serializers.SerializerMethodField()
    message_id = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            'id', 'type', 'title', 'body', 'channel', 'channel_slug',
            'channel_name', 'sender_username', 'sender_id', 'message_id',
            'priority', 'is_read', 'created_at',
        ]

    def get_sender_username(self, obj):
        if obj.sender:
            return obj.sender.username
        if obj.message and obj.message.sender:
            return obj.message.sender.username
        return None

    def get_sender_id(self, obj):
        if obj.sender:
            return obj.sender.id
        if obj.message and obj.message.sender:
            return obj.message.sender.id
        return None

    def get_message_id(self, obj):
        if obj.message:
            return obj.message.id
        return None
