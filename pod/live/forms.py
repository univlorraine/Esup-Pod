from django import forms
from django.conf import settings
from django.contrib.admin import widgets
from django.db.models import Q
from django.utils.translation import ugettext_lazy as _

from pod.live.models import Broadcaster, getBuildingHavingAvailableBroadcaster, \
    getBuildingHavingAvailableBroadcasterAnd, getAvailableBroadcastersOfBuilding
from pod.live.models import Building, Event
from pod.main.forms import add_placeholder_and_asterisk

FILEPICKER = False
if getattr(settings, "USE_PODFILE", False):
    FILEPICKER = True
    from pod.podfile.widgets import CustomFileWidget


class BuildingAdminForm(forms.ModelForm):
    required_css_class = "required"
    is_staff = True
    is_superuser = False
    admin_form = True

    def __init__(self, *args, **kwargs):
        super(BuildingAdminForm, self).__init__(*args, **kwargs)
        if FILEPICKER:
            self.fields["headband"].widget = CustomFileWidget(type="image")

    def clean(self):
        super(BuildingAdminForm, self).clean()

    class Meta(object):
        model = Building
        fields = "__all__"


class BroadcasterAdminForm(forms.ModelForm):
    required_css_class = "required"

    def __init__(self, *args, **kwargs):
        super(BroadcasterAdminForm, self).__init__(*args, **kwargs)
        if FILEPICKER:
            self.fields["poster"].widget = CustomFileWidget(type="image")

    def clean(self):
        super(BroadcasterAdminForm, self).clean()

    class Meta(object):
        model = Broadcaster
        fields = "__all__"

class EventAdminForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super(EventAdminForm, self).__init__(*args, **kwargs)
        self.fields['owner'].initial = self.request.user

    def clean(self):
        super(EventAdminForm, self).clean()

    class Meta(object):
        model = Event
        fields = "__all__"
        widgets = {
            'start_time': forms.TimeInput(format='%H:%M'),
            'end_time': forms.TimeInput(format='%H:%M'),
        }

class LivePasswordForm(forms.Form):
    password = forms.CharField(label=_("Password"), widget=forms.PasswordInput())

    def __init__(self, *args, **kwargs):
        super(LivePasswordForm, self).__init__(*args, **kwargs)
        self.fields = add_placeholder_and_asterisk(self.fields)

class CustomBroadcasterChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
         return obj.name

class EventForm(forms.ModelForm):

    building = forms.ModelChoiceField(
        label=_("Building"),
        queryset=Building.objects.all(),
        to_field_name="name",
        empty_label=None,
    )

    broadcaster = CustomBroadcasterChoiceField(
        label=_("Broadcaster device"),
        queryset=Broadcaster.objects.all(),
        empty_label=None,
    )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super(EventForm, self).__init__(*args, **kwargs)
        self.fields['owner'].initial = self.user
        # Manage required fields html
        self.fields = add_placeholder_and_asterisk(self.fields)

        # mise a jour dynamique de la liste
        if 'building' in self.data:
            # à la sauvegarde
            try:
                build = Building.objects.filter(name=self.data.get('building')).first()
                self.fields['broadcaster'].queryset = getAvailableBroadcastersOfBuilding(self.user, build.id)
            except (ValueError, TypeError):
                pass  # invalid input from the client; ignore and fallback to empty Broadcaster queryset
        else:
            if self.instance.pk:
                # à l'édition
                broadcaster = self.instance.broadcaster
                self.fields['broadcaster'].queryset = Broadcaster.objects.filter(building_id=broadcaster.building_id).order_by('name')
                self.fields['building'].queryset = getBuildingHavingAvailableBroadcasterAnd(self.user, broadcaster.building.id)
                self.initial['building'] = broadcaster.building.name
            else:
                # à la création
                query_buildings = getBuildingHavingAvailableBroadcaster(self.user)
                self.fields['building'].queryset = query_buildings.all()
                self.initial['building'] = query_buildings.first().name
                self.fields['broadcaster'].queryset = getAvailableBroadcastersOfBuilding(self.user, query_buildings.first())

    def clean(self):
        if not {'start_time', 'start_time', 'end_time', 'broadcaster'} <= self.cleaned_data.keys():
            return

        d_deb = self.cleaned_data['start_date']
        h_deb = self.cleaned_data['start_time']
        h_fin = self.cleaned_data['end_time']
        brd = self.cleaned_data['broadcaster']

        if h_deb >= h_fin:
            self.add_error("start_time", _("Start should not be after end"))
            self.add_error("end_time", "Start should not be after end")
            raise forms.ValidationError("Date error.")

        events = Event.objects.filter(
            Q(broadcaster_id=brd.id)
            & Q(start_date=d_deb)
            & (
            (Q(start_time__lte=h_deb) & Q(end_time__gte=h_fin))
            |(Q(start_time__gte=h_deb) & Q(end_time__lte=h_fin))
            |(Q(start_time__lte=h_deb) & Q(end_time__gte=h_deb))
            |(Q(start_time__lte=h_fin) & Q(end_time__gte=h_fin))
            )
        )
        if self.instance.id:
            events = events.exclude(id=self.instance.id)

        if events.exists() :
            self.add_error("start_date", _("An event is already planned at these dates"))
            raise forms.ValidationError("Date error.")


    class Meta(object):
        model = Event
        fields = ["title" ,"description","owner","start_date","start_time","end_time","building","broadcaster","type","is_draft"]
        widgets = {
            'start_date': widgets.AdminDateWidget,
            'start_time': forms.TimeInput(format='%H:%M'),
            'end_time': forms.TimeInput(format='%H:%M'),
        }

class EventDeleteForm(forms.Form):
    agree = forms.BooleanField(
        label=_("I agree"),
        help_text=_("Delete event cannot be undo"),
        widget=forms.CheckboxInput(),
    )

    def __init__(self, *args, **kwargs):
        super(EventDeleteForm, self).__init__(*args, **kwargs)
        self.fields = add_placeholder_and_asterisk(self.fields)