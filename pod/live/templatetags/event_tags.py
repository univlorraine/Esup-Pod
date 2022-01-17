from django import template
from datetime import date,datetime

from pod.live.models import Event

from django.db.models import Q

register = template.Library()

@register.simple_tag(takes_context=True)
def get_next_events(context: object):

    request = context["request"]
    queryset = Event.objects.filter(is_draft=False)

    if not request.user.is_authenticated():
        queryset = queryset.filter(is_restricted=False)

    queryset = queryset.filter(
        Q(start_date__gt=date.today())
        |
        (Q(start_date=date.today()) & Q(end_time__gte=datetime.now()))
    )

    return queryset.all().order_by('start_date','start_time')[:4]