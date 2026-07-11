"""Create demo patients with random Jamaican-flavoured details.

Usage:
    python manage.py seed_demo_patients            # 10 in the first organisation
    python manage.py seed_demo_patients --count 25 --org 3
"""
import random
from datetime import date

from django.core.management.base import BaseCommand

from emr.models import Organisation, Patient

FIRST_NAMES = [
    "Marlon", "Shanice", "Devon", "Kadian", "Rohan", "Tashana", "Andre", "Kemar",
    "Latoya", "Oneil", "Shantel", "Damion", "Kerry-Ann", "Romario", "Sasha",
    "Delroy", "Alecia", "Jermaine", "Nordia", "Craig", "Georgia", "Everton",
]
LAST_NAMES = [
    "Brown", "Campbell", "Clarke", "Bailey", "Grant", "Reid", "Williams", "Gordon",
    "Robinson", "Thompson", "Palmer", "Walker", "Henry", "Morgan", "Blake", "Powell",
    "Ellis", "Dixon", "McKenzie", "Nelson",
]
PARISHES = [
    "Kingston", "St. Andrew", "St. Catherine", "Clarendon", "Manchester",
    "St. Elizabeth", "Westmoreland", "St. James", "Trelawny", "St. Ann",
    "Portland", "St. Thomas", "St. Mary", "Hanover",
]
COMMUNITIES = ["Old Harbour", "Spanish Town", "May Pen", "Mandeville", "Santa Cruz", "Savanna-la-Mar", "Port Antonio"]


class Command(BaseCommand):
    help = "Create demo patients with random details for testing."

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=10)
        parser.add_argument("--org", type=int, default=None, help="Organisation id (defaults to the first).")

    def handle(self, *args, **opts):
        org = (
            Organisation.objects.filter(pk=opts["org"]).first()
            if opts["org"] else Organisation.objects.order_by("pk").first()
        )
        if org is None:
            self.stderr.write(self.style.ERROR("No organisation found. Open the EMR once to create one."))
            return

        created = 0
        for _ in range(opts["count"]):
            fn = random.choice(FIRST_NAMES)
            ln = random.choice(LAST_NAMES)
            year = random.randint(1948, 2022)
            dob = date(year, random.randint(1, 12), random.randint(1, 28))
            Patient.objects.create(
                organisation=org,
                legal_first_name=fn,
                legal_last_name=ln,
                date_of_birth=dob,
                sex=random.choice(["male", "female"]),
                parish=random.choice(PARISHES),
                community=random.choice(COMMUNITIES),
                trn=str(random.randint(100000000, 999999999)),
                nhf_card_number=str(random.randint(100000, 999999)),
                phone_primary="876" + str(random.randint(2000000, 9999999)),
            )
            created += 1
        self.stdout.write(self.style.SUCCESS(f"Created {created} demo patients in “{org.name}”."))
