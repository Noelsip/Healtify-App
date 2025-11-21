import logging
import hashlib
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db import transaction, models
from django.db.models import Q
from django.http import Http404

from .models import Claim, VerificationResult, Source, ClaimSource, Dispute
from .serializers import (
    ClaimCreateSerializer, 
    ClaimDetailSerializer, 
    DisputeCreateSerializer, 
    DisputeDetailSerializer,
    DisputeAdminActionSerializer
)
from .ai_adapter import call_ai_verify
from .email_service import email_service

logger = logging.getLogger(__name__)

# ===========================
# Utility Functions
# ===========================

def normalize_claim_text(text: str) -> str:
    """Normalisasi teks klaim untuk konsistensi"""
    return text.strip().lower()

def generate_claim_hash(text: str) -> str:
    """Generate hash unik untuk claim text"""
    normalized = normalize_claim_text(text)
    return hashlib.sha256(normalized.encode()).hexdigest()

def check_cached_result(claim_text: str):
    """Mengecek apakah claim sudah pernah diverifikasi sebelumnya"""
    text_hash = generate_claim_hash(claim_text)

    try:
        # Mencari klaim dengan hash yang sesuai
        claim = Claim.objects.filter(
            text_hash=text_hash,
            status=Claim.STATUS_DONE
        ).order_by('-updated_at').first()

        if claim:
            # Mengambil verification result terbaru
            verification = VerificationResult.objects.filter(
                claim=claim
            ).order_by('-created_at').first()
            
            if verification:
                logger.info(f"[CACHE HIT] Found cached result for claim ID: {claim.id}")
                return True, claim, verification
        
        logger.info("[CACHE MISS] Claim tidak ditemukan di cache.")
        return False, None, None
    except Exception as e:
        logger.error(f"[CACHE ERROR] Terjadi kesalahan saat mengecek cache: {str(e)}", exc_info=True)
        return False, None, None

# ===========================
# Claim Views
# ===========================

