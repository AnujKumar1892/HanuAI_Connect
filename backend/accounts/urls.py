from django.urls import path
from .api_views import LoginView, LogoutView, CurrentUserView, UserListView, UserDetailView, ProfileUpdateView

urlpatterns = [
    path('login/', LoginView.as_view(), name='api_login'),
    path('logout/', LogoutView.as_view(), name='api_logout'),
    path('me/', CurrentUserView.as_view(), name='api_current_user'),
    path('me/update/', ProfileUpdateView.as_view(), name='api_profile_update'),
    path('users/', UserListView.as_view(), name='api_user_list'),
    path('users/<int:id>/', UserDetailView.as_view(), name='api_user_detail'),
]
