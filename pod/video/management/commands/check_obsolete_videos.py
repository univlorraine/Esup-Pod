"""Esup-Pod - Check for obsolete videos.

*  run with 'python manage.py check_obsolete_videos [--dry]'
"""

from datetime import date, timedelta

from django.conf import settings
from django.contrib.sites.shortcuts import get_current_site

# from django.core.mail import mail_admins
from django.core.mail import mail_managers, send_mail
from django.core.management.base import BaseCommand, CommandError
from django.http import request
from django.template.defaultfilters import striptags
from django.urls import reverse
from django.utils import translation
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from pod.video.models import Video
from pod.video.utils import archive_video, is_archiving_authorized, write_in_csv

ENABLE_PAGE_OBSO_MAIL = getattr(settings, "ENABLE_PAGE_OBSO_MAIL", False)
PROLONGATION_GRANTED = getattr(settings, "PROLONGATION_GRANTED", False)
DELETION_GRANTED = getattr(settings, "DELETION_GRANTED", False)

USE_OBSOLESCENCE = getattr(settings, "USE_OBSOLESCENCE", False)
USE_ESTABLISHMENT = getattr(settings, "USE_ESTABLISHMENT_FIELD", False)
MANAGERS = getattr(settings, "MANAGERS", [])
CONTACT_US_EMAIL = getattr(
    settings,
    "CONTACT_US_EMAIL",
    [mail for name, mail in MANAGERS],
)

SECURE_SSL_REDIRECT = getattr(settings, "SECURE_SSL_REDIRECT", False)
URL_SCHEME = "https" if SECURE_SSL_REDIRECT else "http"

##
# Settings exposed in templates
#
TEMPLATE_VISIBLE_SETTINGS = getattr(
    settings,
    "TEMPLATE_VISIBLE_SETTINGS",
    {
        "TITLE_SITE": "Pod",
        "TITLE_ETB": "University name",
        "LOGO_SITE": "img/logoPod.svg",
        "LOGO_ETB": "img/esup-pod.svg",
        "LOGO_PLAYER": "img/pod_favicon.svg",
        "LINK_PLAYER": "",
        "LINK_PLAYER_NAME": _("Home"),
        "FOOTER_TEXT": ("",),
        "FAVICON": "img/pod_favicon.svg",
        "CSS_OVERRIDE": "",
        "PRE_HEADER_TEMPLATE": "",
        "POST_FOOTER_TEMPLATE": "",
        "TRACKING_TEMPLATE": "",
    },
)
__TITLE_SITE__ = (
    TEMPLATE_VISIBLE_SETTINGS["TITLE_SITE"]
    if (TEMPLATE_VISIBLE_SETTINGS.get("TITLE_SITE"))
    else "Pod"
)
DEFAULT_FROM_EMAIL = getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@univ.fr")
ARCHIVE_OWNER_USERNAME = getattr(settings, "ARCHIVE_OWNER_USERNAME", "archive")
# number of step in days defore deletion
WARN_DEADLINES = getattr(settings, "WARN_DEADLINES", [60, 30, 7])
LANGUAGE_CODE = getattr(settings, "LANGUAGE_CODE", "fr")


