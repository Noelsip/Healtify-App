from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
import logging

logger = logging.getLogger(__name__)


class AdminLoginView(APIView):
    """
    POST /api/admin/login/
    
    Login endpoint untuk admin. Mengembalikan JWT access & refresh token.
    
    Request Body:
    {
        "username": "admin",
        "password": "password123"
    }
    
    Response:
    {
        "access": "eyJ0eXAiOiJKV1QiLCJhbGc...",
        "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc...",
        "user": {
            "id": 1,
            "username": "admin",
            "email": "admin@healthify.com",
            "is_staff": true,
            "is_superuser": true
        }
    }
    """
    permission_classes = [AllowAny]

    def post(self, request):
        username = request.data.get('username')
        password = request.data.get('password')

        logger.info(f"[ADMIN_LOGIN] Login attempt for username: {username}")

        # Validasi input
        if not username or not password:
            logger.warning("[ADMIN_LOGIN] Missing username or password")
            return Response(
                {'error': 'Username dan password wajib diisi.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Authenticate user
        user = authenticate(username=username, password=password)

        if user is None:
            logger.warning(f"[ADMIN_LOGIN] Failed login attempt for username: {username}")
            return Response(
                {'error': 'Username atau password salah.'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        # Check if user is admin/staff
        if not user.is_staff:
            logger.warning(f"[ADMIN_LOGIN] Non-admin user tried to login: {username}")
            return Response(
                {'error': 'Anda tidak memiliki akses admin.'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Generate JWT token
        refresh = RefreshToken.for_user(user)
        
        logger.info(f"[ADMIN_LOGIN] Login successful for admin: {username}")

        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'is_staff': user.is_staff,
                'is_superuser': user.is_superuser,
            }
        }, status=status.HTTP_200_OK)


class AdminLogoutView(APIView):
    """
    POST /api/admin/logout/
    
    Logout endpoint untuk admin. Mem-blacklist refresh token.
    
    Request Body:
    {
        "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc..."
    }
    
    Response:
    {
        "message": "Logout berhasil."
    }
    """
    permission_classes = [AllowAny]  # Allow any karena user mungkin sudah expired token

    def post(self, request):
        try:
            refresh_token = request.data.get('refresh')
            
            if not refresh_token:
                logger.warning("[ADMIN_LOGOUT] Refresh token not provided")
                return Response(
                    {'error': 'Refresh token required.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Blacklist the token
            token = RefreshToken(refresh_token)
            token.blacklist()

            username = request.user.username if request.user.is_authenticated else 'unknown'
            logger.info(f"[ADMIN_LOGOUT] Logout successful for user: {username}")
            
            return Response(
                {'message': 'Logout berhasil.'},
                status=status.HTTP_200_OK
            )

        except Exception as e:
            logger.error(f"[ADMIN_LOGOUT] Error during logout: {str(e)}", exc_info=True)
            return Response(
                {'error': 'Token tidak valid atau sudah expired.'},
                status=status.HTTP_400_BAD_REQUEST
            )


class AdminTokenRefreshView(APIView):
    """
    POST /api/admin/token/refresh/
    
    Refresh access token menggunakan refresh token.
    
    Request Body:
    {
        "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc..."
    }
    
    Response:
    {
        "access": "eyJ0eXAiOiJKV1QiLCJhbGc..."
    }
    """
    permission_classes = [AllowAny]

    def post(self, request):
        refresh_token = request.data.get('refresh')
        
        if not refresh_token:
            logger.warning("[TOKEN_REFRESH] Refresh token not provided")
            return Response(
                {'error': 'Refresh token required.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            refresh = RefreshToken(refresh_token)
            access_token = str(refresh.access_token)

            logger.info("[TOKEN_REFRESH] Token refreshed successfully")

            return Response({
                'access': access_token
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"[TOKEN_REFRESH] Error refreshing token: {str(e)}", exc_info=True)
            return Response(
                {'error': 'Token tidak valid atau sudah expired.'},
                status=status.HTTP_401_UNAUTHORIZED
            )


class AdminMeView(APIView):
    """
    GET /api/admin/me/
    
    Mendapatkan informasi user yang sedang login.
    
    Headers:
    Authorization: Bearer <access_token>
    
    Response:
    {
        "id": 1,
        "username": "admin",
        "email": "admin@healthify.com",
        "is_staff": true,
        "is_superuser": true
    }
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        logger.info(f"[ADMIN_ME] User info requested by: {user.username}")

        return Response({
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'is_staff': user.is_staff,
            'is_superuser': user.is_superuser,
        }, status=status.HTTP_200_OK)


class AdminCreateView(APIView):
    """
    POST /api/admin/create/
    
    Endpoint untuk membuat admin user baru (hanya superuser yang bisa akses).
    
    Request Body:
    {
        "username": "newadmin",
        "email": "newadmin@healthify.com",
        "password": "securepassword123",
        "is_superuser": false
    }
    
    Response:
    {
        "message": "Admin user berhasil dibuat.",
        "user": {
            "id": 2,
            "username": "newadmin",
            "email": "newadmin@healthify.com",
            "is_staff": true,
            "is_superuser": false
        }
    }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # Only superuser can create new admin
        if not request.user.is_superuser:
            logger.warning(f"[ADMIN_CREATE] Non-superuser tried to create admin: {request.user.username}")
            return Response(
                {'error': 'Hanya superuser yang dapat membuat admin baru.'},
                status=status.HTTP_403_FORBIDDEN
            )

        username = request.data.get('username')
        email = request.data.get('email')
        password = request.data.get('password')
        is_superuser = request.data.get('is_superuser', False)

        # Validasi input
        if not username or not password:
            return Response(
                {'error': 'Username dan password wajib diisi.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check if username already exists
        if User.objects.filter(username=username).exists():
            return Response(
                {'error': 'Username sudah digunakan.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check if email already exists
        if email and User.objects.filter(email=email).exists():
            return Response(
                {'error': 'Email sudah digunakan.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Create new admin user
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                is_staff=True,
                is_superuser=is_superuser
            )

            logger.info(f"[ADMIN_CREATE] New admin created: {username} by {request.user.username}")

            return Response({
                'message': 'Admin user berhasil dibuat.',
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'email': user.email,
                    'is_staff': user.is_staff,
                    'is_superuser': user.is_superuser,
                }
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.error(f"[ADMIN_CREATE] Error creating admin: {str(e)}", exc_info=True)
            return Response(
                {'error': f'Gagal membuat admin: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )