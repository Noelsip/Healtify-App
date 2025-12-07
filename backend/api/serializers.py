from rest_framework import serializers
from .models import Claim, VerificationResult, Source, ClaimSource, Dispute, JournalArticle

class ClaimCreateSerializer(serializers.Serializer):
    text = serializers.CharField(
        max_length=5000,
        required=True,
        error_messages={
            'required': 'Teks klaim wajib diisi',
            'blank': 'Teks klaim tidak boleh kosong',
            'max_length': 'Teks klaim terlalu panjang (maksimal 5000 karakter)'
        }
    )

class SourceSerializer(serializers.ModelSerializer):
    """serialization untuk sources."""
    
    class Meta:
        model = Source
        fields = [
            'id',
            'title',
            'doi',
            'url',
            'authors',
            'publisher',
            'published_date',
            'source_type',
            'credibility_score',
            'created_at'
        ]

class ClaimSourceSerializer(serializers.ModelSerializer):
    """
        Serializer untuk relasi Claim-source dengan relevance score
    """
    source = SourceSerializer(read_only=True)
    
    class Meta:
        model = ClaimSource
        fields = [
            'source',
            'relevance_score',
            'excerpt',
            'rank'
        ]

class VerificationResultSerializer(serializers.ModelSerializer):
    confidence_percent = serializers.SerializerMethodField()
    label_display = serializers.CharField(source='get_label_display', read_only=True)
    label_color = serializers.SerializerMethodField()
    
    class Meta:
        model = VerificationResult
        fields = [
            'id', 
            'label', 
            'label_display',
            'label_color',
            'summary', 
            'confidence',  # Can be NULL
            'confidence_percent',  # Can be NULL
            'reviewer_notes',
            'created_at', 
            'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_confidence_percent(self, obj):
        """Return confidence sebagai persentase, or None for unverified."""
        return obj.confidence_percent()
    
    def get_label_color(self, obj):
        """Return warna untuk frontend berdasarkan label."""
        color_map = {
            VerificationResult.LABEL_VALID: 'green',
            VerificationResult.LABEL_HOAX: 'red',
            VerificationResult.LABEL_UNCERTAIN: 'yellow',
            VerificationResult.LABEL_UNVERIFIED: 'gray'
        }
        return color_map.get(obj.label, 'gray')

class ClaimDetailSerializer(serializers.ModelSerializer):
    """
        Serializer lengkap untuk claim dengan verification result dan sources.
    """
    verification_result = VerificationResultSerializer(read_only=True)
    sources = serializers.SerializerMethodField()
    
    class Meta:
        model = Claim
        fields = [
            'id',
            'text',
            'text_normalized',
            'status',
            'created_at',
            'updated_at',
            'verification_result',
            'sources'
        ]
    
    def get_sources(self, obj):
        """Get sources dengan ranking dan relevance score."""
        claim_sources = ClaimSource.objects.filter(claim=obj).select_related('source').order_by('rank')
        return ClaimSourceSerializer(claim_sources, many=True).data

class DisputeCreateSerializer(serializers.Serializer):
    """Serializer untuk membuat dispute baru."""
    claim_id = serializers.IntegerField(required=False, allow_null=True)
    claim_text = serializers.CharField(required=False, allow_blank=True, max_length=5000)

    reporter_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    reporter_email = serializers.EmailField(required=False, allow_blank=True)

    reason = serializers.CharField(min_length=20, max_length=5000)
    supporting_doi = serializers.CharField(max_length=500, required=False, allow_blank=True)  # UBAH: 255 → 500
    supporting_url = serializers.URLField(required=False, allow_blank=True)

    def validate(self, data):
        """Validasi bahwa minimal ada claim_id atau claim_text."""
        if not data.get('claim_id') and not data.get('claim_text'):
            raise serializers.ValidationError("Harus menyertakan claim_id atau claim_text.")
        return data
        
class DisputeDetailSerializer(serializers.ModelSerializer):
    """Serializer detail untuk dispute dengan info lengkap.
        Digunakan untuk retrieve single dispute di admin panel.
    """
    claim_text_display = serializers.SerializerMethodField()
    claim_detail = serializers.SerializerMethodField()
    reviewer_name = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    supporting_file_url = serializers.SerializerMethodField()

    class Meta:
        model = Dispute
        fields = (
            'id',
            'claim',
            'claim_text',
            'claim_text_display',
            'claim_detail',
            'reporter_name',
            'reporter_email',
            'reason',
            'supporting_doi',
            'supporting_url',
            'supporting_file_url',
            'status',
            'status_display',
            'reviewed',
            'review_note',
            'reviewed_by',
            'reviewer_name',
            'reviewed_at',
            'original_label',
            'original_confidence',
            'created_at',
        )
        read_only_fields = [
            'id',
            'created_at',
            'reviewed_at'
        ]

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
                'text': obj.claim.text,
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
                'summary': verification.summary,
                'created_at': verification.created_at,
            }
        except VerificationResult.DoesNotExist:
            return None
    
    def get_reviewer_name(self, obj):
        """
            Tampilkan nama reviewer 
        """
        if obj.reviewed_by:
            return obj.reviewed_by.username
        return None
    
    def get_supporting_file_url(self, obj):
        """
            Get URL untuk supporting file jika ada
        """
        if obj.supporting_file:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.supporting_file.url)
            return obj.supporting_file.url
        return None
    
class DisputeAdminActionSerializer(serializers.Serializer):
    """Serializer untuk tindakan admin pada dispute."""
    dispute_ids = serializers.ListField(
        child=serializers.IntegerField(),
        min_length=1,
        help_text="List of dispute IDs untuk di-action"
    )
    action = serializers.ChoiceField(
        choices=['approve', 'reject'],
        help_text="Action yang akan dilakukan"
    )
    review_note = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=2000,
        help_text="Catatan review untuk semua disputes"
    )

