"""Esup-Pod - Test Obsolete videos.

Test with `python manage.py test pod.video.tests.test_obsolescence  --settings=pod.main.test_settings`
"""

import os
import tempfile
from datetime import date, timedelta
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.sites.models import Site
from django.test import RequestFactory, TestCase, override_settings
from django.utils.translation import gettext as _

from pod.authentication.models import Owner

from ..models import Type, Video, VideoToDelete
from ..utils import archive_pack, check_csv_header, read_archived_csv

DEFAULT_YEAR_DATE_DELETE = getattr(settings, "DEFAULT_YEAR_DATE_DELETE", 2)
ARCHIVE_OWNER_USERNAME = getattr(settings, "ARCHIVE_OWNER_USERNAME", "archive")


class ObsolescenceTestCase(TestCase):
    """Test the Obsolete videos."""

    fixtures = [
        "initial_data.json",
    ]

    def setUp(self):
        """Set up."""
        site = Site.objects.get(id=1)
        user = User.objects.create(
            username="pod", password="pod1234pod", email="pod@univ.fr"
        )

        user_faculty = User.objects.create(
            username="pod_faculty", password="pod1234pod", email="pod@univ.fr"
        )

        owner, owner_created = Owner.objects.get_or_create(user=user_faculty)
        owner.auth_type = "CAS"
        owner.affiliation = "faculty"
        owner.save()

        user1 = User.objects.create(
            username="pod1", password="pod1234pod", email="pod@univ.fr"
        )
        user2 = User.objects.create(
            username="pod2", password="pod1234pod", email="pod@univ.fr"
        )
        user3 = User.objects.create(
            username="pod3", password="pod1234pod", email="pod@univ.fr"
        )
        user4 = User.objects.create(
            username="pod4", password="pod1234pod", email="pod@univ.fr"
        )

        # Video 1
        Video.objects.create(
            title="Video_default",
            owner=user,
            video="test.mp4",
            type=Type.objects.get(id=1),
        )

        # Video 2
        Video.objects.create(
            title="Video_faculty_with_accomodation_year",
            owner=user_faculty,
            video="test.mp4",
            type=Type.objects.get(id=1),
        )

        # pour les 3 vidéos suivantes, la date n'est pas changée à la création
        # car l'affiliation du prop n'est pas dans ACCOMMODATION_YEARS

        # Video 3
        Video.objects.create(
            title="Video1_60",
            owner=user1,
            video="test.mp4",
            type=Type.objects.get(id=1),
        )
        # Video 4
        Video.objects.create(
            title="Video2_30",
            owner=user2,
            video="test.mp4",
            type=Type.objects.get(id=1),
        )
        # Video 5
        Video.objects.create(
            title="Video3_7",
            owner=user3,
            video="test.mp4",
            type=Type.objects.get(id=1),
        )

        video60 = Video.objects.get(pk=3)
        video60.date_delete = date.today() + timedelta(days=60)
        video60.save(update_fields=["date_delete"])

        video30 = Video.objects.get(pk=4)
        video30.date_delete = date.today() + timedelta(days=30)
        video30.save(update_fields=["date_delete"])

        video7 = Video.objects.get(pk=5)
        video7.date_delete = date.today() + timedelta(days=7)
        video7.save(update_fields=["date_delete"])

        # Video 6
        vid6 = Video.objects.create(
            title="Video_to_archive",
            owner=user_faculty,
            video="test.mp4",
            type=Type.objects.get(id=1),
        )
        # Modify the date after creation to ensure it is correct
        vid6.date_delete = date.today() - timedelta(days=1)
        vid6.is_draft = False
        vid6.save()

        # Video 7
        vid7 = Video.objects.create(
            title="Video_to_delete",
            owner=user4,
            video="test.mp4",
            type=Type.objects.get(id=1),
        )
        vid7.date_delete = date.today() - timedelta(days=1)
        vid7.save(update_fields=["date_delete"])

        for vid in Video.objects.all():
            vid.sites.add(site)

        print(" --->  SetUp of ObsolescenceTestCase: OK!")

    @override_settings(ACCOMMODATION_YEARS={"faculty": 1})
    def test_check_video_date_delete(self) -> None:
        """Check that the videos deletion date complies with the settings."""
        ACCOMMODATION_YEARS = getattr(settings, "ACCOMMODATION_YEARS", {"faculty": 1})
        video1 = Video.objects.get(id=1)
        date1 = date.today() + timedelta(days=DEFAULT_YEAR_DATE_DELETE * 365)
        self.assertEqual(video1.date_delete, date1)

        user_faculty = User.objects.get(username="pod_faculty")
        video2 = Video.objects.create(
            title="faculty_video",
            owner=user_faculty,
            video="test.mp4",
            type=Type.objects.get(id=1),
        )
        owner_affiliation = video2.owner.owner.affiliation
        self.assertEqual(owner_affiliation, "faculty")
        date2 = date.today() + timedelta(
            days=ACCOMMODATION_YEARS[owner_affiliation] * 365
        )
        self.assertEqual(video2.date_delete, date2)

        print("--->  check_video_date_delete of ObsolescenceTestCase: OK")

    def test_notify_user_obsolete_video(self):
        """Check user notification of obsolete video."""
        from pod.video.management.commands import check_obsolete_videos

        cmd = check_obsolete_videos.Command()
        # kwargs for your command -- lets you override stuff for testing...
        # opts = {}
        video60 = Video.objects.get(id=3)
        mail = cmd.notify_user(video60, 60)
        self.assertEqual(mail, 1)
        print("--->  test_notify_user_obsolete_video of \
            ObsolescenceTestCase: OK")

    def test_obsolete_video(self):
        """Check that videos with deletion date in 7,30 and 60 days will be notified."""
        from pod.video.management.commands import check_obsolete_videos

        cmd = check_obsolete_videos.Command()
        # kwargs for your command -- lets you override stuff for testing...
        # opts = {}
        list_video = cmd.get_video_treatment_and_notify_user()
        video60 = Video.objects.get(id=3)
        self.assertEqual(video60.title, "Video1_60")
        video30 = Video.objects.get(id=4)
        self.assertEqual(video30.title, "Video2_30")
        video7 = Video.objects.get(id=5)
        self.assertEqual(video7.title, "Video3_7")

        self.assertTrue(video60 in list_video["other"]["60"])
        self.assertTrue(video30 in list_video["other"]["30"])
        self.assertTrue(video7 in list_video["other"]["7"])
        print("--->  test_obsolete_video of ObsolescenceTestCase: OK")

    def test_get_video_treatment_and_notify_sends_one_mail_per_recipient(self):
        """Check that a single aggregated mail is sent per recipient email."""
        from pod.video.management.commands import check_obsolete_videos

        cmd = check_obsolete_videos.Command()
        video60 = Video.objects.get(id=3)  # owner user1 -> pod@univ.fr
        video30 = Video.objects.get(id=4)  # owner user2 -> pod@univ.fr
        video7 = Video.objects.get(id=5)  # owner user3 -> pod@univ.fr

        # All users share the same email "pod@univ.fr"
        with patch(
            "pod.video.management.commands.check_obsolete_videos.send_mail"
        ) as mock_send_mail:
            mock_send_mail.return_value = 1
            cmd.get_video_treatment_and_notify_user()

        # One and only one mail should be sent for the shared email.
        self.assertEqual(mock_send_mail.call_count, 1)
        html_message = mock_send_mail.call_args.kwargs["html_message"]
        # The aggregated mail lists the three videos.
        for title in ("Video1_60", "Video2_30", "Video3_7"):
            self.assertIn(title, html_message)
        print("--->  test_one_mail_per_recipient of ObsolescenceTestCase: OK")

    def test_collect_user_notification_groups_owner_and_additional(self):
        """Check collection regroups owner and additional owners by email."""
        from pod.video.management.commands import check_obsolete_videos

        cmd = check_obsolete_videos.Command()
        owner = User.objects.create(
            username="collect_owner", email="owner@univ.fr"
        )
        additional = User.objects.create(
            username="collect_additional", email="additional@univ.fr"
        )
        video = Video.objects.create(
            title="Collect_video",
            owner=owner,
            video="test.mp4",
            type=Type.objects.get(id=1),
        )
        video.additional_owners.add(additional)

        notifications = cmd.collect_user_notification({}, video, 7)

        self.assertIn("owner@univ.fr", notifications)
        self.assertIn("additional@univ.fr", notifications)
        # Owner is not flagged as additional owner.
        self.assertEqual(
            notifications["owner@univ.fr"]["7"][0][1], False
        )
        # Additional owner is flagged as additional owner.
        self.assertEqual(
            notifications["additional@univ.fr"]["7"][0][1], True
        )
        print("--->  test_collect_user_notification of ObsolescenceTestCase: OK")

    def test_get_user_aggregated_videos_skips_name(self):
        """Check aggregated videos ignore the "name" key."""
        from pod.video.management.commands import check_obsolete_videos

        cmd = check_obsolete_videos.Command()
        data = {"name": "John Doe", "7": [("video", False)], "30": [("video2", True)]}
        aggregated = cmd.get_user_aggregated_videos(data)
        self.assertNotIn("name", aggregated)
        self.assertEqual(set(aggregated.keys()), {"7", "30"})
        print("--->  test_get_user_aggregated_videos of ObsolescenceTestCase: OK")

    def test_aggregated_mail_marks_additional_owner_and_deadlines(self):
        """Check aggregated mail flags additional owners and groups by deadline."""
        from django.core import mail as djmail
        from pod.video.management.commands import check_obsolete_videos

        cmd = check_obsolete_videos.Command()
        owner = User.objects.create(
            username="agg_owner", email="owner@univ.fr", is_staff=False
        )
        additional = User.objects.create(
            username="agg_additional", email="additional@univ.fr"
        )
        video7 = Video.objects.create(
            title="Agg_video_7",
            owner=owner,
            video="test.mp4",
            type=Type.objects.get(id=1),
        )
        video7.date_delete = date.today() + timedelta(days=7)
        video7.save(update_fields=["date_delete"])
        video7.additional_owners.add(additional)

        video30 = Video.objects.create(
            title="Agg_video_30",
            owner=owner,
            video="test.mp4",
            type=Type.objects.get(id=1),
        )
        video30.date_delete = date.today() + timedelta(days=30)
        video30.save(update_fields=["date_delete"])

        notifications = cmd.collect_user_notification({}, video7, 7)
        notifications = cmd.collect_user_notification(notifications, video30, 30)

        with self.settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"):
            cmd.notify_user_aggregated("owner@univ.fr", notifications["owner@univ.fr"])
            cmd.notify_user_aggregated(
                "additional@univ.fr", notifications["additional@univ.fr"]
            )

        self.assertEqual(len(djmail.outbox), 2)

        owner_mail = next(m for m in djmail.outbox if m.to == ["owner@univ.fr"])
        # Owner receives both videos, grouped by deadline, none flagged additional.
        self.assertIn("In 7 days:", owner_mail.body)
        self.assertIn("In 30 days:", owner_mail.body)
        self.assertIn("Agg_video_7", owner_mail.body)
        self.assertIn("Agg_video_30", owner_mail.body)
        self.assertNotIn("(additional owner)", owner_mail.body)

        additional_mail = next(m for m in djmail.outbox if m.to == ["additional@univ.fr"])
        # Additional owner receives only its video, flagged as additional owner.
        self.assertIn("(additional owner)", additional_mail.body)
        self.assertNotIn("Agg_video_30", additional_mail.body)
        print("--->  test_aggregated_mail of ObsolescenceTestCase: OK")

    @patch("pod.video.management.commands.check_obsolete_videos.ENABLE_PAGE_OBSO_MAIL", True)
    def test_aggregated_mail_has_action_link_for_each_video(self):
        """Check each video line has its own respite action link."""
        from django.core import mail as djmail
        from pod.video.management.commands import check_obsolete_videos

        cmd = check_obsolete_videos.Command()
        owner = User.objects.create(
            username="link_owner", email="owner@univ.fr", is_staff=False
        )
        video7 = Video.objects.create(
            title="Link_video_7",
            owner=owner,
            video="test.mp4",
            type=Type.objects.get(id=1),
        )
        video7.date_delete = date.today() + timedelta(days=7)
        video7.save(update_fields=["date_delete"])

        video30 = Video.objects.create(
            title="Link_video_30",
            owner=owner,
            video="test.mp4",
            type=Type.objects.get(id=1),
        )
        video30.date_delete = date.today() + timedelta(days=30)
        video30.save(update_fields=["date_delete"])

        notifications = cmd.collect_user_notification({}, video7, 7)
        notifications = cmd.collect_user_notification(notifications, video30, 30)

        with self.settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"):
            cmd.notify_user_aggregated("owner@univ.fr", notifications["owner@univ.fr"])

        self.assertEqual(len(djmail.outbox), 1)
        message = djmail.outbox[0]
        # One action link per video line (2 videos), no single bottom link.
        self.assertEqual(message.body.count("Choose an action for my video"), 2)
        html_message = message.alternatives[0][0]
        self.assertIn("/video/respite/%s" % video7.slug, html_message)
        self.assertIn("/video/respite/%s" % video30.slug, html_message)
        print("--->  test_action_link_per_video of ObsolescenceTestCase: OK")

    def test_aggregated_mail_singular_plural(self):
        """Check singular/plural forms in subject and intro of aggregated mail."""
        from django.core import mail as djmail
        from pod.video.management.commands import check_obsolete_videos

        cmd = check_obsolete_videos.Command()
        owner = User.objects.create(
            username="plural_owner", email="owner@univ.fr", is_staff=True
        )

        video1 = Video.objects.create(
            title="Plural_video_1",
            owner=owner,
            video="test.mp4",
            type=Type.objects.get(id=1),
        )
        video1.date_delete = date.today() + timedelta(days=7)
        video1.save(update_fields=["date_delete"])

        # One video: singular forms.
        notifications = cmd.collect_user_notification({}, video1, 7)
        with self.settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"):
            cmd.notify_user_aggregated(
                "owner@univ.fr", notifications["owner@univ.fr"]
            )
        self.assertEqual(len(djmail.outbox), 1)
        self.assertIn("Your video will be obsolete soon", djmail.outbox[0].subject)
        self.assertIn("The following video will", djmail.outbox[0].body)
        self.assertIn("by editing your video:", djmail.outbox[0].body)

        video2 = Video.objects.create(
            title="Plural_video_2",
            owner=owner,
            video="test.mp4",
            type=Type.objects.get(id=1),
        )
        video2.date_delete = date.today() + timedelta(days=30)
        video2.save(update_fields=["date_delete"])

        # Two videos: plural forms.
        notifications = cmd.collect_user_notification(notifications, video2, 30)
        with self.settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"):
            cmd.notify_user_aggregated(
                "owner@univ.fr", notifications["owner@univ.fr"]
            )
        self.assertEqual(len(djmail.outbox), 2)
        self.assertIn("Your videos will be obsolete soon", djmail.outbox[1].subject)
        self.assertIn("The following videos will", djmail.outbox[1].body)
        self.assertIn("by editing your videos:", djmail.outbox[1].body)
        print("--->  test_singular_plural of ObsolescenceTestCase: OK")

    def test_notify_user_returns_count_without_exception(self):
        """Check notify_user still works as a single-video fallback."""
        from pod.video.management.commands import check_obsolete_videos

        cmd = check_obsolete_videos.Command()
        video60 = Video.objects.get(id=3)
        mail = cmd.notify_user(video60, 60)
        self.assertEqual(mail, 1)
        print("--->  test_notify_user_returns_count of ObsolescenceTestCase: OK")

    def test_get_video_recipients_returns_owner_and_additional(self):
        """Check recipients list contains owner and additional owners emails."""
        from pod.video.management.commands import check_obsolete_videos

        cmd = check_obsolete_videos.Command()
        owner = User.objects.create(
            username="rec_owner", email="owner@univ.fr"
        )
        additional = User.objects.create(
            username="rec_additional", email="additional@univ.fr"
        )
        video = Video.objects.create(
            title="Recipients_video",
            owner=owner,
            video="test.mp4",
            type=Type.objects.get(id=1),
        )
        video.additional_owners.add(additional)

        recipients = cmd.get_video_recipients(video)
        self.assertEqual(
            [(u.email, is_add) for u, is_add in recipients],
            [("owner@univ.fr", False), ("additional@univ.fr", True)],
        )
        print("--->  test_get_video_recipients of ObsolescenceTestCase: OK")

    def test_notify_user_archived_deleted_two_sublists(self):
        """Check aggregated mail lists archived and deleted videos separately."""
        from django.core import mail as djmail
        from pod.video.management.commands import check_obsolete_videos

        cmd = check_obsolete_videos.Command()
        owner = User.objects.create(
            username="ad_owner", email="owner@univ.fr", is_staff=False
        )
        additional = User.objects.create(
            username="ad_additional", email="additional@univ.fr"
        )

        archived_video = Video.objects.create(
            title="Agg_archived",
            owner=owner,
            video="test.mp4",
            type=Type.objects.get(id=1),
        )
        archived_video.save()
        archived_video.additional_owners.add(additional)

        notifications = {
            "owner@univ.fr": {
                "name": "owner",
                "archived": [(archived_video, False)],
                "deleted": [("0002 - Agg_deleted", True)],
            }
        }

        with self.settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"):
            cmd.notify_user_archived_deleted("owner@univ.fr", notifications["owner@univ.fr"])

        self.assertEqual(len(djmail.outbox), 1)
        mail_body = djmail.outbox[0].body
        self.assertIn("Archived videos:", mail_body)
        self.assertIn("Deleted videos:", mail_body)
        self.assertIn("Agg_archived", mail_body)
        self.assertIn("Agg_deleted", mail_body)
        self.assertIn("(additional owner)", mail_body)
        print("--->  test_notify_user_archived_deleted of ObsolescenceTestCase: OK")

    def test_archived_deleted_mail_singular_plural(self):
        """Check singular/plural forms in archived/deleted mail intro."""
        from django.core import mail as djmail
        from pod.video.management.commands import check_obsolete_videos

        cmd = check_obsolete_videos.Command()
        owner = User.objects.create(
            username="adpl_owner", email="owner@univ.fr", is_staff=False
        )

        video1 = Video.objects.create(
            title="ADpl_video_1",
            owner=owner,
            video="test.mp4",
            type=Type.objects.get(id=1),
        )

        # One video: singular form.
        data = {"name": "owner", "archived": [(video1, False)], "deleted": []}
        with self.settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"):
            cmd.notify_user_archived_deleted("owner@univ.fr", data)
        self.assertEqual(len(djmail.outbox), 1)
        self.assertIn(
            "Your video has reached its deletion deadline.", djmail.outbox[0].body
        )

        video2 = Video.objects.create(
            title="ADpl_video_2",
            owner=owner,
            video="test.mp4",
            type=Type.objects.get(id=1),
        )

        # Two videos: plural form.
        data = {
            "name": "owner",
            "archived": [(video1, False), (video2, False)],
            "deleted": [],
        }
        with self.settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"):
            cmd.notify_user_archived_deleted("owner@univ.fr", data)
        self.assertEqual(len(djmail.outbox), 2)
        self.assertIn(
            "Your videos have reached their deletion deadline.", djmail.outbox[1].body
        )
        print("--->  test_archived_deleted_singular_plural of ObsolescenceTestCase: OK")

    @override_settings(POD_ARCHIVE_AFFILIATION=["faculty"])
    def test_archived_deleted_treatment_sends_one_mail_per_recipient(self):
        """Check one aggregated mail per recipient for archived/deleted videos."""
        from pod.video.management.commands import check_obsolete_videos

        cmd = check_obsolete_videos.Command()
        # video6 (owner user_faculty) is archived, video7 (owner user4) is deleted.
        # Both owners share the email pod@univ.fr.
        with patch(
            "pod.video.management.commands.check_obsolete_videos.send_mail"
        ) as mock_send_mail:
            mock_send_mail.return_value = 1
            cmd.get_video_archived_deleted_treatment()

        # One and only one mail for the shared email.
        self.assertEqual(mock_send_mail.call_count, 1)
        html_message = mock_send_mail.call_args.kwargs["html_message"]
        self.assertIn("Archived videos:", html_message)
        self.assertIn("Deleted videos:", html_message)
        print("--->  test_archived_deleted_one_mail of ObsolescenceTestCase: OK")

    @override_settings(POD_ARCHIVE_AFFILIATION=["faculty"])
    def test_archived_deleted_treatment_dry_does_not_send_mail(self):
        """Check no mail is sent in dry mode for archived/deleted videos."""
        from pod.video.management.commands import check_obsolete_videos

        cmd = check_obsolete_videos.Command()
        cmd.dry_mode = True
        with patch(
            "pod.video.management.commands.check_obsolete_videos.send_mail"
        ) as mock_send_mail:
            cmd.get_video_archived_deleted_treatment()
        mock_send_mail.assert_not_called()
        print("--->  test_archived_deleted_dry of ObsolescenceTestCase: OK")

    @override_settings(POD_ARCHIVE_AFFILIATION=["faculty"])
    def test_delete_obsolete_video(self):
        """Check that obsolete videos are deleted."""
        from pod.video.management.commands import check_obsolete_videos

        cmd = check_obsolete_videos.Command()
        # kwargs for your command -- lets you override stuff for testing...
        # opts = {}
        video_to_archive = Video.objects.get(id=6)
        self.assertEqual(video_to_archive.title, "Video_to_archive")

        video_to_delete = Video.objects.get(id=7)
        self.assertEqual(video_to_delete.title, "Video_to_delete")
        title2 = "%s - %s" % (video_to_delete.id, video_to_delete.title)

        (
            list_video_to_delete,
            list_video_to_archive,
        ) = cmd.get_video_archived_deleted_treatment()

        self.assertTrue(title2 in list_video_to_delete["other"]["0"])
        self.assertTrue(video_to_archive in list_video_to_archive["other"]["0"])

        # Check that the archived video has been really archived
        video_to_archive = Video.objects.get(id=6)
        archive_user, created = User.objects.get_or_create(
            username=ARCHIVE_OWNER_USERNAME,
        )
        self.assertTrue(_("Archived") in video_to_archive.title)
        self.assertTrue(video_to_archive.is_draft)
        self.assertTrue(video_to_archive.owner == archive_user)

        vid_delete = VideoToDelete.objects.get(date_deletion=video_to_archive.date_delete)
        self.assertTrue(video_to_archive in vid_delete.video.all())

        # Check that the deleted video has been permanently deleted
        self.assertEqual(Video.objects.filter(id=7).count(), 0)

        # Check that csv file has been created
        file1 = "%s/%s.csv" % (settings.LOG_DIRECTORY, "deleted")
        self.assertTrue(os.path.isfile(file1))
        file2 = "%s/%s.csv" % (settings.LOG_DIRECTORY, "archived")
        self.assertTrue(os.path.isfile(file2))

        fd = open(file1, "r")
        n = 0
        while fd.readline():
            n += 1
        fd.close()
        self.assertEqual(n, 2)

        fd = open(file2, "r")
        n = 0
        while fd.readline():
            n += 1
        fd.close()
        self.assertEqual(n, 2)

        print("--->  test_delete_obsolete_video of ObsolescenceTestCase: OK")

    def tearDown(self):
        """Cleanup all created stuffs."""
        try:
            os.remove("%s/%s.csv" % (settings.LOG_DIRECTORY, "deleted"))
            os.remove("%s/%s.csv" % (settings.LOG_DIRECTORY, "archived"))
        except FileNotFoundError:
            pass


