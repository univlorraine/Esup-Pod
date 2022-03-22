from datetime import date, datetime

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from pod.live.models import Event
from pod.live.views import (
    is_recording,
    event_stoprecord,
    event_startrecord,
)

DEFAULT_EVENT_PATH = getattr(settings, "DEFAULT_EVENT_PATH", "")
DEBUG = getattr(settings, "DEBUG", "")


class Command(BaseCommand):
    help = "start or stop broadcaster recording based on live events "

    debug_mode = DEBUG

    def add_arguments(self, parser):
        parser.add_argument(
            "-f",
            "--force",
            action="store_true",
            help="Start and stop recording FOR REAL",
        )

    def handle(self, *args, **options):

        if options["force"]:
            self.debug_mode = False

        if not self.debug_mode:
            self.stdout.write(" RUN FOR REAL ")
        else:
            self.stdout.write(" RUN ONLY FOR DEBUGGING PURPOSE ")

        self.stop_finished()

        self.start_new()

        self.stdout.write("- Done -")

    def stop_finished(self):
        # finished events in the last 5 minutes
        endtime = datetime.now() + timezone.timedelta(minutes=-5)

        events = Event.objects.filter(
            Q(start_date=date.today()) & Q(end_time__gte=endtime)
        )

        self.stdout.write("-- Stopping finished events (if started with Pod)")
        for event in events:
            if not is_recording(event.broadcaster, True):
                continue

            self.stdout.write(
                f"Broadcaster {event.broadcaster.name} should be stopped : ", ending=""
            )

            if self.debug_mode:
                self.stdout.write("... but not tried (debug mode) ")
                continue

            if event_stoprecord(event.id, event.broadcaster.id):
                self.stdout.write(" ...  stopped ")
            else:
                self.stderr.write(" ... fail to stop recording")

    def start_new(self):

        self.stdout.write("-- Starting new events")

        events = Event.objects.filter(
            Q(is_auto_start=True)
            & Q(start_date=date.today())
            & Q(start_time__lte=datetime.now())
            & Q(end_time__gte=datetime.now())
        )

        for event in events:

            if is_recording(event.broadcaster):
                self.stdout.write(
                    f"Broadcaster {event.broadcaster.name} is already recording"
                )
                continue

            self.stdout.write(
                f"Broadcaster {event.broadcaster.name} should be started : ", ending=""
            )

            if self.debug_mode:
                self.stdout.write("... but not tried (debug mode) ")
                continue

            if event_startrecord(event.id, event.broadcaster.id):
                self.stdout.write(" ... successfully started")
            else:
                self.stderr.write(" ... fail to start")
