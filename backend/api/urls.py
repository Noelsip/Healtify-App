from django.urls import path
from .views import (
    ClaimVerifyView, 
    ClaimDetailView, 
    ClaimListView,
    DisputeCreateView,
    DisputeDetailView,
    DisputeListView,
    DisputeAdminListView,
    DisputeAdminActionView,
    DisputeStatsView,
    DisputeValidIdsView
)
from .auth_views import (
    AdminLoginView, 
    AdminLogoutView, 
    AdminTokenRefreshView,
    AdminMeView,
    AdminCreateView
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
    # Admin Protected Endpoints
    # ===========================
    path('admin/disputes/', DisputeAdminListView.as_view(), name='admin-dispute-list'),
    path('admin/disputes/<int:dispute_id>/action/', DisputeAdminActionView.as_view(), name='admin-dispute-action'),
    path('admin/disputes/stats/', DisputeStatsView.as_view(), name='admin-dispute-stats'),
    path('admin/disputes/valid-ids/', DisputeValidIdsView.as_view(), name='admin-dispute-valid-ids'),  
]