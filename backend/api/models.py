from django.db import models

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
    
    # normalisasi teks klaim dari user
    normalized_text = models.TextField(blank=True, null=True)

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
    # Label hasil
    LABEL_VALID = 'valid'
    LABEL_HOAX = 'hoax'
    LABEL_UNCERTAIN = 'uncertain'
    LABEL_UNVERIFIED = 'unverified'
    
    LABEL_CHOICES = [
        (LABEL_VALID, 'Valid'),
        (LABEL_HOAX, 'Hoax'),
        (LABEL_UNCERTAIN, 'Tidak Tentu'),
        (LABEL_UNVERIFIED, 'Tidak Terverifikasi'),
    ]
    claim = models.OneToOneField(Claim, on_delete=models.CASCADE, related_name='verification_result')
    label = models.CharField(
        max_length=32,
        choices=LABEL_CHOICES,
        default=LABEL_UNVERIFIED,
    )
    summary = models.TextField(blank=True, null=True)  
    confidence = models.FloatField(default=0.0)
    reviewer_notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def confidence_percent(self):
        return round(self.confidence * 100, 2)

    def determine_label_from_confidence(self, has_sources=True):
        """
        Menentukan label berdasarkan confidence score:
        - >= 0.75: Valid
        - <= 0.5: Hoax
        - > 0.5 dan < 0.75: Tidak Tentu
        - Tidak ada sumber: Tidak Terverifikasi
        """
        if not has_sources:
            return self.LABEL_UNVERIFIED
        
        if self.confidence >= 0.75:
            return self.LABEL_VALID
        elif self.confidence <= 0.5:
            return self.LABEL_HOAX
        else:  # 0.5 < confidence < 0.75
            return self.LABEL_UNCERTAIN

    def save(self, *args, **kwargs):
        # Auto-set label based on confidence if not manually set
        if not self.pk:  # Only on creation
            has_sources = self.claim.sources.exists() if self.claim else False
            self.label = self.determine_label_from_confidence(has_sources)
        super().save(*args, **kwargs)
        
    def __str__(self):
        return f'Verification Result for Claim #{self.claim_id}: {self.label} ({self.confidence:.2f})'

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