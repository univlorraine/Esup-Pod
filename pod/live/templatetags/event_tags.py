from django import template
from datetime import date, datetime

from pod.live.models import Event

from django.db.models import Q

register = template.Library()


@register.simple_tag(takes_context=True)
def get_next_events(context: object):

    request = context["request"]
    queryset = Event.objects.filter(
        Q(start_date__gt=date.today())
        | (Q(start_date=date.today()) & Q(end_time__gte=datetime.now()))
    )
    queryset = queryset.filter(is_draft=False)
    if not request.user.is_authenticated():
        queryset = queryset.filter(broadcaster__is_restricted=False)
    #     queryset = queryset.filter(broadcaster__restrict_access_to_groups__isnull=True)
    # elif not request.user.is_superuser:
    #     queryset = queryset.filter(Q(is_draft=False) | Q(owner=request.user))
    #     queryset = queryset.filter(Q(broadcaster__restrict_access_to_groups__isnull=True) |
    #                Q(broadcaster__restrict_access_to_groups__in=request.user.groups.all()))

    return queryset.all().order_by("start_date", "start_time")[:4]
