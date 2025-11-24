import logging
import hashlib
import re
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import api_view
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
from .text_normalization import (
    ClaimSimilarityMatcher, 
    calculate_text_similarity,
    normalize_claim_text
)
from .ai_adapter import call_ai_verify, determine_verification_label
from .email_service import email_service
from .models import Claim

logger = logging.getLogger(__name__)

# ===========================
# Utility Functions - IMPROVED NORMALIZATION
# ===========================

def normalize_claim_text(text: str) -> str:
    """
    Normalisasi teks klaim untuk konsistensi - IMPROVED VERSION.
    
    Proses normalisasi:
    1. Lowercase
    2. Remove extra whitespace
    3. Remove punctuation (kecuali yang bermakna medis)
    4. Standardize medical terms
    5. Remove common stop words (optional)
    """
    if not text:
        return ""
    
    # 1. Lowercase
    normalized = text.lower().strip()
    
    # 2. Replace multiple spaces/tabs/newlines dengan single space
    normalized = re.sub(r'\s+', ' ', normalized)
    
    # 3. Remove punctuation KECUALI yang bermakna (angka, persen, slash untuk dosis)
    # Hapus: . , ! ? ; : " ' ( ) [ ] { } - _ 
    # Tapi pertahankan: / (untuk dosis), % (untuk persentase)
    normalized = re.sub(r'[.,!?;:\"\'\(\)\[\]\{\}_]', '', normalized)
    normalized = re.sub(r'-+', ' ', normalized)  # Tanda hubung jadi spasi
    
    # 4. Standardisasi variasi ejaan medis umum
    medical_variations = {
        r'\bkanker paru paru\b': 'kanker paru',
        r'\bkanker paruparu\b': 'kanker paru',
        r'\bparu paru\b': 'paru',
        r'\bdiabetes mellitus\b': 'diabetes',
        r'\bdiabetes melitus\b': 'diabetes',
        r'\btekanan darah tinggi\b': 'hipertensi',
        r'\bserangan jantung\b': 'infark miokard',
        r'\bstroke\b': 'stroke',
        r'\bcovid 19\b': 'covid19',
        r'\bcovid-19\b': 'covid19',
    }
    
    for pattern, replacement in medical_variations.items():
        normalized = re.sub(pattern, replacement, normalized)
    
    # 5. Remove extra spaces lagi setelah replacements
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    
    return normalized

def generate_claim_hash(text: str) -> str:
    """
    Generate hash unik untuk claim text dengan normalisasi yang lebih baik.
    
    Hash ini digunakan untuk:
    - Deteksi duplikasi claim
    - Cache lookup
    """
    normalized = normalize_claim_text(text)
    return hashlib.sha256(normalized.encode()).hexdigest()

