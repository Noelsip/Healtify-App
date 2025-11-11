from django.db import models

# menyimpan sumber referensi seperti doi, url
class Source(models.Model):
    title = models.CharField(max_length=500)
    doi = models.CharField(max_length=255, blank=True, null=True)
    url = models.URLField(blank=True, null=True)
    authors = models.TextField(blank=True, null=True)
    publisher = models.CharField(max_length=255, blank=True, null=True)
    published_date = models.DateField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

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
    relevance_score = models.FloatField(default=0.0)  # skor relevansi antara klaim dan sumber
    excerpt = models.TextField(blank=True, null=True)  
    rank = models.IntegerField(default=0)  

    class Meta:
        unique_together = ('claim', 'source')

    def __str__(self):
        return f'ClaimSource: Claim #{self.claim_id} - Source #{self.source_id}'

# Model untuk menyimpan hasil verifikasi klaim untuk satu klaim
class VerificationResult(models.Model):
    # Label hasil
    LABEL_TRUE = 'true'
    LABEL_FALSE = 'false'
    LABEL_MISLEADING = 'misleading'
    LABEL_UNSUPPORTED = 'unsupported'
    LABEL_INCONCLUSIVE = 'inconclusive'
    LABEL_CHOICES = [
        (LABEL_TRUE, 'True'),
        (LABEL_FALSE, 'False'),
        (LABEL_MISLEADING, 'Misleading'),
        (LABEL_UNSUPPORTED, 'Unsupported'),
        (LABEL_INCONCLUSIVE, 'Inconclusive'),
    ]
    claim = models.OneToOneField(Claim, on_delete=models.CASCADE, related_name='verification_result')
    label = models.CharField(
        max_length=32,
        choices=LABEL_CHOICES,
        default=LABEL_INCONCLUSIVE,
    )
    summary = models.TextField(blank=True, null=True)  
    confidence = models.FloatField(default=0.0)
    reviewer_notes = models.TextField(blank=True, null=True) # catatan tambahan dari reviewer
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def confidence_percent(self):
        return round(self.confidence * 100, 2)

    def __str__(self):
        return f'Verification Result for Claim #{self.claim_id}: {self.label} ({self.confidence:.2f})'

# Model laporan hasil verifikasi klaim oleh user
class Dispute(models.Model):
    claim = models.ForeignKey(Claim, on_delete=models.SET_NULL, null=True, blank=True, related_name='disputes')
    claim_text = models.TextField(blank=True, null=True)  # menyimpan teks klaim jika claim dihapus atau tidak ada

    reporter_name = models.CharField(max_length=255, blank=True, null=True)
    reporter_email = models.EmailField(blank=True, null=True)

    reason = models.TextField()
    supporting_doi = models.CharField(max_length=255, blank=True, null=True)
    supporting_url = models.URLField(blank=True, null=True)
    supporting_file = models.FileField(upload_to='disputes/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending Review'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_REJECTED, 'Rejected'),
    ]

    status = models.CharField(
        max_length=32,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )

    # laporan telah ditinjau atau belum oleh admin
    reviewed = models.BooleanField(default=False)
    review_note = models.TextField(blank=True, null=True)
    reviewed_by = models.CharField(max_length=255, blank=True, null=True)
    reviewed_at = models.DateTimeField(blank=True, null=True)

    # Original verification result sebelum dispute
    original_label = models.CharField(max_length=32, blank=True, null=True)
    original_confidence = models.FloatField(blank=True, null=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Dispute'
        verbose_name_plural = 'Disputes'

    def __str__(self):
        return f'Report #{self.pk} for Claim #{self.claim_id or "manual"}'
    
# Model untuk FAQ dinamis
class FAQItem(models.Model):
    question = models.CharField(max_length=500)
    answer = models.TextField()
    order = models.IntegerField(default=0)  
    published = models.BooleanField(default=True)

    def __str__(self):
        return f'FAQ: {self.question[:60]}'