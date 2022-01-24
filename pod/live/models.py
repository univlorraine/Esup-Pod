"""Esup-Pod "live" models."""
from datetime import timedelta, date, datetime

from ckeditor.fields import RichTextField
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.models import User
from django.contrib.auth.models import User
from django.contrib.sites.models import Site
from django.db import models
from django.db.models import Q
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.template.defaultfilters import slugify
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import ugettext_lazy as _
from select2 import fields as select2_fields

from pod.main.models import get_nextautoincrement
from pod.video.models import Video, Type

if getattr(settings, "USE_PODFILE", False):
    from pod.podfile.models import CustomImageModel

    FILEPICKER = True
else:
    FILEPICKER = False
    from pod.main.models import CustomImageModel

DEFAULT_THUMBNAIL = getattr(settings, "DEFAULT_THUMBNAIL", "img/default.svg")
DEFAULT_EVENT_THUMBNAIL = getattr(settings, "DEFAULT_EVENT_THUMBNAIL", "img/default-event.svg")
DEFAULT_EVENT_TYPE_ID = getattr(settings, "DEFAULT_EVENT_TYPE_ID", 1)
RESTRICT_EDIT_VIDEO_ACCESS_TO_STAFF_ONLY = getattr(
    settings, "RESTRICT_EDIT_VIDEO_ACCESS_TO_STAFF_ONLY", False
)


class Building(models.Model):
    name = models.CharField(_("name"), max_length=200, unique=True)
    headband = models.ForeignKey(
        CustomImageModel,
        models.SET_NULL,
        blank=True,
        null=True,
        verbose_name=_("Headband"),
    )
    gmapurl = models.CharField(max_length=250, blank=True, null=True)
    sites = models.ManyToManyField(Site)

    def __str__(self):
        return self.name

    def get_headband_url(self):
        if self.headband:
            return self.headband.file.url
        else:
            thumbnail_url = "".join([settings.STATIC_URL, DEFAULT_THUMBNAIL])
            return thumbnail_url

    class Meta:
        verbose_name = _("Building")
        verbose_name_plural = _("Buildings")
        ordering = ["name"]
        permissions = (
            (
                "view_building_supervisor",
                "Can see the supervisor page for building",
            ),
        )


@receiver(post_save, sender=Building)
def default_site_building(sender, instance, created, **kwargs):
    if len(instance.sites.all()) == 0:
        instance.sites.add(Site.objects.get_current())


def getAvailableBroadcastersOfBuilding(user, building_id):
    return Broadcaster.objects.filter(
        Q(status=True) &
        Q(building_id=building_id) &
        (Q(manage_groups__isnull=True) |
            Q(manage_groups__in=user.groups.all()))
    ).distinct().order_by('name')


def getBuildingHavingAvailableBroadcaster(user):
    return Building.objects.filter(
        Q(broadcaster__status=True) &
        (Q(broadcaster__manage_groups__isnull=True) | Q(broadcaster__manage_groups__in=user.groups.all()))
    ).distinct().order_by('name')


def getBuildingHavingAvailableBroadcasterAnd(user, building_id):
    return Building.objects.filter(
        Q(id=building_id) |
        Q(broadcaster__status=True) &
         (Q(broadcaster__manage_groups__isnull=True) | Q(broadcaster__manage_groups__in=user.groups.all()))
    ).distinct().order_by('name')


