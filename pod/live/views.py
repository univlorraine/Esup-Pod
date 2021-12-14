import json
import re
from datetime import date, datetime

import requests
from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.sites.shortcuts import get_current_site
from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import PermissionDenied
from django.core.exceptions import SuspiciousOperation
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.db.models import Prefetch
from django.db.models import Q
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import ugettext_lazy as _
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_protect

from pod.bbb.models import Livestream
from .forms import LivePasswordForm, EventForm, EventDeleteForm
from .models import Building, Broadcaster, HeartBeat, Event
from ..main.views import in_maintenance

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

def events(request):  # affichage des events

    queryset = Event.objects.filter(is_draft=False)
    if not request.user.is_authenticated():
        queryset.filter(is_restricted=False)

    events_list = queryset.all().order_by("-start_date", "-start_time", "-end_time")

    page = request.GET.get("page", 1)
    full_path = ""
    if page:
        full_path = (
            request.get_full_path()
            .replace("?page=%s" % page, "")
            .replace("&page=%s" % page, "")
        )

    paginator = Paginator(events_list, 12)
    try:
        events = paginator.page(page)
    except PageNotAnInteger:
        events = paginator.page(1)
    except EmptyPage:
        events = paginator.page(paginator.num_pages)

    return render(
        request,
        "live/events.html",
        {
            "events": events,
            "full_path": full_path,
        }
    )

@csrf_protect
@ensure_csrf_cookie
@login_required(redirect_field_name="referrer")
def my_events(request):
    queryset = request.user.event_set

    past_events = queryset.filter(
        Q(start_date__lt=date.today())
        |(Q(start_date=date.today()) & Q(end_time__lte=datetime.now()))
        ).all().order_by("-start_date", "-start_time", "-end_time")

    coming_events = queryset.filter(
        Q(start_date__gt=date.today())
        |(Q(start_date=date.today()) & Q(end_time__gte=datetime.now()))
        ).all().order_by("start_date", "start_time", "end_time")

    events_number = queryset.all().distinct().count()

    PREVIOUS_EVENT_URL_NAME= "ppage"
    NEXT_EVENT_URL_NAME= "npage"

    full_path = request.get_full_path()
    full_path = re.sub("\?|\&"+PREVIOUS_EVENT_URL_NAME+"=\d+", "", full_path)
    full_path = re.sub("\?|\&"+NEXT_EVENT_URL_NAME+"=\d+", "", full_path)

    paginatorComing = Paginator(coming_events, 8)
    paginatorPast = Paginator(past_events, 8)

    pageP = request.GET.get(PREVIOUS_EVENT_URL_NAME,1)
    pageN = request.GET.get(NEXT_EVENT_URL_NAME,1)

    try:
        coming_events = paginatorComing.page(pageN)
        past_events = paginatorPast.page(pageP)
    except PageNotAnInteger:
        pageP = 1
        pageN = 1
        coming_events = paginatorComing.page(1)
        past_events = paginatorPast.page(1)
    except EmptyPage:
        pageP = 1
        pageN = 1
        coming_events = paginatorComing.page(paginatorComing.num_pages)
        past_events = paginatorPast.page(paginatorPast.num_pages)

    return render(
        request,
        "live/my_events.html",
        {
            "full_path": full_path,
            "types": request.GET.getlist("type"),
            "events_number": events_number,
            "past_events": past_events,
            "past_events_url": PREVIOUS_EVENT_URL_NAME,
            "past_events_url_page": PREVIOUS_EVENT_URL_NAME+"="+str(pageP),
            "coming_events": coming_events,
            "coming_events_url": NEXT_EVENT_URL_NAME,
            "coming_events_url_page": NEXT_EVENT_URL_NAME+"="+str(pageN),
        }
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

    if not parseAndCheckPilotingConfJson(broadcaster.piloting_conf):
        raise SuspiciousOperation("the broadcaster is not set for recording")

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

        if not parseAndCheckPilotingConfJson(broadcaster.piloting_conf):
            raise SuspiciousOperation("the broadcaster is not set for recording")

        pilot_conf = json.loads(broadcaster.piloting_conf)

        if event_isstreamrecording(idbroadcaster) == False:
            raise SuspiciousOperation("the broadcaster is not recording")
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

        if not parseAndCheckPilotingConfJson(broadcaster.piloting_conf):
            raise SuspiciousOperation("the broadcaster is not set for recording")

        pilot_conf = json.loads(broadcaster.piloting_conf)

        if event_isstreamrecording(idbroadcaster) == False:
            raise SuspiciousOperation("the broadcaster is not recording")
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

    if not parseAndCheckPilotingConfJson(broadcaster.piloting_conf):
        return False

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

    if not parseAndCheckPilotingConfJson(broadcaster.piloting_conf):
        return JsonResponse({"success": False}, status=400)

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

def parseAndCheckPilotingConfJson(piloting_conf):

     # TODO verifier aussi l'implementation
    if not piloting_conf:
        print("piloting_conf value is not set")
        return False

    try:
        decoded = json.loads(piloting_conf)
    except:
        print("piloting_conf has not a valid Json format")
        return False

    if not {"server", "port", "application", "livestream"} <= decoded.keys():
        print("piloting_conf format value must be like : {'server':'...','port':'...','application':'...','livestream':'...'}")
        return False

    return True