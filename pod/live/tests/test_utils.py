import json

from django.test import TestCase
from django.contrib.auth.models import User


class LiveTestUtils(TestCase):
    fixtures = [
        "initial_data.json",
    ]

    def setUp(self):
        self.user = User.objects.create(username="pod", password="podword")

    def todo(self):
        self.assertEqual("WILL DO", True)
