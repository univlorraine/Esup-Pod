from datetime import date, datetime

from django.core.management.base import BaseCommand
from django.db.models import Q
from pod.live.models import Event, Broadcaster
from pod.live.views import  is_recording, is_available_to_record,start_record,stop_record



class Command(BaseCommand):

    help = 'Vérifie les lancements et arrêts d\'enregistrement'

    def event_isstreamavailabletorecord(broadcaster_id):
        broadcaster = Broadcaster.objects.get(pk=broadcaster_id)

        if is_recording(broadcaster):
            return {"available": True, "recording": True}

        available = is_available_to_record(broadcaster)
        return {"available": available, "recording": False}

    def event_startrecord(broadcaster_id):
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

        for event in events:
            self.stdout.write(f"Event {event.title} ({event.start_date:%d-%m-%Y} de {event.start_time:%H:%M} à {event.end_time:%H:%M})")
            if not is_recording(event.broadcaster.pk):
                sr = self.event_startrecord(event.broadcaster.pk)
                if sr.get("success")=="success" or sr.get("message")=="the broadcaster is already recording":
                    broadcaster_recording.append(event.broadcaster.p)
            else:
                broadcaster_recording.append(event.broadcaster.pk)

        broadcasters = Broadcaster.objects.all()
        broadcaster_to_stop = []
        for broadcaster in broadcasters:
            if is_recording(broadcaster.pk) & broadcaster.pk not in broadcaster_recording:
                broadcaster_to_stop.append(broadcaster.pk)

        for broadcaster in broadcaster_to_stop:
            stop_record(broadcaster)