class Broadcaster(models.Model):
    name = models.CharField(_("name"), max_length=200, unique=True)
    slug = models.SlugField(
        _("Slug"),
        unique=True,
        max_length=200,
        help_text=_(
            u'Used to access this instance, the "slug" is a short label '
            + "containing only letters, numbers, underscore or dash top."
        ),
        editable=False,
        default="",
    )  # default empty, fill it in save
    building = models.ForeignKey("Building", verbose_name=_("Building"))
    description = RichTextField(_("description"), config_name="complete", blank=True)
    poster = models.ForeignKey(
        CustomImageModel,
        models.SET_NULL,
        blank=True,
        null=True,
        verbose_name=_("Poster"),
    )
    url = models.URLField(_("URL"), help_text=_("Url of the stream"), unique=True)
    video_on_hold = select2_fields.ForeignKey(
        Video,
        help_text=_("This video will be displayed when there is no live stream."),
        blank=True,
        null=True,
        verbose_name=_("Video on hold"),
    )
    iframe_url = models.URLField(
        _("Embedded Site URL"),
        help_text=_("Url of the embedded site to display"),
        null=True,
        blank=True,
    )
    iframe_height = models.IntegerField(
        _("Embedded Site Height"),
        null=True,
        blank=True,
        help_text=_("Height of the embedded site (in pixels)"),
    )
    aside_iframe_url = models.URLField(
        _("Embedded aside Site URL"),
        help_text=_("Url of the embedded site to display on aside"),
        null=True,
        blank=True,
    )
    status = models.BooleanField(
        default=0,
        help_text=_("Check if the broadcaster is currently sending stream."),
    )
    enable_viewer_count = models.BooleanField(
        default=1,
        verbose_name=_(u"Enable viewers count"),
        help_text=_("Enable viewers count on live."),
    )
    is_restricted = models.BooleanField(
        verbose_name=_(u"Restricted access"),
        help_text=_("Live is accessible only to authenticated users."),
        default=False,
    )
    public = models.BooleanField(
        verbose_name=_(u"Show in live tab"),
        help_text=_("Live is accessible from the Live tab"),
        default=True,
    )
    password = models.CharField(
        _("password"),
        help_text=_("Viewing this live will not be possible without this password."),
        max_length=50,
        blank=True,
        null=True,
    )
    viewcount = models.IntegerField(_("Number of viewers"), default=0, editable=False)
    viewers = models.ManyToManyField(User, editable=False)
    # restrict_access_to_groups = select2_fields.ManyToManyField(
    #     AccessGroup,
    #     blank=True,
    #     verbose_name=_("Access Groups"),
    #     help_text=_("Select one or more groups who can access to this broadcater."),
    #     related_name='restrictaccesstogroups',
    # )

    manage_groups = select2_fields.ManyToManyField(
        Group,
        blank=True,
        verbose_name=_("Groups"),
        help_text=_("Select one or more groups who can manage event to this broadcaster."),
        related_name='managegroups'
    )

    piloting_implementation = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name=_("Piloting implementation"),
        help_text=_("Select the piloting implementation for to this broadcaster."),
    )

    piloting_conf = models.TextField(
        null=True,
        blank=True,
        verbose_name=_("Piloting configuration parameters"),
        help_text=_("Add piloting configuration parameters in Json format."),
    )

    def get_absolute_url(self):
        return reverse("live:video_live", args=[str(self.slug)])

    def __str__(self):
        return "%s - %s" % (self.name, self.url)

    def get_poster_url(self):
        if self.poster:
            return self.poster.file.url
        else:
            thumbnail_url = "".join([settings.STATIC_URL, DEFAULT_THUMBNAIL])
            return thumbnail_url

    def save(self, *args, **kwargs):
        self.slug = slugify(self.name)
        super(Broadcaster, self).save(*args, **kwargs)

    class Meta:
        verbose_name = _("Broadcaster")
        verbose_name_plural = _("Broadcasters")
        ordering = ["building", "name"]

    @property
    def sites(self):
        return self.building.sites


class HeartBeat(models.Model):
    user = models.ForeignKey(User, null=True, verbose_name=_("Viewer"))
    viewkey = models.CharField(_("Viewkey"), max_length=200, unique=True)
    broadcaster = models.ForeignKey(
        Broadcaster, null=False, verbose_name=_("Broadcaster")
    )
    last_heartbeat = models.DateTimeField(_("Last heartbeat"), default=timezone.now)

    class Meta:
        verbose_name = _("Heartbeat")
        verbose_name_plural = _("Heartbeats")
        ordering = ["broadcaster"]


def one_hour_hence():
    return datetime.now() + timezone.timedelta(hours=1)


