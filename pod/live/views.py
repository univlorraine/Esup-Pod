from django import forms
from django.conf.urls import url
from django.shortcuts import render
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_protect, csrf_exempt

from .models import Building, Broadcaster, HeartBeat, Event
from .forms import LivePasswordForm, EventForm, EventDeleteForm
from django.conf import settings
from django.shortcuts import redirect
from django.contrib.sites.shortcuts import get_current_site
from django.contrib import messages
from django.utils.translation import ugettext_lazy as _
from django.db.models import Prefetch
from django.core.exceptions import ObjectDoesNotExist, SuspiciousOperation
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
import json
from django.utils import timezone
from pod.bbb.models import Livestream
from ..main.views import in_maintenance

import requests

VIEWERS_ONLY_FOR_STAFF = getattr(settings, "VIEWERS_ONLY_FOR_STAFF", False)

HEARTBEAT_DELAY = getattr(settings, "HEARTBEAT_DELAY", 45)

USE_BBB = getattr(settings, "USE_BBB", False)
USE_BBB_LIVE = getattr(settings, "USE_BBB_LIVE", False)


def lives(request):  # affichage des directs
    site = get_current_site(request)
    buildings = (
        Building.objects.all()
        .filter(sites=site)
        .prefetch_related(
            Prefetch(
                "broadcaster_set",
                queryset=Broadcaster.objects.filter(public=True),
            )
        )
    )
    return render(
        request,
        "live/lives.html",
        {
            "buildings": buildings,
            "is_supervisor": (
                request.user.is_superuser
                or request.user.has_perm("live.view_building_supervisor")
            ),
        },
    )


@login_required(redirect_field_name="referrer")
def building(request, building_id):  # affichage des directs
    if not (
        request.user.is_superuser
        or request.user.has_perm("live.view_building_supervisor")
    ):
        messages.add_message(request, messages.ERROR, _("You cannot view this page."))
        raise PermissionDenied
    building = get_object_or_404(Building, id=building_id)
    return render(request, "live/building.html", {"building": building})


def get_broadcaster_by_slug(slug, site):
    broadcaster = None
    if slug.isnumeric():
        try:
            broadcaster = Broadcaster.objects.get(id=slug, building__sites=site)
        except ObjectDoesNotExist:
            pass
    if broadcaster is None:
        broadcaster = get_object_or_404(Broadcaster, slug=slug, building__sites=site)
    return broadcaster


def video_live(request, slug):  # affichage des directs
    site = get_current_site(request)
    broadcaster = get_broadcaster_by_slug(slug, site)
    if broadcaster.is_restricted and not request.user.is_authenticated():
        iframe_param = "is_iframe=true&" if (request.GET.get("is_iframe")) else ""
        return redirect(
            "%s?%sreferrer=%s"
            % (settings.LOGIN_URL, iframe_param, request.get_full_path())
        )
    is_password_protected = (
        broadcaster.password is not None and broadcaster.password != ""
    )
    if is_password_protected and not (
        request.POST.get("password")
        and request.POST.get("password") == broadcaster.password
    ):
        form = LivePasswordForm(request.POST) if request.POST else LivePasswordForm()
        if (
            request.POST.get("password")
            and request.POST.get("password") != broadcaster.password
        ):
            messages.add_message(request, messages.ERROR, _("The password is incorrect."))
        return render(
            request,
            "live/live.html",
            {
                "broadcaster": broadcaster,
                "form": form,
                "heartbeat_delay": HEARTBEAT_DELAY,
            },
        )
    # Search if broadcaster is used to display a BBB streaming live
    # for which students can send message from this live page
    display_chat = False
    if USE_BBB and USE_BBB_LIVE:
        livestreams_list = Livestream.objects.filter(broadcaster_id=broadcaster.id)
        for livestream in livestreams_list:
            display_chat = livestream.enable_chat
    return render(
        request,
        "live/live.html",
        {
            "display_chat": display_chat,
            "broadcaster": broadcaster,
            "heartbeat_delay": HEARTBEAT_DELAY,
        },
    )


""" use rest api to change status
def change_status(request, slug):
    broadcaster = get_object_or_404(Broadcaster, slug=slug)
    if request.GET.get("online") == "1":
        broadcaster.status = 1
    else:
        broadcaster.status = 0
    broadcaster.save()
    return HttpResponse("ok")
"""


def heartbeat(request):
    if request.is_ajax() and request.method == "GET":
        broadcaster_id = int(request.GET.get("liveid", 0))
        broadcast = get_object_or_404(Broadcaster, id=broadcaster_id)
        key = request.GET.get("key", "")
        heartbeat, created = HeartBeat.objects.get_or_create(
            viewkey=key, broadcaster_id=broadcaster_id
        )
        if created:
            if not request.user.is_anonymous:
                heartbeat.user = request.user
        heartbeat.last_heartbeat = timezone.now()
        heartbeat.save()

        mimetype = "application/json"
        viewers = broadcast.viewers.values("first_name", "last_name", "is_superuser")
        can_see = (
            VIEWERS_ONLY_FOR_STAFF and request.user.is_staff
        ) or not VIEWERS_ONLY_FOR_STAFF
        return HttpResponse(
            json.dumps(
                {
                    "viewers": broadcast.viewcount,
                    "viewers_list": list(viewers) if can_see else [],
                }
            ),
            mimetype,
        )
    return HttpResponseBadRequest()

