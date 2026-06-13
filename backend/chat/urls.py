from django.urls import path
from .api_views import (
    MessageListView, MessageCreateView, MessageEditView,
    MessageDeleteForMeView, MessageDeleteForEveryoneView,
    MessageHistoryView, UploadFileView, ClearChatView,
)

urlpatterns = [
    path('channels/<slug:slug>/messages/', MessageListView.as_view(), name='api_messages'),
    path('channels/<slug:slug>/messages/create/', MessageCreateView.as_view(), name='api_message_create'),
    path('messages/<int:message_id>/edit/', MessageEditView.as_view(), name='api_message_edit'),
    path('messages/<int:message_id>/delete-for-me/', MessageDeleteForMeView.as_view(), name='api_message_delete_for_me'),
    path('messages/<int:message_id>/delete-for-everyone/', MessageDeleteForEveryoneView.as_view(), name='api_message_delete_for_everyone'),
    path('messages/history/', MessageHistoryView.as_view(), name='api_message_history'),
    path('channels/<slug:slug>/clear/', ClearChatView.as_view(), name='api_clear_chat'),
    path('channels/<slug:slug>/upload/', UploadFileView.as_view(), name='api_upload_file'),
]
