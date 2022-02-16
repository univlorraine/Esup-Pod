import json
import os.path
import re
import logging
from datetime import date, datetime, timedelta
from time import sleep
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
    HttpResponseNotFound, Http404, HttpResponseServerError
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import ugettext_lazy as _
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_protect

from pod.bbb.models import Livestream
from .forms import LivePasswordForm, EventForm, EventDeleteForm
from .models import Building, Broadcaster, HeartBeat, Event, get_available_broadcasters_of_building
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

logger = logging.getLogger("pod.live")


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

def get_event_access(request, event, slug_private):
    """Return True if access is granted to current user."""
    is_draft = event.is_draft
    is_restricted = event.broadcaster.is_restricted
    is_restricted_to_group = False
    #is_restricted_to_group = video.restrict_access_to_groups.all().exists()

    is_access_protected = (
        is_draft
        or is_restricted
       # or is_restricted_to_group
    )
    if is_access_protected:
        access_granted_for_private = slug_private and slug_private == event.get_hashkey()
        access_granted_for_draft = request.user.is_authenticated() and (
            request.user == event.owner
            or request.user in event.additional_owners.all()
            or request.user.is_superuser
            or request.user.has_perm("live.view_event")
           # or (request.user in video.additional_owners.all())
        )
        access_granted_for_restricted = (
            request.user.is_authenticated() and not is_restricted_to_group
        )
        # access_granted_for_group = (
        #     (request.user.is_authenticated() and is_in_video_groups(request.user, video))
        #     or request.user == video.owner
        #     or request.user.is_superuser
        #     or request.user.has_perm("live.view_event")
        #     or (request.user in video.additional_owners.all())
        # )

        return (
            access_granted_for_private
            or (is_draft and access_granted_for_draft)
            or (is_restricted and access_granted_for_restricted)
            #or (is_restricted_to_group and access_granted_for_group)
        )
    else:
        return True

def event(request, slug, slug_private=None):  # affichage d'un event

    # modif de l'url d'appel pour compatibilité avec le template link_video.html (variable : urleditapp)
    request.resolver_match.namespace = ""

    event = get_object_or_404(Event, slug=slug)

    if event.broadcaster.is_restricted and not request.user.is_authenticated():
        url = reverse("authentication_login")
        url += "?referrer=" + request.get_full_path()
        return redirect(url)

    if not get_event_access(request, event, slug_private):
        #return render(request, "live/event.html", {"access_not_allowed": True})
        messages.add_message(
            request, messages.ERROR, _("You cannot watch this event.")
        )
        raise PermissionDenied

    need_piloting_buttons = False
    if ((event.owner == request.user or request.user in event.additional_owners.all()) and (not RESTRICT_EDIT_EVENT_ACCESS_TO_STAFF_ONLY or
                                         (RESTRICT_EDIT_EVENT_ACCESS_TO_STAFF_ONLY and request.user.is_staff))) \
            or request.user.is_superuser:
        need_piloting_buttons = True

    return render(
        request,
        "live/event.html",
        {
            "event": event,
            "need_piloting_buttons": need_piloting_buttons,
            "heartbeat_delay": HEARTBEAT_DELAY,
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
            "display_broadcaster_name": False,
        }
    )


@csrf_protect
@ensure_csrf_cookie
@login_required(redirect_field_name="referrer")
def my_events(request):
    queryset = request.user.event_set

    queryset = request.user.event_set.all() \
               | request.user.owners_events.all()


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
            "display_broadcaster_name": True,
        }
    )