def check_cached_result(claim_text: str):
    """
    Mengecek apakah claim sudah pernah diverifikasi sebelumnya.
    
    Returns:
        tuple: (is_cached, claim_object, verification_result)
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
                logger.info(f"[CACHE HIT] Found cached result for claim ID: {claim.id}")
                return True, claim, verification
        
        logger.info("[CACHE MISS] Claim tidak ditemukan di cache.")
        return False, None, None
    except Exception as e:
        logger.error(f"[CACHE ERROR] Terjadi kesalahan saat mengecek cache: {str(e)}", exc_info=True)
        return False, None, None

def find_similar_claims(claim_text: str, threshold: float = 0.85) -> list:
    """
    Cari claim yang mirip berdasarkan similarity score.
    Berguna untuk mendeteksi claim yang semantically similar tapi tidak exact match.
    
    Args:
        claim_text: Text claim yang dicari
        threshold: Minimum similarity score (0-1)
    
    Returns:
        list: List of similar claims
    """
    from difflib import SequenceMatcher
    
    normalized = normalize_claim_text(claim_text)
    
    # Get recent claims untuk comparison
    recent_claims = Claim.objects.filter(
        status=Claim.STATUS_DONE
    ).order_by('-created_at')[:100]
    
    similar_claims = []
    
    for claim in recent_claims:
        if not claim.normalized_text:
            continue
            
        # Calculate similarity ratio
        similarity = SequenceMatcher(
            None, 
            normalized, 
            claim.normalized_text
        ).ratio()
        
        if similarity >= threshold:
            similar_claims.append({
                'claim': claim,
                'similarity': similarity
            })
    
    # Sort by similarity descending
    similar_claims.sort(key=lambda x: x['similarity'], reverse=True)
    
    return similar_claims

# ===========================
# Claim Views
# ===========================

class ClaimVerifyView(APIView):
    """
    POST endpoint untuk submit claim dan mendapatkan hasil verifikasi.
    
    Process:
        1. Validate input claim text
        2. Normalize text untuk consistency
        3. Check exact match cache (by hash)
        4. Check similar claims (semantic similarity)
        5. Jika tidak ada match, process dengan AI verification
        6. Save hasil dan return response
    
    Returns:
        - 200: Verification result (dari cache atau baru)
        - 400: Invalid request data
        - 500: Verification failed
    """
    
    # Label determination thresholds
    CONFIDENCE_THRESHOLD_VALID = 0.75
    CONFIDENCE_THRESHOLD_HOAX = 0.5
    SIMILARITY_THRESHOLD = 0.90  # 90% similarity = consider as duplicate

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

        # Ambil text klaim segera setelah validasi agar tidak ada UnboundLocalError
        claim_text = serializer.validated_data.get('text', '')  # defensive: default ke ''
        # logging singkat dari klaim (maks 80 char) — aman karena claim_text sudah ada
        logger.info(f"[VERIFY] Processing claim: '{claim_text[:80]}...'")

        # flag force refresh - pastikan cast ke bool
        force_refresh = bool(request.data.get('_force_refresh', False))

        # Skip cache jika force refresh
        if not force_refresh:
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
            # Jika terjadi error di sini, pastikan kita punya claim_text untuk context (bisa kosong)
            logger.error(f"[VERIFY] Verification failed: {str(e)}", exc_info=True)
            return self._handle_verification_error(e, claim_text, request)
    
    def _get_cached_result(self, claim_text):
        """
        Check if claim has been verified before (exact match by hash).
        
        PENTING: Juga check apakah verification result sudah di-update 
        (misalnya dari dispute approval).
        
        Args:
            claim_text (str): The claim text to check
            
        Returns:
            Response or None: Response object if cached, None otherwise
        """
        is_cached, cache_claim, cached_verification = check_cached_result(claim_text)

        if is_cached:
            # ✅ TAMBAHAN: Check fresh verification
            fresh_verification = VerificationResult.objects.filter(
                claim=cache_claim
            ).latest('updated_at')
            
            # ✅ Compare timestamps
            if fresh_verification.updated_at > cached_verification.updated_at:
                logger.info("[CACHE] Verification was UPDATED!")
                cached_verification = fresh_verification  # Use fresh!
            
            # Serialize the claim for response
            serializer = ClaimDetailSerializer(cache_claim)
            return Response({
                **serializer.data,
                '_from_cache': True,
                '_updated_at': fresh_verification.updated_at.isoformat()
            })
    
    def _check_similar_claims(self, claim_text):
        """
        Check for semantically similar claims.
        
        Args:
            claim_text (str): The claim text to check
            
        Returns:
            Response or None: Response object if similar claim found, None otherwise
        """
        try:
            similar_claims = find_similar_claims(claim_text, threshold=self.SIMILARITY_THRESHOLD)
            
            if similar_claims:
                best_match = similar_claims[0]
                similarity = best_match['similarity']
                matched_claim = best_match['claim']
                
                logger.info(
                    f"[VERIFY] Similar claim found - "
                    f"Claim ID: {matched_claim.id}, "
                    f"Similarity: {similarity:.2%}"
                )
                
                # Get verification result
                if hasattr(matched_claim, 'verification_result'):
                    response_data = ClaimDetailSerializer(matched_claim).data
                    response_data['_cache_hit'] = 'similar'
                    response_data['_similarity_score'] = round(similarity, 4)
                    response_data['_matched_claim_id'] = matched_claim.id
                    
                    logger.info(
                        f"[VERIFY] Cache HIT (similar) - "
                        f"Using result from Claim ID: {matched_claim.id}"
                    )
                    
                    return Response(response_data, status=status.HTTP_200_OK)
        
        except Exception as e:
            logger.warning(f"[VERIFY] Error checking similar claims: {e}")
        
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
            text_normalized=normalized_text,
            text_hash=text_hash,
            status=Claim.STATUS_PROCESSING
        )
        
        logger.info(
            f"[VERIFY] Created Claim ID: {claim.id} "
            f"(hash: {text_hash[:16]}...)"
        )
        logger.debug(f"[VERIFY] Normalized: '{normalized_text}'")
        
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
        confidence = ai_result.get('confidence')  # Bisa None untuk unverified
        summary = ai_result.get('summary', '')
        label = ai_result.get('label', 'unverified')

        # Validate label
        valid_labels = ['valid', 'hoax', 'uncertain', 'unverified']
        if label not in valid_labels:
            logger.warning(f"[VERIFY] Invalid label '{label}' dari AI, fallback ke 'unverified'")
            label = 'unverified'

        # Create verification result
        verification = VerificationResult.objects.create(
            claim=claim,
            label=label,
            summary=summary,
            confidence=confidence,  # None untuk unverified
            logic_version="v2.0"
        )
        
        logger.info(
            f"[VERIFY] Created VerificationResult ID: {verification.id} - "
            f"Label: {label}, "
            f"Confidence: {confidence if confidence is not None else 'N/A'}, "
            f"Sources: {len(sources_data)}"
        )
        
        # Process and link sources
        if sources_data:
            self._process_sources(claim, sources_data)
        
        return verification
    
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
            'confidence': round(vr.confidence, 4) if vr.confidence is not None else None,
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
            'confidence': None,
            'confidence_percent': None,
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
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        validated_data = serializer.validated_data
        claim_id = validated_data.get('claim_id')
        claim_text = validated_data.get('claim_text', '')
        
        # ✅ PENTING: Auto-link dispute ke claim jika ada
        claim = None
        
        if claim_id:
            # Explicit claim_id provided
            try:
                claim = Claim.objects.get(id=claim_id)
                logger.info(f"[DISPUTE CREATE] Using explicit claim_id: {claim_id}")
            except Claim.DoesNotExist:
                logger.warning(f"[DISPUTE CREATE] Claim {claim_id} not found, will create without link")
        
        elif claim_text:
            # Try to find matching claim by text similarity
            try:
                from .text_normalization import normalize_claim_text, calculate_text_similarity
                
                normalized_input = normalize_claim_text(claim_text)
                
                # Find all claims dengan similarity >= 0.85
                all_claims = Claim.objects.filter(status=Claim.STATUS_DONE).values_list('id', 'text')
                
                best_match = None
                best_similarity = 0.0
                
                for cid, ctext in all_claims:
                    similarity = calculate_text_similarity(claim_text, ctext)
                    if similarity > best_similarity:
                        best_similarity = similarity
                        best_match = cid
                
                # ✅ AUTO-LINK jika similarity >= 0.80
                if best_match and best_similarity >= 0.80:
                    claim = Claim.objects.get(id=best_match)
                    logger.info(
                        f"[DISPUTE CREATE] Auto-linked to Claim {best_match} "
                        f"(similarity: {best_similarity:.2%})"
                    )
                else:
                    logger.warning(
                        f"[DISPUTE CREATE] No good match found "
                        f"(best: {best_similarity:.2%}, threshold: 0.80)"
                    )
            
            except Exception as e:
                logger.warning(f"[DISPUTE CREATE] Error matching claim: {e}")
        
        # ✅ Store original verification result SEBELUM update
        original_label = None
        original_confidence = None
        
        if claim and hasattr(claim, 'verification_result'):
            vr = claim.verification_result
            original_label = vr.label
            original_confidence = vr.confidence
            logger.info(
                f"[DISPUTE CREATE] Storing original verification: "
                f"label={original_label}, confidence={original_confidence}"
            )
        
        # Create dispute
        try:
            dispute = Dispute.objects.create(
                claim=claim,  # ✅ Bisa None jika tidak ada match
                claim_text=claim_text or (claim.text if claim else ''),
                reason=validated_data['reason'],
                reporter_name=validated_data.get('reporter_name', 'Anonymous'),
                reporter_email=validated_data.get('reporter_email', ''),
                supporting_doi=validated_data.get('supporting_doi', ''),
                supporting_url=validated_data.get('supporting_url', ''),
                supporting_file=validated_data.get('supporting_file'),
                original_label=original_label,
                original_confidence=original_confidence
            )
            
            logger.info(f"[DISPUTE CREATE] Created dispute ID: {dispute.id}")
            
            # Send admin notification
            try:
                email_service.notify_admin_new_dispute(dispute)
            except Exception as e:
                logger.error(f"[DISPUTE CREATE] Failed to send admin notification: {e}")
            
            return Response(
                {
                    'id': dispute.id,
                    'message': 'Dispute created successfully',
                    'claim_linked': claim is not None
                },
                status=status.HTTP_201_CREATED
            )
        
        except Exception as e:
            logger.error(f"[DISPUTE CREATE] Error creating dispute: {e}", exc_info=True)
            return Response(
                {'error': 'Failed to create dispute'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
            
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
            
@api_view(['POST'])
def check_claim_duplicate(request):
    """
    Check if incoming claim is duplicate/similar to existing claims
    """
    text = request.data.get('text', '')
    
    if not text:
        return Response(
            {'error': 'Text is required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Get all existing claims
    existing_claims = Claim.objects.values('id', 'text', 'text_normalized')
    existing_list = [
        (c['id'], c['text'], c['text_normalized']) 
        for c in existing_claims
    ]
    
    # Find similar claims
    matcher = ClaimSimilarityMatcher()
    result = matcher.find_duplicates(text, existing_list)
    
    return Response({
        'text': text,
        'normalized': normalize_claim_text(text),
        'is_duplicate': result['match_found'],
        'match_level': result['match_level'],
        'matched_claim_id': result['claim_id'],
        'similarity_score': round(result['similarity'], 3),
        'explanation': _get_explanation(result['similarity']),
        'all_matches': [
            {'id': m[0], 'similarity': round(m[1], 3)} 
            for m in result.get('all_matches', [])[:5]
        ]
    })


def _get_explanation(similarity: float) -> str:
    """Helper function untuk penjelasan"""
    if similarity >= 0.95:
        return "Sangat mirip (kemungkinan besar duplikat)"
    elif similarity >= 0.85:
        return "Mirip (kemungkinan variasi dari klaim yang sama)"
    elif similarity >= 0.75:
        return "Agak mirip (mungkin topik yang sama)"
    else:
        return "Tidak mirip"