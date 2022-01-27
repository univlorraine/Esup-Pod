from django import forms
from django.conf import settings
from django.contrib.admin import widgets
from django.db.models import Q
from django.utils.translation import ugettext_lazy as _

from pod.live.models import Broadcaster, get_building_having_available_broadcaster, \
    get_available_broadcasters_of_building
from pod.live.models import Building, Event
from pod.main.forms import add_placeholder_and_asterisk
from django.forms.widgets import HiddenInput

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
        queryset=Building.objects.none(),
        to_field_name="name",
        empty_label=None,
    )

    broadcaster = CustomBroadcasterChoiceField(
        label=_("Broadcaster device"),
        queryset=Broadcaster.objects.none(),
        empty_label=None,
    )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        is_current_event = kwargs.pop('is_current_event', None)
        super(EventForm, self).__init__(*args, **kwargs)
        self.fields['owner'].initial = self.user
        # Manage required fields html
        self.fields = add_placeholder_and_asterisk(self.fields)
        if not self.user.is_superuser:
            self.remove_field("owner")
            self.instance.owner = self.user
        if is_current_event:
            self.remove_field("start_date")
            self.remove_field("start_time")
            self.remove_field("is_draft")
            self.remove_field("building")
            self.remove_field("broadcaster")
            self.remove_field("owner")

        # mise a jour dynamique de la liste
        if 'building' in self.data:
            # à la sauvegarde
            try:
                build = Building.objects.filter(name=self.data.get('building')).first()
                self.fields['broadcaster'].queryset = get_available_broadcasters_of_building(self.user, build.id)
            except (ValueError, TypeError):
                pass  # invalid input from the client; ignore and fallback to empty Broadcaster queryset
        else:
            if self.instance.pk and not self.instance.is_current:
                # à l'édition
                broadcaster = self.instance.broadcaster
                self.fields['broadcaster'].queryset = get_available_broadcasters_of_building(self.user, broadcaster.building.id, broadcaster.id)
                self.fields['building'].queryset = get_building_having_available_broadcaster(self.user, broadcaster.building.id)
                self.initial['building'] = broadcaster.building.name
            elif not self.instance.pk:
                # à la création
                query_buildings = get_building_having_available_broadcaster(self.user)
                if query_buildings:
                    self.fields['building'].queryset = query_buildings.all()
                    self.initial['building'] = query_buildings.first().name
                    self.fields['broadcaster'].queryset = get_available_broadcasters_of_building(self.user, query_buildings.first())

    def remove_field(self, field):
        if self.fields.get(field):
            del self.fields[field]

    def clean(self):
        if not {'start_time', 'start_time', 'end_time', 'broadcaster'} <= self.cleaned_data.keys():
            return

        d_deb = self.cleaned_data['start_date']
        h_deb = self.cleaned_data['start_time']
        h_fin = self.cleaned_data['end_time']
        brd = self.cleaned_data['broadcaster']

        if h_deb >= h_fin:
            self.add_error("start_time", _("Start should not be after end"))
            self.add_error("end_time", _("Start should not be after end"))
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
        fields = ["title", "description", "owner", "start_date", "start_time", "end_time", "building", "broadcaster", "type", "is_draft"]
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