def get_event_edition_access(request, event):
    if request.user.is_superuser :
        return True
    if event is None:#creation
        if request.user.has_perm("live.add_event") \
            or (RESTRICT_EDIT_EVENT_ACCESS_TO_STAFF_ONLY and request.user.is_staff) \
            or (not RESTRICT_EDIT_EVENT_ACCESS_TO_STAFF_ONLY and request.user.is_authenticated):
            return True
    else:#edition
        if request.user.has_perm("live.change_event") \
            or request.user == event.owner \
            or request.user in event.additional_owners.all():
            return True
    return False


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
    if not get_event_edition_access(request, event):
        return render(request, "live/event_edit.html", {"access_not_allowed": True})

    form = EventForm(
        request.POST or None,
        instance=event,
        user=request.user,
        is_current_event=event.is_current() if slug else None
    )

    if request.POST:
        form = EventForm(
            request.POST,
            instance=event,
            user=request.user,
            is_current_event=event.is_current() if slug else None
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
        request.user.is_superuser or request.user.has_perm("live.delete_event")
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
    broadcasters = get_available_broadcasters_of_building(request.user, build.id)

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
def ajax_event_startrecord(request):
    if request.method == "POST" and request.is_ajax():

        event_id = request.POST.get("idevent", None)
        broadcaster_id = request.POST.get("idbroadcaster", None)
        return event_startrecord(event_id, broadcaster_id)

    return HttpResponseNotAllowed(["POST"])

def event_startrecord(event_id, broadcaster_id):
    broadcaster = Broadcaster.objects.get(pk=broadcaster_id)
    if not check_piloting_conf(broadcaster):
        return JsonResponse({"success": False, "message": "implementation error"})

    if is_recording(broadcaster):
        return JsonResponse({"success": False, "message": "the broadcaster is already recording"})

    if start_record(broadcaster, event_id):
        return JsonResponse({"success": True})

    return JsonResponse({"success": False, "message": ""})


@csrf_protect
@login_required(redirect_field_name="referrer")
def ajax_event_splitrecord(request):
    if request.method == "POST" and request.is_ajax():
        event_id = request.POST.get("idevent", None)
        broadcaster_id = request.POST.get("idbroadcaster", None)

        return event_splitrecord(event_id, broadcaster_id)

    return HttpResponseNotAllowed(["POST"])


def event_splitrecord(event_id, broadcaster_id):
    broadcaster = Broadcaster.objects.get(pk=broadcaster_id)

    if not check_piloting_conf(broadcaster):
        return JsonResponse({"success": False, "error": "implementation error"})

    if not is_recording(broadcaster):
        return JsonResponse({"success": False, "error": "the broadcaster is not recording"})

    # file infos before split is done
    current_record_info = get_info_current_record(broadcaster)

    if split_record(broadcaster):
        return event_video_transform(event_id, current_record_info.get("currentFile", None),
                                     current_record_info.get("segmentNumber", None))

    return JsonResponse({"success": False, "error": ""})

@csrf_protect
@login_required(redirect_field_name="referrer")
def ajax_event_stoprecord(request):
    if request.method == "POST" and request.is_ajax():
        event_id = request.POST.get("idevent", None)
        broadcaster_id = request.POST.get("idbroadcaster", None)
        return event_stoprecord(event_id, broadcaster_id)

    return HttpResponseNotAllowed(["POST"])


def event_stoprecord(event_id, broadcaster_id):
    broadcaster = Broadcaster.objects.get(pk=broadcaster_id)

    if not check_piloting_conf(broadcaster):
        return JsonResponse({"success": False, "error": "implementation error"})

    if not is_recording(broadcaster):
        return JsonResponse({"success": False, "error": "the broadcaster is not recording"})

    current_record_info = get_info_current_record(broadcaster)

    if stop_record(broadcaster):
        return event_video_transform(event_id, current_record_info.get("currentFile", None),
                                     current_record_info.get("segmentNumber", None))

    return JsonResponse({"success": False, "error": ""})


@login_required(redirect_field_name="referrer")
def ajax_event_info_record(request):
    if request.method == "POST" and request.is_ajax():
        event_id = request.POST.get("idevent", None)
        broadcaster_id = request.POST.get("idbroadcaster", None)
        return event_info_record(event_id, broadcaster_id)

    return HttpResponseNotAllowed(["POST"])

def event_info_record(event_id, broadcaster_id):
    broadcaster = Broadcaster.objects.get(pk=broadcaster_id)

    if not check_piloting_conf(broadcaster):
        return JsonResponse({"success": False, "error": "implementation error"})

    if not is_recording(broadcaster):
        return JsonResponse({"success": False, "error": "the broadcaster is not recording"})

    current_record_info = get_info_current_record(broadcaster)

    if current_record_info.get("segmentDuration")!="":
        return JsonResponse({"success": True, "duration": int((timedelta(milliseconds=current_record_info.get("segmentDuration"))).total_seconds())})

    return JsonResponse({"success": False, "error": ""})


@csrf_protect
def event_get_video_cards(request):
    if request.is_ajax():
        event_id = request.GET.get("idevent", None)
        event = Event.objects.get(pk=event_id)

        html = ""
        if event.videos.count() > 0:
            request.resolver_match.namespace = ""
            html = render_to_string('live/event_videos.html', {'event': event}, request=request)
        return JsonResponse({"content": html})

    return HttpResponseBadRequest


def event_video_transform(event_id, current_file, segment_number):
    live_event = Event.objects.get(pk=event_id)

    filename = os.path.basename(current_file)

    dest_file = os.path.join(
        settings.MEDIA_ROOT,
        VIDEOS_DIR,
        live_event.owner.owner.hashkey,
        filename,
    )

    dest_path = os.path.join(
        VIDEOS_DIR,
        live_event.owner.owner.hashkey,
        filename,
    )

    # dir creation if not exists
    dest_dir_name = os.path.dirname(dest_file)
    os.makedirs(dest_dir_name, exist_ok=True)

    try :
        checkDirExists(dest_dir_name)
    except:
        return JsonResponse(status=500, data={"success": False, "error": f"Dir: {dest_dir_name} does not exists"})

    # file creation if not exists
    full_file_name = os.path.join(DEFAULT_EVENT_PATH, filename)

    try :
        checkFileExists(full_file_name)
    except:
        return JsonResponse(status=500, data={"success": False, "error": f"File: {full_file_name} does not exists"})

    # verif si la taille du fichier d'origine ne bouge plus
    try :
        checkFileSize(full_file_name)
    except:
        return JsonResponse(status=500, data={"success": False, "error": "check file to copy aborted"})

    # moving the file
    try:
        os.rename(
            full_file_name,
            dest_file,
        )
    except FileNotFoundError as err:
        logger.error(f"FileNotFoundError: {format(err)}")
        return JsonResponse(status=500, data={"success": False, "error": f"FileNotFoundError: {format(err)}"})

    # verif si la taille du fichier copié ne bouge plus
    try :
        checkFileSize(dest_file)
    except:
        return JsonResponse(status=500, data={"success": False, "error": "check file moved aborted"})

    segment = "(" + segment_number + ")" if segment_number else ""

    video = Video.objects.create(
        video=dest_path,
        title=live_event.title + segment,
        owner=live_event.owner,
        description=live_event.description + "<br/>" + _("Record the %(start_date)s from %(start_time)s to %(end_time)s")
                    % {'start_date': live_event.start_date.strftime("%d/%m/%Y"),
                       'start_time': live_event.start_time.strftime("%H:%M"),
                       'end_time': live_event.end_time.strftime("%H:%M")},
        is_draft=live_event.is_draft,
        type=live_event.type,
    )
    video.launch_encode = True
    video.save()

    live_event.videos.add(video)
    live_event.save()

    videos = live_event.videos.all()

    video_list = {}
    for video in videos:
        video_list[video.id] = {
            'id': video.id,
            'slug': video.slug,
            'title': video.title,
            'get_absolute_url': video.get_absolute_url(),
        }

    return JsonResponse({"success": True, "videos": video_list})

def checkFileSize(full_file_name, max_attempt = 6):
    file_size = os.path.getsize(full_file_name)
    size_match = False

    attempt_number = 1
    while not size_match and attempt_number <= max_attempt:
        # if attempt_number > 1:
        sleep(0.5)
        new_size = os.path.getsize(full_file_name)
        if file_size != new_size:
            logger.warning(f"File size changing from {file_size} to {new_size}, attempt number {attempt_number} ")
            file_size = new_size
            attempt_number = attempt_number + 1
            if attempt_number == max_attempt:
                logger.error(f"File: {full_file_name} is still changing")
                raise Exception("checkFileSize aborted")
        else:
            logger.info("Size checked")
            size_match = True


def checkDirExists(dest_dir_name, max_attempt = 6):

    attempt_number = 1
    while not os.path.isdir(dest_dir_name) and attempt_number <= max_attempt:
        logger.warning(f"Dir does not exists, attempt number {attempt_number} ")

        if attempt_number == max_attempt:
            logger.error(f"Impossible to create dir {dest_dir_name}")
            raise Exception("Dir creation aborted")

        attempt_number = attempt_number + 1
        sleep(0.5)

    logger.info("Dir exists")


def checkFileExists(full_file_name, max_attempt = 6):

    attempt_number = 1
    while not os.path.exists(full_file_name) and attempt_number <= max_attempt:
        logger.warning(f"File does not exists, attempt number {attempt_number} ")

        if attempt_number == max_attempt:
            logger.error(f"Impossible to get file {full_file_name}")
            raise Exception(f"File {full_file_name} is nowhere")

        attempt_number = attempt_number + 1
        sleep(0.5)

    logger.info("File exists")


def get_piloting_implementation(broadcaster) -> Optional[PilotingInterface]:
    logger.debug("get_piloting_implementation")
    piloting_impl = broadcaster.piloting_implementation
    if not piloting_impl:
        logger.info("'piloting_implementation' value is not set for '" + broadcaster.name + "' broadcaster.")
        return None

    if not piloting_impl.lower() in map(str.lower, BROADCASTER_IMPLEMENTATION):
        logger.warning("'piloting_implementation' : " + piloting_impl + " is not know for '" + broadcaster.name
                        + "' broadcaster. Available piloting_implementations are '"
                        + "','".join(BROADCASTER_IMPLEMENTATION) + "'")
        return None

    if piloting_impl.lower() == "wowza":
        logger.debug("'piloting_implementation' found : " + piloting_impl.lower() + " for '"
                      + broadcaster.name + "' broadcaster.")
        return Wowza(broadcaster)

    logger.warning("->get_piloting_implementation - This should not happen.")
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
            'segmentNumber': '',
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
