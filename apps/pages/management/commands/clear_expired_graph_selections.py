"""
Remove expired temporary membership without reviving old session selections
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.pages.temporary_selections import prune_expired_selections


class Command(BaseCommand):
    """
    Clean graph selection buckets belonging to expired database sessions
    """

    help = "Clear expired graph membership and remove buckets for expired database sessions."

    def handle(self, *args, **options):
        """
        Report cleanup counts without exposing session keys or selected records

        Parameters
        ----------
        *args : object
            Standard management command arguments.
        **options : object
            Standard command options.
        """
        if settings.SESSION_ENGINE not in {
            "django.contrib.sessions.backends.db", "django.contrib.sessions.backends.cached_db",
        }:
            raise CommandError("Graph selection cleanup requires database-backed sessions.")
        cleared, removed = prune_expired_selections()
        self.stdout.write(f"Cleared {cleared} expired graph selection buckets; removed {removed} expired session buckets.")
