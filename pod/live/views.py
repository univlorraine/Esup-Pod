import json
import os.path
import re
import logging
from datetime import date, datetime
from typing import Optional

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.sites.shortcuts import get_current_site
from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.db.models import Prefetch
from django.db.models import Q
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse, HttpResponseNotAllowed, \
    HttpResponseNotFound, Http404
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import ugettext_lazy as _
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_protect

from pod.bbb.models import Livestream
from .forms import LivePasswordForm, EventForm, EventDeleteForm
from .models import Building, Broadcaster, HeartBeat, Event, getAvailableBroadcastersOfBuilding
from .pilotingInterface import Wowza, PilotingInterface, BROADCASTER_IMPLEMENTATION
from ..main.views import in_maintenance
from ..video.models import Video, Type
from django.template.defaultfilters import slugify

VIEWERS_ONLY_FOR_STAFF = getattr(settings, "VIEWERS_ONLY_FOR_STAFF", False)

HEARTBEAT_DELAY = getattr(settings, "HEARTBEAT_DELAY", 45)

USE_BBB = getattr(settings, "USE_BBB", False)
USE_BBB_LIVE = getattr(settings, "USE_BBB_LIVE", False)

DEFAULT_EVENT_PATH = getattr(settings, "DEFAULT_EVENT_PATH", "")
DEFAULT_EVENT_THUMBNAIL = getattr(settings, "DEFAULT_EVENT_THUMBNAIL", "/img/default-event.svg")
RESTRICT_EDIT_EVENT_ACCESS_TO_STAFF_ONLY = getattr(
    settings, "RESTRICT_EDIT_EVENT_ACCESS_TO_STAFF_ONLY", True
)
VIDEOS_DIR = getattr(settings, "VIDEOS_DIR", "videos")


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

    # modif de l'url d'appel pour compatibilité avec le template link_video.html (variable : urleditapp)
    request.resolver_match.namespace = ""

    event = get_object_or_404(Event, slug=slug)

    # draft ou non on l'affiche

    # droits sur le broadcaster : public, restricted , access en view
    # restricted_groups = event.broadcaster.restrict_access_to_groups.all()
    if not event.broadcaster.public and not request.user.is_superuser:
        # if event.broadcaster.is_restricted or restricted_groups.exists():
        if event.broadcaster.is_restricted:
            if not request.user.is_authenticated():
                url = reverse("authentication_login")
                url += "?referrer=" + request.get_full_path()
                return redirect(url)
        # if restricted_groups.exists():
        #     user_groups = request.user.groups.all()
        #     if set(user_groups).isdisjoint(restricted_groups):
        #         raise PermissionDenied
    need_piloting_buttons = False
    if (event.owner == request.user and (not RESTRICT_EDIT_EVENT_ACCESS_TO_STAFF_ONLY or
                                         (RESTRICT_EDIT_EVENT_ACCESS_TO_STAFF_ONLY and request.user.is_staff))) \
            or request.user.is_superuser:
        need_piloting_buttons = True
    return render(
        request,
        "live/event.html",
        {
            "event": event,
            "need_piloting_buttons": need_piloting_buttons,
        }
    )


