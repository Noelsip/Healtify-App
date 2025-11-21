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
        Serializer untuk admin melakukan review pada dispute
        Mendukung approve/reject dengan opsi re-verify otomatis atau manual update.
    """

    # Action utama
    action = serializers.ChoiceField(
        choices=['approve', 'reject'],
        help_text="Action: approve (terima) atau reject (tolak) "
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

    # Opsi untuk manual update verification result
    manual_update = serializers.BooleanField(
        default=False,
        help_text="Update verification result secara manual tanpa AI"
    )

    new_label = serializers.ChoiceField(
        choices = [
            ('true', 'True/Valid'),
            ('false', 'False/Hoax'),
            ('misleading', 'Misleading'),
            ('unsupported', 'Unsupported'),
            ('inconclusive', 'Inconclusive')
        ],
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
        help_text="Confidence score baru (0.0 - 1.0, jika manual_update=True)"
    )
    new_summary = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=5000,
        help_text="Summary baru untuk verification result (jika manual_update=True)"
    )

    def validate(self, data):
        """
            Validasi bahwaa jika manual_update = True,
            maka new_label, new_confidence, dan new_summary harus diisi.
        """
        action = data.get('action')
        manual_update = data.get('manual_update', False)
        re_verify = data.get('re_verify', True)

        # Validasi hanya untuk action approve
        if action == 'approve':
            if manual_update:
                # Jika manual update, validasi field-field baru
                if not data.get('new_label'):
                    raise serializers.ValidationError({
                        "new_label": "Label baru harus diisi jika manual_update=True."
                    })
                if data.get('new_confidence') is None:
                    raise serializers.ValidationError({
                        "new_confidence": "Confidence baru harus diisi jika manual_update=True."
                    })
                if not data.get('new_summary'):
                    raise serializers.ValidationError({
                        "new_summary": "Summary baru harus diisi jika manual_update=True."
                    })
                
                # Jika manual update, matikan re_verify
                data['re_verify'] = False
            
            elif not re_verify and not manual_update:
                # Jika approve tapi tidak ada re_verify atau manual_update
                raise serializers.ValidationError({
                    "re_verify": "Untuk approve, harus pilih re_verify=True atau manual_update=True"
                })

        # Untuk reject, re_verify dan manual_update tidak digunakan
        if action == 'reject':
            data['re_verify'] = False
            data['manual_update'] = False

        return data    
