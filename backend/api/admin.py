from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
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
class DisputeAdmin(admin.ModelAdmin):
    list_display = ('id', 'claim_link', 'reporter_name', 'status', 'reviewed', 'reviewed_by', 'created_at')
    list_filter = ('status', 'reviewed', 'created_at')
    search_fields = ('reason', 'supporting_doi', 'claim_text', 'reporter_email', 'reviewer_note')
    readonly_fields = ('created_at', 'reviewed_at', 'original_label', 'original_confidence')
    ordering = ('-created_at',)
    
    fieldsets = (
        ('Dispute Information', {
            'fields': ('claim', 'claim_text', 'reason')
        }),
        ('Reporter Details', {
            'fields': ('reporter_name', 'reporter_email')
        }),
        ('Supporting Evidence', {
            'fields': ('supporting_doi', 'supporting_url', 'supporting_file')
        }),
        ('Review Status', {
            'fields': ('status', 'reviewed', 'review_note', 'reviewed_by', 'reviewed_at')
        }),
        ('Original Verification', {
            'fields': ('original_label', 'original_confidence'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )
    
    def claim_link(self, obj):
        if obj.claim:
            url = reverse('admin:api_claim_change', args=[obj.claim.id])
            return format_html('<a href="{}">{}</a>', url, f"Claim #{obj.claim.id}")
        return "No Claim"
    claim_link.short_description = 'Related Claim'
    
    actions = ['mark_as_reviewed', 'approve_disputes', 'reject_disputes']
    
    def mark_as_reviewed(self, request, queryset):
        from django.utils import timezone
        updated = queryset.update(reviewed=True, reviewed_at=timezone.now())
        self.message_user(request, f'{updated} disputes marked as reviewed.')
    mark_as_reviewed.short_description = 'Mark selected as reviewed'
    
    def approve_disputes(self, request, queryset):
        from django.utils import timezone
        updated = queryset.update(
            status=Dispute.STATUS_APPROVED,
            reviewed=True,
            reviewed_at=timezone.now()
        )
        self.message_user(request, f'{updated} disputes approved.')
    approve_disputes.short_description = 'Approve selected disputes'
    
    def reject_disputes(self, request, queryset):
        from django.utils import timezone
        updated = queryset.update(
            status=Dispute.STATUS_REJECTED,
            reviewed=True,
            reviewed_at=timezone.now()
        )
        self.message_user(request, f'{updated} disputes rejected.')
    reject_disputes.short_description = 'Reject selected disputes'


# Admin untuk FAQItem
@admin.register(FAQItem)
class FAQItemAdmin(admin.ModelAdmin):
    list_display = ('id', 'question', 'published', 'order')
    list_editable = ('order', 'published')
    search_fields = ('question', 'answer')
    ordering = ('order',)