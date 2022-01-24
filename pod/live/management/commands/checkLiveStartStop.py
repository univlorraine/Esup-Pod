import datetime
from datetime import date, datetime

from django.core.management.base import BaseCommand
from django.db.models import Q

from pod.live.models import Event, Broadcaster
from pod.live.views import is_recording, start_record, stop_record, check_piloting_conf


class Command(BaseCommand):

    help = 'Check events to start or stop'

    def add_arguments(self, parser):
        parser.add_argument(
            '-p',
            '--prod',
            action='store_true',
            help='Start and stop broadcasters FOR REAL',
        )

    def handle(self,*args,**options):

        is_prod = options['prod']

        if is_prod:
            self.stderr.write(" RUN FOR REAL ")
        else:
            self.stderr.write(" RUN ONLY FOR DEBUGGING PURPOSE ")

        events = Event.objects.filter(
            Q(start_date=date.today())
            & Q(start_time__lte=datetime.now())
            & Q(end_time__gte=datetime.now())
        )
        rec_bro_ids=[]

        self.stdout.write("-- Starting new events")
        for event in events:
            rec_bro_ids.append(event.broadcaster.id)

            if not is_recording(event.broadcaster):

                self.stdout.write(f"Broadcaster {event.broadcaster.name} should be started : " + event.broadcaster.name, ending="")

                if not check_piloting_conf(event.broadcaster):
                    self.stderr.write("Config error")
                    continue

                if is_prod:
                    if start_record(event.broadcaster):
                        self.stdout.write(" ... successfully started")
                    else:
                        self.stderr.write(" ... fail to start")
                    continue
                else:
                    self.stderr.write(" but not tried (debug mode) ")
            else:
                self.stdout.write(f"Broadcaster {event.broadcaster.name} is recording")

        broadcasters = Broadcaster.objects.order_by("name").all()

        self.stdout.write("-- Stopping finished events")
        for broadcaster in broadcasters:
            if broadcaster.id not in rec_bro_ids:
                if not check_piloting_conf(broadcaster):
                    self.stderr.write(f"Config error for Broadcaster {broadcaster.name}")
                    continue

                if is_recording(broadcaster):
                    self.stdout.write(f"Broadcaster {broadcaster.name} should be stopped : " + broadcaster.name, ending="")

                    if is_prod:
                        if stop_record(broadcaster):
                            self.stdout.write(" ...  stopped ")
                        else:
                            self.stderr.write(" ... fail to stop recording")
                    else:
                        self.stdout.write(" but not tried (debug mode) ")

        self.stdout.write("- Done -")