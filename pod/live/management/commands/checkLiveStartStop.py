from datetime import date, datetime

from django.core.management.base import BaseCommand
from django.db.models import Q
from pod.live.models import Event, Broadcaster
from pod.live.views import  is_recording, is_available_to_record,start_record,stop_record



class Command(BaseCommand):

    help = 'Vérifie les lancements et arrêts d\'enregistrement'

    def event_startrecord(self,broadcaster_id):
        broadcaster = Broadcaster.objects.get(pk=broadcaster_id)
        if is_recording(broadcaster):
            return {"success": False, "message": "the broadcaster is already recording"}
        if start_record(broadcaster):
            return {"success": True}
        return {"success": False, "message": ""}

    def handle(self,*args,**options):
        self.stdout.write("Vérification des events en enregistrement")
        events = Event.objects.filter(
            Q(start_date=date.today())
            & Q(start_time__lte=datetime.now())
            & Q(end_time__gte=datetime.now())
        )
        broadcaster_recording=[]

        self.stdout.write("--->Start record prepared")
        for event in events:
            if not is_recording(event.broadcaster):
                self.stdout.write(f"Broadcaster {event.broadcaster.name} -> not recording")
                sr = self.event_startrecord(event.broadcaster.pk)
                if sr.get("success")==True or sr.get("message")=="the broadcaster is already recording":
                    broadcaster_recording.append(event.broadcaster.pk)
                    self.stdout.write(f"Broadcaster {event.broadcaster.name} -> recording")
                else:
                    self.stdout.write(f"Broadcaster {event.broadcaster.name} -> problem when start recording")
            else:
                self.stdout.write(f"Broadcaster {event.broadcaster.name} -> already recording")
                broadcaster_recording.append(event.broadcaster.pk)

        broadcasters = Broadcaster.objects.all()

        self.stdout.write("--->Stop record prepared")
        for broadcaster in broadcasters:
            if is_recording(broadcaster) != False and broadcaster.pk not in broadcaster_recording:
                if stop_record(broadcaster):
                    self.stdout.write(f"Broadcaster {broadcaster.name} -> stop recording")
                else:
                    self.stdout.write(f"Broadcaster {broadcaster.name} -> problem when stop recording")

        self.stdout.write("Fin de vérification des events en enregistrement")