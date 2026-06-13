from django.contrib import admin
from .models import ChatMessage


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = (
        'sender',
        'channel',
        'message',
        'created_at',
        'is_deleted_for_everyone',
    )

    list_filter = (
        'channel',
        'sender',
        'created_at',
        'is_deleted_for_everyone',
    )

    search_fields = (
        'message',
        'sender__username',
        'channel__name',
    )

    filter_horizontal = (
        'deleted_for',
    )
