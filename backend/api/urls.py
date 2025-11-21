from django.urls import path
from .views import (
    ClaimVerifyView, 
    ClaimDetailView, 
    ClaimListView,
    DisputeCreateView,
    DisputeDetailView,
    DisputeListView,
)

from .auth_views import (
    AdminLoginView, 
    AdminLogoutView, 
    AdminTokenRefreshView,
    AdminMeView,
    AdminCreateView,
)

from .admin_views import (
    AdminDashboardStatsView,
    AdminUserListView,
    AdminUserDetailView,
    AdminDisputeListView,
    AdminDisputeDetailView,
    AdminSourceListView,
    AdminSourceDetailView,
    AdminSourceStatsView
)

urlpatterns = [
    # ===========================
    # Public Endpoints - Claim
    # ===========================
    path('verify/', ClaimVerifyView.as_view(), name='claim-verify'),
    path('claims/', ClaimListView.as_view(), name='claim-list'),
    path('claims/<int:claim_id>/', ClaimDetailView.as_view(), name='claim-detail'),

    # ===========================
    # Public Endpoints - Dispute
    # ===========================
    path('disputes/', DisputeListView.as_view(), name='dispute-list'),
    path('disputes/create/', DisputeCreateView.as_view(), name='dispute-create'),
    path('disputes/<int:dispute_id>/', DisputeDetailView.as_view(), name='dispute-detail'),
    
    # ===========================
    # Admin Authentication
    # ===========================
    path('admin/login/', AdminLoginView.as_view(), name='admin-login'),
    path('admin/logout/', AdminLogoutView.as_view(), name='admin-logout'),
    path('admin/token/refresh/', AdminTokenRefreshView.as_view(), name='admin-token-refresh'),
    path('admin/me/', AdminMeView.as_view(), name='admin-me'),
    path('admin/create/', AdminCreateView.as_view(), name='admin-create'),
    
    # ===========================
    # Admin Dashboard
    # ===========================
    path('admin/dashboard/stats/', AdminDashboardStatsView.as_view(), name='admin-dashboard-stats'),
    
        
    # ===========================
    # Admin Users
    # ===========================
    path('admin/users/', AdminUserListView.as_view(), name='admin-user-list'),
    path('admin/users/<int:user_id>/', AdminUserDetailView.as_view(), name='admin-user-detail'),

    # ===========================
    # Admin Operations
    # ===========================
    path('admin/dashboard/stats/', AdminDashboardStatsView.as_view(), name='admin-dashboard-stats'),
    path('admin/users/', AdminUserListView.as_view(), name='admin-user-list'),
    path('admin/users/<int:user_id>/', AdminUserDetailView.as_view(), name='admin-user-detail'),
    
    # Admin Disputes
    path('admin/disputes/', AdminDisputeListView.as_view(), name='admin-dispute-list'),
    path('admin/disputes/<int:dispute_id>/', AdminDisputeDetailView.as_view(), name='admin-dispute-detail'),
    path('admin/disputes/<int:dispute_id>/action/', AdminDisputeDetailView.as_view(), name='admin-dispute-action'),

    # ===========================
    # Admin Sources 
    # ===========================
    path('admin/sources/', AdminSourceListView.as_view(), name='admin-source-list'),
    path('admin/sources/stats/', AdminSourceStatsView.as_view(), name='admin-source-stats'),
    path('admin/sources/<int:source_id>/', AdminSourceDetailView.as_view(), name='admin-source-detail'),
]