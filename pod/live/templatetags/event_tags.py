from django import template
from datetime import date,datetime

from pod.live.models import Event

from django.db.models import Q

register = template.Library()

@register.simple_tag(takes_context=True)
def get_last_events(context: object):
    request = context["request"]
    events = Event.objects.filter(
        Q(start_date__gt=date.today())
        |
        (Q(start_date=date.today()) & Q(end_time__gte=datetime.now()))
    ).order_by('start_date','start_time')
    return events