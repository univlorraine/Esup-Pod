from django.conf.urls import url

from .views import settings, broadcasters_from_building, building, event, events, event_add, event_edit, event_delete, heartbeat, \
    lives, my_events, video_live,event_startrecord,event_stoprecord, event_splitrecord, event_isstreamrecording, event_isstreamavailabletorecord

app_name = "live"

USE_EVENT = getattr(settings, "USE_EVENT", False)

urlpatterns = []

if not USE_EVENT:
    urlpatterns += [
        url(r"^$", lives, name="lives"),
        url(r"^ajax_calls/heartbeat/", heartbeat),
        url(r"^building/(?P<building_id>[\d]+)/$", building, name="building"),
        url(r"^(?P<slug>[\-\d\w]+)/$", video_live, name="video_live")
    ]
else:
    urlpatterns += [
        url(r"^ajax_calls/getbroadcastersfrombuiding/$", broadcasters_from_building, name="broadcasters_from_building"),
        url(r"^event/(?P<slug>[\-\d\w]+)/$", event, name="event"),
        url(r"^event_add/$", event_add, name="event_add"),
        url(r"^event_edit/(?P<slug>[\-\d\w]+)/$", event_edit, name="event_edit"),
        url(r"^event_delete/(?P<slug>[\-\d\w]+)/$", event_delete, name="event_delete"),
        url(r"^events/$", events, name="events"),
        url(r"^my_events/$", my_events, name="my_events"),
        url(r"^event_startrecord/$", event_startrecord, name="event_startrecord"),
        url(r"^event_stoprecord/$", event_stoprecord, name="event_stoprecord"),
        url(r"^event_splitrecord/$", event_splitrecord, name="event_splitrecord"),
        url(r"^event_isstreamrecording/$", event_isstreamrecording, name="event_isstreamrecording"),
        url(r"^event_isstreamavailabletorecord/$", event_isstreamavailabletorecord,
            name="event_isstreamavailabletorecord")
    ]
