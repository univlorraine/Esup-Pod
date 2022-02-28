import os
from datetime import date, datetime

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from pod.live.models import Event
from pod.live.views import (
    is_recording,
    get_info_current_record,
    event_stoprecord,
    event_startrecord,
)

DEFAULT_EVENT_PATH = getattr(settings, "DEFAULT_EVENT_PATH", "")


class Command(BaseCommand):
    help = "start or stop broadcaster recording based on live events "

    is_prod = False

    def add_arguments(self, parser):
        parser.add_argument(
            "-p",
            "--prod",
            action="store_true",
            help="Start and stop recording FOR REAL",
        )

    def handle(self, *args, **options):

        self.is_prod = options["prod"]

        if self.is_prod:
            self.stderr.write(" RUN FOR REAL ")
        else:
            self.stderr.write(" RUN ONLY FOR DEBUGGING PURPOSE ")

        self.stop_finished()

        self.start_new()

        self.stdout.write("- Done -")

    def stop_finished(self):
        # finished events in the last 5 minutes
        endtime = datetime.now() + timezone.timedelta(minutes=-5)

        events = Event.objects.filter(
            Q(start_date=date.today()) & Q(end_time__gte=endtime)
        )

        self.stdout.write("-- Stopping finished events")
        for event in events:
            if not is_recording(event.broadcaster):
                continue

            self.stdout.write(
                f"Broadcaster {event.broadcaster.name} should be stopped : ", ending=""
            )

            if not self.is_prod:
                self.stdout.write("... but not tried (debug mode) ")
                continue

            # Récupération du fichier associé à l'enregistrement du broadcaster
            current_record_info = get_info_current_record(event.broadcaster)

            if not current_record_info.get("currentFile"):
                self.stderr.write(" ... impossible to get recording file name")
                continue

            filename = current_record_info.get("currentFile")
            full_file_name = os.path.join(DEFAULT_EVENT_PATH, filename)

            # Vérification qu'il existe bien pour cette instance ce Pod
            if not os.path.exists(full_file_name):
                self.stdout.write(
                    " ...  is not a on POD recording filesystem : " + full_file_name
                )
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

            if not self.is_prod:
                self.stdout.write("... but not tried (debug mode) ")
                continue

            if event_startrecord(event.id, event.broadcaster.id):
                self.stdout.write(" ... successfully started")
            else:
                self.stderr.write(" ... fail to start")
