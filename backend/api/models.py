from django.db import models
from .text_normalization import normalize_claim_text, generate_semantic_hash


# menyimpan sumber referensi seperti doi, url
class Source(models.Model):
    title = models.CharField(max_length=500)
    doi = models.CharField(max_length=255, blank=True, null=True)
    url = models.URLField(blank=True, null=True)
    authors = models.TextField(blank=True, null=True)
    publisher = models.CharField(max_length=255, blank=True, null=True)
    published_date = models.DateField(blank=True, null=True)
    credibility_score = models.FloatField(default=0.5, help_text="Skor kredibilitas 0.0 - 1.0")

    SOURCE_TYPE_CHOICES = [
        ('website', 'Website'),
        ('journal', 'Journal'),
        ('news', 'News'),
        ('government', 'Government'),
        ('organization', 'Organization'),
        ('other', 'Other'),
    ]
    source_type = models.CharField(
        max_length=50, 
        choices=SOURCE_TYPE_CHOICES, 
        default='website',
        help_text="Tipe sumber"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.title} ({self.doi or self.url or 'no-id'})"
        
# menyimpan klaim yang dikirim untuk diverifikasi
class Claim(models.Model):
    text = models.TextField()
    text_normalized = models.TextField(blank=True, null=True)
    text_hash = models.CharField(max_length=64, unique=True, db_index=True)

    def save(self, *args, **kwargs):
        # Auto-generate normalized text & hash saat save
        self.text_normalized = normalize_claim_text(self.text)
        self.text_hash = generate_semantic_hash(self.text)
        super().save(*args, **kwargs)

    # status proses verifikasi klaim
    STATUS_PENDING = 'pending'
    STATUS_PROCESSING = 'processing'
    STATUS_DONE = 'done'
    STATUS_DISPUTED = 'disputed'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_PROCESSING, 'Processing'),
        (STATUS_DONE, 'Done'),
        (STATUS_DISPUTED, 'Disputed'),
    ]

    status = models.CharField(
        max_length=32,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )

    # timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # relasi ke sumber
    sources = models.ManyToManyField(Source, through='ClaimSource', blank=True)
    
    text_hash = models.CharField(max_length=64, db_index=True, null=True, blank=True)

    def save(self, *args, **kwargs):
        # generate hash untuk claim text
        if not self.text_hash and self.text:
            import hashlib
            self.text_hash = hashlib.sha256(self.text.strip().lower()).hexdigest()
        super().save(*args, **kwargs)
        
    def __str__(self):
        return f'Claim #{self.pk} - {self.text[:50]}...'
    
    class Meta:
        indexes = [
            models.Index(fields=['text_hash']),
            models.Index(fields=['text_normalized']),
        ]
    
# Model hubungan antara claim dan sumber
class ClaimSource(models.Model):
    claim = models.ForeignKey(Claim, on_delete=models.CASCADE)
    source = models.ForeignKey(Source, on_delete=models.CASCADE)
    relevance_score = models.FloatField(default=0.0)  
    excerpt = models.TextField(blank=True, null=True)  
    rank = models.IntegerField(default=0)  

    class Meta:
        unique_together = ('claim', 'source')
        ordering = ['rank']
        indexes = [
            models.Index(fields=['claim', 'source']),
            models.Index(fields=['rank']),
        ]

    def __str__(self):
        return f'ClaimSource: Claim #{self.claim_id} - Source #{self.source_id}'
    
    def save(self, *args, **kwargs):
        """
            Override save to handle duplicates gracefully.
        """
        try:
            super().save(*args, **kwargs)
        except Exception as e:
            if 'unique constraint' in str(e).lower():
                # log and skip duplicate
                logger = logging.getLogger(__name__)
                logger.warning(
                    f"Skipping duplicate ClaimSource: "
                    f"Claim_id={self.claim_id}, Source_id={self.source_id}"
                )
            else:
                raise e

