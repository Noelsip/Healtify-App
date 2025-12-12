from django.core.management.base import BaseCommand
from pathlib import Path
import shutil

class Command(BaseCommand):
    help = 'Clear all cache directories (LLM, embedding, fetch)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--type',
            type=str,
            default='all',
            help='Cache type to clear: all, llm, embedding, fetch'
        )
        parser.add_argument(
            '--confirm',
            action='store_true',
            help='Skip confirmation prompt'
        )

    def handle(self, *args, **options):
        cache_type = options['type']
        confirm = options['confirm']
        
        # Define cache directories
        BASE_DIR = Path(__file__).resolve().parents[3]
        TRAINING_DIR = BASE_DIR / "training"
        
        cache_dirs = {
            'llm': TRAINING_DIR / "data" / "llm_cache",
            'embedding': TRAINING_DIR / "data" / "cache",
            'fetch': TRAINING_DIR / "data" / "cache",
            'all': TRAINING_DIR / "data"
        }
        
        # Select directories to clear
        if cache_type == 'all':
            dirs_to_clear = [
                TRAINING_DIR / "data" / "llm_cache",
                TRAINING_DIR / "data" / "cache"
            ]
        elif cache_type in cache_dirs:
            dirs_to_clear = [cache_dirs[cache_type]]
        else:
            self.stdout.write(
                self.style.ERROR(f'Invalid cache type: {cache_type}')
            )
            return
        
        # Confirmation
        if not confirm:
            self.stdout.write(
                self.style.WARNING(
                    f'\nThis will DELETE the following cache directories:'
                )
            )
            for d in dirs_to_clear:
                self.stdout.write(f'  - {d}')
            
            response = input('\nContinue? (yes/no): ')
            if response.lower() != 'yes':
                self.stdout.write(self.style.WARNING('Aborted.'))
                return
        
        # Clear caches
        cleared_count = 0
        for cache_dir in dirs_to_clear:
            if cache_dir.exists():
                try:
                    # Count files before deletion
                    if cache_dir.is_dir():
                        file_count = len(list(cache_dir.glob('**/*')))
                        
                        # Delete all contents
                        for item in cache_dir.iterdir():
                            if item.is_file():
                                item.unlink()
                            elif item.is_dir():
                                shutil.rmtree(item)
                        
                        cleared_count += file_count
                        
                        self.stdout.write(
                            self.style.SUCCESS(
                                f'✓ Cleared {file_count} files from {cache_dir.name}'
                            )
                        )
                    
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(
                            f'✗ Error clearing {cache_dir}: {e}'
                        )
                    )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f'⊘ {cache_dir} does not exist'
                    )
                )
        
        self.stdout.write(
            self.style.SUCCESS(
                f'\n✓ Successfully cleared {cleared_count} cached files'
            )
        )