import logging
import hashlib
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db import transaction, models
from django.http import Http404

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
    Jika approved, akan re-verify claim dengan AI dan update verification result.
    """
    permission_classes = [IsAuthenticated, IsAdminUser]

    def post(self, request, dispute_id):
        logger.info(f"[DISPUTE_ADMIN_ACTION] Admin action on dispute {dispute_id} from {request.META.get('REMOTE_ADDR', 'unknown')}")

        try:
            # ✅ Improved error handling untuk dispute not found
            try:
                dispute = Dispute.objects.get(id=dispute_id)
            except Dispute.DoesNotExist:
                logger.warning(f"[DISPUTE_ADMIN_ACTION] Dispute {dispute_id} not found")
                return Response(
                    {
                        'error': 'Dispute tidak ditemukan.',
                        'detail': f'Dispute dengan ID {dispute_id} tidak ada di database.'
                    },
                    status=status.HTTP_404_NOT_FOUND
                )

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
                # Update dispute status
                if action == 'approve':
                    dispute.status = Dispute.STATUS_APPROVED
                    logger.info(f"[DISPUTE_ADMIN_ACTION] Dispute {dispute_id} approved")
                    
                    # Jika ada claim terkait, re-verify dengan AI
                    if dispute.claim:
                        logger.info(f"[DISPUTE_ADMIN_ACTION] Re-verifying claim {dispute.claim.id} with AI")
                        self._reverify_claim_with_ai(dispute.claim, validated_data=serializer.validated_data, dispute=dispute)
                    else:
                        logger.warning(f"[DISPUTE_ADMIN_ACTION] No claim linked to dispute {dispute_id}")
                        
                elif action == 'reject':
                    dispute.status = Dispute.STATUS_REJECTED
                    logger.info(f"[DISPUTE_ADMIN_ACTION] Dispute {dispute_id} rejected")
                    
                    # Update claim status back to done jika sebelumnya disputed
                    if dispute.claim and dispute.claim.status == Claim.STATUS_DISPUTED:
                        dispute.claim.status = Claim.STATUS_DONE
                        dispute.claim.save()
                        logger.info(f"[DISPUTE_ADMIN_ACTION] Restored claim {dispute.claim.id} status to DONE")

                # Update dispute review info
                dispute.reviewed = True
                dispute.review_note = review_note
                dispute.reviewed_by = reviewed_by
                dispute.reviewed_at = timezone.now()
                dispute.save()

                logger.info(f"[DISPUTE_ADMIN_ACTION] Dispute {dispute_id} processed successfully")

            response_data = DisputeDetailSerializer(dispute).data
            return Response(response_data, status=status.HTTP_200_OK)

        except Http404:
            # Handle Django's Http404 explicitly
            logger.warning(f"[DISPUTE_ADMIN_ACTION] Dispute {dispute_id} not found (Http404)")
            return Response(
                {
                    'error': 'Dispute tidak ditemukan.',
                    'detail': f'Dispute dengan ID {dispute_id} tidak ada di database.'
                },
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"[DISPUTE_ADMIN_ACTION] Unexpected error: {str(e)}", exc_info=True)
            return Response(
                {'error': f'Gagal memproses action: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def _reverify_claim_with_ai(self, claim, validated_data, dispute):
        """
        Re-verify claim dengan AI untuk mendapatkan confidence score yang baru.
        Menggunakan supporting evidence dari dispute jika ada.
        """
        try:
            logger.info(f"[REVERIFY] Starting AI re-verification for claim {claim.id}")
            
            # Ambil verification result yang ada
            try:
                verification = claim.verification_result
                original_label = verification.label
                original_confidence = verification.confidence
            except VerificationResult.DoesNotExist:
                logger.warning(f"[REVERIFY] No existing verification for claim {claim.id}")
                verification = None
                original_label = None
                original_confidence = None

            # Simpan original values ke dispute
            dispute.original_label = original_label
            dispute.original_confidence = original_confidence
            dispute.save(update_fields=['original_label', 'original_confidence'])

            # Build context untuk AI dengan evidence dari dispute
            claim_context = self._build_dispute_context(claim, dispute)
            
            logger.info(f"[REVERIFY] Calling AI verification for claim {claim.id}")
            
            # Panggil AI adapter untuk re-verify
            ai_result = ai_adapter.call_ai_verify(claim_context)
            
            logger.info(f"[REVERIFY] AI verification completed. Label: {ai_result.get('label')}, Confidence: {ai_result.get('confidence')}")

            # Update atau create verification result dengan hasil AI
            if verification:
                # Update existing verification
                verification.label = ai_result.get('label', verification.label)
                verification.confidence = ai_result.get('confidence', verification.confidence)
                verification.summary = ai_result.get('summary', verification.summary)
                
                # Tambahkan reviewer note
                reviewer_note = (
                    f"[UPDATED AFTER DISPUTE #{dispute.id}]\n"
                    f"Reviewed by: {dispute.reviewed_by}\n"
                    f"Review note: {dispute.review_note or 'No note provided'}\n"
                    f"Supporting evidence: {dispute.supporting_doi or dispute.supporting_url or 'See attached file'}\n"
                    f"---\n"
                    f"AI re-verification result:\n"
                    f"Previous: {original_label} (confidence: {original_confidence:.2%})\n"
                    f"Updated: {verification.label} (confidence: {verification.confidence:.2%})\n"
                )
                
                if verification.reviewer_notes:
                    verification.reviewer_notes = f"{reviewer_note}\n---\nPrevious notes:\n{verification.reviewer_notes}"
                else:
                    verification.reviewer_notes = reviewer_note
                    
                verification.save()
                logger.info(f"[REVERIFY] Updated verification result for claim {claim.id}")
                
            else:
                # Create new verification result
                verification = VerificationResult.objects.create(
                    claim=claim,
                    label=ai_result.get('label', 'inconclusive'),
                    summary=ai_result.get('summary', ''),
                    confidence=ai_result.get('confidence', 0.0),
                    reviewer_notes=f"Created after dispute #{dispute.id} approval by {dispute.reviewed_by}"
                )
                logger.info(f"[REVERIFY] Created new verification result for claim {claim.id}")

            # Update sources dari AI result jika ada
            sources_data = ai_result.get('sources', [])
            if sources_data:
                logger.info(f"[REVERIFY] Processing {len(sources_data)} sources from AI")
                self._update_claim_sources(claim, sources_data)

            # Update claim status
            claim.status = Claim.STATUS_DONE
            claim.save()
            
            logger.info(f"[REVERIFY] Successfully re-verified claim {claim.id}")

        except Exception as e:
            logger.error(f"[REVERIFY] Error re-verifying claim {claim.id}: {str(e)}", exc_info=True)
            # Jangan raise error, biar dispute tetap bisa di-approve
            # Tapi log errornya untuk investigation
            if verification:
                verification.reviewer_notes = (
                    f"{verification.reviewer_notes or ''}\n\n"
                    f"[ERROR] AI re-verification failed: {str(e)}"
                )
                verification.save()

    def _build_dispute_context(self, claim, dispute) -> str:
        """
        Build context string untuk AI verification dengan evidence dari dispute.
        """
        context_parts = [
            f"Original Claim: {claim.text}",
            "",
            "Additional Evidence from Dispute:",
        ]
        
        if dispute.reason:
            context_parts.append(f"Reason: {dispute.reason}")
        
        if dispute.supporting_doi:
            context_parts.append(f"Supporting DOI: {dispute.supporting_doi}")
            
        if dispute.supporting_url:
            context_parts.append(f"Supporting URL: {dispute.supporting_url}")
            
        if dispute.supporting_file:
            context_parts.append(f"Supporting File: {dispute.supporting_file.name}")
        
        return "\n".join(context_parts)

    def _update_claim_sources(self, claim, sources_data):
        """Update sources untuk claim berdasarkan AI result."""
        try:
            # Clear existing sources
            ClaimSource.objects.filter(claim=claim).delete()
            
            for idx, src_data in enumerate(sources_data, start=1):
                # Get or create source
                source_obj, created = Source.objects.get_or_create(
                    doi=src_data.get('doi', ''),
                    defaults={
                        'title': src_data.get('title', ''),
                        'url': src_data.get('url', ''),
                        'authors': src_data.get('authors', ''),
                        'publisher': src_data.get('publisher', ''),
                    }
                )
                
                # Create claim-source relation
                ClaimSource.objects.create(
                    claim=claim,
                    source=source_obj,
                    relevance_score=src_data.get('relevance_score', 0.0),
                    rank=idx
                )
            
            logger.info(f"[UPDATE_SOURCES] Updated {len(sources_data)} sources for claim {claim.id}")
            
        except Exception as e:
            logger.error(f"[UPDATE_SOURCES] Error updating sources: {str(e)}", exc_info=True)

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

class DisputeValidIdsView(APIView):
    """
    GET endpoint untuk melihat dispute IDs yang valid (untuk debugging).
    """
    permission_classes = [IsAuthenticated, IsAdminUser]

    def get(self, request):
        disputes = Dispute.objects.all().values('id', 'status', 'reviewed', 'created_at')
        return Response({
            'total': disputes.count(),
            'disputes': list(disputes)
        }, status=status.HTTP_200_OK)