def event(request, slug):  # affichage d'un event
    event = Event.objects.filter(slug=slug).first()
    isstreamavailabletorecord = event_isstreamrecording(event.broadcaster.id)

    return render(
        request,
        "live/event.html",
        {
            "event":event,
            "isStreamRecording": isstreamavailabletorecord
        }
    )

def events(request):  # affichage des evenemants
    lives = Event.objects.all()
    return render(
        request,
        "live/events.html",
        {
            "events": lives
        }
    )

@csrf_protect
@ensure_csrf_cookie
@login_required(redirect_field_name="referrer")
def my_events(request):
    data_context = {}
    lives_list = request.user.event_set.all().order_by("-start_date","-start_time","-end_time")
    lives_list = lives_list.distinct()
    data_context["events"] = lives_list

    return render(
        request,
        "live/my_events.html",
        data_context
    )

@csrf_protect
@ensure_csrf_cookie
@login_required(redirect_field_name="referrer")
def event_add(request):
    if request.POST:
        form = EventForm(
            request.POST
        )
        if form.is_valid():
            form.save()
            return redirect("/live/events")
    else:
        form = EventForm()
        form.fields['videos'].widget = forms.HiddenInput()

    return render(
        request, "live/event_add.html", {"form": form}
    )

@csrf_protect
@ensure_csrf_cookie
@login_required(redirect_field_name="referrer")
def event_edit(request, slug=None):
    if in_maintenance():
        return redirect(reverse("maintenance"))

    event = (
        get_object_or_404(Event, slug=slug)
        if slug
        else None
    )

    form = EventForm(
        request.POST or None,
        instance=event,
    )
    form.fields['videos'].widget = forms.HiddenInput()

    if request.POST:
        form = EventForm(
            request.POST,
            instance= event
        )
        if form.is_valid():
            event = form.save()
            messages.add_message(
                request, messages.INFO, _("The changes have been saved.")
            )
            return redirect(reverse("live:my_events"))
        else:
            messages.add_message(
                request,
                messages.ERROR,
                _(u"One or more errors have been found in the form."),
            )
    return render(request, "live/event_edit.html", {"form": form})

@csrf_protect
@login_required(redirect_field_name="referrer")
def event_delete(request, slug=None):

    event = get_object_or_404(Event, slug=slug)

    if request.user != event.owner and not (
        request.user.is_superuser or request.user.has_perm("event.delete_video")
    ):
        messages.add_message(request, messages.ERROR, _(u"You cannot delete this event."))
        raise PermissionDenied

    form = EventDeleteForm()

    if request.method == "POST":
        form = EventDeleteForm(request.POST)
        if form.is_valid():
            event.delete()
            messages.add_message(request, messages.INFO, _("The event has been deleted."))
            return redirect(reverse("live:events"))
        else:
            messages.add_message(
                request,
                messages.ERROR,
                _(u"One or more errors have been found in the form."),
            )

    return render(request, "live/event_delete.html", {"event": event, "form": form})

def broadcasters_from_building(request):
    building_name = request.GET.get('building')
    building = Building.objects.filter(name=building_name).first()
    broadcasters = Broadcaster.objects.filter(building=building)
    response_data={}
    for broadcaster in broadcasters:
        response_data[broadcaster.id] = {'id':broadcaster.id, 'name':broadcaster.name}
    return JsonResponse(response_data)

@csrf_protect
@login_required(redirect_field_name="referrer")
def event_startrecord(request):
    idbroadcaster = request.POST.get("idbroadcaster", None)
    broadcaster = Broadcaster.objects.get(pk=idbroadcaster)
    pilot_conf = json.loads(broadcaster.piloting_conf)

    if request.method == "POST" and request.is_ajax():
        if event_isstreamrecording(idbroadcaster)==True :
            raise SuspiciousOperation("the broadcaster is already recording")
        else:
            # if request.method == "POST" and request.is_ajax():
            url_start_record = "http://{server}:{port}/v2/servers/_defaultServer_/vhosts/_defaultVHost_/applications/{application}/instances/_definst_/streamrecorders/{livestream}".format(
                server=pilot_conf["server"],
                port=pilot_conf["port"],
                application=pilot_conf["application"],
                livestream=pilot_conf["livestream"],
            )
            data = {
                "instanceName": "",
                "fileVersionDelegateName": "",
                "serverName": "",
                "recorderName": "",
                "currentSize": 0,
                "segmentSchedule": "",
                "startOnKeyFrame": True,
                "outputPath": "//data//partage//VideosUL//vod_live_sandbox//",
                "baseFile": "_pod_test_${RecordingStartTime}",
                "currentFile": "",
                "saveFieldList": [""],
                "recordData": False,
                "applicationName": "",
                "moveFirstVideoFrameToZero": False,
                "recorderErrorString": "",
                "segmentSize": 0,
                "defaultRecorder": False,
                "splitOnTcDiscontinuity": False,
                "version": "",
                "segmentDuration": 0,
                "recordingStartTime": "",
                "fileTemplate": "",
                "backBufferTime": 0,
                "segmentationType": "",
                "currentDuration": 0,
                "fileFormat": "",
                "recorderState": "",
                "option": ""
            }

            response = requests.post(url_start_record, json=data, headers={"Accept": "application/json","Content-Type": "application/json"})
            response_dict = json.loads(response.text)
            print(response_dict)
            return JsonResponse(
                {'state': 'début enregistrement'}
            )