def events(request):  # affichage des events

    queryset = Event.objects.filter(
        Q(start_date__gt=date.today())
        |
        (Q(start_date=date.today()) & Q(end_time__gte=datetime.now()))
    )
    queryset = queryset.filter(is_draft=False)
    if not request.user.is_authenticated():
        queryset = queryset.filter(broadcaster__is_restricted=False)
    #     queryset = queryset.filter(broadcaster__restrict_access_to_groups__isnull=True)
    # elif not request.user.is_superuser:
    #     queryset = queryset.filter(Q(is_draft=False) | Q(owner=request.user))
    #     queryset = queryset.filter(Q(broadcaster__restrict_access_to_groups__isnull=True) |
    #              Q(broadcaster__restrict_access_to_groups__in=request.user.groups.all()))

    events_list = queryset.all().order_by("start_date", "start_time", "end_time")

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
            "DEFAULT_EVENT_THUMBNAIL": DEFAULT_EVENT_THUMBNAIL,
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
            "DEFAULT_EVENT_THUMBNAIL": DEFAULT_EVENT_THUMBNAIL,
        }
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

    if RESTRICT_EDIT_EVENT_ACCESS_TO_STAFF_ONLY and request.user.is_staff is False:
        return render(request, "live/event_edit.html", {"access_not_allowed": True})

    form = EventForm(
        request.POST or None,
        instance=event,
        user=request.user,
        is_current_event=event.is_current if slug else None
    )

    if request.POST:
        form = EventForm(
            request.POST,
            instance=event,
            user=request.user,
            is_current_event=event.is_current if slug else None
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
            return redirect(reverse("live:my_events"))
        else:
            messages.add_message(
                request,
                messages.ERROR,
                _(u"One or more errors have been found in the form."),
            )

    return render(request, "live/event_delete.html", {"event": event, "form": form})

def broadcasters_from_building(request):
    building_name = request.GET.get('building')
    if not building_name:
        return HttpResponseBadRequest()
    build = Building.objects.filter(name=building_name).first()
    if not build:
        return HttpResponseNotFound()
    broadcasters = getAvailableBroadcastersOfBuilding(request.user, build.id)

    response_data={}
    for broadcaster in broadcasters:
        response_data[broadcaster.id] = {'id':broadcaster.id, 'name':broadcaster.name}
    return JsonResponse(response_data)

@csrf_protect
@login_required(redirect_field_name="referrer")
def event_isstreamavailabletorecord(request):
    if request.method == "GET" and request.is_ajax():
        broadcaster_id = request.GET.get("idbroadcaster", None)
        broadcaster = Broadcaster.objects.get(pk=broadcaster_id)

        if not check_piloting_conf(broadcaster):
            return JsonResponse({"available": False, "recording": False, "message": "implementation error"})

        if is_recording(broadcaster):
            return JsonResponse({"available": True, "recording": True})

        available = is_available_to_record(broadcaster)
        return JsonResponse({"available": available, "recording": False})

    return HttpResponseNotAllowed(["GET"])


@csrf_protect
@login_required(redirect_field_name="referrer")
def event_startrecord(request):
    if request.method == "POST" and request.is_ajax():
        event_id = request.POST.get("idevent", None)
        broadcaster_id = request.POST.get("idbroadcaster", None)
        broadcaster = Broadcaster.objects.get(pk=broadcaster_id)
        if not check_piloting_conf(broadcaster):
            return JsonResponse({"success": False, "message": "implementation error"})

        if is_recording(broadcaster):
            return JsonResponse({"success": False, "message": "the broadcaster is already recording"})

        if start_record(broadcaster,event_id):
            return JsonResponse({"success": True})

        return JsonResponse({"success": False, "message": ""})

    return HttpResponseNotAllowed(["POST"])


@csrf_protect
@login_required(redirect_field_name="referrer")
def event_splitrecord(request):
    if request.method == "POST" and request.is_ajax():
        broadcaster_id = request.POST.get("idbroadcaster", None)
        broadcaster = Broadcaster.objects.get(pk=broadcaster_id)

        if not check_piloting_conf(broadcaster):
            return JsonResponse({"success": False, "message": "implementation error"})

        if not is_recording(broadcaster):
            return JsonResponse({"success": False, "message": "the broadcaster is not recording"})

        current_record_info = get_info_current_record(broadcaster)
        if split_record(broadcaster):
            return JsonResponse({"success": True,"current_record_info":current_record_info})

        return JsonResponse({"success": False, "message": ""})

    return HttpResponseNotAllowed(["POST"])


@csrf_protect
@login_required(redirect_field_name="referrer")
def event_stoprecord(request):
    if request.method == "POST" and request.is_ajax():
        broadcaster_id = request.POST.get("idbroadcaster", None)
        broadcaster = Broadcaster.objects.get(pk=broadcaster_id)

        if not check_piloting_conf(broadcaster):
            return JsonResponse({"success": False, "message": "implementation error"})

        if not is_recording(broadcaster):
            return JsonResponse({"success": False, "message": "the broadcaster is not recording"})

        current_record_info = get_info_current_record(broadcaster)
        if stop_record(broadcaster):
            return JsonResponse({"success": True,"current_record_info":current_record_info})

        return JsonResponse({"success": False, "message": ""})

    return HttpResponseNotAllowed(["POST"])


def event_video_transform(request):

    event_id = request.POST.get("event", None)

    event = Event.objects.get(pk=event_id)

    currentFile = request.POST.get("currentFile", None)

    filename = os.path.basename(currentFile)

    dest_file = os.path.join(
        settings.MEDIA_ROOT,
        VIDEOS_DIR,
        request.user.owner.hashkey,
        filename,
    )

    dest_path = os.path.join(
        VIDEOS_DIR,
        request.user.owner.hashkey,
        filename,
    )

    os.makedirs(os.path.dirname(dest_file), exist_ok=True)

    os.rename(
        os.path.join(DEFAULT_EVENT_PATH, filename),
        dest_file,
    )

    video = Video.objects.create(
        title=event.title,
        owner=request.user,
        video=dest_path,
        is_draft=True,
        type=Type.objects.get(id=1),
    )
    video.launch_encode = True
    video.save()

    event.videos.add(video)
    event.save()

    videos = event.videos.all()

    video_list = {}
    for video in videos:
        video_list[video.id] = {'id': video.id, 'slug': video.slug, 'title': video.title,
                                'get_absolute_url': video.get_absolute_url()}

    return JsonResponse({"success": True, "videos": video_list})

def get_piloting_implementation(broadcaster) -> Optional[PilotingInterface]:
    logging.debug("get_piloting_implementation")
    piloting_impl = broadcaster.piloting_implementation
    if not piloting_impl:
        logging.debug("'piloting_implementation' value is not set for '" + broadcaster.name + "' broadcaster.")
        return None

    if not piloting_impl.lower() in map(str.lower, BROADCASTER_IMPLEMENTATION):
        logging.warning("'piloting_implementation' : " + piloting_impl + " is not know for '" + broadcaster.name
                        + "' broadcaster. Available piloting_implementations are '"
                        + "','".join(BROADCASTER_IMPLEMENTATION) + "'")
        return None

    if piloting_impl.lower() == "wowza":
        logging.debug("'piloting_implementation' found : " + piloting_impl.lower() + " for '"
                      + broadcaster.name + "' broadcaster.")
        return Wowza(broadcaster)

    logging.debug("->get_piloting_implementation - This should not happen.")
    return None


def check_piloting_conf(broadcaster: Broadcaster) -> bool:
    impl_class = get_piloting_implementation(broadcaster)
    if not impl_class:
        return False
    return impl_class.check_piloting_conf()


def start_record(broadcaster: Broadcaster, event_id) -> bool:
    impl_class = get_piloting_implementation(broadcaster)
    if not impl_class:
        return False
    return impl_class.start(event_id)


def split_record(broadcaster: Broadcaster) -> bool:
    impl_class = get_piloting_implementation(broadcaster)
    if not impl_class:
        return False
    return impl_class.split()


def stop_record(broadcaster: Broadcaster) -> bool:
    impl_class = get_piloting_implementation(broadcaster)
    if not impl_class:
        return False
    return impl_class.stop()

def get_info_current_record(broadcaster: Broadcaster) -> dict:
    impl_class = get_piloting_implementation(broadcaster)
    if not impl_class:
        return {
            'currentFile': '',
            'outputPath': '',
            'segmentDuration': '',
        }
    return impl_class.get_info_current_record()


def is_available_to_record(broadcaster: Broadcaster) -> bool:
    impl_class = get_piloting_implementation(broadcaster)
    if not impl_class:
        return False
    return impl_class.is_available_to_record()


def is_recording(broadcaster: Broadcaster) -> bool:
    impl_class = get_piloting_implementation(broadcaster)
    if not impl_class:
        return False
    return impl_class.is_recording()
