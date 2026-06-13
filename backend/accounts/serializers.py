from rest_framework import serializers
from .models import CustomUser


class UserSerializer(serializers.ModelSerializer):
    profile_pic_url = serializers.CharField(read_only=True)
    last_seen = serializers.DateTimeField(read_only=True)

    class Meta:
        model = CustomUser
        fields = [
            'id', 'username', 'email', 'role', 'department',
            'about', 'profile_pic_url', 'last_seen',
        ]


class UserListSerializer(serializers.ModelSerializer):
    initial = serializers.SerializerMethodField()
    profile_pic_url = serializers.CharField(read_only=True)

    class Meta:
        model = CustomUser
        fields = [
            'id', 'username', 'email', 'role', 'department',
            'about', 'profile_pic_url', 'last_seen', 'initial',
        ]

    def get_initial(self, obj):
        return obj.username[0].upper() if obj.username else ''
