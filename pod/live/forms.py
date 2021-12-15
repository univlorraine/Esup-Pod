from django import forms
from django.conf import settings
from django.utils.translation import ugettext_lazy as _
from django.contrib.admin import widgets
from pod.live.models import Broadcaster
from pod.live.models import Building, Event
from pod.main.forms import add_placeholder_and_asterisk
from django.contrib.auth.models import User

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

    buildingQueryset=Building.objects.filter(
            broadcaster__is_restricted=False # TODO modifier ça selon les regles d'acces du Broadcaster
        ).distinct()

    building = forms.ModelChoiceField(
        queryset=buildingQueryset,
        to_field_name="name",
        empty_label=None,
    )

    broadcaster = CustomBroadcasterChoiceField(
        queryset=Broadcaster.objects.all(),
        # queryset=Broadcaster.objects.filter(building=buildingQueryset.first()),
        empty_label=None,
    )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super(EventForm, self).__init__(*args, **kwargs)
        self.fields['owner'].initial = self.user

        # gère la mise a jour dynamique de la liste
        if 'building' in self.data:
            try:
                building_name = self.data.get('building')
                self.fields['broadcaster'].queryset = Broadcaster.objects.filter(building__name=building_name).order_by('name')
            except (ValueError, TypeError):
                pass  # invalid input from the client; ignore and fallback to empty Broadcaster queryset
        elif self.instance.pk:
            building_name = self.instance.broadcaster.building.name
            self.fields['broadcaster'].queryset = Broadcaster.objects.filter(building__name=building_name).order_by('name')
            self.initial['building'] = building_name

    class Meta(object):
        model = Event
        fields = ["title" ,"description","owner","start_date","start_time","end_time","building","broadcaster","type","is_draft","is_restricted","password","videos"]
        widgets = {
            'start_date': widgets.AdminDateWidget,
            'start_time': forms.TimeInput(format='%H:%M'),
            'end_time': forms.TimeInput(format='%H:%M'),
        }

class EventDeleteForm(forms.Form):
    agree = forms.BooleanField(
        label=_("I agree"),
        help_text=_("Delete Event cannot be undo"),
        widget=forms.CheckboxInput(),
    )

    def __init__(self, *args, **kwargs):
        super(EventDeleteForm, self).__init__(*args, **kwargs)
        self.fields = add_placeholder_and_asterisk(self.fields)