class Command(BaseCommand):
    """Checking obsolete videos."""

    help = "Treatment of obsolete videos."
    dry_mode = False

    def add_arguments(self, parser) -> None:
        """Add possible args to the command."""
        parser.add_argument(
            "--dry",
            help="Simulate what would be done.",
            action="store_true",
            default=False,
        )

    def handle(self, *args, **options) -> None:
        """Handle the check_obsolete_videos command call."""
        if options["dry"]:
            self.dry_mode = True
            print("Simulation mode ('dry'). Nothing will be deleted.")

        # Activate a fixed locale fr
        translation.activate(LANGUAGE_CODE)

        if USE_OBSOLESCENCE:
            # Notify users for videos with close deadlines
            list_video = self.get_video_treatment_and_notify_user()
            self.notify_manager_of_obsolete_video(list_video)

            # Archive and delete videos with past deadlines
            (
                list_video_deleted,
                list_video_archived,
            ) = self.get_video_archived_deleted_treatment()
            self.notify_manager_of_deleted_video(list_video_deleted)
            self.notify_manager_of_archived_video(list_video_archived)
        else:
            self.stderr.write(self.style.ERROR(_("An Error occurred while processing.")))
            raise CommandError(_("USE_OBSOLESCENCE is FALSE"))

    def get_video_treatment_and_notify_user(self) -> dict:
        """Check video with close deadlines to send email to each owner."""
        list_video_notified_by_establishment = {"other": {}}

        site = get_current_site(settings.SITE_ID)
        managers = dict(MANAGERS) if MANAGERS else {}
        use_estab = bool(USE_ESTABLISHMENT and managers)

        # Group videos per recipient (owner email + additional owners emails),
        # then per deadline (step_day) to send a single mail by recipient.
        notifications: dict = {}

        for step_day in sorted(WARN_DEADLINES):
            step_date = date.today() + timedelta(days=step_day)
            videos = Video.objects.filter(date_delete=step_date, sites=site)

            for video in videos:
                notifications = self.collect_user_notification(
                    notifications, video, step_day
                )

                estab_key = "other"
                if use_estab:
                    try:
                        estab = video.owner.owner.establishment.lower()
                    except Exception:
                        estab = ""
                    if estab in managers:
                        estab_key = estab

                list_video_notified_by_establishment.setdefault(estab_key, {})
                list_video_notified_by_establishment[estab_key].setdefault(
                    str(step_day), []
                ).append(video)

        if not self.dry_mode:
            self.notify_users_from_collection(notifications)

        return list_video_notified_by_establishment

    def collect_user_notification(
        self, notifications: dict, video: Video, step_day: int
    ) -> dict:
        """Add a video to the per-recipient pending notifications."""
        owners = [(video.owner, False)]
        for additional in video.additional_owners.all():
            owners.append((additional, True))

        for user, is_additional in owners:
            if not user.email:
                continue
            notifications.setdefault(user.email, {})
            notifications[user.email].setdefault("name", self.user_full_name(user))
            notifications[user.email].setdefault(str(step_day), [])
            notifications[user.email][str(step_day)].append((video, is_additional))
        return notifications

    @staticmethod
    def user_full_name(user) -> str:
        """Return the display name of a user."""
        return user.last_name + " " + user.first_name

    def notify_users_from_collection(self, notifications: dict) -> None:
        """Send a single aggregated mail per recipient."""
        for email, data in notifications.items():
            self.notify_user_aggregated(email, data)

    def get_user_aggregated_videos(self, data: dict) -> dict:
        """Return a dict of videos aggregated per deadline for a recipient."""
        aggregated = {}
        for step_day, entries in data.items():
            if step_day == "name":
                continue
            aggregated[step_day] = []
            for video, is_additional in entries:
                aggregated[step_day].append((video, is_additional))
        return aggregated

    def get_video_archived_deleted_treatment(self):  # tuple[dict, dict]
        """Get video with deadline out of time and delete them."""
        vids = Video.objects.filter(
            sites=get_current_site(None), date_delete__lt=date.today()
        ).exclude(owner__username=ARCHIVE_OWNER_USERNAME)

        managers = dict(MANAGERS) if MANAGERS else {}
        use_estab = bool(USE_ESTABLISHMENT and managers)

        # "0" is for the WARN DEADLINE "now"
        list_video_deleted_by_establishment = {"other": {"0": []}}
        list_video_archived_by_establishment = {"other": {"0": []}}
        nb_deleted = 0
        nb_archived = 0

        # Group notifications per recipient (owner + additional owners), split
        # into "archived" and "deleted" sub-lists, to send one mail by user.
        notifications = {}

        for vid in vids:
            title = "%s - %s" % (vid.id, vid.title)
            estab = vid.owner.owner.establishment.lower()

            # Collect recipients (owner + additional owners) BEFORE archiving
            # or deleting, since the owner may change on archive and the object
            # is removed on delete.
            recipients = self.get_video_recipients(vid)

            if is_archiving_authorized(vid):
                if not self.dry_mode:
                    archive_video(vid)

                nb_archived += 1
                if not (use_estab and estab in managers):
                    estab = "other"
                list_video_archived_by_establishment.setdefault(estab, {})
                list_video_archived_by_establishment[estab].setdefault(str(0), []).append(
                    vid
                )

                for user, is_additional in recipients:
                    notifications.setdefault(user.email, {})
                    notifications[user.email].setdefault("name", self.user_full_name(user))
                    notifications[user.email].setdefault("archived", [])
                    notifications[user.email]["archived"].append((vid, is_additional))

            else:
                if not self.dry_mode:
                    write_in_csv(vid, "deleted")
                    vid.delete()
                else:
                    print("Video %s would have been deleted." % vid)
                nb_deleted += 1
                if not (use_estab and estab in managers):
                    estab = "other"
                list_video_deleted_by_establishment.setdefault(estab, {})
                list_video_deleted_by_establishment[estab].setdefault(str(0), []).append(
                    title
                )

                # The video object no longer exists, so keep only the title.
                for user, is_additional in recipients:
                    notifications.setdefault(user.email, {})
                    notifications[user.email].setdefault("name", self.user_full_name(user))
                    notifications[user.email].setdefault("deleted", [])
                    notifications[user.email]["deleted"].append((title, is_additional))

        print(_("%s video(s) deleted.") % nb_deleted)
        print(_("%s video(s) archived.") % nb_archived)

        if not self.dry_mode:
            self.notify_users_of_archived_deleted(notifications)

        return (
            list_video_deleted_by_establishment,
            list_video_archived_by_establishment,
        )

    def get_video_recipients(self, video: Video) -> list:
        """Return the (user, is_additional) recipients of a video that have a mail."""
        recipients = [(video.owner, False)]
        for additional in video.additional_owners.all():
            recipients.append((additional, True))
        return [(user, is_add) for user, is_add in recipients if user.email]

    def notify_users_of_archived_deleted(self, notifications: dict) -> None:
        """Send a single aggregated mail per recipient on archiving/deleting."""
        for email, data in notifications.items():
            self.notify_user_archived_deleted(email, data)

    def notify_user_archived_deleted(self, email: str, data: dict) -> int:
        """Send a single mail to a user listing archived and deleted videos."""
        name = data.get("name", email)
        archived = data.get("archived", [])
        deleted = data.get("deleted", [])
        nb_videos = len(archived) + len(deleted)

        msg_html = _("Hello %(name)s,") % {"name": name}
        msg_html += "<br>\n<p>" + ngettext(
            "Your video has reached its deletion deadline.",
            "Your videos have reached their deletion deadline.",
            nb_videos,
        ) + "</p>\n"

        if archived:
            msg_html += "\n<p><strong>" + _("Archived videos:") + "</strong></p>\n<ul>"
            for video, is_additional in archived:
                tag = " " + _("(additional owner)") if is_additional else ""
                msg_html += (
                    "\n<li>%(title)s ("
                    + "<a href='%(scheme)s:%(url)s' rel='noopener'"
                    + " target='_blank'>%(scheme)s:%(url)s</a>)"
                    + "%(tag)s.</li>"
                ) % {
                    "scheme": URL_SCHEME,
                    "url": video.get_full_url(),
                    "title": video,
                    "tag": tag,
                }
            msg_html += "</ul>"

        if deleted:
            msg_html += "\n<p><strong>" + _("Deleted videos:") + "</strong></p>\n<ul>"
            for title, is_additional in deleted:
                tag = " " + _("(additional owner)") if is_additional else ""
                msg_html += "\n<li>%(title)s%(tag)s.</li>" % {
                    "title": title,
                    "tag": tag,
                }
            msg_html += "</ul>"

        msg_html += "\n<p>" + _("Regards") + "</p>\n"

        print(
            _("Sending archiving/deletion mail to %(email)s for %(nb)s video(s).")
            % {"email": email, "nb": len(archived) + len(deleted)}
        )

        return send_mail(
            "[%s] %s"
            % (
                __TITLE_SITE__,
                _("Your videos have reached their deletion deadline"),
            ),
            striptags(msg_html),
            DEFAULT_FROM_EMAIL,
            [email],
            fail_silently=False,
            html_message=msg_html,
        )

    def notify_user(self, video: Video, step_day: int) -> int:
        """Notify a user that his video will be deleted soon."""
        notifications = self.collect_user_notification({}, video, step_day)
        for email, data in notifications.items():
            self.notify_user_aggregated(email, data)
        return 1 if notifications else 0

    def notify_user_aggregated(self, email: str, data: dict) -> int:
        """Send a single aggregated mail to a recipient for his obsolete videos."""
        name = data.get("name", email)
        aggregated_videos = self.get_user_aggregated_videos(data)
        nb_videos = sum(len(entries) for entries in aggregated_videos.values())

        has_staff = any(
            video.owner.is_staff
            for entries in aggregated_videos.values()
            for video, _ in entries
        )

        # Build the "action" block once, using the first video as a reference
        # for dates/urls displayed within the aggregated list.
        first_video = next(
            (
                video
                for entries in aggregated_videos.values()
                for video, _ in entries
            ),
            None,
        )

        msg_html = _("Hello %(name)s,") % {"name": name}
        msg_html += "<br>\n"
        msg_html += "<p>" + ngettext(
            "The following video will soon arrive at the deletion deadline and "
            + "will be unpublished on the date indicated.",
            "The following videos will soon arrive at the deletion deadline and "
            + "will be unpublished on the indicated dates.",
            nb_videos,
        ) + "</p>"

        if ENABLE_PAGE_OBSO_MAIL and first_video is not None:
            msg_html += self.get_page_obso_mail_block(first_video)
        else:
            msg_html += "\n<p>"
            if has_staff:
                msg_html += ngettext(
                    "If you want to keep it, "
                    + "you can change the removal date "
                    + "by editing your video:",
                    "If you want to keep them, "
                    + "you can change the removal date "
                    + "by editing your videos:",
                    nb_videos,
                )
                msg_html += (
                    "\n"
                    + '<a href="%(scheme)s:%(url)s" '
                    + 'rel="noopener" target="_blank">'
                    + "%(scheme)s:%(url)s</a>"
                ) % {"scheme": URL_SCHEME, "url": first_video.get_full_url()}
            else:
                msg_html += _(
                    "If you want to keep them, "
                    + "please contact the manager(s) in charge of your "
                    + "establishment at this address(es): %(email_address)s."
                ) % {"email_address": ", ".join(self.get_manager_emails(first_video))}

        msg_html += self.get_aggregated_list_video_html(aggregated_videos)

        msg_html += "\n<p>" + _("Regards") + "</p>\n"

        print(
            _("Sending aggregated mail to %(email)s for %(nb)s video(s).")
            % {"email": email, "nb": nb_videos}
        )

        return send_mail(
            "[%s] %s"
            % (
                __TITLE_SITE__,
                ngettext(
                    "Your video will be obsolete soon",
                    "Your videos will be obsolete soon",
                    nb_videos,
                ),
            ),
            striptags(msg_html),
            DEFAULT_FROM_EMAIL,
            [email],
            fail_silently=False,
            html_message=msg_html,
        )

    def get_aggregated_list_video_html(self, aggregated_videos: dict) -> str:
        """Generate the list of videos grouped by deadline for a recipient."""
        msg_html = ""
        base_url = ""
        if ENABLE_PAGE_OBSO_MAIL:
            domain = get_current_site(request).domain
            base_url = f"{URL_SCHEME}://{domain}"
        for i, step_day in enumerate(sorted(aggregated_videos, key=int)):
            msg_html += "<p><strong>"
            msg_html += _("In %(deadline)s days:") % {"deadline": step_day}
            msg_html += "</strong></p>\n<ul>"
            for video, is_additional in aggregated_videos[step_day]:
                tag = (
                    " "
                    + _("(additional owner)")
                    if is_additional
                    else ""
                )
                msg_html += "\n<li>"
                msg_html += (
                    "<strong>%(title)s</strong> %(tag)s("
                    + "<a href='%(scheme)s:%(url)s' rel='noopener'"
                    + " target='_blank'>%(scheme)s:%(url)s</a>)"
                    + " %(date)s"
                ) % {
                    "scheme": URL_SCHEME,
                    "url": video.get_full_url(),
                    "title": video,
                    "date": video.date_delete,
                    "tag": tag,
                }
                if ENABLE_PAGE_OBSO_MAIL:
                    respite_url = reverse("video:video_respite", args=(video.slug,))
                    msg_html += (
                        '=> <a href="%s%s">%s</a>'
                        % (base_url, respite_url, _("Choose an action for my video"))
                    )
                msg_html += "</li>"
            msg_html += "</ul>"
        return msg_html

    def get_page_obso_mail_block(self, video: Video) -> str:
        """Return the html options block used when ENABLE_PAGE_OBSO_MAIL is on."""
        custom_message_page_obso_mail = "<p>%s</p>" % _(
            "You can choose to do an action on your videos:"
        )
        custom_message_page_obso_mail += self.html_options(video)
        custom_message_page_obso_mail += "<p>%s</p>" % _(
            "Unless you take action, your videos will be archived (unpublished) and may be deleted."
        )
        return custom_message_page_obso_mail

    def html_options(self, video):
        options = []
        if is_archiving_authorized(video):
            options.append(
                _("archive it (it will be unpublished and no longer accessible)")
            )

        if PROLONGATION_GRANTED:
            options.append(_("postpone it’s deletion date"))

        if DELETION_GRANTED:
            options.append(_("delete it (after saving it)"))
        options.append(_("download it along with all its associated data"))

        return "<ul><li>%s</li></ul>" % "</li><li>".join(options)

    def notify_manager_of_obsolete_video(self, list_video: dict) -> None:
        """Notify manager(s) with a list of obsolete videos."""
        for estab in list_video:
            # list_video[estab] has entries for each WARN_DEADLINE
            total = sum(len(videos) for videos in list_video[estab].values())
            if total > 0:
                if estab != "other":
                    msg_html = _("Hello manager(s) of %(estab)s on %(site_title)s,") % {
                        "estab": estab,
                        "site_title": __TITLE_SITE__,
                    }
                else:
                    msg_html = _("Hello manager(s) of %(site_title)s,") % {
                        "site_title": __TITLE_SITE__
                    }
                msg_html += (
                    "<br>\n<p>"
                    + _(
                        "For your information, "
                        + "below is the list of videos that will soon reach "
                        + "the deletion deadline."
                    )
                    + "</p>"
                )
                msg_html += "\n<p>"
                msg_html += self.get_list_video_html(list_video[estab], False)
                msg_html += "\n</p>"
                msg_html += "\n<p>" + _("Regards") + "</p>\n"

                subject = _("The obsolete videos on Pod")

                if estab == "other":
                    mail_managers(
                        subject,
                        striptags(msg_html),
                        fail_silently=False,
                        html_message=msg_html,
                    )
                else:
                    to_email = []
                    to_email.append(dict(MANAGERS)[estab])
                    send_mail(
                        "[%s] %s"
                        % (
                            __TITLE_SITE__,
                            subject,
                        ),
                        striptags(msg_html),
                        DEFAULT_FROM_EMAIL,
                        to_email,
                        fail_silently=False,
                        html_message=msg_html,
                    )
                if MANAGERS:
                    print(
                        _(
                            "Manager of “%(estab)s” notified for"
                            + " %(nb)s soon to be obsolete video(s)."
                        )
                        % {"estab": estab, "nb": total}
                    )

    def notify_manager_of_deleted_video(self, list_video: dict) -> None:
        """Notify manager(s) with a list of deleted videos."""
        for estab in list_video:
            # list_video[estab] has entries for each WARN_DEADLINE
            total = sum(len(videos) for videos in list_video[estab].values())
            if total > 0:
                if estab != "other":
                    msg_html = _("Hello manager(s) of %(estab)s on %(site_title)s,") % {
                        "estab": estab,
                        "site_title": __TITLE_SITE__,
                    }
                else:
                    msg_html = _("Hello manager(s) of %(site_title)s,") % {
                        "site_title": __TITLE_SITE__
                    }
                msg_html += (
                    "<br>\n<p>"
                    + _(
                        "For information, "
                        + "you will find below the list of deleted video."
                    )
                    + "</p>"
                )

                msg_html += "\n<p>"
                msg_html += self.get_list_video_html(list_video[estab], True)
                msg_html += "\n</p>"
                msg_html += "\n<p>" + _("Regards") + "</p>\n"

                subject = _("The deleted videos on Pod")

                if estab == "other":
                    mail_managers(
                        subject,
                        striptags(msg_html),
                        fail_silently=False,
                        html_message=msg_html,
                    )
                else:
                    to_email = []
                    to_email.append(dict(MANAGERS)[estab])
                    send_mail(
                        "[%s] %s"
                        % (
                            __TITLE_SITE__,
                            subject,
                        ),
                        striptags(msg_html),
                        DEFAULT_FROM_EMAIL,
                        to_email,
                        fail_silently=False,
                        html_message=msg_html,
                    )
                if MANAGERS:
                    print(
                        _("Manager of “%(et)s” notified for %(nb)s deleted video(s).")
                        % {"et": estab, "nb": total}
                    )

    def notify_manager_of_archived_video(self, list_video: dict) -> None:
        """Notify manager(s) with a list of archived videos."""
        for estab in list_video:
            # list_video[estab] has entries for each WARN_DEADLINE
            total = sum(len(videos) for videos in list_video[estab].values())
            if total > 0:
                if estab != "other":
                    msg_html = _("Hello manager(s) of %(estab)s on %(site_title)s,") % {
                        "estab": estab,
                        "site_title": __TITLE_SITE__,
                    }
                else:
                    msg_html = _("Hello manager(s) of %(site_title)s,") % {
                        "site_title": __TITLE_SITE__
                    }
                msg_html += (
                    "<br>\n<p>"
                    + _(
                        "For information, "
                        + "you will find below the list of archived video."
                    )
                    + "</p>"
                )

                msg_html += "\n<p>"
                msg_html += self.get_list_video_html(list_video[estab], False)
                msg_html += "\n</p>"
                msg_html += "\n<p>" + _("Regards") + "</p>\n"

                subject = _("The archived videos on Pod")

                if estab == "other":
                    # mail_managers() add EMAIL_SUBJECT_PREFIX in front of subject
                    mail_managers(
                        subject,
                        striptags(msg_html),
                        fail_silently=False,
                        html_message=msg_html,
                    )
                else:
                    to_email = []
                    to_email.append(dict(MANAGERS)[estab])
                    send_mail(
                        "[%s] %s"
                        % (
                            __TITLE_SITE__,
                            subject,
                        ),
                        striptags(msg_html),
                        DEFAULT_FROM_EMAIL,
                        to_email,
                        fail_silently=False,
                        html_message=msg_html,
                    )
                if MANAGERS:
                    print(
                        _("Manager of “%(estab)s” notified for %(nb)s archived video(s).")
                        % {"estab": estab, "nb": total}
                    )

    def get_list_video_html(self, list_video: dict, deleted: bool) -> str:
        """Generate an html version of list_video."""
        msg_html = ""
        for i, deadline in enumerate(list_video):
            if deleted is False and deadline != "0":
                msg_html += "<p><strong>"
                msg_html += _("In %(deadline)s days:") % {"deadline": deadline}
                msg_html += "</strong></p>\n<ol>"
            for vid in list_video[deadline]:
                msg_html += "\n<li>"
                if deleted:
                    msg_html += vid
                else:
                    msg_html += (
                        "%(title)s ("
                        + "<a href='%(scheme)s:%(url)s' rel='noopener'"
                        + " target='_blank'>%(scheme)s:%(url)s</a>)."
                    ) % {
                        "scheme": URL_SCHEME,
                        "url": vid.get_full_url(),
                        "title": vid,
                    }
                msg_html += "</li>"
            msg_html += "</ol>"
        return msg_html

    def get_manager_emails(self, video: Video):
        """Return the list of manager emails."""
        if (
            USE_ESTABLISHMENT
            and MANAGERS
            and video.owner.owner.establishment.lower() in dict(MANAGERS)
        ):
            video_estab = video.owner.owner.establishment.lower()
            return dict(MANAGERS)[video_estab]
        else:
            return CONTACT_US_EMAIL


"""
# TO CHANGE DATE DELETED FOR ALL VIDEOS
from pod.video.models import Video
from datetime import date
vds = Video.objects.all()
for vid in vds:
  vid.date_delete = date(vid.date_added.year+2,
                          vid.date_added.month,vid.date_added.day)
  print("%s,%s" % (vid.id, vid.title))
  vid.save()
"""

"""
# TO CHANGE DATE DELETED for user "adminPod"
from pod.video.models import Video
from datetime import date

vds = Video.objects.filter(date_delete__lte="2023-03-01", owner__username="adminPod")
# Do only the 50 first to avoid too many connexion on DB
for vid in vds[:50]:
  vid.date_delete = date(vid.date_delete.year+9,
                          vid.date_delete.month,vid.date_delete.day)
  print("%s,vid.owner,%s" % (vid.id, vid.title))
  vid.save()
"""