class ClaimVerifyView(APIView):
    """POST endpoint untuk submit claim dan mendapatkan hasil verifikasi."""

    def post(self, request):
        logger.info(f"[VERIFY] Received request from {request.META.get('REMOTE_ADDR', 'unknown')}")
        logger.debug(f"[VERIFY] Request data: {request.data}")

        serializer = ClaimCreateSerializer(data=request.data)

        if not serializer.is_valid():
            logger.warning(f"[VERIFY] Invalid request data: {serializer.errors}")
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        claim_text = serializer.validated_data['text']
        normalized_text = normalize_claim_text(claim_text)
        text_hash = generate_claim_hash(claim_text)

        logger.info(f"[VERIFY] Processing claim: '{claim_text[:80]}...' (hash: {text_hash[:16]})")

        # Mengecek cache
        is_cached, cache_claim, cached_verification = check_cached_result(claim_text)

        if is_cached and cached_verification:
            # Menggunakan hasil dari cache
            logger.info(f"[VERIFY] Using cached result for claim ID: {cache_claim.id}")
            logger.debug(f"[VERIFY] Cached label: {cached_verification.label}, confidence: {cached_verification.confidence}")

            # Serialize hasil dari cache
            response_data = ClaimDetailSerializer(cache_claim).data
            return Response(response_data, status=status.HTTP_200_OK)
        
        # Membuat claim baru jika tidak ada di cache
        logger.info(f"[VERIFY] Processing new claim: '{claim_text[:80]}'")

        with transaction.atomic():
            # Membuat objek Claim baru
            claim = Claim.objects.create(
                text=claim_text,
                normalized_text=normalized_text,
                text_hash=text_hash,
                status=Claim.STATUS_PROCESSING
            )
            logger.info(f"[VERIFY] Created new Claim object with ID: {claim.id}")

            try:
                # Panggil AI verification
                ai_result = call_ai_verify(claim_text)
                logger.info(f"[VERIFY] AI verification completed for claim {claim.id}")
                logger.debug(f"[VERIFY] AI result: {ai_result}")

                # Simpan verification result
                verification = VerificationResult.objects.create(
                    claim=claim,
                    label=ai_result.get('label', 'inconclusive'),
                    summary=ai_result.get('summary', ''),
                    confidence=ai_result.get('confidence', 0.0)
                )
                logger.info(f"[VERIFY] Created VerificationResult ID: {verification.id}")

                # Simpan sources
                sources_data = ai_result.get('sources', [])
                for idx, source_data in enumerate(sources_data):
                    try:
                        # Get or create Source
                        source, created = Source.objects.get_or_create(
                            doi=source_data.get('doi', ''),
                            defaults={
                                'title': source_data.get('title', 'Unknown'),
                                'url': source_data.get('url', ''),
                            }
                        )
                        
                        # Create ClaimSource relationship
                        ClaimSource.objects.create(
                            claim=claim,
                            source=source,
                            relevance_score=source_data.get('relevance_score', 0.0),
                            rank=idx + 1,
                            excerpt=source_data.get('excerpt', '')
                        )
                        logger.debug(f"[VERIFY] Linked source {source.id} to claim {claim.id}")
                    except Exception as e:
                        logger.error(f"[VERIFY] Error saving source {idx}: {str(e)}")

                # Update claim status
                claim.status = Claim.STATUS_DONE
                claim.save()
                logger.info(f"[VERIFY] Claim {claim.id} verification completed successfully")

                # Serialize dan return
                response_data = ClaimDetailSerializer(claim).data
                return Response(response_data, status=status.HTTP_201_CREATED)

            except Exception as e:
                logger.error(f"[VERIFY] AI verification failed: {str(e)}", exc_info=True)
                
                # Kirim email ke admin jika verification failed
                try:
                    email_service.notify_admin_system_error(
                        error_type="Claim Verification Failed",
                        error_message=str(e),
                        context={
                            'claim_id': claim.id,
                            'claim_text': claim_text[:100],
                            'user_ip': request.META.get('REMOTE_ADDR', 'unknown')
                        }
                    )
                except Exception as email_error:
                    logger.error(f"[VERIFY] Failed to send error notification: {email_error}")
                
                # Update claim status to error
                claim.status = 'error'
                claim.save()
                
                return Response({
                    'error': 'Verification failed',
                    'detail': str(e)
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ClaimDetailView(APIView):
    """GET endpoint untuk mendapatkan detail klaim berdasarkan ID"""

    def get(self, request, claim_id):
        logger.info(f"[DETAIL] Fetching claim detail for ID: {claim_id}")
        
        try:
            claim = get_object_or_404(Claim, id=claim_id)
            logger.debug(f"[DETAIL] Found claim: '{claim.text[:50]}...'")
            
            serializer = ClaimDetailSerializer(claim)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"[DETAIL] Error fetching claim {claim_id}: {str(e)}", exc_info=True)
            raise


class ClaimListView(APIView):
    """GET /api/claims/ - List all claims dengan pagination dan filtering."""
    
    def get(self, request):
        try:
            # Ambil query parameters
            search = request.GET.get('search', '').strip()
            label_filter = request.GET.get('label', '').strip().upper()
            page = int(request.GET.get('page', 1))
            per_page = int(request.GET.get('per_page', 50))
            
            # Base queryset dengan prefetch verification result
            claims = Claim.objects.select_related('verification_result').order_by('-created_at')
            
            # Filter by search term
            if search:
                claims = claims.filter(
                    Q(text__icontains=search) |
                    Q(normalized_text__icontains=search)
                )
            
            # Filter by label (dari verification result)
            if label_filter and label_filter != 'ALL':
                # Map frontend labels ke database labels
                label_mapping = {
                    'TRUE': ['true', 'valid'],
                    'FALSE': ['false', 'hoax'],
                    'MIXTURE': ['misleading', 'partially_valid'],
                    'UNVERIFIED': ['inconclusive', 'unsupported', 'unverified']
                }
                
                db_labels = label_mapping.get(label_filter, [label_filter.lower()])
                claims = claims.filter(verification_result__label__in=db_labels)
            
            # Count total
            total = claims.count()
            
            # Pagination
            start = (page - 1) * per_page
            end = start + per_page
            claims_page = claims[start:end]
            
            # Build response data
            claims_data = []
            for claim in claims_page:
                claim_dict = {
                    'id': claim.id,
                    'text': claim.text,
                    'status': claim.status,
                    'created_at': claim.created_at.isoformat(),
                    'updated_at': claim.updated_at.isoformat(),
                }
                
                # Add verification result if exists
                if hasattr(claim, 'verification_result'):
                    vr = claim.verification_result
                    
                    # Normalize label to frontend format
                    db_label = vr.label.lower()
                    frontend_label = self._map_label_to_frontend(db_label)
                    
                    claim_dict.update({
                        'label': frontend_label,
                        'confidence': vr.confidence,
                        'summary': vr.summary,
                        'verification_created_at': vr.created_at.isoformat()
                    })
                else:
                    claim_dict.update({
                        'label': 'UNVERIFIED',
                        'confidence': 0.0,
                        'summary': None,
                        'verification_created_at': None
                    })
                
                claims_data.append(claim_dict)
            
            logger.info(f"[CLAIM_LIST] Returned {len(claims_data)} claims (page {page}, total {total})")
            
            return Response({
                'claims': claims_data,
                'pagination': {
                    'page': page,
                    'per_page': per_page,
                    'total': total,
                    'total_pages': (total + per_page - 1) // per_page
                }
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"[CLAIM_LIST] Error: {str(e)}", exc_info=True)
            return Response({
                'error': 'Failed to fetch claims',
                'detail': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def _map_label_to_frontend(self, db_label: str) -> str:
        """Map database label ke format yang diharapkan frontend."""
        mapping = {
            'true': 'TRUE',
            'valid': 'TRUE',
            'false': 'FALSE',
            'hoax': 'FALSE',
            'misleading': 'MIXTURE',
            'partially_valid': 'MIXTURE',
            'inconclusive': 'UNVERIFIED',
            'unsupported': 'UNVERIFIED',
            'unverified': 'UNVERIFIED'
        }
        return mapping.get(db_label, 'UNVERIFIED')


# ===========================
# Dispute Views
# ===========================

class DisputeCreateView(APIView):
    """POST endpoint untuk membuat dispute baru"""

    def post(self, request):
        logger.info(f"[DISPUTE CREATE] Received request from {request.META.get('REMOTE_ADDR', 'unknown')}")

        serializer = DisputeCreateSerializer(data=request.data)

        if not serializer.is_valid():
            logger.warning(f"[DISPUTE CREATE] Invalid request data: {serializer.errors}")
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        data = serializer.validated_data
        claim_id = data.get('claim_id')
        claim_text = data.get('claim_text', '')

        # Mencari claim jika ada claim_id
        claim_obj = None
        if claim_id:
            try:
                claim_obj = Claim.objects.get(id=claim_id)
                claim_text = claim_obj.text
            except Claim.DoesNotExist:
                logger.warning(f"[DISPUTE CREATE] Claim ID {claim_id} tidak ditemukan")
        
        # Membuat Dispute
        try:
            # Simpan original verification result jika ada
            original_label = ''
            original_confidence = None
            
            if claim_obj and hasattr(claim_obj, 'verification_result'):
                vr = claim_obj.verification_result
                original_label = vr.label
                original_confidence = vr.confidence
            
            dispute = Dispute.objects.create(
                claim=claim_obj,
                claim_text=claim_text,
                user_feedback=data['reason'],
                reporter_name=data.get('reporter_name', 'Anonymous'),
                reporter_email=data.get('reporter_email', ''),
                supporting_doi=data.get('supporting_doi', ''),
                supporting_url=data.get('supporting_url', ''),
                original_label=original_label,
                original_confidence=original_confidence
            )
            
            logger.info(f"[DISPUTE CREATE] Created dispute ID: {dispute.id}")
            
            # Kirim email ke admin
            try:
                email_service.notify_admin_new_dispute(dispute)
            except Exception as e:
                logger.error(f"[DISPUTE CREATE] Failed to send admin notification: {e}")
            
            return Response({
                'status': True,
                'message': 'Dispute created successfully',
                'dispute': {
                    'id': dispute.id,
                    'status': dispute.status,
                    'created_at': dispute.created_at.isoformat()
                }
            }, status=status.HTTP_201_CREATED)
        
        except Exception as e:
            logger.error(f"[DISPUTE CREATE] Error: {str(e)}", exc_info=True)
            return Response({
                'status': False,
                'message': 'Failed to create dispute'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class DisputeListView(APIView):
    """GET endpoint untuk list dispute"""

    def get(self, request):
        logger.info("[DISPUTE_LIST] Fetching disputes list")

        try:
            disputes = Dispute.objects.select_related('claim').order_by('-created_at')[:50]
            
            dispute_list = []
            for dispute in disputes:
                dispute_list.append({
                    'id': dispute.id,
                    'claim_text': dispute.claim_text[:100],
                    'status': dispute.status,
                    'created_at': dispute.created_at.isoformat()
                })
            
            return Response({
                'disputes': dispute_list,
                'total': disputes.count()
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"[DISPUTE_LIST] Error: {str(e)}", exc_info=True)
            return Response({
                'error': 'Failed to fetch disputes'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class DisputeDetailView(APIView):
    """GET endpoint untuk detail satu dispute"""

    def get(self, request, dispute_id):
        logger.info(f"[DISPUTE_DETAIL] Fetching dispute ID: {dispute_id}")

        try:
            dispute = get_object_or_404(Dispute, id=dispute_id)
            serializer = DisputeDetailSerializer(dispute)
            return Response(serializer.data, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"[DISPUTE_DETAIL] Error: {str(e)}", exc_info=True)
            return Response({
                'error': 'Failed to fetch dispute details'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)