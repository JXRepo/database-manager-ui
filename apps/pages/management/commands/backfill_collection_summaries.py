"""
Prepare a bounded batch of existing collection summaries outside page requests
"""

from django.core.management.base import BaseCommand, CommandError

from apps.pages.collection_graph import collection_summaries
from apps.pages.models import JSONData


class Command(BaseCommand):
    """
    Build missing summaries without rewriting original JSON or existing summaries
    """

    help = "Prepare missing collection summaries in a bounded, restartable batch."

    def add_arguments(self, parser):
        """
        Accept a batch size and an explicit configured database alias

        Parameters
        ----------
        parser : ArgumentParser
            Django command argument parser.
        """
        scope = parser.add_mutually_exclusive_group()
        scope.add_argument("--limit", type=int, default=100, help="Prepare at most this many missing summaries.")
        scope.add_argument("--all", action="store_true", help="Prepare existing records in batches of 100.")
        parser.add_argument("--database", default="default")

    def handle(self, *args, **options):
        """
        Prepare the requested bounded batch or the existing records at command start

        Parameters
        ----------
        *args : str
            Standard positional arguments supplied by Django.
        **options : object
            Parsed limit, database alias and output settings.
        """
        limit = options["limit"]
        if limit < 1:
            raise CommandError("Use a positive --limit value.")
        objects = JSONData.objects.using(options["database"])
        upper_pk = objects.order_by("-pk").values_list("pk", flat=True).first() or 0
        batch_size = 100 if options["all"] else limit
        last_pk = 0
        prepared = 0
        while last_pk < upper_pk:
            ids = list(objects.filter(
                pk__gt=last_pk, pk__lte=upper_pk, collection_summary__isnull=True,
            ).order_by("pk").values_list("pk", flat=True)[:batch_size])
            if not ids:
                break
            prepared += sum(1 for _ in collection_summaries(objects.filter(pk__in=ids), prepare_all=True))
            last_pk = ids[-1]
            if not options["all"]:
                break
        remaining = objects.filter(collection_summary__isnull=True).count()
        self.stdout.write(f"Prepared {prepared} summaries. {remaining} records still need summaries.")
