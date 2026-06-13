from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from channels_app.models import TeamChannel


class Command(BaseCommand):
    help = 'Permanently delete channels that have been in Recently Deleted for more than 30 days'

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=30)
        expired = TeamChannel.objects.filter(
            is_deleted=True,
            deleted_at__isnull=False,
            deleted_at__lt=cutoff
        )
        count = expired.count()
        expired.delete()
        self.stdout.write(f'Permanently deleted {count} expired channel(s)')
