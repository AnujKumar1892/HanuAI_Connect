from rest_framework import serializers
from .models import ChatMessage
from accounts.serializers import UserSerializer


class ChatMessageSerializer(serializers.ModelSerializer):
    sender = UserSerializer(read_only=True)
    channel_name = serializers.CharField(source='channel.name', read_only=True)
    channel_slug = serializers.CharField(source='channel.slug', read_only=True)
    file_url = serializers.SerializerMethodField()
    image_url = serializers.SerializerMethodField()
    reply_to_data = serializers.SerializerMethodField()

    class Meta:
        model = ChatMessage
        fields = [
            'id', 'sender', 'message', 'file_url', 'image_url',
            'channel', 'channel_name', 'channel_slug',
            'is_edited', 'original_message', 'is_delivered', 'is_seen', 'is_deleted_for_everyone',
            'is_broadcast', 'broadcast_type', 'broadcast_channels',
            'created_at', 'updated_at', 'reply_to_data',
        ]
        read_only_fields = ['sender', 'created_at', 'updated_at']

    def get_file_url(self, obj):
        if obj.file:
            return obj.file.url
        return None

    def get_image_url(self, obj):
        if obj.image:
            return obj.image.url
        return None

    def get_reply_to_data(self, obj):
        if obj.reply_to and not obj.reply_to.is_deleted_for_everyone:
            return {
                'id': obj.reply_to.id,
                'sender': obj.reply_to.sender.username,
                'sender_id': obj.reply_to.sender.id,
                'message': obj.reply_to.message,
                'created_at': obj.reply_to.created_at.isoformat() if obj.reply_to.created_at else None,
            }
        return None


class MessageCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatMessage
        fields = ['message']
