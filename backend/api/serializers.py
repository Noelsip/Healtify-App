from rest_framework import serializers
from .models import Claim, VerificationResult, Source, ClaimSource, Dispute

class ClaimCreateSerializer(serializers.Serializer):
    text = serializers.CharField(min_length=10, max_length=5000)

class SourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Source
        fields = (
            'id',
            'title',
            'doi', 
            'url', 
            'authors',
            'publisher', 
            'published_date'
        )

class ClaimSourceSerializer(serializers.ModelSerializer):
    """
        Serializer untuk relasi Claim-source dengan relevance score
    """
    source = SourceSerializer(read_only=True)

    class Meta:
        model = ClaimSource
        fields = (
            'source',
            'relevance_score',
            'rank',
            'excerpt'
        )

class VerificationResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = VerificationResult
        fields = (
            'label',
            'summary',
            'confidence',
            'created_at',
            'updated_at'
        )

class ClaimDetailSerializer(serializers.ModelSerializer):
    """
        Serializer lengkap untuk claim dengan verification result dan sources.
    """
    verification_result = VerificationResultSerializer(read_only=True)
    sources = serializers.SerializerMethodField()

    class Meta:
        model = Claim
        fields = (
            'id',
            'text',
            'normalized_text',
            'status',
            'created_at',
            'updated_at',
            'verification_result',
            'sources'
        )

    def get_sources(self, obj):
        """Get sources yang terhubung dengan claim ini, diurutkan berdasarkan rank."""
        claim_sources = ClaimSource.objects.filter(
            claim=obj
        ).select_related('source').order_by('rank')
        
        return ClaimSourceSerializer(claim_sources, many=True).data

class DisputeCreateSerializer(serializers.Serializer):
    """Serializer untuk membuat dispute baru."""
    claim_id = serializers.IntegerField(required=False, allow_null=True)
    claim_text = serializers.CharField(required=False, allow_blank=True, max_length=5000)

    reporter_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    reporter_email = serializers.EmailField(required=False, allow_blank=True)

    reason = serializers.CharField(min_length=20, max_length=5000)
    supporting_doi = serializers.CharField(max_length=255, required=False, allow_blank=True)
    supporting_url = serializers.URLField(required=False, allow_blank=True)

    def validate(self, data):
        """Validasi bahwa minimal ada claim_id atau claim_text."""
        if not data.get('claim_id') and not data.get('claim_text'):
            raise serializers.ValidationError("Harus menyertakan claim_id atau claim_text.")
        return data
        
class DisputeDetailSerializer(serializers.ModelSerializer):
    """Serializer detail untuk dispute dengan info lengkap."""
    claim_text_display = serializers.SerializerMethodField()
    claim_detail = serializers.SerializerMethodField()

    class Meta:
        model = Dispute
        fields = (
            'id',
            'claim',
            'claim_text_display',
            'claim_detail',
            'reporter_name',
            'reporter_email',
            'reason',
            'supporting_doi',
            'supporting_url',
            'supporting_file',
            'created_at',
            'status',
            'reviewed',
            'review_note',
            'reviewed_by',
            'reviewed_at',
            'original_label',
            'original_confidence',
        )

    def get_claim_text_display(self, obj):
        """Mengambil Teks Klaim dari relasi atau field claim_text"""
        if obj.claim:
            return obj.claim.text
        return obj.claim_text or ""

    def get_claim_detail(self, obj):
        """Mengambil detail claim jika tersedia."""
        if obj.claim:
            return {
                'id': obj.claim.id,
                'status': obj.claim.status,
                'created_at': obj.claim.created_at,
                'verification': self._get_verification_detail(obj.claim)
            }
        return None
    
    def _get_verification_detail(self, claim):
        """Mendapatkan detail verifikasi untuk klaim tertentu."""
        try:
            verification = claim.verification_result
            return {
                'label': verification.label,
                'confidence': verification.confidence,
                'summary': verification.summary
            }
        except VerificationResult.DoesNotExist:
            return None
    
class DisputeAdminActionSerializer(serializers.Serializer):
    """Serializer untuk tindakan admin pada dispute."""
    action = serializers.ChoiceField(choices=['approve', 'reject'])
    review_note = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    reviewed_by = serializers.CharField(max_length=255)

    # untuk approved dispute
    new_label = serializers.ChoiceField(
        choices=[
            ('true', 'True'),
            ('false', 'False'),
            ('misleading', 'Misleading'),
            ('unsupported', 'Unsupported'),
            ('inconclusive', 'Inconclusive')
        ],
        required=False,
        allow_null=True
    )
    new_confidence = serializers.FloatField(required=False, allow_null=True, min_value=0.0, max_value=1.0)
    new_summary = serializers.CharField(required=False, allow_blank=True, max_length=5000)