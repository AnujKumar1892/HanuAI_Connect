from django.urls import path
from .api_views import (
    ChannelListView, ChannelDetailView, ChannelCreateView,
    ChannelEditView, ChannelDeleteView, ChannelManageUsersView,
    ChannelUsersView, ChannelUploadPicView,
    BroadcastView,
)

urlpatterns = [
    path('channels/', ChannelListView.as_view(), name='api_channels'),
    path('channels/<slug:slug>/', ChannelDetailView.as_view(), name='api_channel_detail'),
    path('channels/create/', ChannelCreateView.as_view(), name='api_channel_create'),
    path('channels/<slug:slug>/edit/', ChannelEditView.as_view(), name='api_channel_edit'),
    path('channels/<slug:slug>/delete/', ChannelDeleteView.as_view(), name='api_channel_delete'),
    path('channels/<slug:slug>/manage-users/', ChannelManageUsersView.as_view(), name='api_channel_manage_users'),
    path('channels/<slug:slug>/users/', ChannelUsersView.as_view(), name='api_channel_users'),
    path('channels/upload-pic/<slug:slug>/', ChannelUploadPicView.as_view(), name='api_channel_upload_pic'),
    path('broadcast/', BroadcastView.as_view(), name='api_broadcast'),
]