# Model untuk menyimpan hasil verifikasi klaim untuk satu klaim
class VerificationResult(models.Model):
    # Label hasil - UPDATED LABELS
    LABEL_VALID = 'valid'
    LABEL_HOAX = 'hoax'
    LABEL_UNCERTAIN = 'uncertain'
    LABEL_UNVERIFIED = 'unverified'
    
    LABEL_CHOICES = [
        (LABEL_VALID, 'FAKTA'),  # Changed from 'Valid'
        (LABEL_HOAX, 'HOAX'),    # Remains same
        (LABEL_UNCERTAIN, 'TIDAK PASTI'),  # Changed from 'Tidak Tentu'
        (LABEL_UNVERIFIED, 'TIDAK TERVERIFIKASI'),  # Changed from 'Tidak Terverifikasi'
    ]
    
    claim = models.OneToOneField(Claim, on_delete=models.CASCADE, related_name='verification_result')
    label = models.CharField(
        max_length=32,
        choices=LABEL_CHOICES,
        default=LABEL_UNVERIFIED,
    )
    summary = models.TextField(blank=True, null=True)
    
    # IMPORTANT: Confidence can be NULL for UNVERIFIED claims
    confidence = models.FloatField(default=0.0, null=True, blank=True)
    
    reviewer_notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    logic_version = models.CharField(max_length=32, default="v2.0", null=True)

    def confidence_percent(self):
        """Return confidence as percentage, or None if unverified."""
        if self.label == self.LABEL_UNVERIFIED or self.confidence is None:
            return None
        return round(self.confidence * 100, 2)

    def determine_label_from_confidence(self, has_sources=True, has_journal=False):
        """
        Menentukan label berdasarkan confidence score dan sumber.
        
        Rules:
        - TIDAK TERVERIFIKASI: tidak ada sumber atau bukan topik kesehatan
        - FAKTA: confidence >= 0.75 dengan sumber jurnal
        - HOAX: confidence <= 0.55 dengan sumber jurnal
        - TIDAK PASTI: 0.55 < confidence < 0.75 dengan sumber jurnal
        """
        if not has_sources or not has_journal:
            return self.LABEL_UNVERIFIED
        
        if self.confidence is None:
            return self.LABEL_UNVERIFIED
        
        if self.confidence >= 0.75:
            return self.LABEL_VALID
        elif self.confidence <= 0.55:
            return self.LABEL_HOAX
        else:  # 0.55 < confidence < 0.75
            return self.LABEL_UNCERTAIN

    def save(self, *args, **kwargs):
        """Auto-set label based on confidence if not manually set."""
        if not self.pk:  # Only on creation
            has_sources = self.claim.sources.exists() if self.claim else False
            has_journal = False
            if has_sources:
                # Check if any source is a journal (has DOI)
                has_journal = self.claim.sources.filter(
                    models.Q(doi__isnull=False) | models.Q(source_type='journal')
                ).exists()
            
            self.label = self.determine_label_from_confidence(has_sources, has_journal)
            
            # Set confidence to NULL for unverified
            if self.label == self.LABEL_UNVERIFIED:
                self.confidence = None
                
        super().save(*args, **kwargs)
        
    def __str__(self):
        conf_str = f"{self.confidence:.2f}" if self.confidence is not None else "N/A"
        return f'Verification Result for Claim #{self.claim_id}: {self.get_label_display()} ({conf_str})'

# Model laporan hasil verifikasi klaim oleh user
class Dispute(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending Review'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_REJECTED, 'Rejected'),
    ]
    
    claim = models.ForeignKey(Claim, on_delete=models.CASCADE, null=True, blank=True)
    claim_text = models.TextField(help_text="Teks klaim yang dilaporkan")
    reason = models.TextField(help_text="Alasan pelaporan")
    
    reporter_name = models.CharField(max_length=255, blank=True, default='Anonymous')
    reporter_email = models.EmailField(blank=True, default='')
    
    supporting_doi = models.CharField(max_length=500, blank=True, default='')
    supporting_url = models.URLField(blank=True, default='')
    supporting_file = models.FileField(upload_to='disputes/', blank=True, null=True)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    reviewed = models.BooleanField(default=False)
    reviewed_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True, default='')
    
    # Menyimpan hasil verifikasi original sebelum dispute
    original_label = models.CharField(max_length=50, blank=True, default='')
    original_confidence = models.FloatField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Dispute'
        verbose_name_plural = 'Disputes'
    
    def __str__(self):
        return f"Dispute #{self.id} - {self.status}"
   
# Model untuk FAQ dinamis
class FAQItem(models.Model):
    question = models.CharField(max_length=500)
    answer = models.TextField()
    order = models.IntegerField(default=0)  
    published = models.BooleanField(default=True)

    def __str__(self):
        return f'FAQ: {self.question[:60]}'