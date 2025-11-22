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
from django.conf import settings

from .models import Claim, VerificationResult, Source, ClaimSource, Dispute
from .serializers import (
    ClaimCreateSerializer, 
    ClaimDetailSerializer, 
    DisputeCreateSerializer, 
    DisputeDetailSerializer,
    DisputeAdminActionSerializer
)
from .ai_adapter import call_ai_verify, determine_verification_label
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
    """
    POST endpoint untuk submit claim dan mendapatkan hasil verifikasi.
    
    Process:
        1. Validate input claim text
        2. Check cache untuk hasil verifikasi sebelumnya
        3. Jika cache miss, process dengan AI verification
        4. Tentukan label berdasarkan confidence score
        5. Save hasil dan return response
    
    Returns:
        - 200: Verification result (dari cache atau baru)
        - 400: Invalid request data
        - 500: Verification failed
    """
    
    # Label determination thresholds
    CONFIDENCE_THRESHOLD_VALID = 0.75
    CONFIDENCE_THRESHOLD_HOAX = 0.5

    def post(self, request):
        """Process claim verification request."""
        logger.info(f"[VERIFY] Received request from {request.META.get('REMOTE_ADDR', 'unknown')}")
        
        # Validate input
        serializer = ClaimCreateSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning(f"[VERIFY] Invalid request data: {serializer.errors}")
            return Response(
                serializer.errors, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        claim_text = serializer.validated_data['text']
        logger.info(f"[VERIFY] Processing claim: '{claim_text[:80]}...'")
        
        # Check cache first
        cached_response = self._get_cached_result(claim_text)
        if cached_response:
            return cached_response
        
        # Process new claim
        try:
            claim = self._create_new_claim(claim_text)
            verification = self._process_verification(claim)
            
            # Update claim status to done
            claim.status = Claim.STATUS_DONE
            claim.save()
            
            # Return response
            logger.info(f"[VERIFY] Successfully processed claim {claim.id}")
            response_data = ClaimDetailSerializer(claim).data
            return Response(response_data, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"[VERIFY] Verification failed: {str(e)}", exc_info=True)
            return self._handle_verification_error(e, claim_text, request)
    
    def _get_cached_result(self, claim_text):
        """
        Check if claim has been verified before.
        
        Args:
            claim_text (str): The claim text to check
            
        Returns:
            Response or None: Response object if cached, None otherwise
        """
        is_cached, cache_claim, cached_verification = check_cached_result(claim_text)
        
        if is_cached and cached_verification:
            logger.info(
                f"[VERIFY] Cache HIT - Claim ID: {cache_claim.id}, "
                f"Label: {cached_verification.label}, "
                f"Confidence: {cached_verification.confidence:.2f}"
            )
            
            response_data = ClaimDetailSerializer(cache_claim).data
            return Response(response_data, status=status.HTTP_200_OK)
        
        logger.info("[VERIFY] Cache MISS - Processing new claim")
        return None
    
    def _create_new_claim(self, claim_text):
        """
        Create new Claim object in database.
        
        Args:
            claim_text (str): The claim text
            
        Returns:
            Claim: Created claim object
        """
        normalized_text = normalize_claim_text(claim_text)
        text_hash = generate_claim_hash(claim_text)
        
        claim = Claim.objects.create(
            text=claim_text,
            normalized_text=normalized_text,
            text_hash=text_hash,
            status=Claim.STATUS_PROCESSING
        )
        
        logger.info(
            f"[VERIFY] Created Claim ID: {claim.id} "
            f"(hash: {text_hash[:16]}...)"
        )
        
        return claim
    
    def _process_verification(self, claim):
        """
        Process AI verification and create VerificationResult.
        
        Args:
            claim (Claim): The claim to verify
            
        Returns:
            VerificationResult: Created verification result
            
        Raises:
            Exception: If AI verification fails
        """
        # Call AI verification service
        ai_result = call_ai_verify(claim.text)
        
        logger.info(f"[VERIFY] AI verification completed for claim {claim.id}")
        logger.debug(f"[VERIFY] AI result summary: {ai_result.get('summary', '')[:100]}...")
        
        # Extract results
        sources_data = ai_result.get('sources', [])
        confidence = ai_result.get('confidence', 0.0)
        summary = ai_result.get('summary', '')

        has_journal = any(
            (s.get('doi') or '').strip() or s.get('source_type') == 'journal'
            for s in sources_data
        )

        label = determine_verification_label(
            confidence_score=confidence,
            has_sources=bool(sources_data),
            has_journal=has_journal
        )

        verification = VerificationResult.objects.create(
            claim=claim,
            label=label,
            summary=summary,
            confidence=confidence
        )
        
        logger.info(
            f"[VERIFY] Created VerificationResult ID: {verification.id} - "
            f"Label: {label}, Confidence: {confidence:.2f}, "
            f"Sources: {len(sources_data)}"
        )
        
        # Process and link sources
        if sources_data:
            self._process_sources(claim, sources_data)
        
        return verification
    
    def _determine_label(self, confidence, sources_data):
        """
        Determine verification label based on confidence score and sources.
        
        Logic:
            - No sources → UNVERIFIED
            - Confidence >= 0.75 → VALID
            - Confidence <= 0.5 → HOAX
            - 0.5 < Confidence < 0.75 → UNCERTAIN
        
        Args:
            confidence (float): Confidence score (0.0 - 1.0)
            sources_data (list): List of source data
            
        Returns:
            str: Label constant (LABEL_VALID, LABEL_HOAX, etc.)
        """
        has_sources = len(sources_data) > 0
        
        if not has_sources:
            logger.info("[VERIFY] No sources found → UNVERIFIED")
            return VerificationResult.LABEL_UNVERIFIED
        
        if confidence >= self.CONFIDENCE_THRESHOLD_VALID:
            logger.info(f"[VERIFY] Confidence {confidence:.2f} >= {self.CONFIDENCE_THRESHOLD_VALID} → VALID")
            return VerificationResult.LABEL_VALID
        
        if confidence <= self.CONFIDENCE_THRESHOLD_HOAX:
            logger.info(f"[VERIFY] Confidence {confidence:.2f} <= {self.CONFIDENCE_THRESHOLD_HOAX} → HOAX")
            return VerificationResult.LABEL_HOAX
        
        # 0.5 < confidence < 0.75
        logger.info(
            f"[VERIFY] Confidence {confidence:.2f} between "
            f"{self.CONFIDENCE_THRESHOLD_HOAX}-{self.CONFIDENCE_THRESHOLD_VALID} → UNCERTAIN"
        )
        return VerificationResult.LABEL_UNCERTAIN
    
    def _process_sources(self, claim, sources_data):
        """
        Process and link sources to claim.
        
        Args:
            claim (Claim): The claim object
            sources_data (list): List of source dictionaries from AI
        """
        processed_count = 0
        
        for idx, source_data in enumerate(sources_data):
            try:
                source = self._create_or_get_source(source_data)
                
                # Create ClaimSource relationship
                ClaimSource.objects.create(
                    claim=claim,
                    source=source,
                    relevance_score=source_data.get('relevance_score', 0.0),
                    excerpt=source_data.get('excerpt', ''),
                    rank=idx + 1
                )
                
                processed_count += 1
                
            except Exception as e:
                logger.error(
                    f"[VERIFY] Failed to process source {idx + 1}: {str(e)}", 
                    exc_info=True
                )
        
        logger.info(
            f"[VERIFY] Linked {processed_count}/{len(sources_data)} sources to claim {claim.id}"
        )
    
    def _create_or_get_source(self, source_data):
        """
        Create or retrieve existing Source object.
        
        Args:
            source_data (dict): Source information from AI
            
        Returns:
            Source: Created or existing source object
        """
        doi = source_data.get('doi', '').strip()
        url = source_data.get('url', '').strip()
        
        # Try to find existing source by DOI or URL
        if doi:
            source = Source.objects.filter(doi=doi).first()
            if source:
                return source
        
        if url:
            source = Source.objects.filter(url=url).first()
            if source:
                return source
        
        # Create new source
        source = Source.objects.create(
            title=source_data.get('title', 'Unknown')[:500],
            doi=doi if doi else None,
            url=url if url else None,
            authors=source_data.get('authors', ''),
            publisher=source_data.get('publisher', '')[:255],
            published_date=source_data.get('published_date'),
            source_type=source_data.get('source_type', 'journal'),
            credibility_score=source_data.get('credibility_score', 0.5)
        )
        
        logger.debug(f"[VERIFY] Created new Source ID: {source.id}")
        return source
    
    def _handle_verification_error(self, error, claim_text, request):
        """
        Handle verification errors gracefully.
        
        Args:
            error (Exception): The exception that occurred
            claim_text (str): The claim text being processed
            request: The HTTP request object
            
        Returns:
            Response: Error response
        """
        logger.error(f"[VERIFY] Verification error: {str(error)}", exc_info=True)
        
        # Try to send admin notification
        try:
            email_service.notify_admin_system_error(
                error_type="Claim Verification Failed",
                error_message=str(error),
                context={
                    'claim_text': claim_text[:100],
                    'user_ip': request.META.get('REMOTE_ADDR', 'unknown'),
                    'error_type': type(error).__name__
                }
            )
        except Exception as email_error:
            logger.error(
                f"[VERIFY] Failed to send error notification: {str(email_error)}"
            )
        
        return Response(
            {
                'error': 'Verification failed',
                'message': 'Terjadi kesalahan saat memverifikasi klaim. Tim kami telah diberitahu.',
                'detail': str(error) if settings.DEBUG else None
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

class ClaimDetailView(APIView):
    """
    GET endpoint untuk mendapatkan detail klaim berdasarkan ID.
    
    Returns:
        - 200: Claim detail dengan verification result
        - 404: Claim tidak ditemukan
        - 500: Server error
    """

    def get(self, request, claim_id):
        """Retrieve detailed information for a specific claim."""
        logger.info(f"[CLAIM_DETAIL] Fetching claim ID: {claim_id}")
        
        try:
            claim = self._get_claim_or_404(claim_id)
            serializer = ClaimDetailSerializer(claim)
            
            logger.info(f"[CLAIM_DETAIL] Successfully retrieved claim {claim_id}")
            return Response(serializer.data, status=status.HTTP_200_OK)
            
        except Http404:
            logger.warning(f"[CLAIM_DETAIL] Claim {claim_id} not found")
            raise
            
        except Exception as e:
            logger.error(f"[CLAIM_DETAIL] Unexpected error for claim {claim_id}: {str(e)}", exc_info=True)
            return Response(
                {
                    'error': 'Failed to fetch claim details',
                    'detail': 'An unexpected error occurred'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def _get_claim_or_404(self, claim_id):
        """
        Get claim by ID or raise 404.
        
        Args:
            claim_id: The claim ID to fetch
            
        Returns:
            Claim object with prefetched relations
            
        Raises:
            Http404: If claim doesn't exist
        """
        return get_object_or_404(
            Claim.objects.select_related('verification_result')
                         .prefetch_related('sources'),
            id=claim_id
        )

class ClaimListView(APIView):
    """
    GET endpoint untuk list claims dengan pagination dan filtering.
    
    Query Parameters:
        - search (str): Search term untuk claim text
        - label (str): Filter by label (valid, hoax, uncertain, unverified)
        - page (int): Page number (default: 1)
        - per_page (int): Items per page (default: 50, max: 100)
    
    Returns:
        - 200: List of claims dengan pagination info
        - 400: Invalid parameters
        - 500: Server error
    """
    
    DEFAULT_PAGE = 1
    DEFAULT_PER_PAGE = 50
    MAX_PER_PAGE = 100
    
    # Valid filter labels
    VALID_LABELS = ['valid', 'hoax', 'uncertain', 'unverified']

    def get(self, request):
        """List all claims with filtering and pagination."""
        logger.info(f"[CLAIM_LIST] Request from {request.META.get('REMOTE_ADDR', 'unknown')}")
        
        try:
            # Parse and validate query parameters
            params = self._parse_query_params(request)
            
            # Build queryset with filters
            claims = self._build_queryset(params)
            
            # Get total count before pagination
            total = claims.count()
            
            # Apply pagination
            claims_page = self._paginate_queryset(claims, params)
            
            # Serialize claims data
            claims_data = self._serialize_claims(claims_page)
            
            # Build pagination metadata
            pagination = self._build_pagination_metadata(params, total)
            
            logger.info(
                f"[CLAIM_LIST] Returned {len(claims_data)} claims "
                f"(page {params['page']}/{pagination['total_pages']}, total {total})"
            )
            
            return Response(
                {
                    'claims': claims_data,
                    'pagination': pagination,
                    'filters': {
                        'search': params['search'],
                        'label': params['label']
                    }
                },
                status=status.HTTP_200_OK
            )
            
        except ValueError as e:
            logger.warning(f"[CLAIM_LIST] Invalid parameters: {str(e)}")
            return Response(
                {
                    'error': 'Invalid parameters',
                    'detail': str(e)
                },
                status=status.HTTP_400_BAD_REQUEST
            )
            
        except Exception as e:
            logger.error(f"[CLAIM_LIST] Unexpected error: {str(e)}", exc_info=True)
            return Response(
                {
                    'error': 'Failed to fetch claims',
                    'detail': 'An unexpected error occurred'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def _parse_query_params(self, request):
        """
        Parse and validate query parameters.
        
        Args:
            request: The HTTP request object
            
        Returns:
            dict: Validated parameters
            
        Raises:
            ValueError: If parameters are invalid
        """
        # Search term
        search = request.GET.get('search', '').strip()
        
        # Label filter
        label_filter = request.GET.get('label', '').strip().lower()
        if label_filter and label_filter not in ['all', ''] + self.VALID_LABELS:
            raise ValueError(
                f"Invalid label filter. Must be one of: {', '.join(self.VALID_LABELS)}"
            )
        
        # Pagination
        try:
            page = int(request.GET.get('page', self.DEFAULT_PAGE))
            if page < 1:
                raise ValueError("Page must be >= 1")
        except (ValueError, TypeError):
            raise ValueError("Invalid page number")
        
        try:
            per_page = int(request.GET.get('per_page', self.DEFAULT_PER_PAGE))
            if per_page < 1:
                raise ValueError("per_page must be >= 1")
            if per_page > self.MAX_PER_PAGE:
                per_page = self.MAX_PER_PAGE
        except (ValueError, TypeError):
            raise ValueError("Invalid per_page number")
        
        return {
            'search': search,
            'label': label_filter if label_filter not in ['all', ''] else None,
            'page': page,
            'per_page': per_page
        }
    
    def _build_queryset(self, params):
        """
        Build queryset dengan filters yang diterapkan.
        
        Args:
            params (dict): Validated query parameters
            
        Returns:
            QuerySet: Filtered claims queryset
        """
        # Base queryset dengan optimized prefetch
        claims = Claim.objects.select_related(
            'verification_result'
        ).prefetch_related(
            'sources'
        ).order_by('-created_at')
        
        # Apply search filter
        if params['search']:
            claims = claims.filter(
                Q(text__icontains=params['search']) |
                Q(normalized_text__icontains=params['search'])
            )
        
        # Apply label filter
        if params['label']:
            claims = claims.filter(verification_result__label=params['label'])
        
        return claims
    
    def _paginate_queryset(self, queryset, params):
        """
        Apply pagination to queryset.
        
        Args:
            queryset: The queryset to paginate
            params (dict): Contains page and per_page
            
        Returns:
            QuerySet: Paginated slice of queryset
        """
        start = (params['page'] - 1) * params['per_page']
        end = start + params['per_page']
        return queryset[start:end]
    
    def _serialize_claims(self, claims):
        """
        Convert claims to serialized data.
        
        Args:
            claims: Iterable of Claim objects
            
        Returns:
            list: List of claim dictionaries
        """
        claims_data = []
        
        for claim in claims:
            claim_dict = self._serialize_claim(claim)
            claims_data.append(claim_dict)
        
        return claims_data
    
    def _serialize_claim(self, claim):
        """
        Serialize single claim object.
        
        Args:
            claim: Claim object
            
        Returns:
            dict: Serialized claim data
        """
        claim_dict = {
            'id': claim.id,
            'text': claim.text,
            'status': claim.status,
            'created_at': claim.created_at.isoformat(),
            'updated_at': claim.updated_at.isoformat(),
        }
        
        # Add verification result if exists
        if hasattr(claim, 'verification_result'):
            verification = self._serialize_verification_result(claim.verification_result)
            claim_dict.update(verification)
        else:
            claim_dict.update(self._get_default_verification())
        
        return claim_dict
    
    def _serialize_verification_result(self, vr):
        """
        Serialize verification result.
        
        Args:
            vr: VerificationResult object
            
        Returns:
            dict: Serialized verification data
        """
        return {
            'label': vr.label,
            'label_display': vr.get_label_display(),
            'confidence': round(vr.confidence, 4),
            'confidence_percent': vr.confidence_percent(),
            'summary': vr.summary,
            'verification_created_at': vr.created_at.isoformat(),
            'verification_updated_at': vr.updated_at.isoformat()
        }
    
    def _get_default_verification(self):
        """
        Get default verification data for claims without results.
        
        Returns:
            dict: Default verification data
        """
        return {
            'label': VerificationResult.LABEL_UNVERIFIED,
            'label_display': 'Tidak Terverifikasi',
            'confidence': 0.0,
            'confidence_percent': 0.0,
            'summary': None,
            'verification_created_at': None,
            'verification_updated_at': None
        }
    
    def _build_pagination_metadata(self, params, total):
        """
        Build pagination metadata.
        
        Args:
            params (dict): Query parameters with page and per_page
            total (int): Total number of items
            
        Returns:
            dict: Pagination metadata
        """
        total_pages = (total + params['per_page'] - 1) // params['per_page']
        
        return {
            'page': params['page'],
            'per_page': params['per_page'],
            'total': total,
            'total_pages': max(total_pages, 1),
            'has_next': params['page'] < total_pages,
            'has_previous': params['page'] > 1
        }

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