@csrf_protect
@login_required(redirect_field_name="referrer")
def event_splitrecord(request):
    if request.method == "POST" and request.is_ajax():
        idbroadcaster = request.POST.get("idbroadcaster", None)
        broadcaster = Broadcaster.objects.get(pk=idbroadcaster)
        pilot_conf = json.loads(broadcaster.piloting_conf)
        if event_isstreamrecording(idbroadcaster) == False:
            raise SuspiciousOperation("the broadcaster does not recording")
        else:
            url_split_record = "http://{server}:{port}/v2/servers/_defaultServer_/vhosts/_defaultVHost_/applications/{application}/instances/_definst_/streamrecorders/{livestream}/actions/splitRecording".format(
                server=pilot_conf["server"],
                port=pilot_conf["port"],
                application=pilot_conf["application"],
                livestream=pilot_conf["livestream"],
            )
            response = requests.put(url_split_record,
                                    headers={"Accept": "application/json", "Content-Type": "application/json"})
            response_dict = json.loads(response.text)
            print(response_dict)
            return JsonResponse(
                {'action': 'split enregistrement'}
            )


@csrf_protect
@login_required(redirect_field_name="referrer")
def event_stoprecord(request):
    if request.method == "POST" and request.is_ajax():
        idbroadcaster = request.POST.get("idbroadcaster", None)
        broadcaster = Broadcaster.objects.get(pk=idbroadcaster)
        pilot_conf = json.loads(broadcaster.piloting_conf)

        if event_isstreamrecording(idbroadcaster) == False:
            raise SuspiciousOperation("the broadcaster does not recording")
        else:
            url_stop_record = "http://{server}:{port}/v2/servers/_defaultServer_/vhosts/_defaultVHost_/applications/{application}/instances/_definst_/streamrecorders/{livestream}/actions/stopRecording".format(
                server=pilot_conf["server"],
                port=pilot_conf["port"],
                application=pilot_conf["application"],
                livestream=pilot_conf["livestream"],
            )
        response = requests.put(url_stop_record,headers={"Accept": "application/json","Content-Type": "application/json"})
        response_dict = json.loads(response.text)

        return JsonResponse(
            {'action': 'arrêt enregistrement'}
        )


@csrf_exempt
def event_isstreamrecording(idbroadcaster):

    broadcaster = Broadcaster.objects.get(pk=idbroadcaster)

    pilot_conf = json.loads(broadcaster.piloting_conf)

    url_state_live_stream_recording = "http://{server}:{port}/v2/servers/_defaultServer_/vhosts/_defaultVHost_/applications/{application}/instances/_definst_/streamrecorders".format(
        server=pilot_conf["server"],
        port=pilot_conf["port"],
        application=pilot_conf["application"]
    )
    response = requests.get(url_state_live_stream_recording,verify=True,headers={"Accept": "application/json","Content-Type": "application/json"})
    response_dict = json.loads(response.text)

    if response_dict["streamrecorder"]:
         for streamrecorder in response_dict["streamrecorder"]:
             if streamrecorder["recorderName"] == pilot_conf["livestream"]:
                 return True
    return False


@csrf_protect
def event_isstreamavailabletorecord(idbroadcaster):
    broadcaster = Broadcaster.objects.get(pk=idbroadcaster)
    pilot_conf = json.loads(broadcaster.piloting_conf)
    url_state_live_stream_recording = "http://{server}:{port}/v2/servers/_defaultServer_/vhosts/_defaultVHost_/applications/{application}/streamfiles".format(
        server=pilot_conf["server"],
        port=pilot_conf["port"],
        application=pilot_conf["application"],
	)

    response = requests.get(url_state_live_stream_recording,headers={"Accept": "application/json","Content-Type": "application/json"})

    response_dict = json.loads(response.text)

    livestream = pilot_conf["livestream"]

    if ".stream" not in livestream:
        return JsonResponse({"success": False}, status=400)

    livestream_id = livestream[0:-7]

    for stream in response_dict["streamFiles"]:
        if stream["id"]==livestream_id:
            return JsonResponse({"success":True}, status=200)

    return JsonResponse({"success": False}, status=400)