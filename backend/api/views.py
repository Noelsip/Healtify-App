import logging
import hashlib
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db import transaction, models

from .models import Claim, VerificationResult, Source, ClaimSource, Dispute
from .serializers import (
    ClaimCreateSerializer, 
    ClaimDetailSerializer, 
    DisputeCreateSerializer, 
    DisputeDetailSerializer,
    DisputeAdminActionSerializer
)
from . import ai_adapter

logger = logging.getLogger(__name__)

def normalize_claim_text(text: str) -> str:
    """
    Normalisasi teks klaim untuk konsistensi
    """
    return text.strip().lower()

def generate_claim_hash(text: str) -> str:
    """
    Generate hash unik untuk claim text
    """
    normalized = normalize_claim_text(text)
    return hashlib.sha256(normalized.encode()).hexdigest()

def check_cached_result(claim_text: str):
    """
    Mengecek apakah claim sudah pernah diverifikasi sebelumnya
    """
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
                logger.info(f"[CACHE HIT] Claim ditemukan di cache dengan ID: {claim.id}")
                return True, claim, verification
        
        logger.info("[CACHE MISS] Claim tidak ditemukan di cache.")
        return False, None, None
    except Exception as e:
        logger.error(f"[CACHE ERROR] Terjadi kesalahan saat mengecek cache: {str(e)}", exc_info=True)
        return False, None, None
    
