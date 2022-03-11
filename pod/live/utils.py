
from django.conf import settings
from django.utils.translation import ugettext_lazy as _
from django.core.mail import EmailMultiAlternatives

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

def send_email_confirmation(event):
    url_scheme = "https" if SECURE_SSL_REDIRECT else "http"
    url_event = "%s:%s" % (url_scheme, event.get_full_url())
    if event.is_draft:
        url_event += event.get_hashkey() + "/"

    message = "%s\n%s\n\n%s\n" % (
        _("Hello,"),
        _(
            u"Vous venez de programmer un nouvel évènement direct intitulé “%(content_title)s” pour le %(start_date)s de %(start_time)s à %(end_time)s sur le serveur vidéo de l'Université de Lorraine : %(url_event)s)"
            +"Vous pouvez retrouver les autres options de partage dans l'onglet dédié."
        )
        % {"content_title": event.title, "start_date": (event.start_date).strftime("%d/%m/%Y"), "start_time": event.start_time, "end_time": event.end_time,
           "url_event": url_event},
        _("Regards."),
    )

    html_message = '<p>%s</p><p>%s</p><p>%s</p>' % (
        _("Hello,"),
        _(
             u"Vous venez de programmer un nouvel évènement direct intitulé “%(content_title)s” pour le %(start_date)s de %(start_time)s à %(end_time)s sur le serveur vidéo de l'Université de Lorraine : <a href=\"%(url_event)s\">%(url_event)s)</a>"
            +"Vous pouvez retrouver les autres options de partage dans l'onglet dédié."
        )
        % {
            "content_title": event.title, "start_date": (event.start_date).strftime("%d/%m/%Y"), "start_time": event.start_time, "end_time": event.end_time,
           "url_event": url_event
        },
        _("Regards."),
    )

    subject = "[%s] %s" % (
        TITLE_SITE,
        _(u"Registration of event #%(content_id)s")
        % {"content_id": event.id},
    )

    from_email = DEFAULT_FROM_EMAIL

    to_email = []
    to_email.append(event.owner.email)

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



