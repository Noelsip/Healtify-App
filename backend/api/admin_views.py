from typing import Dict, Any, List
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.contrib.auth.hashers import make_password
from django.db.models import Count
from django.db import transaction
from django.utils import timezone
from django.http import Http404

# IMPORT MODELS 
from .models import Claim, Source, Dispute, VerificationResult, ClaimSource
from .permissions import IsAdminOrReadOnly, IsSuperAdminOnly
from .serializers import DisputeDetailSerializer, DisputeReviewSerializer
from .email_service import email_service
from .ai_adapter import call_ai_verify, normalize_ai_response

import logging

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
                    'reason': dispute.reason,  
                    'reporter_name': dispute.reporter_name,
                    'reporter_email': dispute.reporter_email,
                    'status': dispute.status,
                    'status_display': dispute.get_status_display(),
                    'supporting_doi': dispute.supporting_doi,
                    'supporting_url': dispute.supporting_url,
                    'supporting_file': bool(dispute.supporting_file),
                    'created_at': dispute.created_at.isoformat(),
                    'reviewed_at': dispute.reviewed_at.isoformat() if dispute.reviewed_at else None,  
                    'reviewed_by': dispute.reviewed_by.username if dispute.reviewed_by else None,
                    'review_note': dispute.review_note,  
                    'original_label': dispute.original_label,
                    'original_confidence': dispute.original_confidence
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
    POST /api/admin/disputes/<id>/
    
    GET: Fetch detail single dispute
    POST: Approve/Reject dispute dan update verification result
    """
    permission_classes = [IsAuthenticated, IsAdminOrReadOnly]

    def get(self, request, dispute_id):
        """Get detail satu dispute"""
        try:
            dispute = Dispute.objects.select_related(
                'claim', 
                'reviewed_by'
            ).get(id=dispute_id)
            
            serializer = DisputeDetailSerializer(
                dispute,
                context={'request': request}
            )
            
            logger.info(f"[ADMIN_DISPUTE_DETAIL] Fetched dispute {dispute_id} by {request.user.username}")
            
            return Response(serializer.data, status=status.HTTP_200_OK)
            
        except Dispute.DoesNotExist:
            logger.warning(f"[ADMIN_DISPUTE_DETAIL] Dispute {dispute_id} not found")
            return Response({
                'error': 'Dispute not found'
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"[ADMIN_DISPUTE_DETAIL] Error: {str(e)}", exc_info=True)
            return Response({
                'error': 'Failed to fetch dispute details'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @transaction.atomic
    def post(self, request, dispute_id):
        """
        Approve/Reject dispute dengan opsi:
        1. Re-verify otomatis (menggunakan AI)
        2. Manual update verification result
        3. Keduanya
        """
        try:
            # Validate request data
            serializer = DisputeReviewSerializer(data=request.data)
            if not serializer.is_valid():
                logger.warning(f"[ADMIN_DISPUTE_REVIEW] Invalid data: {serializer.errors}")
                return Response(
                    serializer.errors,
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            validated_data = serializer.validated_data
            
            # Fetch dispute
            dispute = Dispute.objects.select_related('claim').get(id=dispute_id)
            
            # Check if already reviewed
            if dispute.status != Dispute.STATUS_PENDING:
                logger.warning(f"[ADMIN_DISPUTE_REVIEW] Dispute {dispute_id} already {dispute.status}")
                return Response({
                    'error': f'Dispute sudah {dispute.status}. Tidak bisa diubah.'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            action = validated_data['action']
            review_note = validated_data.get('review_note', '')
            
            logger.info(f"[ADMIN_DISPUTE_REVIEW] Processing {action} for dispute {dispute_id}")
            
            # ====== HANDLE APPROVE ======
            if action == 'approve':
                result = self._handle_approve(
                    dispute=dispute,
                    request=request,
                    review_note=review_note,
                    manual_update=validated_data.get('manual_update', False),
                    re_verify=validated_data.get('re_verify', True),
                    new_label=validated_data.get('new_label'),
                    new_confidence=validated_data.get('new_confidence'),
                    new_summary=validated_data.get('new_summary')
                )
                
            # ====== HANDLE REJECT ======
            else:  # action == 'reject'
                result = self._handle_reject(
                    dispute=dispute,
                    request=request,
                    review_note=review_note
                )
            
            return Response(result, status=status.HTTP_200_OK)
            
        except Dispute.DoesNotExist:
            logger.error(f"[ADMIN_DISPUTE_REVIEW] Dispute {dispute_id} not found")
            return Response({
                'error': 'Dispute not found'
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"[ADMIN_DISPUTE_REVIEW] Error: {str(e)}", exc_info=True)
            return Response({
                'error': 'Failed to review dispute',
                'detail': str(e) if settings.DEBUG else None
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _handle_approve(self, dispute: Dispute, request, review_note: str,
                       manual_update: bool = False, re_verify: bool = True,
                       new_label: str = None, new_confidence: float = None,
                       new_summary: str = None) -> Dict[str, Any]:
        """
        Handle dispute approval dengan update verification result.
        
        Flow:
        1. Jika manual_update: update langsung dengan data yang diberikan
        2. Jika re_verify: panggil AI untuk re-verify dengan data baru
        3. Update dispute status
        4. Kirim email ke user
        """
        logger.info(f"[APPROVE] Starting approval for dispute {dispute.id}")
        
        # Update dispute status
        dispute.status = Dispute.STATUS_APPROVED
        dispute.reviewed = True
        dispute.reviewed_by = request.user
        dispute.reviewed_at = timezone.now()
        dispute.review_note = review_note
        dispute.save()
        
        logger.info(f"[APPROVE] Dispute {dispute.id} status updated to APPROVED")
        
        # Get or create verification result
        if dispute.claim:
            verification, created = VerificationResult.objects.get_or_create(
                claim=dispute.claim
            )
            
            # ====== MANUAL UPDATE ======
            if manual_update and new_label and new_confidence is not None:
                logger.info(f"[APPROVE] Manual update: label={new_label}, conf={new_confidence}")
                
                verification.label = new_label
                verification.confidence = new_confidence if new_label != 'unverified' else None
                verification.summary = new_summary or verification.summary
                verification.reviewer_notes = f"Admin approved dispute #{dispute.id}\n{review_note}"
                verification.save()
                
                logger.info(f"[APPROVE] VerificationResult {verification.id} updated manually")
                
                updated_via = "manual_admin_update"
                final_label = new_label
                final_confidence = new_confidence
                final_summary = new_summary
            
            # ====== RE-VERIFY WITH AI ======
            elif re_verify:
                logger.info(f"[APPROVE] Re-verifying claim with AI...")
                
                try:
                    # Call AI dengan claim text terbaru
                    ai_result = call_ai_verify(dispute.claim.text)
                    normalized = normalize_ai_response(ai_result, claim_text=dispute.claim.text)
                    
                    logger.info(f"[APPROVE] AI re-verify result: {normalized['label']}")
                    
                    # Update verification result dengan hasil AI baru
                    verification.label = normalized['label']
                    verification.confidence = normalized['confidence']
                    verification.summary = normalized['summary']
                    verification.reviewer_notes = f"Admin approved dispute #{dispute.id} with re-verification\n{review_note}"
                    verification.save()
                    
                    # Update sources jika ada
                    if normalized['sources']:
                        self._update_claim_sources(dispute.claim, normalized['sources'])
                    
                    logger.info(f"[APPROVE] VerificationResult {verification.id} updated with AI re-verify")
                    
                    updated_via = "ai_reverify"
                    final_label = normalized['label']
                    final_confidence = normalized['confidence']
                    final_summary = normalized['summary']
                    
                except Exception as e:
                    logger.error(f"[APPROVE] AI re-verify failed: {str(e)}")
                    # Fallback: gunakan manual data jika ada, atau keep original
                    if manual_update and new_label:
                        verification.label = new_label
                        verification.confidence = new_confidence if new_label != 'unverified' else None
                        verification.summary = new_summary or verification.summary
                    verification.reviewer_notes = f"Admin approved dispute #{dispute.id} (AI re-verify failed)\n{review_note}"
                    verification.save()
                    
                    updated_via = "manual_fallback"
                    final_label = verification.label
                    final_confidence = verification.confidence
                    final_summary = verification.summary
            
            else:
                # Neither manual nor re-verify - keep original
                updated_via = "no_update"
                final_label = verification.label
                final_confidence = verification.confidence
                final_summary = verification.summary
        
        else:
            # Dispute tidak linked ke claim - hanya update dispute
            logger.warning(f"[APPROVE] Dispute {dispute.id} not linked to any claim")
            updated_via = "no_claim"
            final_label = dispute.original_label
            final_confidence = dispute.original_confidence
            final_summary = ""
        
        # ====== SEND EMAIL NOTIFICATION ======
        email_sent = False
        if dispute.reporter_email:
            try:
                email_sent = email_service.notify_user_dispute_approved(
                    dispute=dispute,
                    admin_notes=review_note
                )
                logger.info(f"[APPROVE] Email sent to {dispute.reporter_email}")
            except Exception as e:
                logger.error(f"[APPROVE] Failed to send email: {str(e)}")
        
        logger.info(f"[APPROVE] Dispute {dispute.id} approval completed")
        
        return {
            'message': f'Dispute #{dispute.id} telah di-approve',
            'dispute_id': dispute.id,
            'status': dispute.status,
            'updated_via': updated_via,
            'verification_update': {
                'label': final_label,
                'confidence': final_confidence,
                'summary': final_summary[:200] + '...' if final_summary and len(final_summary) > 200 else final_summary
            },
            'email_sent': email_sent,
            'reviewed_at': dispute.reviewed_at.isoformat() if dispute.reviewed_at else None
        }

    def _handle_reject(self, dispute: Dispute, request, review_note: str) -> Dict[str, Any]:
        """
        Handle dispute rejection - tidak ada perubahan ke verification result.
        """
        logger.info(f"[REJECT] Starting rejection for dispute {dispute.id}")
        
        # Update dispute status
        dispute.status = Dispute.STATUS_REJECTED
        dispute.reviewed = True
        dispute.reviewed_by = request.user
        dispute.reviewed_at = timezone.now()
        dispute.review_note = review_note
        dispute.save()
        
        logger.info(f"[REJECT] Dispute {dispute.id} status updated to REJECTED")
        
        # ====== SEND EMAIL NOTIFICATION ======
        email_sent = False
        if dispute.reporter_email:
            try:
                email_sent = email_service.notify_user_dispute_rejected(
                    dispute=dispute,
                    admin_notes=review_note
                )
                logger.info(f"[REJECT] Email sent to {dispute.reporter_email}")
            except Exception as e:
                logger.error(f"[REJECT] Failed to send email: {str(e)}")
        
        logger.info(f"[REJECT] Dispute {dispute.id} rejection completed")
        
        return {
            'message': f'Dispute #{dispute.id} telah di-reject',
            'dispute_id': dispute.id,
            'status': dispute.status,
            'reason': 'Laporan ditolak. Verification result original tetap berlaku.',
            'email_sent': email_sent,
            'reviewed_at': dispute.reviewed_at.isoformat() if dispute.reviewed_at else None
        }

    def _update_claim_sources(self, claim: Claim, new_sources: List[Dict[str, Any]]):
        """Update sources untuk klaim berdasarkan hasil AI."""
        try:
            # Clear existing sources
            ClaimSource.objects.filter(claim=claim).delete()
            logger.info(f"[SOURCES] Cleared old sources for claim {claim.id}")
            
            # Add new sources
            for idx, source_data in enumerate(new_sources):
                # Get or create source
                doi = (source_data.get('doi') or '').strip()
                url = (source_data.get('url') or '').strip()
                
                source = None
                if doi:
                    source = Source.objects.filter(doi=doi).first()
                elif url:
                    source = Source.objects.filter(url=url).first()
                
                if not source:
                    source = Source.objects.create(
                        title=source_data.get('title', 'Unknown')[:500],
                        doi=doi if doi else None,
                        url=url if url else None,
                        source_type=source_data.get('source_type', 'journal'),
                        credibility_score=source_data.get('relevance_score', 0.5)
                    )
                
                # Create claim-source link
                ClaimSource.objects.create(
                    claim=claim,
                    source=source,
                    relevance_score=source_data.get('relevance_score', 0.0),
                    excerpt=source_data.get('excerpt', ''),
                    rank=idx
                )
            
            logger.info(f"[SOURCES] Added {len(new_sources)} new sources for claim {claim.id}")
        
        except Exception as e:
            logger.error(f"[SOURCES] Error updating sources: {str(e)}")
            
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

