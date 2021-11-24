from django.conf.urls import url
from .views import lives, heartbeat, building, event, events,my_events, event_add, event_edit, event_delete, \
    broadcasters_from_building
from .views import video_live

app_name = "live"

urlpatterns = [
    url(r"^ajax_calls/heartbeat/", heartbeat),
    url(r"^$", lives, name="lives"),
    url(r"^building/(?P<building_id>[\d]+)/$", building, name="building"),
    url(r"^event/(?P<slug>[\-\d\w]+)/$", event, name="event"),
    url(r"^my_events/$", my_events, name="my_events"),
    url(r"^event_add/$", event_add, name="event_add"),
    url(r"^event_edit/(?P<slug>[\-\d\w]+)/$", event_edit, name="event_edit"),
    url(r"^event_delete/(?P<slug>[\-\d\w]+)/$", event_delete, name="event_delete"),
    url(r"^event_add/getbfromb/$", broadcasters_from_building, name="event_add_get_broadcaster"),
    url(r"^event_edit/getbfromb/$", broadcasters_from_building, name="event_edit_get_broadcaster"),
    url(r"^events/$", events, name="events"),
    url(r"^getbfromb/$", broadcasters_from_building, name="event_get_broadcaster"),
    url(r"^(?P<slug>[\-\d\w]+)/$", video_live, name="video_live"),
]
