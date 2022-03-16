
from django.conf import settings
from django.utils.translation import ugettext_lazy as _
from django.core.mail import EmailMultiAlternatives, mail_managers

SECURE_SSL_REDIRECT = getattr(settings, "SECURE_SSL_REDIRECT", False)

TEMPLATE_VISIBLE_SETTINGS = getattr(
    settings,
    "TEMPLATE_VISIBLE_SETTINGS",
    {
        "TITLE_SITE": "Pod",
        "TITLE_ETB": "University name",
        "LOGO_SITE": "img/logoPod.svg",
        "LOGO_ETB": "img/logo_etb.svg",
        "LOGO_PLAYER": "img/logoPod.svg",
        "LINK_PLAYER": "",
        "FOOTER_TEXT": ("",),
        "FAVICON": "img/logoPod.svg",
        "CSS_OVERRIDE": "",
        "PRE_HEADER_TEMPLATE": "",
        "POST_FOOTER_TEMPLATE": "",
        "TRACKING_TEMPLATE": "",
    },
)

TITLE_SITE = (
    TEMPLATE_VISIBLE_SETTINGS["TITLE_SITE"]
    if (TEMPLATE_VISIBLE_SETTINGS.get("TITLE_SITE"))
    else "Pod"
)

DEFAULT_FROM_EMAIL = getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@univ.fr")

USE_ESTABLISHMENT = getattr(settings, "USE_ESTABLISHMENT_FIELD", False)

MANAGERS = getattr(settings, "MANAGERS", {})

DEBUG = getattr(settings, "DEBUG", True)

def send_email_confirmation(event):
    """Send an email on creation/modification event."""
    if DEBUG:
        print("SEND EMAIL ON EVENT SCHEDULING")
    url_scheme = "https" if SECURE_SSL_REDIRECT else "http"
    url_event = "%s:%s" % (url_scheme, event.get_full_url())
    if event.is_draft:
        url_event += event.get_hashkey() + "/"

    subject = "[%s] %s" % (
        TITLE_SITE,
        _(u"Registration of event #%(content_id)s")
        % {"content_id": event.id},
    )

    from_email = DEFAULT_FROM_EMAIL

    to_email = []
    to_email.append(event.owner.email)

    message = "%s\n%s\n\n%s\n" % (
        _("Hello,"),
        _(
            u"You have just scheduled a new event called “%(content_title)s” in date of %(start_date)s from %(start_time)s to %(end_time)s on video server : %(url_event)s)"
            +". You can find the other sharing options in the dedicated tab."
        )
        % {"content_title": event.title, "start_date": (event.start_date).strftime("%d/%m/%Y"), "start_time": event.start_time, "end_time": event.end_time,
           "url_event": url_event},
        _("Regards."),
    )

    full_message = message + "\n%s%s" % (
        _("Post by:"),
        event.owner,
    )

    html_message = '<p>%s</p><p>%s</p><p>%s</p>' % (
        _("Hello,"),
        _(
             u"You have just scheduled a new event called “%(content_title)s” in date of %(start_date)s from %(start_time)s to %(end_time)s on video server : %(url_event)s)"
            +". You can find the other sharing options in the dedicated tab."
        )
        % {
            "content_title": event.title, "start_date": (event.start_date).strftime("%d/%m/%Y"), "start_time": event.start_time, "end_time": event.end_time,
           "url_event": url_event
        },
        _("Regards."),
    )

    full_html_message = html_message + "<br/>%s%s" % (
        _("Post by:"),
        event.owner,
    )

    if (
            USE_ESTABLISHMENT
            and MANAGERS
            and event.owner.owner.establishment.lower() in dict(MANAGERS)
    ):
        bcc_email = []
        event_estab = event.owner.owner.establishment.lower()
        manager = dict(MANAGERS)[event_estab]
        if type(manager) in (list, tuple):
            bcc_email = manager
        elif type(manager) == str:
            bcc_email.append(manager)
        msg = EmailMultiAlternatives(
            subject, message, from_email, to_email, bcc=bcc_email
        )
        msg.attach_alternative(html_message, "text/html")
        msg.send()
    else:
        mail_managers(
            subject,
            full_message,
            fail_silently=False,
            html_message=full_html_message,
        )
        if not DEBUG:
            to_cc = []
            for additional_owners in event.additional_owners.all():
                to_cc.append(additional_owners.email)

            msg = EmailMultiAlternatives(
                subject,
                message,
                from_email,
                to_email,
                cc=to_cc,
            )

            msg.attach_alternative(html_message, "text/html")
            msg.send()