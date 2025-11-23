"""
Management command untuk merge duplicate claims yang sudah ada.

Usage:
    python manage.py merge_duplicate_claims --dry-run
    python manage.py merge_duplicate_claims --execute
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from api.models import Claim, VerificationResult
from api.views import normalize_claim_text, generate_claim_hash
from collections import defaultdict


class Command(BaseCommand):
    help = 'Merge duplicate claims berdasarkan normalized hash'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be merged without actually doing it',
        )
        parser.add_argument(
            '--execute',
            action='store_true',
            help='Actually merge the duplicates',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=100,
            help='Number of claims to process at once',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        execute = options['execute']
        batch_size = options['batch_size']

        if not dry_run and not execute:
            self.stdout.write(
                self.style.WARNING(
                    'Please specify either --dry-run or --execute'
                )
            )
            return

        self.stdout.write('Starting duplicate claim analysis...\n')

        # Step 1: Re-normalize all existing claims
        self.stdout.write('Step 1: Re-normalizing all claims...')
        updated = self._renormalize_claims(batch_size, execute)
        self.stdout.write(
            self.style.SUCCESS(f'  ✓ {updated} claims re-normalized')
        )

        # Step 2: Find duplicates
        self.stdout.write('\nStep 2: Finding duplicates...')
        duplicates = self._find_duplicates()
        
        if not duplicates:
            self.stdout.write(self.style.SUCCESS('  ✓ No duplicates found!'))
            return

        self.stdout.write(
            self.style.WARNING(f'  ! Found {len(duplicates)} groups of duplicates')
        )

        # Step 3: Merge duplicates
        if execute:
            self.stdout.write('\nStep 3: Merging duplicates...')
            merged_count = self._merge_duplicates(duplicates)
            self.stdout.write(
                self.style.SUCCESS(f'  ✓ Merged {merged_count} duplicate claims')
            )
        else:
            self.stdout.write('\nStep 3: Preview of duplicates to merge:')
            self._preview_duplicates(duplicates)

        self.stdout.write(
            self.style.SUCCESS('\n✓ Operation completed successfully!')
        )

    def _renormalize_claims(self, batch_size, execute):
        """Re-normalize all claims with improved normalization."""
        claims = Claim.objects.all()
        total = claims.count()
        updated = 0

        self.stdout.write(f'  Processing {total} claims...')

        for i in range(0, total, batch_size):
            batch = claims[i:i+batch_size]
            
            for claim in batch:
                old_normalized = claim.normalized_text
                old_hash = claim.text_hash
                
                # Apply new normalization
                new_normalized = normalize_claim_text(claim.text)
                new_hash = generate_claim_hash(claim.text)
                
                if old_normalized != new_normalized or old_hash != new_hash:
                    if execute:
                        claim.normalized_text = new_normalized
                        claim.text_hash = new_hash
                        claim.save(update_fields=['normalized_text', 'text_hash'])
                    updated += 1
            
            if (i + batch_size) % 500 == 0:
                self.stdout.write(f'    ... processed {i + batch_size}/{total}')

        return updated

    def _find_duplicates(self):
        """Find claims with duplicate hashes."""
        hash_groups = defaultdict(list)
        
        # Group claims by hash
        for claim in Claim.objects.select_related('verification_result'):
            if claim.text_hash:
                hash_groups[claim.text_hash].append(claim)
        
        # Filter only groups with duplicates
        duplicates = {
            hash_val: claims 
            for hash_val, claims in hash_groups.items() 
            if len(claims) > 1
        }
        
        return duplicates

    def _preview_duplicates(self, duplicates):
        """Show preview of what would be merged."""
        for hash_val, claims in duplicates.items():
            self.stdout.write(f'\n  Hash: {hash_val[:16]}...')
            self.stdout.write(f'  Found {len(claims)} duplicates:')
            
            for claim in claims:
                label = 'N/A'
                confidence = 'N/A'
                
                if hasattr(claim, 'verification_result'):
                    vr = claim.verification_result
                    label = vr.label
                    confidence = f"{vr.confidence:.2f}" if vr.confidence else 'N/A'
                
                self.stdout.write(
                    f'    - ID {claim.id}: "{claim.text[:60]}..." '
                    f'[{label}, conf={confidence}]'
                )

    @transaction.atomic
    def _merge_duplicates(self, duplicates):
        """
        Merge duplicate claims, keeping the best one.
        
        Priority:
        1. Claim with verification result
        2. Higher confidence
        3. More sources
        4. Newer claim
        """
        merged_count = 0
        
        for hash_val, claims in duplicates.items():
            # Sort claims by priority
            sorted_claims = sorted(
                claims,
                key=lambda c: (
                    hasattr(c, 'verification_result'),  # Has verification
                    c.verification_result.confidence if hasattr(c, 'verification_result') and c.verification_result.confidence else 0,  # Confidence
                    c.sources.count(),  # Number of sources
                    c.created_at  # Newer
                ),
                reverse=True
            )
            
            # Keep the best one
            primary_claim = sorted_claims[0]
            duplicates_to_merge = sorted_claims[1:]
            
            self.stdout.write(
                f'\n  Keeping Claim ID {primary_claim.id} '
                f'(label: {primary_claim.verification_result.label if hasattr(primary_claim, "verification_result") else "N/A"})'
            )
            
            for dup in duplicates_to_merge:
                self.stdout.write(f'    - Merging ID {dup.id}...')
                
                # Transfer any unique sources
                for source_link in dup.claimsource_set.all():
                    if not primary_claim.claimsource_set.filter(
                        source=source_link.source
                    ).exists():
                        source_link.claim = primary_claim
                        source_link.save()
                
                # Delete duplicate
                dup.delete()
                merged_count += 1
                
                self.stdout.write(
                    self.style.SUCCESS(f'      ✓ Merged ID {dup.id} into {primary_claim.id}')
                )
        
        return merged_count