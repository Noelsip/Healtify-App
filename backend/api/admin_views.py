import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from .email_service import email_service
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken  
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.contrib.auth.hashers import make_password
from django.db.models import Count
from django.db import transaction
from django.utils import timezone
from .models import Claim, Source, Dispute, VerificationResult
from .permissions import IsAdminOrReadOnly, IsSuperAdminOnly

logger = logging.getLogger(__name__)

class AdminDashboardStatsView(APIView):
    """
    GET /api/admin/dashboard/stats/
    
    Mendapatkan statistik dashboard admin.
    """
    permission_classes = [IsAuthenticated, IsAdminOrReadOnly]

    def get(self, request):
        try:
            # Total Claims
            total_claims = Claim.objects.count()
            
            # Pending Disputes
            pending_disputes = Dispute.objects.filter(status='pending').count()
            
            # Total Sources
            total_sources = Source.objects.count()
            
            # Verified Claims (yang sudah ada hasil verifikasi)
            verified_claims = VerificationResult.objects.values('claim').distinct().count()
            
            # Recent Activity (8 aktivitas terbaru)
            recent_claims = Claim.objects.select_related('verification_result').order_by('-created_at')[:5]
            recent_activity = []
            
            for claim in recent_claims:
                activity_text = f"New claim: {claim.text[:50]}..."
                if hasattr(claim, 'verification_result'):
                    activity_text = f"Verified claim ({claim.verification_result.label}): {claim.text[:50]}..."
                
                recent_activity.append({
                    'id': claim.id,
                    'text': activity_text,
                    'time': claim.created_at.isoformat(),
                    'type': 'claim'
                })
            
            # Recent Disputes
            recent_disputes = Dispute.objects.select_related('claim').order_by('-created_at')[:3]
            for dispute in recent_disputes:
                recent_activity.append({
                    'id': dispute.id,
                    'text': f"New dispute: {dispute.claim_text[:50]}..." if dispute.claim_text else "New dispute submitted",
                    'time': dispute.created_at.isoformat(),
                    'type': 'dispute'
                })
            
            # Sort by time
            recent_activity.sort(key=lambda x: x['time'], reverse=True)
            
            logger.info(f"[ADMIN_DASHBOARD] Stats fetched by {request.user.username}")
            
            return Response({
                'stats': {
                    'total_claims': total_claims,
                    'pending_disputes': pending_disputes,
                    'total_sources': total_sources,
                    'verified_claims': verified_claims
                },
                'recent_activity': recent_activity[:8]
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"[ADMIN_DASHBOARD] Error fetching stats: {str(e)}", exc_info=True)
            return Response({
                'error': 'Failed to fetch dashboard stats'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class AdminUserListView(APIView):
    """
    GET: Melihat semua admin users
    POST: Membuat admin user baru
    """
    permission_classes = [IsAuthenticated, IsSuperAdminOnly]

    def get(self, request):
        """Melihat semua admin users"""
        logger.info(f"[ADMIN_USER_LIST] Request from {request.user.username}")

        try:
            admins = User.objects.filter(is_staff=True).values(
                'id',
                'username',
                'email',
                'is_superuser',
                'is_staff',
                'date_joined',
                'last_login'
            )

            return Response({
                'status': True,
                'total': admins.count(),
                'admins': list(admins)
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"[ADMIN_USER_LIST][ERROR] {str(e)}", exc_info=True)
            return Response({
                'status': False,
                'message': 'Terjadi kesalahan saat mengambil data admin users.'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
    def post(self, request):
        """Membuat admin user baru"""
        logger.info(f"[ADMIN_USER_CREATE] Request from {request.user.username}")

        username = request.data.get('username')
        email = request.data.get('email')
        password = request.data.get('password')
        is_superuser = request.data.get('is_superuser', False)

        if not username or not email or not password:
            return Response({
                'status': False,
                'message': 'Username, email, dan password wajib diisi.'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            new_admin = User.objects.create(
                username=username,
                email=email,
                password=make_password(password),
                is_staff=True,
                is_superuser=is_superuser
            )

            logger.info(f"[ADMIN_USER_CREATE] Admin user '{username}' created by '{request.user.username}'")

            return Response({
                'status': True,
                'message': 'Admin user created successfully',
                'admin': {
                    'id': new_admin.id,
                    'username': new_admin.username,
                    'email': new_admin.email,
                    'is_superuser': new_admin.is_superuser,
                }
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.error(f"[ADMIN_USER_CREATE][ERROR] {str(e)}", exc_info=True)
            return Response({
                'status': False,
                'message': 'Terjadi kesalahan saat membuat admin user.'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class AdminUserDetailView(APIView):
    """
    GET: Melihat detail satu admin
    DELETE: Menghapus satu admin  
    """
    permission_classes = [IsAuthenticated, IsSuperAdminOnly]

    def get(self, request, user_id):
        """Melihat detail satu admin berdasarkan ID"""
        logger.info(f"[ADMIN_USER_DETAIL] request for user {user_id}")

        try:
            admin = User.objects.filter(id=user_id, is_staff=True).values(
                'id',
                'username',
                'email',
                'is_superuser',
                'is_staff',
                'date_joined',
                'last_login'
            ).first()

            if not admin:
                return Response({
                    'status': False,
                    'message': 'Admin user not found.'
                }, status=status.HTTP_404_NOT_FOUND)
            
            return Response({
                'status': True,
                'admin': admin
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"[ADMIN_USER_DETAIL][ERROR] {str(e)}", exc_info=True)
            return Response({
                'status': False,
                'message': 'Terjadi kesalahan saat mengambil data admin user.'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
    def delete(self, request, user_id):
        """Menghapus satu admin berdasarkan ID"""
        logger.info(f"[ADMIN_USER_DELETE] request to delete user {user_id}")

        if request.user.id == user_id:
            return Response({
                'status': False,
                'message': 'Admin tidak dapat menghapus dirinya sendiri.'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            admin = User.objects.filter(id=user_id, is_staff=True).first()

            if not admin:
                return Response({
                    'status': False,
                    'message': 'Admin user not found.'
                }, status=status.HTTP_404_NOT_FOUND)
            
            username = admin.username
            admin.delete()

            logger.info(f"[ADMIN_USER_DELETE] Admin user '{username}' deleted by '{request.user.username}'")

            return Response({
                'status': True,
                'message': 'Admin user deleted successfully.'
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"[ADMIN_USER_DELETE][ERROR] {str(e)}", exc_info=True)
            return Response({
                'status': False,
                'message': 'Terjadi kesalahan saat menghapus admin user.'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class AdminDisputeListView(APIView):

    """
        GET /api/admin/disputes/
        Melihat semua dispute dengan filter
    """
    permission_classes = [IsAuthenticated, IsAdminOrReadOnly]

    def get(self, request):
        try:
            status_filter = request.query_params.get('status', 'all')

            disputes = Dispute.objects.all()

            if status_filter != 'all':
                disputes = disputes.filter(status=status_filter)

            disputes = disputes.select_related('claim').order_by('-created_at')

            dispute_list = []
            for dispute in disputes:
                dispute_list.append({
                    'id': dispute.id,
                    'claim_id': dispute.claim.id if dispute.claim else None,
                    'claim_text': dispute.claim_text,
                    'user_feedback': dispute.user_feedback,
                    'status': dispute.status,
                    'original_label': dispute.original_label,
                    'created_at': dispute.created_at.isoformat(),
                    'resolved_at': dispute.resolved_at.isoformat() if dispute.resolved_at else None,
                    'admin_notes': dispute.admin_notes
                })

            logger.info(f"[ADMIN_DISPUTE_LIST] Disputes fetched by {request.user.username}")

            return Response({
                'disputes': dispute_list,
                'total': len(dispute_list)
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"[ADMIN_DISPUTE_LIST] Error fetching disputes: {str(e)}", exc_info=True)
            return Response({
                'error': 'Failed to fetch disputes'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class AdminDisputeDetailView(APIView):
    """
    GET /api/admin/disputes/<id>/
    POST /api/admin/disputes/<id>/action/
    """
    permission_classes = [IsAuthenticated, IsAdminOrReadOnly]

    # ...existing get method...

    @transaction.atomic
    def post(self, request, dispute_id):
        """Resolve dispute (approve/reject) dengan email notification"""
        try:
            dispute = Dispute.objects.select_related('claim').get(id=dispute_id)
            
            if dispute.status != 'pending':
                return Response({
                    'error': f'Dispute already {dispute.status}. Cannot process again.'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            action = request.data.get('action')
            admin_notes = request.data.get('admin_notes', '')
            new_label = request.data.get('new_label', None)
            
            if action not in ['approve', 'reject']:
                return Response({
                    'error': 'Invalid action. Must be "approve" or "reject"'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Update dispute
            dispute.status = action + 'd'
            dispute.admin_notes = admin_notes
            dispute.resolved_at = timezone.now()
            dispute.reviewed = True
            dispute.reviewed_by = request.user
            dispute.save()
            
            response_data = {
                'message': f'Dispute {action}d successfully',
                'dispute': {
                    'id': dispute.id,
                    'status': dispute.status,
                    'resolved_at': dispute.resolved_at.isoformat()
                }
            }
            
            # Update verification jika APPROVE
            if action == 'approve' and dispute.claim:
                try:
                    if hasattr(dispute.claim, 'verification_result'):
                        verification = dispute.claim.verification_result
                        old_label = verification.label
                        old_confidence = verification.confidence
                        
                        if new_label:
                            updated_label = new_label
                        else:
                            updated_label = self._analyze_feedback_for_label(
                                dispute.user_feedback, 
                                old_label
                            )
                        
                        verification.label = updated_label
                        verification.confidence = 0.95
                        verification.save()
                        
                        response_data['verification_updated'] = {
                            'claim_id': dispute.claim.id,
                            'old_label': old_label,
                            'old_confidence': float(old_confidence) if old_confidence else None,
                            'new_label': updated_label,
                            'new_confidence': 0.95
                        }
                        
                        logger.info(
                            f"[ADMIN_DISPUTE_APPROVE] Updated claim #{dispute.claim.id} "
                            f"verification: {old_label} → {updated_label}"
                        )
                    else:
                        # Create new verification if doesn't exist
                        new_label_determined = new_label or self._analyze_feedback_for_label(
                            dispute.user_feedback, 
                            dispute.original_label
                        )
                        
                        VerificationResult.objects.create(
                            claim=dispute.claim,
                            label=new_label_determined,
                            confidence=0.95,
                            summary="Updated by admin after dispute approval",
                        )
                        
                        response_data['verification_created'] = {
                            'claim_id': dispute.claim.id,
                            'label': new_label_determined,
                            'confidence': 0.95
                        }
                        
                except Exception as e:
                    logger.error(
                        f"[ADMIN_DISPUTE_APPROVE] Failed to update verification: {str(e)}", 
                        exc_info=True
                    )
                    raise
            
            # ✅ KIRIM EMAIL KE USER (NEW FEATURE)
            try:
                if action == 'approve':
                    email_service.notify_user_dispute_approved(dispute, admin_notes)
                else:  # reject
                    email_service.notify_user_dispute_rejected(dispute, admin_notes)
            except Exception as e:
                logger.error(f"[ADMIN_DISPUTE_ACTION] Failed to send user notification: {e}")
                # Don't fail the request if email fails
            
            logger.info(f"[ADMIN_DISPUTE_ACTION] Dispute {dispute_id} {action}ed by {request.user.username}")
            
            return Response(response_data, status=status.HTTP_200_OK)
            
        except Dispute.DoesNotExist:
            return Response({
                'error': 'Dispute not found'
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"[ADMIN_DISPUTE_ACTION] Error: {str(e)}", exc_info=True)
            return Response({
                'error': 'Failed to process dispute action'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class AdminSourceListView(APIView):
    """
    GET /api/admin/sources/
    POST /api/admin/sources/
    
    Melihat dan membuat source baru.
    """
    permission_classes = [IsAuthenticated, IsAdminOrReadOnly]

    def get(self, request):
        """List all sources with pagination and search"""
        try:
            search = request.GET.get('search', '')
            page = int(request.GET.get('page', 1))
            per_page = int(request.GET.get('per_page', 20))
            
            sources = Source.objects.all()
            
            # Search by title or url
            if search:
                from django.db.models import Q
                sources = sources.filter(
                    Q(title__icontains=search) | 
                    Q(url__icontains=search)
                )
            
            # Order by created date
            sources = sources.order_by('-created_at')
            
            # Pagination
            total = sources.count()
            start = (page - 1) * per_page
            end = start + per_page
            sources_page = sources[start:end]
            
            source_list = []
            for source in sources_page:
                source_list.append({
                    'id': source.id,
                    'title': source.title,
                    'url': source.url,
                    'credibility_score': source.credibility_score,
                    'source_type': source.source_type,
                    'created_at': source.created_at.isoformat(),
                    'updated_at': source.updated_at.isoformat(),
                })
            
            logger.info(f"[ADMIN_SOURCES] Listed {len(source_list)} sources (page {page}) by {request.user.username}")
            
            return Response({
                'sources': source_list,
                'pagination': {
                    'page': page,
                    'per_page': per_page,
                    'total': total,
                    'total_pages': (total + per_page - 1) // per_page
                }
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"[ADMIN_SOURCES] Error listing sources: {str(e)}", exc_info=True)
            return Response({
                'error': 'Failed to fetch sources'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def post(self, request):
        """Create new source"""
        try:
            title = request.data.get('title')
            url = request.data.get('url')
            credibility_score = request.data.get('credibility_score', 0.5)
            source_type = request.data.get('source_type', 'website')
            
            # Validation
            if not title or not url:
                return Response({
                    'error': 'Title and URL are required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Check if URL already exists
            if Source.objects.filter(url=url).exists():
                return Response({
                    'error': 'Source with this URL already exists'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Validate credibility score
            try:
                credibility_score = float(credibility_score)
                if not 0 <= credibility_score <= 1:
                    raise ValueError("Score must be between 0 and 1")
            except ValueError as e:
                return Response({
                    'error': f'Invalid credibility score: {str(e)}'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Create source
            source = Source.objects.create(
                title=title,
                url=url,
                credibility_score=credibility_score,
                source_type=source_type
            )
            
            logger.info(f"[ADMIN_SOURCES] Created source #{source.id} '{title}' by {request.user.username}")
            
            return Response({
                'message': 'Source created successfully',
                'source': {
                    'id': source.id,
                    'title': source.title,
                    'url': source.url,
                    'credibility_score': source.credibility_score,
                    'source_type': source.source_type,
                    'created_at': source.created_at.isoformat()
                }
            }, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            logger.error(f"[ADMIN_SOURCES] Error creating source: {str(e)}", exc_info=True)
            return Response({
                'error': 'Failed to create source'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class AdminSourceDetailView(APIView):
    """
    GET /api/admin/sources/<id>/
    PUT /api/admin/sources/<id>/
    DELETE /api/admin/sources/<id>/
    
    Melihat, update, dan delete source.
    """
    permission_classes = [IsAuthenticated, IsAdminOrReadOnly]

    def get(self, request, source_id):
        """Get source detail"""
        try:
            source = Source.objects.get(id=source_id)
            
            return Response({
                'id': source.id,
                'title': source.title,
                'url': source.url,
                'credibility_score': source.credibility_score,
                'source_type': source.source_type,
                'created_at': source.created_at.isoformat(),
                'updated_at': source.updated_at.isoformat(),
            }, status=status.HTTP_200_OK)
            
        except Source.DoesNotExist:
            return Response({
                'error': 'Source not found'
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"[ADMIN_SOURCE_DETAIL] Error: {str(e)}", exc_info=True)
            return Response({
                'error': 'Failed to fetch source details'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def put(self, request, source_id):
        """Update source"""
        try:
            source = Source.objects.get(id=source_id)
            
            # Update fields
            title = request.data.get('title', source.title)
            url = request.data.get('url', source.url)
            credibility_score = request.data.get('credibility_score', source.credibility_score)
            source_type = request.data.get('source_type', source.source_type)
            
            # Validate URL uniqueness (excluding current source)
            if url != source.url and Source.objects.filter(url=url).exists():
                return Response({
                    'error': 'Another source with this URL already exists'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Validate credibility score
            try:
                credibility_score = float(credibility_score)
                if not 0 <= credibility_score <= 1:
                    raise ValueError("Score must be between 0 and 1")
            except ValueError as e:
                return Response({
                    'error': f'Invalid credibility score: {str(e)}'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Update
            source.title = title
            source.url = url
            source.credibility_score = credibility_score
            source.source_type = source_type
            source.save()
            
            logger.info(f"[ADMIN_SOURCE_UPDATE] Updated source #{source_id} by {request.user.username}")
            
            return Response({
                'message': 'Source updated successfully',
                'source': {
                    'id': source.id,
                    'title': source.title,
                    'url': source.url,
                    'credibility_score': source.credibility_score,
                    'source_type': source.source_type,
                    'updated_at': source.updated_at.isoformat()
                }
            }, status=status.HTTP_200_OK)
            
        except Source.DoesNotExist:
            return Response({
                'error': 'Source not found'
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"[ADMIN_SOURCE_UPDATE] Error: {str(e)}", exc_info=True)
            return Response({
                'error': 'Failed to update source'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def delete(self, request, source_id):
        """Delete source"""
        try:
            source = Source.objects.get(id=source_id)
            
            title = source.title
            source.delete()
            
            logger.info(f"[ADMIN_SOURCE_DELETE] Deleted source #{source_id} '{title}' by {request.user.username}")
            
            return Response({
                'message': f'Source "{title}" deleted successfully'
            }, status=status.HTTP_200_OK)
            
        except Source.DoesNotExist:
            return Response({
                'error': 'Source not found'
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"[ADMIN_SOURCE_DELETE] Error: {str(e)}", exc_info=True)
            return Response({
                'error': 'Failed to delete source'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class AdminSourceStatsView(APIView):
    """
    GET /api/admin/sources/stats/
    
    Statistik sources untuk dashboard.
    """
    permission_classes = [IsAuthenticated, IsAdminOrReadOnly]

    def get(self, request):
        try:
            total_sources = Source.objects.count()
            
            # Sources by type
            sources_by_type = Source.objects.values('source_type').annotate(
                count=Count('id')
            ).order_by('-count')
            
            # Average credibility score
            from django.db.models import Avg
            avg_credibility = Source.objects.aggregate(
                avg=Avg('credibility_score')
            )['avg'] or 0
            
            # Recent sources
            recent_sources = Source.objects.order_by('-created_at')[:5].values(
                'id', 'title', 'url', 'credibility_score', 'created_at'
            )
            
            return Response({
                'total_sources': total_sources,
                'sources_by_type': list(sources_by_type),
                'avg_credibility': float(avg_credibility),
                'recent_sources': list(recent_sources)
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"[ADMIN_SOURCE_STATS] Error: {str(e)}", exc_info=True)
            return Response({
                'error': 'Failed to fetch source stats'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

