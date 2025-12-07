from django.urls import path
from . import views

from .views import (
    ClaimVerifyView, 
    ClaimDetailView, 
    ClaimListView,
    DisputeCreateView,
    DisputeDetailView,
    DisputeListView,
    translate_verification_result,
    AdminJournalListView,
    AdminJournalDetailView,
    AdminJournalImportView,
    AdminJournalEmbedView,
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
    # Public Endpoints - Claim
    path('verify/', ClaimVerifyView.as_view(), name='claim-verify'),
    path('translate/', translate_verification_result, name='translate-verification-result'),
    path('claims/', ClaimListView.as_view(), name='claim-list'),
    path('claims/<int:claim_id>/', ClaimDetailView.as_view(), name='claim-detail'),
    path('claims/check-duplicate/', views.check_claim_duplicate, name='check-duplicate'),

    # Public Endpoints - Dispute
    path('disputes/', DisputeListView.as_view(), name='dispute-list'),
    path('disputes/create/', DisputeCreateView.as_view(), name='dispute-create'),
    path('disputes/<int:dispute_id>/', DisputeDetailView.as_view(), name='dispute-detail'),

    # Admin Authentication
    path('admin/login/', AdminLoginView.as_view(), name='admin-login'),
    path('admin/logout/', AdminLogoutView.as_view(), name='admin-logout'),
    path('admin/token/refresh/', AdminTokenRefreshView.as_view(), name='admin-token-refresh'),
    path('admin/me/', AdminMeView.as_view(), name='admin-me'),
    path('admin/create/', AdminCreateView.as_view(), name='admin-create'),

    # Admin Dashboard & Operations (TANPA DUPLIKASI)
    path('admin/dashboard/stats/', AdminDashboardStatsView.as_view(), name='admin-dashboard-stats'),
    path('admin/users/', AdminUserListView.as_view(), name='admin-user-list'),
    path('admin/users/<int:user_id>/', AdminUserDetailView.as_view(), name='admin-user-detail'),
    path('admin/disputes/', AdminDisputeListView.as_view(), name='admin-dispute-list'),
    path('admin/disputes/<int:dispute_id>/', AdminDisputeDetailView.as_view(), name='admin-dispute-detail'),
    path('admin/disputes/<int:dispute_id>/action/', AdminDisputeDetailView.as_view(), name='admin-dispute-action'),

    # Admin Sources
    path('admin/sources/', AdminSourceListView.as_view(), name='admin-source-list'),
    path('admin/sources/stats/', AdminSourceStatsView.as_view(), name='admin-source-stats'),
    path('admin/sources/<int:source_id>/', AdminSourceDetailView.as_view(), name='admin-source-detail'),

    # Admin Journal Management
    path('admin/journals/', AdminJournalListView.as_view(), name='admin-journal-list'),
    path('admin/journals/<int:journal_id>/', AdminJournalDetailView.as_view(), name='admin-journal-detail'),
    path('admin/journals/import/', AdminJournalImportView.as_view(), name='admin-journal-import'),
    path('admin/journals/embed/', AdminJournalEmbedView.as_view(), name='admin-journal-embed'),
]