class DisputeListSerializer(serializers.ModelSerializer):
    """
        Serializer untuk list disputes di admin panel.
        Menampilkan ringkasan informasi dispute.
    """
    claim_text_short = serializers.SerializerMethodField()
    reviewer_name = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Dispute
        fields = [
            'id',
            'claim',
            'claim_text_short',
            'reason',
            'reporter_name',
            'reporter_email',
            'status',
            'status_display',
            'reviewed',
            'reviewer_name',
            'created_at',
            'reviewed_at',
            'supporting_doi',
            'supporting_url',
            'supporting_file',
        ]
        read_only_fields = ['id', 'created_at' ]

    def get_claim_text_short(self, obj):
        """
            Potong text klaim jika terlalu panjang untuk ditampilkan di list.
        """
        if obj.claim:
            text = obj.claim.text
        else:
            text = obj.claim_text or ""
        return (text[:100] + '...') if len(text) > 100 else text
    
    def get_reviewer_name(self, obj):
        """
            Tampilkan nama reviewer jika ada
        """
        if obj.reviewed_by:
            return obj.reviewed_by.username
        return None
    
class DisputeReviewSerializer(serializers.Serializer):
    """
    Serializer untuk admin melakukan review pada dispute.
    Mendukung approve/reject dengan opsi re-verify atau manual update.
    """
    
    action = serializers.ChoiceField(
        choices=['approve', 'reject'],
        help_text="Action: approve (terima) atau reject (tolak)"
    )
    
    review_note = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=2000,
        help_text="Catatan review dari admin"
    )
    
    # Opsi untuk re-verify otomatis
    re_verify = serializers.BooleanField(
        default=True,
        help_text="Lakukan re-verify otomatis menggunakan AI (hanya untuk approve)"
    )
    
    # Opsi untuk manual update
    manual_update = serializers.BooleanField(
        default=False,
        help_text="Update verification result secara manual tanpa AI"
    )
    
    # Manual update fields
    new_label = serializers.ChoiceField(
        choices=['valid', 'hoax', 'uncertain', 'unverified'],
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Label baru untuk klaim (jika manual_update=True)"
    )
    
    new_confidence = serializers.FloatField(
        required=False,
        allow_null=True,
        min_value=0.0,
        max_value=1.0,
        help_text="Confidence score baru 0.0-1.0 (jika manual_update=True)"
    )
    
    new_summary = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=5000,
        help_text="Summary baru (jika manual_update=True)"
    )
    
    def validate(self, data):
        """Validasi rules untuk approve vs reject."""
        action = data.get('action')
        manual_update = data.get('manual_update', False)
        re_verify = data.get('re_verify', True)
        
        # ===== UNTUK ACTION APPROVE =====
        if action == 'approve':
            if manual_update:
                # Jika manual update, validasi required fields
                if not data.get('new_label'):
                    raise serializers.ValidationError({
                        'new_label': 'Label baru wajib diisi jika manual_update=True'
                    })
                if data.get('new_confidence') is None:
                    raise serializers.ValidationError({
                        'new_confidence': 'Confidence score wajib diisi jika manual_update=True'
                    })
                # Summary optional untuk manual update
                
                # Jika manual update, disable re_verify
                data['re_verify'] = False
            
            elif not re_verify:
                # Jika approve tapi tidak ada re_verify dan tidak manual
                raise serializers.ValidationError({
                    'non_field_errors': 'Untuk approve, pilih re_verify=True atau manual_update=True'
                })
        
        # ===== UNTUK ACTION REJECT =====
        if action == 'reject':
            # Untuk reject, abaikan manual_update dan re_verify
            data['re_verify'] = False
            data['manual_update'] = False
        
        return data


# ===========================
# Journal Article Serializers
# ===========================

class JournalArticleSerializer(serializers.ModelSerializer):
    """Serializer untuk menampilkan JournalArticle."""
    created_by_name = serializers.SerializerMethodField()
    
    class Meta:
        model = JournalArticle
        fields = [
            'id',
            'title',
            'abstract',
            'authors',
            'doi',
            'url',
            'publisher',
            'journal_name',
            'published_date',
            'source_portal',
            'is_embedded',
            'credibility_score',
            'keywords',
            'created_at',
            'updated_at',
            'created_by',
            'created_by_name'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'is_embedded']
    
    def get_created_by_name(self, obj):
        if obj.created_by:
            return obj.created_by.username
        return None


class JournalArticleCreateSerializer(serializers.Serializer):
    """Serializer untuk membuat JournalArticle baru."""
    title = serializers.CharField(max_length=1000, required=True)
    abstract = serializers.CharField(required=True)
    authors = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    doi = serializers.CharField(max_length=255, required=False, allow_blank=True, allow_null=True)
    url = serializers.URLField(required=False, allow_blank=True, allow_null=True)
    publisher = serializers.CharField(max_length=500, required=False, allow_blank=True)
    journal_name = serializers.CharField(max_length=500, required=False, allow_blank=True)
    published_date = serializers.DateField(required=False, allow_null=True)
    source_portal = serializers.ChoiceField(
        choices=['sinta', 'garuda', 'doaj', 'google_scholar', 'other'],
        default='other'
    )
    keywords = serializers.CharField(required=False, allow_blank=True)
    
    def validate_doi(self, value):
        """Validasi DOI unik jika ada."""
        if value:
            value = value.strip()
            if JournalArticle.objects.filter(doi=value).exists():
                raise serializers.ValidationError("Jurnal dengan DOI ini sudah ada.")
        return value or None