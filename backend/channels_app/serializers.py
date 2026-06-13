from rest_framework import serializers
from .models import TeamChannel


class MemberSummarySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()
    role = serializers.CharField()
    initial = serializers.SerializerMethodField()

    def get_initial(self, obj):
        return obj.username[0].upper() if obj.username else ''


class TeamChannelSerializer(serializers.ModelSerializer):
    profile_pic_url = serializers.CharField(read_only=True)
    member_count = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()
    members = MemberSummarySerializer(many=True, read_only=True)

    class Meta:
        model = TeamChannel
        fields = [
            'id', 'name', 'slug', 'description', 'profile_pic_url',
            'member_count', 'unread_count', 'members', 'created_at',
        ]

    def get_member_count(self, obj):
        return obj.members.count()

    def get_unread_count(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            from notifications.models import Notification
            return Notification.objects.filter(
                user=request.user, channel=obj, is_read=False
            ).count()
        return 0


class ChannelCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = TeamChannel
        fields = ['name', 'description']

