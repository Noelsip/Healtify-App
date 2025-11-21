from rest_framework import permissions

class IsAdminOrReadOnly(permissions.BasePermission):
    """
        Custom permission:
        - Admin dapat melakukan semua aksi (GET, POST, PUT, DELETE).
        - User biasa hanya bisa READ (GET).    
    """
    def has_permission(self, request, view):
        # Allow GET, HEAD, OPTIONS untuk semua orang
        if request.method in permissions.SAFE_METHODS:
            return True
        
        # Untuk method lain (POST, PUT, DELETE), hanya izinkan untuk admin
        return request.user and request.user.is_staff
    
class IsSuperAdminOnly(permissions.BasePermission):
    """
        Hanya superadmin yang dapat mengakses.
    """
    def has_permission(self, request, view):
        return request.user and request.user.is_superuser