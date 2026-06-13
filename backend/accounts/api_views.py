from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken
from .serializers import UserSerializer, UserListSerializer

User = get_user_model()


class LoginView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        username = request.data.get('username')
        password = request.data.get('password')
        if not username or not password:
            return Response(
                {'error': 'Username and password required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            refresh = RefreshToken.for_user(user)
            serializer = UserSerializer(user)
            return Response({
                'user': serializer.data,
                'access_token': str(refresh.access_token),
                'refresh_token': str(refresh),
            })
        return Response(
            {'error': 'Invalid credentials'},
            status=status.HTTP_401_UNAUTHORIZED
        )


class LogoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        logout(request)
        return Response({'success': True})


class AdminOrManagementPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role in ('admin', 'management')


class CurrentUserView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)

    def patch(self, request):
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UserListView(generics.ListAPIView):
    serializer_class = UserListSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'admin':
            return User.objects.all()
        elif user.role == 'management':
            return User.objects.exclude(role='admin')
        return User.objects.none()


class UserDetailView(generics.RetrieveAPIView):
    serializer_class = UserSerializer
    permission_classes = [AdminOrManagementPermission]
    queryset = User.objects.all()
    lookup_field = 'id'


class ProfileUpdateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request):
        if not request.user.is_active:
            return Response({'error': 'Account deactivated'}, status=status.HTTP_403_FORBIDDEN)
        user = request.user
        email = request.data.get('email', '').strip()
        department = request.data.get('department', '').strip()
        about = request.data.get('about', '').strip()
        if email:
            user.email = email
        user.department = department if department else None
        user.about = about if about else None
        user.save()
        serializer = UserSerializer(user)
        return Response(serializer.data)

    def post(self, request):
        if not request.user.is_active:
            return Response({'error': 'Account deactivated'}, status=status.HTTP_403_FORBIDDEN)
        if request.FILES.get('profile_pic'):
            user = request.user
            user.profile_pic = request.FILES['profile_pic']
            user.save()
            serializer = UserSerializer(user)
            return Response(serializer.data)
        return Response({'error': 'No file'}, status=status.HTTP_400_BAD_REQUEST)