class ValidFormRespitTestCase(TestCase):

    fixtures = [
        "initial_data.json",
    ]

    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="testuser", password="password123")
        self.user.owner.affiliation = "faculty"
        self.user.owner.save()

        self.video1 = Video.objects.create(
            title="Video_to_delete",
            owner=self.user,
            video="test.mp4",
            type=Type.objects.get(id=1),
        )
        self.archive_user, created = User.objects.get_or_create(
            username=ARCHIVE_OWNER_USERNAME,
        )

    @override_settings(POD_ARCHIVE_AFFILIATION=["faculty"])
    def test_archive_action(self):
        """Test archive option in the form"""
        # Connect the user
        self.client.force_login(self.user)

        # Simulates the submission of the form with archive action
        response = self.client.post(
            f"/video/valid/form/respite/{self.video1.slug}/",
            {"action": "Archive"},
            follow=True,
        )
        self.assertContains(
            response, _("This video is not approaching its obsolescence date.")
        )

        self.video1.date_delete = date.today() + timedelta(days=30)
        self.video1.save(update_fields=["date_delete"])

        # Simulates the submission of the form with extend action
        response = self.client.post(
            f"/video/valid/form/respite/{self.video1.slug}/",
            {"action": "Archive"},
            follow=True,
        )
        from pod.video.utils import is_archiving_authorized

        print("is_archiving_authorized = %s" % is_archiving_authorized(self.video1))
        self.assertContains(response, _("Are you sure you want to archive this video?"))

        print("--->  test_archive_action of ValidFormRespitTestCase: OK")

    @override_settings(POD_ARCHIVE_AFFILIATION=["faculty"])
    def test_archive_option_hidden_if_user_not_authorized(self):
        """Test archive option is hidden when user affiliation is not allowed."""
        self.video1.date_delete = date.today() + timedelta(days=50)
        self.video1.save()

        self.user.owner.affiliation = "student"
        self.user.owner.save()
        self.client.force_login(self.user)

        response = self.client.get(f"/video/respite/{self.video1.slug}/")

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'value="Archive"')

    @override_settings(POD_ARCHIVE_AFFILIATION=["faculty"])
    def test_archive_action_forbidden_if_user_not_authorized(self):
        """Test archive action returns bad request when user is not allowed."""
        self.user.owner.affiliation = "student"
        self.user.owner.save()
        self.client.force_login(self.user)

        response = self.client.post(
            f"/video/valid/form/respite/{self.video1.slug}/",
            {"action": "Archive"},
            follow=True,
        )
        self.assertContains(
            response, _("This video is not approaching its obsolescence date.")
        )

        self.video1.date_delete = date.today() + timedelta(days=30)
        self.video1.save(update_fields=["date_delete"])
        response = self.client.post(
            f"/video/valid/form/respite/{self.video1.slug}/",
            {"action": "Archive"},
            follow=True,
        )
        self.assertContains(response, _("This action is forbidden."))

    @override_settings(PROLONGATION_GRANTED=True)
    def test_extend_action(self):
        """Test extend option in the form"""
        ACCOMMODATION_YEARS = getattr(settings, "ACCOMMODATION_YEARS", {"faculty": 1})
        add_year = self.video1.get_date_delete_for_affiliation(ACCOMMODATION_YEARS)
        date1 = date.today() + timedelta(days=add_year * 365)
        self.assertEqual(self.video1.date_delete, date1)

        # Connect the user
        self.client.force_login(self.user)

        # Simulates the submission of the form with extend action
        response = self.client.post(
            f"/video/valid/form/respite/{self.video1.slug}/",
            {"action": "Extend"},
            follow=True,
        )
        self.assertContains(
            response, _("This video is not approaching its obsolescence date.")
        )

        self.video1.date_delete = date.today() + timedelta(days=30)
        self.video1.save(update_fields=["date_delete"])

        # Simulates the submission of the form with extend action
        response = self.client.post(
            f"/video/valid/form/respite/{self.video1.slug}/",
            {"action": "Extend"},
            follow=True,
        )
        self.assertContains(
            response, _("Are you sure to want to extend this video life span?")
        )

        print("--->  test_extend_action of ValidFormRespitTestCase: OK")

    def test_delete_action(self):
        """Test delete option in the form"""
        # Connect the user
        self.client.force_login(self.user)

        # Simulates the submission of the form with delete action
        response = self.client.post(
            f"/video/valid/form/respite/{self.video1.slug}/",
            {"action": "Delete"},
            follow=True,
        )
        self.assertContains(
            response, _("This video is not approaching its obsolescence date.")
        )

        self.video1.date_delete = date.today() + timedelta(days=30)
        self.video1.save(update_fields=["date_delete"])

        # Simulates the submission of the form with delete action
        response = self.client.post(
            f"/video/valid/form/respite/{self.video1.slug}/",
            {"action": "Delete"},
            follow=True,
        )

        self.assertContains(
            response, _("You cannot delete a media that is being encoded.")
        )

        print("--->  test_delete_action of ValidFormRespitTestCase: OK")

    def test_anonymous_action(self):
        """Test do respite actions when user is not connected."""
        # Simulates the submission of the form with delete action
        response = self.client.post(
            f"/video/valid/form/respite/{self.video1.slug}/",
            {"action": "Archive"},
            follow=True,
        )
        self.assertContains(response, _("You are not logged in. Please log in first."))
        response = self.client.post(
            f"/video/valid/form/respite/{self.video1.slug}/",
            {"action": "Extend"},
            follow=True,
        )
        self.assertContains(response, _("You are not logged in. Please log in first."))
        response = self.client.post(
            f"/video/valid/form/respite/{self.video1.slug}/",
            {"action": "Delete"},
            follow=True,
        )
        self.assertContains(response, _("You are not logged in. Please log in first."))
        print("--->  test_anonymous_action of ValidFormRespitTestCase: OK")

    @patch("pod.video.views.ENABLE_PAGE_OBSO_MAIL", True)
    def test_go_prolong_action(self):
        """Test extend confirmation by the form"""
        self.video1.date_delete = date.today() + timedelta(days=50)
        self.video1.save(update_fields=["date_delete"])

        # Connect the user
        self.client.force_login(self.user)

        response = self.client.post(f"/video/go/prolong/{self.video1.slug}/")
        self.assertEqual(response.get("Location"), f"/video/{self.video1.slug}/")
        vid = Video.objects.get(id=1)

        self.assertEqual(vid.date_delete, date.today() + timedelta(days=365 + 50))

        print("--->  test_go_prolong_action of ValidFormRespitTestCase: OK")

    @patch("pod.video.views.ENABLE_PAGE_OBSO_MAIL", True)
    @override_settings(POD_ARCHIVE_AFFILIATION=["faculty"])
    def test_go_archive_action(self):
        """Test archive confirmation by the form"""
        self.video1.date_delete = date.today() + timedelta(days=50)
        self.video1.save(update_fields=["date_delete"])

        self.assertEqual(self.video1.owner, self.user)
        # Connect the user
        self.client.force_login(self.user)

        response = self.client.post(f"/video/go/archive/{self.video1.slug}/")
        self.assertEqual(response.get("Location"), "/video/dashboard/")
        vid = Video.objects.get(id=1)
        self.assertEqual(vid.owner, self.archive_user)

        print("--->  test_go_archive_action of ValidFormRespitTestCase: OK")

    def test_check_csv_header_action(self):
        """Test check_csv_header in utils.py directly"""
        initial_content = "col1;col2\nvalue1;value2\n"

        with tempfile.NamedTemporaryFile(mode="w+", delete=False) as tmp:
            tmp.write(initial_content)
            tmp_path = tmp.name

        check_csv_header(tmp_path, ["col1", "col2", "col3"])

        with open(tmp_path, "r") as f:
            first_line = f.readline()

        self.assertEqual(first_line, "col1;col2;col3\n")

    def test_read_csv_action(self):
        """Test read_archived_csv in utils.py directly"""
        csv_content = "2024-01-01;John Doe;john@example.com;Affil;Estab;123;Title;url;type;2024-01-02\n"

        with tempfile.NamedTemporaryFile(
            mode="w+", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(csv_content)
            tmp_path = tmp.name

        with patch("pod.video.utils.ARCHIVE_CSV", tmp_path):
            result = read_archived_csv()

        self.assertIn("123", result)
        self.assertEqual(result["123"]["User name"], "John Doe")

    @patch("pod.video.utils.move_video_to_archive")
    @patch("pod.video.utils.copy_archive_to")
    @patch("pod.video.utils.export_complement")
    @patch("pod.video.utils.store_as_dublincore")
    @patch("pod.video.utils.os.makedirs")
    def test_archive_pack_move_and_real_mode(
        self,
        mock_makedirs,
        mock_store_dc,
        mock_export,
        mock_copy_archive,
        mock_move_archive,
    ):
        archive_pack("/tmp/test", "John", self.video1, only_copy=False, dry_mode=False)

        # ✅ Folder created
        mock_makedirs.assert_called_once_with("/tmp/test", exist_ok=True)

        # ✅ Dublincore generated with object
        mock_store_dc.assert_called_once_with(self.video1, "/tmp/test", "John")

        # ✅ Move called with object
        mock_export.assert_any_call("/tmp/test", "Video", [self.video1], False)

        # Check if dry_mode=False is well spread everywhere
        for call in mock_export.call_args_list:
            self.assertFalse(call.args[-1])

        # ❌ No copy
        mock_copy_archive.assert_not_called()

        # ✅ Move called with object
        mock_move_archive.assert_called_once_with("/tmp/test", self.video1, False)

    def tearDown(self):
        """Cleanup all created stuffs."""
        try:
            os.remove("%s/%s.csv" % (settings.LOG_DIRECTORY, "archived"))
        except FileNotFoundError:
            pass
