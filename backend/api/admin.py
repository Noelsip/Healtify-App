from django.contrib import admin
from .models import Source, Claim, ClaimSource, VerificationResult, FAQItem, Dispute

# admin untuk source
@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    # menampilkan kolom di admin
    list_display = ('id', 'title', 'doi', 'url', 'publisher', 'published_date', 'created_at')
    search_fields = ('title', 'doi', 'url', 'authors', 'publisher')
    ordering = ('-created_at',)

# admin untuk claim
@admin.register(Claim)
class ClaimAdmin(admin.ModelAdmin):
    list_display = ('id', 'text_short', 'status', 'created_at', 'updated_at')
    search_fields = ('text',)
    list_filter = ('status',)
    ordering = ('-created_at',)

    # fungsi agar teks klaim yang panjang dipotong di tampilan admin
    def text_short(self, obj):
        return (obj.text[:80] + '...') if len(obj.text) > 80 else obj.text
    text_short.short_description = 'Claim Text'

# Admin untuk ClaimSource
@admin.register(ClaimSource)
class ClaimSourceAdmin(admin.ModelAdmin):
    list_display = ('id', 'claim', 'source', 'relevance_score', 'rank')
    search_fields = ('claim__text', 'source__title')
    list_filter = ('relevance_score',)
    ordering = ('rank',)

# Admin untuk VerificationResult
@admin.register(VerificationResult)
class VerificationResultAdmin(admin.ModelAdmin):
    list_display = ('id', 'claim', 'label', 'confidence_percent', 'created_at')
    search_fields = ('label',)
    list_filter = ('claim__text',)
    ordering = ('-created_at',)

    # menampilkan confidence dalam persen di admin
    def confidence_percent(self, obj):
        return f"{obj.confidence * 100:.1f}%"
    confidence_percent.short_description = 'Confidence'

# Admin untuk report
@admin.register(Dispute)
class ReportAdmin(admin.ModelAdmin):
    list_display = ('id', 'claim_id', 'reporter_name', 'reviewed', 'created_at')
    list_filter = ('reviewed',)
    search_fields = ('reason', 'supporting_doi', 'claim_text')
    readonly_fields = ('created_at',)
    ordering = ('-created_at',)

# Admin untuk FAQItem
@admin.register(FAQItem)
class FAQItemAdmin(admin.ModelAdmin):
    list_display = ('id', 'question', 'published', 'order')
    list_editable = ('order', 'published')
    search_fields = ('question', 'answer')
    ordering = ('order',)