def get_default_event_type():
    return Type.objects.get(id=DEFAULT_EVENT_TYPE_ID).id


def select_event_owner():
    if RESTRICT_EDIT_VIDEO_ACCESS_TO_STAFF_ONLY:
        return lambda q: (
            Q(is_staff=True) & (Q(first_name__icontains=q) | Q(last_name__icontains=q))
        ) & Q(owner__sites=Site.objects.get_current())
    else:
        return lambda q: (Q(first_name__icontains=q) | Q(last_name__icontains=q)) & Q(
            owner__sites=Site.objects.get_current()
        )


class Event(models.Model):
    slug = models.SlugField(
        _("Slug"),
        unique=True,
        max_length=255,
        editable=False,
    )

    title = models.CharField(
        _("Title"),
        max_length=250,
        help_text=_(
            "Please choose a title as short and accurate as "
            "possible, reflecting the main subject / context "
            "of the content.(max length: 250 characters)"
        ),
    )

    description = RichTextField(
        _("Description"),
        config_name="complete",
        blank=True,
        help_text=_(
            "In this field you can describe your content, "
            "add all needed related information, and "
            "format the result using the toolbar."
        ),
    )

    owner = select2_fields.ForeignKey(
        User,
        ajax=True,
        verbose_name=_("Owner"),
        search_field=select_event_owner(),
        on_delete=models.CASCADE,
    )
    start_date = models.DateField(
        _("Date of Event"),
        default=date.today,
        help_text=_("Start date of the live."),
    )
    start_time = models.TimeField(
        _("Start time"),
        default=datetime.now,
        help_text=_("Start time of the live event."),
    )
    end_time = models.TimeField(
        _("End time"),
        default=one_hour_hence,
        help_text=_("End time of the live event."),
    )

    broadcaster = models.ForeignKey(
        Broadcaster,
        verbose_name=_("Broadcaster"),
        help_text=_(
            "If this box is checked, "
            "the video will be visible and accessible only by you "
            "and the additional owners."
        ),
    )

    type = models.ForeignKey(
        Type,
        default=get_default_event_type,
        verbose_name=_("Type")
    )

    is_draft = models.BooleanField(
        verbose_name=_("Draft"),
        help_text=_(
            "If this box is checked, "
            "the video will be visible and accessible only by you "
            "and the additional owners."
        ),
        default=True,
    )
    is_restricted = models.BooleanField(
        verbose_name=_("Restricted access"),
        help_text=_(
            "If this box is checked, "
            "the video will only be accessible to authenticated users."
        ),
        default=False,
    )

    # password = models.CharField(
    #     _("password"),
    #     help_text=_("Viewing this video will not be possible without this password."),
    #     max_length=50,
    #     blank=True,
    #     null=True,
    # )

    videos = models.ManyToManyField(
        Video,
        editable=False,
    )

    class Meta:
        verbose_name = _("Event")
        verbose_name_plural = _("Events")
        ordering = ["start_date", "start_time"]

    def save(self, *args, **kwargs):
        if not self.id:
            try:
                new_id = get_nextautoincrement(Event)
            except Exception:
                try:
                    new_id = Event.objects.latest("id").id
                    new_id += 1
                except Exception:
                    new_id = 1
        else:
            new_id = self.id
        new_id = "%04d" % new_id
        self.slug = "%s-%s" % (new_id, slugify(self.title))
        super(Event, self).save(*args, **kwargs)

    def __str__(self):
        if self.id:
            return "%s - %s" % ("%04d" % self.id, self.title)
        else:
            return "None"

    def get_absolute_url(self):
        return reverse("live:event", args=[str(self.slug)])

    @property
    def is_current(self):
        return self.start_date == date.today() and (self.start_time <= datetime.now().time() <= self.end_time)

    @property
    def is_past(self):
        return self.start_date < date.today() or (
                    self.start_date == date.today() and self.end_time < datetime.now().time())

    @property
    def is_coming(self):
        return self.start_date > date.today() or (
                    self.start_date == date.today() and datetime.now().time() < self.start_time)
