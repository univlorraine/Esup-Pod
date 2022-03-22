"""
Unit tests for live views
"""
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.test import TestCase, override_settings
from django.test import Client
from django.contrib.auth.models import User
from pod.live.models import Building, Broadcaster, HeartBeat, Event
from pod.video.models import Video
from pod.video.models import Type
from django.core.management import call_command

# from django.core.exceptions import PermissionDenied
import ast
from django.http import JsonResponse
import datetime
import pytz


if getattr(settings, "USE_PODFILE", False):
    FILEPICKER = True
    from pod.podfile.models import CustomImageModel
    from pod.podfile.models import UserFolder
else:
    FILEPICKER = False
    from pod.main.models import CustomImageModel


class LiveViewsTestCase(TestCase):
    fixtures = [
        "initial_data.json",
    ]

    def setUp(self):
        user = User.objects.create(username="pod", password="podv2")
        building = Building.objects.create(name="bulding1")
        if FILEPICKER:
            homedir, created = UserFolder.objects.get_or_create(name="Home", owner=user)
            poster = CustomImageModel.objects.create(
                folder=homedir, created_by=user, file="blabla.jpg"
            )
        else:
            poster = CustomImageModel.objects.create(file="blabla.jpg")
        Broadcaster.objects.create(
            name="broadcaster1",
            poster=poster,
            url="http://test.live",
            status=True,
            is_restricted=True,
            building=building,
        )
        video_on_hold = Video.objects.create(
            title="VideoOnHold",
            owner=user,
            video="test.mp4",
            type=Type.objects.get(id=1),
        )
        Broadcaster.objects.create(
            name="broadcaster2",
            poster=poster,
            url="http://test2.live",
            status=True,
            is_restricted=False,
            video_on_hold=video_on_hold,
            building=building,
        )
        Event.objects.create(
            title="event1",
            owner=user,
            is_restricted=True,
            is_draft=True,
            broadcaster=Broadcaster.objects.get(id=1),
            type=Type.objects.get(id=1),
        )


        print(" --->  SetUp of liveViewsTestCase : OK !")

    def test_lives(self):
        # User not logged in
        with self.settings(USE_EVENT=False):
            response = self.client.get("/live/")
            self.assertTemplateUsed(response, "live/lives.html")
            print("   --->  test_lives of liveViewsTestCase : OK !")

        with self.settings(USE_EVENT=True):
            self.client = Client()
            response = self.client.get("/live/")
            self.assertEqual(response.status_code, 403)
            print("   --->  test_lives of liveViewsTestCase : OK !")

        # Admin
        self.superuser = User.objects.create_superuser(
            "myuser", "myemail@test.com", "superpassword"
        )
        self.client.force_login(self.superuser)
        response = self.client.get("/live/")
        self.assertTemplateUsed(response, "live/lives.html")
        print("   --->  test_lives of liveViewsTestCase : OK !")

    def test_building(self):
        self.client = Client()
        self.user = User.objects.create(
            username="randomviewer", first_name="Jean", last_name="Viewer"
        )

        password = "password"
        self.superuser = User.objects.create_superuser(
            "myuser", "myemail@test.com", password
        )

        self.building = Building.objects.get(name="bulding1")
        response = self.client.get("/live/building/%s/" % self.building.id)

        self.assertRedirects(
            response,
            "%s?referrer=%s"
            % (settings.LOGIN_URL, "/live/building/%s/" % self.building.id),
            status_code=302,
            target_status_code=302,
        )

        # User logged in
        self.client.force_login(self.user)
        # Broadcaster restricted
        response = self.client.get("/live/building/%s/" % self.building.id)
        # self.assertRaises(PermissionDenied, response)
        self.assertEqual(response.status_code, 403)

        # User logged in
        self.client.force_login(self.superuser)
        # Broadcaster restricted
        response = self.client.get("/live/building/%s/" % self.building.id)
        self.assertTemplateUsed(response, "live/building.html")

        print("   --->  test_building of liveViewsTestCase : OK !")

    def test_heartbeat(self):
        self.client = Client()
        self.user = User.objects.create(
            username="randomviewer", first_name="Jean", last_name="Viewer"
        )
        response = self.client.get(
            "/live/ajax_calls/heartbeat/?key=testkey&liveid=1",
            {},
            False,
            False,
            **{"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}
        )
        self.assertEqual(response.status_code, 200)

        data = {"viewers": 0, "viewers_list": []}
        expected_content = JsonResponse(data, safe=False).content
        exp_content = expected_content.decode("UTF-8")
        exp_content = ast.literal_eval(exp_content)

        resp_content = response.content.decode("UTF-8")
        resp_content = ast.literal_eval(resp_content)

        self.assertEqual(resp_content, exp_content)
        call_command("live_viewcounter")

        response = self.client.get(
            "/live/ajax_calls/heartbeat/?key=testkey&liveid=1",
            {},
            False,
            False,
            **{"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}
        )
        self.assertEqual(response.status_code, 200)

        data = {"viewers": 1, "viewers_list": []}
        expected_content = JsonResponse(data, safe=False).content
        exp_content = expected_content.decode("UTF-8")
        exp_content = ast.literal_eval(exp_content)

        resp_content = response.content.decode("UTF-8")
        resp_content = ast.literal_eval(resp_content)

        self.assertEqual(resp_content, exp_content)

        self.client.force_login(self.user)
        response = self.client.get(
            "/live/ajax_calls/heartbeat/?key=testkeypod&liveid=1",
            {},
            False,
            False,
            **{"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}
        )
        self.assertEqual(response.status_code, 200)
        call_command("live_viewcounter")

        response = self.client.get(
            "/live/ajax_calls/heartbeat/?key=testkeypod&liveid=1",
            {},
            False,
            False,
            **{"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}
        )
        self.assertEqual(response.status_code, 200)

        data = {
            "viewers": 2,
            "viewers_list": [
                {
                    "first_name": "Jean",
                    "is_superuser": False,
                    "last_name": "Viewer",
                }
            ],
        }
        expected_content = JsonResponse(data, safe=False).content
        exp_content = expected_content.decode("UTF-8")
        exp_content = exp_content.replace("false", "False")
        exp_content = ast.literal_eval(exp_content)

        resp_content = response.content.decode("UTF-8")
        resp_content = resp_content.replace("false", "False")
        resp_content = ast.literal_eval(resp_content)

        self.assertEqual(resp_content, exp_content)

        hb1 = HeartBeat.objects.get(viewkey="testkey")
        hb2 = HeartBeat.objects.get(viewkey="testkeypod")

        paris_tz = pytz.timezone("Europe/Paris")
        # make heartbeat expire now
        hb1.last_heartbeat = paris_tz.localize(datetime.datetime(2012, 3, 3, 1, 30))
        hb1.save()
        hb2.last_heartbeat = paris_tz.localize(datetime.datetime(2012, 3, 3, 1, 30))
        hb2.save()

        call_command("live_viewcounter")

        broad = Broadcaster.objects.get(name="broadcaster1")
        self.assertEqual(broad.viewcount, 0)

        print("   --->  test_heartbeat of liveViewsTestCase : OK !")

    @override_settings(USE_EVENT=False)
    def test_video_live(self):
        self.client = Client()
        self.user = User.objects.get(username="pod")

        # User not logged in
        # Broadcaster restricted
        with self.settings(USE_EVENT=True):
            self.broadcaster = Broadcaster.objects.get(name="broadcaster1")
            response = self.client.get("/live/%s/" % self.broadcaster.slug)
            self.assertEqual(response.status_code, 403)

        self.broadcaster = Broadcaster.objects.get(name="broadcaster1")
        response = self.client.get("/live/%s/" % self.broadcaster.slug)
        self.assertRedirects(
            response,
            "%s?referrer=%s" % (settings.LOGIN_URL, "/live/%s/" % self.broadcaster.slug),
            status_code=302,
            target_status_code=302,
        )
        # Broadcaster not restricted
        self.broadcaster = Broadcaster.objects.get(name="broadcaster2")
        response = self.client.get("/live/%s/" % self.broadcaster.slug)
        self.assertTemplateUsed(response, "live/live.html")

        # User logged in
        self.client.force_login(self.user)
        # Broadcaster restricted
        self.broadcaster = Broadcaster.objects.get(name="broadcaster1")
        response = self.client.get("/live/%s/" % self.broadcaster.slug)
        self.assertTemplateUsed(response, "live/live.html")
        # Broadcaster not restricted
        self.broadcaster = Broadcaster.objects.get(name="broadcaster2")
        response = self.client.get("/live/%s/" % self.broadcaster.slug)
        self.assertTemplateUsed(response, "live/live.html")

        self.broadcaster.password = "password"
        self.broadcaster.save()
        response = self.client.get("/live/%s/" % self.broadcaster.slug)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"])

        print("   --->  test_video_live of liveViewsTestCase : OK !")

    def test_events(self):
        self.client = Client()

        # User not logged in
        response = self.client.get("/live/events/")
        self.assertTemplateUsed(response, "live/events.html")
        print("   --->  test_events of live/events : OK !")

        response = self.client.get("/live/my_events/")
        self.assertRedirects(
            response,
            "%s?referrer=%s" % (settings.LOGIN_URL, "/live/my_events/"),
            status_code=302,
            target_status_code=302,
        )
        print("   --->  test_events of live/my_events : OK !")

        # event restricted and draft
        self.event = Event.objects.get(title="event1")
        response = self.client.get("/live/event/%s/" % self.event.slug)
        self.assertRedirects(
            response,
            "%s?referrer=%s" % (settings.LOGIN_URL, "/live/event/%s/" % self.event.slug),
            status_code=302,
            target_status_code=302,
        )
        print("   --->  test_events access restricted event : OK !")

        # event not restricted but draft (permission denied)
        self.event.is_restricted = False
        self.event.save()
        response = self.client.get("/live/event/%s/" % self.event.slug)
        self.assertTrue(403, response.status_code)
        print("   --->  test_events access not restricted but draft event : OK !")

        # event not restricted but draft (public link)
        response = self.client.get("/live/event/%s/%s/" % (self.event.slug, self.event.get_hashkey()))
        self.assertTemplateUsed(response, "live/event.html")
        print("   --->  test_events access not restricted but draft with public link event : OK !")

        # event not restricted nor draft
        self.event.is_draft = False
        self.event.save()
        response = self.client.get("/live/event/%s/" % self.event.slug)
        self.assertTemplateUsed(response, "live/event.html")
        print("   --->  test_events access not restricted nor draft event : OK !")

        # event creation
        response = self.client.get("/live/event_edit/")
        self.assertRedirects(
            response,
            "%s?referrer=%s" % (settings.LOGIN_URL, "/live/event_edit/"),
            status_code=302,
            target_status_code=302,
        )
        print("   --->  test_events creation event : OK !")


        # User logged in
        self.user = User.objects.create(username="johndoe", password="johnpwd")
        self.client.force_login(self.user)

        response = self.client.get("/live/my_events/")
        self.assertTemplateUsed(response, "live/my_events.html")
        print("   --->  test_events of live/my_events : OK !")

        # event restricted and draft (permission denied)
        self.event = Event.objects.get(title="event1")
        self.event.is_restricted = True
        self.event.is_draft = True
        self.event.save()
        response = self.client.get("/live/event/%s/" % self.event.slug)
        self.assertTrue(403, response.status_code)
        print("   --->  test_events access restricted and draft with logged user : OK !")

        # event restricted but not draft
        self.event.is_draft = False
        self.event.save()
        response = self.client.get("/live/event/%s/" % self.event.slug)
        self.assertTemplateUsed(response, "live/event.html")
        print("   --->  test_events access restricted not draft with logged user : OK !")

        # event creation
        response = self.client.get("/live/event_edit/")
        self.assertTemplateUsed(response, "live/event_edit.html")
        print("   --->  test_events creation event : OK !")

        # event delete  (permission denied)
        response = self.client.get("/live/event_delete/%s/" % self.event.slug)
        self.assertTrue(403, response.status_code)
        print("   --->  test_events delete event : OK !")

        # User is event's owner
        self.user = User.objects.get(username="pod")
        self.client.force_login(self.user)

        self.event = Event.objects.get(title="event1")
        self.event.is_restricted = True
        self.event.is_draft = True
        self.event.save()

        # myevents contains the event
        response = self.client.get("/live/my_events/")
        self.assertTemplateUsed(response, "live/my_events.html")
        self.assertTemplateUsed(response, "live/events_list.html")
        print("   --->  test_events owner sees his event's list: OK !")

        # user's event (restricted and draft)
        response = self.client.get("/live/event/%s/" % self.event.slug)
        self.assertTemplateUsed(response, "live/event.html")
        print("   --->  test_events access of restricted event for owner: OK !")

        # event delete
        response = self.client.get("/live/event_delete/%s/" % self.event.slug)
        self.assertTemplateUsed(response, "live/event_delete.html")
        print("   --->  test_events delete event : OK !")
