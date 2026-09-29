from django.core.management.base import BaseCommand, CommandError

from apps.pages.assistant_semantics import prepare_model


class Command(BaseCommand):
    """
    Prepare pinned local assets before the assistant serves questions
    """

    help = "Download and verify the local assistant model (no account or API key needed)"
    requires_system_checks = []

    def handle(self, *args, **options):
        """
        Report successful setup or stop the build on an incomplete download

        Parameters
        ----------
        *args : object
            Positional command arguments.
        **options : object
            Standard management command options.
        """
        try:
            directory = prepare_model()
        except Exception as error:
            raise CommandError(f"Assistant model setup failed: {error}") from error
        self.stdout.write(self.style.SUCCESS(f"Verified assistant model: {directory}"))
