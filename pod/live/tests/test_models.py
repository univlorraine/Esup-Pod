from datetime import date

from django.test import TestCase
from django.conf import settings
from django.contrib.auth.models import User

from pod.video.models import Type
from pod.video.models import Video
from ..models import Building, Broadcaster, HeartBeat, Event
from django.utils import timezone

if getattr(settings, "USE_PODFILE", False):
    FILEPICKER = True
    from pod.podfile.models import CustomImageModel
    from pod.podfile.models import UserFolder
else:
    FILEPICKER = False
    from pod.main.models import CustomImageModel


class BuildingTestCase(TestCase):
    def setUp(self):
        Building.objects.create(name="building1")
        print(" --->  SetUp of BuildingTestCase : OK !")

    """
        test attributs
    """

    def test_attributs(self):
        building = Building.objects.get(id=1)
        self.assertEqual(building.name, "building1")
        building.gmapurl = "b"
        building.save()
        self.assertEqual(building.gmapurl, "b")
        if FILEPICKER:
            user = User.objects.create(username="pod")
            homedir, created = UserFolder.objects.get_or_create(name="Home", owner=user)
            headband = CustomImageModel.objects.create(
                folder=homedir, created_by=user, file="blabla.jpg"
            )
        else:
            headband = CustomImageModel.objects.create(file="blabla.jpg")
        building.headband = headband
        building.save()
        self.assertTrue("blabla" in building.headband.name)
        print("   --->  test_attributs of BuildingTestCase : OK !")

    """
        test delete object
    """

    def test_delete_object(self):
        Building.objects.get(id=1).delete()
        self.assertEquals(Building.objects.all().count(), 0)

        print("   --->  test_delete_object of BuildingTestCase : OK !")


"""
    test recorder object
"""


class BroadcasterTestCase(TestCase):
    fixtures = [
        "initial_data.json",
    ]

    def setUp(self):
        building = Building.objects.create(name="building1")
        if FILEPICKER:
            user = User.objects.create(username="pod")
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
            iframe_url="http://iframe.live",
            iframe_height=120,
            public=False,
        )
        # Test with a video on hold
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
            iframe_url="http://iframe2.live",
            iframe_height=140,
            password="mot2passe",
        )
        print(" --->  SetUp of BroadcasterTestCase : OK !")

    """
        test attributs
    """

    def test_attributs(self):
        broadcaster = Broadcaster.objects.get(id=1)
        self.assertEqual(broadcaster.name, "broadcaster1")
        self.assertTrue("blabla" in broadcaster.poster.name)
        self.assertEqual(broadcaster.url, "http://test.live")
        self.assertEqual(broadcaster.iframe_url, "http://iframe.live")
        self.assertEqual(broadcaster.iframe_height, 120)
        self.assertEqual(broadcaster.status, True)
        self.assertEqual(broadcaster.public, False)
        self.assertEqual(broadcaster.is_restricted, True)
        self.assertEqual(broadcaster.building.id, 1)
        self.assertEqual(
            broadcaster.__str__(),
            "%s - %s" % (broadcaster.name, broadcaster.url),
        )
        broadcaster2 = Broadcaster.objects.get(id=2)
        self.assertEqual(broadcaster2.video_on_hold.id, 1)
        self.assertEqual(broadcaster2.password, "mot2passe")
        print("   --->  test_attributs of BroadcasterTestCase : OK !")

    """
        test delete object
    """

    def test_delete_object(self):
        Broadcaster.objects.get(id=1).delete()
        Broadcaster.objects.get(id=2).delete()
        self.assertEquals(Broadcaster.objects.all().count(), 0)

        print("   --->  test_delete_object of BroadcasterTestCase : OK !")


class HeartbeatTestCase(TestCase):
    def setUp(self):
        building = Building.objects.create(name="building1")
        broad = Broadcaster.objects.create(
            name="broadcaster1",
            url="http://test.live",
            status=True,
            is_restricted=True,
            building=building,
            iframe_url="http://iframe.live",
            iframe_height=120,
            public=False,
        )
        user = User.objects.create(username="pod")
        HeartBeat.objects.create(
            user=user,
            viewkey="testkey",
            broadcaster=broad,
            last_heartbeat=timezone.now(),
        )
        print(" --->  SetUp of HeartbeatTestCase : OK !")

    """
        test attributs
    """

    def test_attributs(self):
        hb = HeartBeat.objects.get(id=1)
        self.assertEqual(hb.user.username, "pod")
        self.assertEqual(hb.viewkey, "testkey")
        self.assertEqual(hb.broadcaster.name, "broadcaster1")
        print("   --->  test_attributs of HeartbeatTestCase : OK !")


def add_video(event):
    e_video = Video.objects.get(id=1)
    event.videos.add(e_video)
    return event


class EventTestCase(TestCase):

    def setUp(self):
        building = Building.objects.create(name="building1")
        e_broad = Broadcaster.objects.create(
            name="broadcaster1",
            building=building,
        )
        e_user = User.objects.create(username="user1")
        e_type = Type.objects.create(title="type1")
        e_video = Video.objects.create(
            video="event_video.mp4",
            owner=e_user,
            type=e_type,
        )
        Event.objects.create(
            title="event1",
            owner=e_user,
            broadcaster=e_broad,
            type=e_type,
        )
        print("--->  SetUp of EventTestCase : OK !")

    def test_create(self):
        e_broad = Broadcaster.objects.get(id=1)
        e_user = User.objects.get(id=1)
        e_type = Type.objects.get(id=1)
        event = Event.objects.create(
            title="event2",
            owner=e_user,
            broadcaster=e_broad,
            type=e_type,
        )
        self.assertEqual(2, event.id)
        print(" --->  test_create of EventTestCase : OK !")

    def test_attributs(self):
        event = Event.objects.get(id=1)
        self.assertEqual(event.title, "event1")
        self.assertTrue(event.is_draft)
        self.assertFalse(event.is_restricted)
        self.assertFalse(event.is_auto_start)
        self.assertEqual(event.description, "")
        self.assertTrue(event.is_current())
        self.assertFalse(event.is_past())
        self.assertFalse(event.is_coming())
        self.assertEqual(event.videos.count(), 0)
        event.save()
        print(" --->  test_attributs of EventTestCase : OK !")

    def test_add_thumbnail(self):
        event = Event.objects.get(id=1)
        if FILEPICKER:
            fp_user, created = User.objects.get_or_create(username="pod")
            homedir, created = UserFolder.objects.get_or_create(name="Home", owner=fp_user)
            thumb = CustomImageModel.objects.create(
                folder=homedir, created_by=fp_user, file="blabla.jpg"
            )
        else:
            thumb = CustomImageModel.objects.create(file="blabla.jpg")
        event.thumbnail = thumb
        event.save()
        self.assertTrue("blabla" in event.thumbnail.name)
        print(" --->  test_add_thumbnail of EventTestCase : OK !")

    def test_add_video(self):
        event = Event.objects.get(id=1)
        event = add_video(event)
        event.save()

        self.assertEquals(event.videos.count(), 1)
        print(" --->  test_add_video of EventTestCase : OK !")

    def test_delete_object(self):
        event = Event.objects.get(id=1)
        event.delete()
        self.assertEquals(Event.objects.all().count(), 0)
        print(" --->  test_delete_object of EventTestCase : OK !")

    def test_delete_object_keep_video(self):
        event = Event.objects.get(id=1)
        add_video(event)
        event.delete()
        # video is not deleted with event
        self.assertEquals(Video.objects.all().count(), 1)
        print(" --->  test_delete_object_keep_video of EventTestCase : OK !")