class ClaimVerifyView(APIView):
    """
    POST endpoint untuk submit claim dan mendapatkan hasil verifikasi.
    Menggunakan cache untuk mempercepat
    """

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
                # Log sebelum memanggil AI adapter
                logger.info(f"[VERIFY] Calling AI verification for claim ID: {claim.id}")
                logger.debug(f"[VERIFY] Normalized text: '{normalized_text}'")
                
                # Memanggil AI adapter untuk verifikasi
                ai_result = ai_adapter.call_ai_verify(claim_text)

                # Log hasil dari AI
                logger.info(f"[VERIFY] AI verification completed for claim ID: {claim.id}")
                logger.info(f"[VERIFY] Result label: {ai_result.get('label', 'unknown')}, confidence: {ai_result.get('confidence', 0.0):.2%}")
                logger.debug(f"[VERIFY] Full AI result: {ai_result}")

                # Menyimpan hasil verifikasi
                verification = VerificationResult.objects.create(
                    claim=claim,
                    label=ai_result.get('label', 'inconclusive'),
                    summary=ai_result.get('summary', ''),
                    confidence=ai_result.get('confidence', 0.0)
                )
                logger.info(f"[VERIFY] Created VerificationResult with ID: {verification.id}")

                # Menyimpan sources
                sources_data = ai_result.get('sources', [])
                logger.info(f"[VERIFY] Processing {len(sources_data)} sources for claim ID: {claim.id}")
            
                for idx, src_data in enumerate(sources_data, start=1):
                    # Mencari atau membuat source
                    doi = src_data.get('doi', '') or ''

                    if doi:
                        source, created = Source.objects.get_or_create(
                            doi=doi,
                            defaults={
                                'title': src_data.get('title', '')[:500],
                                'url': src_data.get('url', '')
                            }
                        )
                        logger.debug(f"[VERIFY] Source {idx}/{len(sources_data)}: DOI={doi} (Created: {created})")
                    else:
                        # Jika tidak ada DOI, buat source baru
                        source = Source.objects.create(
                            title=src_data.get('title', '')[:500],
                            url=src_data.get('url', ''),
                            doi=''
                        )
                        created = True
                        logger.debug(f"[VERIFY] Source {idx}/{len(sources_data)}: No DOI, created new source ID: {source.id}")
                    
                    if not created and src_data.get('title'):
                        # Update title jika source sudah ada
                        source.title = src_data.get('title', '')[:500]
                        source.save()
                        logger.debug(f"[VERIFY] Updated title for existing source: {source.doi}")

                    # Membuat relasi ClaimSource
                    ClaimSource.objects.create(
                        claim=claim,
                        source=source,
                        relevance_score=src_data.get('relevance_score', 0.0),
                        rank=idx
                    )

                logger.info(f"[VERIFY] Successfully processed all {len(sources_data)} sources")

                # Update status claim
                claim.status = Claim.STATUS_DONE
                claim.save()

                logger.info(f"[VERIFY]  Claim {claim.id} processed successfully (label: {verification.label})")

                # Return response
                response_data = ClaimDetailSerializer(claim).data
                return Response(response_data, status=status.HTTP_201_CREATED)

            except Exception as e:
                # Log error dengan full traceback
                logger.error(f"[VERIFY]  Error processing claim ID {claim.id}: {str(e)}", exc_info=True)
                
                # Jika error, update status ke pending
                claim.status = Claim.STATUS_PENDING
                claim.save()
                logger.warning(f"[VERIFY] Updated claim {claim.id} status to PENDING due to error")

                return Response(
                    {'error': f'Gagal memverifikasi klaim: {str(e)}'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            
class ClaimDetailView(APIView):
    """
    GET endpoint untuk mendapatkan detail klaim berdasarkan ID
    """

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
    """
    GET endpoint untuk mendapatkan list semua claims
    """

    def get(self, request):
        logger.info("[LIST] Fetching claims list")
        
        try:
            claims = Claim.objects.filter(
                status=Claim.STATUS_DONE
            ).order_by('-created_at')[:50]
            
            logger.info(f"[LIST] Found {claims.count()} completed claims")
            
            serializer = ClaimDetailSerializer(claims, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"[LIST] Error fetching claims list: {str(e)}", exc_info=True)
            return Response(
                {'error': 'Gagal mengambil daftar klaim'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
class DisputeCreateView(APIView):
    """
        POST endpoit untuk membuat dispute baru
    """

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
                logger.info(f"[DISPUTE] Found claim ID: {claim_id}")
            except Claim.DoesNotExist:
                logger.warning(f"[DISPUTE] Claim ID {claim_id} not found")
                return Response(
                    {'error': f'Claim dengan ID {claim_id} tidak ditemukan.'},
                    status=status.HTTP_404_NOT_FOUND
                )
            
        # Membuat Dispute
        try:
            dispute = Dispute.objects.create(
                claim=claim_obj,
                claim_text=claim_text if not claim_obj else claim_obj.text,
                reporter_name = data.get('reporter_name', ''),
                reporter_email = data.get('reporter_email', ''),
                reason = data['reason'],
                supporting_doi = data.get('supporting_doi', ''),
                supporting_url = data.get('supporting_url', ''),
                supporting_file = request.FILES.get('supporting_file')
            )

            logger.info(f"[DISPUTE CREATE] Created Dispute ID: {dispute.id} ")

            # Mengupdate status claim jika ada
            if claim_obj:
                claim_obj.status = Claim.STATUS_DISPUTED
                claim_obj.save()
                logger.info(f"[DISPUTE CREATE] Updated Claim ID {claim_obj.id} status to DISPUTED")
            
            response_data = DisputeDetailSerializer(dispute).data
            return Response(response_data, status=status.HTTP_201_CREATED)
        
        except Exception as e:
            logger.error(f"[DISPUTE CREATE] Error creating dispute: {str(e)}", exc_info=True)
            return Response(
                {'error': 'Gagal membuat dispute.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
class DisputeListView(APIView):
    """
    GET endpoint untuk list dispute (admin only atau public?)
    """

    def get(self, request):
        logger.info("[DISPUTE_LIST] Fetching disputes list")

        try:
            # Filter berdasarkan status reviewd
            reviewed_filter = request.query_params.get('reviewed')

            disputes = Dispute.objects.all()

            if reviewed_filter is not None:
                reviewed_bool = reviewed_filter.lower() in ['true', '1', 'yes']
                disputes = disputes.filter(reviewed=reviewed_bool)

            disputes = disputes.order_by('-created_at')[:50]

            logger.info(f"[DISPUTE_LIST] Found {disputes.count()} disputes")

            serializer = DisputeDetailSerializer(disputes, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"[DISPUTE_LIST] Error fetching disputes list: {str(e)}", exc_info=True)
            return Response(
                {'error': 'Gagal mengambil daftar dispute.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class DisputeDetailView(APIView):
    """
        GET endpoint untuk detail satu dispute
    """

    def get(self, request, dispute_id):
        logger.info(f"[DISPUTE_DETAIL] Fetching dispute ID: {dispute_id}")

        try:
            dispute = get_object_or_404(Dispute, id=dispute_id)
            serializer = DisputeDetailSerializer(dispute)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"[DISPUTE_DETAIL] Error: {str(e)}", exc_info=True)
            raise

class DisputeAdminListView(APIView):
    """
    GET endpoint untuk admin melihat semua disputes dengan filtering.
    Admin only endpoint.
    """
    permission_classes = [IsAuthenticated, IsAdminUser]  # ✅ AKTIF

    def get(self, request):
        logger.info(f"[DISPUTE_ADMIN_LIST] Admin request from {request.META.get('REMOTE_ADDR', 'unknown')}")

        try:
            status_filter = request.query_params.get('status')
            reviewed_filter = request.query_params.get('reviewed')
            has_claim = request.query_params.get('has_claim')

            disputes = Dispute.objects.all()

            if status_filter and status_filter in dict(Dispute.STATUS_CHOICES):
                disputes = disputes.filter(status=status_filter)
                logger.debug(f"[DISPUTE_ADMIN_LIST] Filtered by status: {status_filter}")

            if reviewed_filter is not None:
                reviewed_bool = reviewed_filter.lower() in ['true', '1', 'yes']
                disputes = disputes.filter(reviewed=reviewed_bool)
                logger.debug(f"[DISPUTE_ADMIN_LIST] Filtered by reviewed: {reviewed_bool}")

            if has_claim is not None:
                has_claim_bool = has_claim.lower() in ['true', '1', 'yes']
                if has_claim_bool:
                    disputes = disputes.filter(claim__isnull=False)
                else:
                    disputes = disputes.filter(claim__isnull=True)
                logger.debug(f"[DISPUTE_ADMIN_LIST] Filtered by has_claim: {has_claim_bool}")

            disputes = disputes.order_by(
                models.Case(
                    models.When(status=Dispute.STATUS_PENDING, then=0),
                    models.When(status=Dispute.STATUS_APPROVED, then=1),
                    models.When(status=Dispute.STATUS_REJECTED, then=2),
                    default=3,
                    output_field=models.IntegerField(),
                ),
                '-created_at'
            )

            page_size = int(request.query_params.get('page_size', 20))
            page = int(request.query_params.get('page', 1))
            start = (page - 1) * page_size
            end = start + page_size

            total_count = disputes.count()
            disputes_page = disputes[start:end]

            logger.info(f"[DISPUTE_ADMIN_LIST] Returning {disputes_page.count()} of {total_count} disputes")

            serializer = DisputeDetailSerializer(disputes_page, many=True)

            return Response({
                'results': serializer.data,
                'count': total_count,
                'page': page,
                'page_size': page_size,
                'total_pages': (total_count + page_size - 1) // page_size
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"[DISPUTE_ADMIN_LIST] Error: {str(e)}", exc_info=True)
            return Response(
                {'error': 'Gagal mengambil daftar disputes.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class DisputeAdminActionView(APIView):
    """
    POST endpoint untuk admin approve/reject dispute.
    Jika approved, akan update verification result dari claim terkait.
    """
    permission_classes = [IsAuthenticated, IsAdminUser]  # ✅ AKTIF

    def post(self, request, dispute_id):
        logger.info(f"[DISPUTE_ADMIN_ACTION] Admin action on dispute {dispute_id} from {request.META.get('REMOTE_ADDR', 'unknown')}")

        try:
            dispute = get_object_or_404(Dispute, id=dispute_id)

            if dispute.reviewed:
                logger.warning(f"[DISPUTE_ADMIN_ACTION] Dispute {dispute_id} already reviewed")
                return Response(
                    {'error': 'Dispute ini sudah di-review sebelumnya.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            serializer = DisputeAdminActionSerializer(data=request.data)
            if not serializer.is_valid():
                logger.warning(f"[DISPUTE_ADMIN_ACTION] Invalid data: {serializer.errors}")
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            action = serializer.validated_data['action']
            review_note = serializer.validated_data.get('review_note', '')
            reviewed_by = serializer.validated_data.get('reviewed_by', request.user.username)

            logger.info(f"[DISPUTE_ADMIN_ACTION] Action: {action}, Reviewed by: {reviewed_by}")

            with transaction.atomic():
                if dispute.claim:
                    try:
                        original_verification = dispute.claim.verification_result
                        dispute.original_label = original_verification.label
                        dispute.original_confidence = original_verification.confidence
                    except VerificationResult.DoesNotExist:
                        pass

                dispute.reviewed = True
                dispute.reviewed_at = timezone.now()
                dispute.review_note = review_note
                dispute.reviewed_by = reviewed_by
                dispute.status = Dispute.STATUS_APPROVED if action == 'approve' else Dispute.STATUS_REJECTED
                dispute.save()

                logger.info(f"[DISPUTE_ADMIN_ACTION] Dispute {dispute_id} marked as {dispute.status}")

                if action == 'approve' and dispute.claim:
                    self._update_claim_verification(
                        dispute.claim,
                        serializer.validated_data,
                        dispute
                    )
                    logger.info(f"[DISPUTE_ADMIN_ACTION] Updated verification for claim {dispute.claim.id}")

            response_data = DisputeDetailSerializer(dispute).data
            return Response(response_data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"[DISPUTE_ADMIN_ACTION] Error: {str(e)}", exc_info=True)
            return Response(
                {'error': f'Gagal memproses action: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def _update_claim_verification(self, claim, validated_data, dispute):
        """Helper method untuk update verification result dari claim."""
        try:
            verification = claim.verification_result

            new_label = validated_data.get('new_label')
            new_confidence = validated_data.get('new_confidence')
            new_summary = validated_data.get('new_summary')

            if new_label:
                verification.label = new_label
                logger.debug(f"[UPDATE_VERIFICATION] New label: {new_label}")

            if new_confidence is not None:
                verification.confidence = new_confidence
                logger.debug(f"[UPDATE_VERIFICATION] New confidence: {new_confidence}")

            if new_summary:
                verification.summary = new_summary
                logger.debug(f"[UPDATE_VERIFICATION] New summary length: {len(new_summary)}")

            reviewer_note = (
                f"Verification updated based on approved dispute #{dispute.id}. "
                f"Reviewed by: {dispute.reviewed_by}. "
            )
            if dispute.review_note:
                reviewer_note += f"Admin note: {dispute.review_note}"

            verification.reviewer_notes = reviewer_note
            verification.save()

            claim.status = Claim.STATUS_DONE
            claim.save()

            logger.info(f"[UPDATE_VERIFICATION] Successfully updated claim {claim.id}")

        except VerificationResult.DoesNotExist:
            logger.warning(f"[UPDATE_VERIFICATION] No verification result for claim {claim.id}")
            if validated_data.get('new_label'):
                VerificationResult.objects.create(
                    claim=claim,
                    label=validated_data['new_label'],
                    confidence=validated_data.get('new_confidence', 0.5),
                    summary=validated_data.get('new_summary', ''),
                    reviewer_notes=f"Created from approved dispute #{dispute.id}"
                )
                logger.info(f"[UPDATE_VERIFICATION] Created new verification for claim {claim.id}")


class DisputeStatsView(APIView):
    """
    GET endpoint untuk statistik disputes (untuk dashboard admin).
    """
    permission_classes = [IsAuthenticated, IsAdminUser]  # ✅ AKTIF

    def get(self, request):
        logger.info("[DISPUTE_STATS] Fetching dispute statistics")

        try:
            stats = {
                'total': Dispute.objects.count(),
                'pending': Dispute.objects.filter(status=Dispute.STATUS_PENDING).count(),
                'approved': Dispute.objects.filter(status=Dispute.STATUS_APPROVED).count(),
                'rejected': Dispute.objects.filter(status=Dispute.STATUS_REJECTED).count(),
                'with_claim': Dispute.objects.filter(claim__isnull=False).count(),
                'reviewed': Dispute.objects.filter(reviewed=True).count(),
                'unreviewed': Dispute.objects.filter(reviewed=False).count(),
            }

            logger.info(f"[DISPUTE_STATS] Stats: {stats}")
            return Response(stats, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"[DISPUTE_STATS] Error: {str(e)}", exc_info=True)
            return Response(
                {'error': 'Gagal mengambil statistik.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )