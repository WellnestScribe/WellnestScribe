from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import DoctorProfile
from emr.models import AuditLog, OrganisationMembership, Patient
from scribe.models import ScribeSession


class EMRSmokeTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="doctor1",
            password="testpass123",
            email="doctor@example.com",
        )
        DoctorProfile.objects.create(
            user=self.user,
            full_name="Dr Test User",
            facility="Mandeville Health Centre",
            role=DoctorProfile.ROLE_ADMIN,
        )
        self.client.login(username="doctor1", password="testpass123")

    def test_dashboard_bootstraps_default_organisation(self):
        response = self.client.get(reverse("emr:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(OrganisationMembership.objects.filter(user=self.user, is_default=True).exists())

    def test_patient_registration_creates_patient_and_audit_log(self):
        self.client.get(reverse("emr:dashboard"))
        response = self.client.post(
            reverse("emr:patient_create"),
            {
                "legal_first_name": "Maya",
                "legal_last_name": "Brown",
                "preferred_name": "Maya",
                "date_of_birth": "1990-01-15",
                "sex": "female",
                "gender_identity": "",
                "nhf_card_number": "NHF-12345",
                "trn": "",
                "nids_number": "",
                "street_address": "",
                "community": "Mandeville",
                "district": "Northern",
                "parish": "Manchester",
                "phone_primary": "8765551212",
                "phone_secondary": "",
                "phone_is_whatsapp": "on",
                "email": "",
                "emergency_contact_name": "",
                "emergency_contact_relationship": "",
                "emergency_contact_phone": "",
                "next_of_kin_name": "",
                "next_of_kin_relationship": "",
                "nhf_card_programme": "",
                "private_insurer_name": "",
                "private_policy_number": "",
                "occupation": "",
                "ethnicity": "",
                "nationality": "Jamaican",
                "language_preference": "English",
                "blood_group": "",
                "herbal_history": "",
                "consent_given": "on",
                "consent_date": "",
                "consent_method": "written",
                "deceased": "",
                "deceased_date": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        patient = Patient.objects.get(legal_first_name="Maya", legal_last_name="Brown")
        self.assertEqual(patient.parish, "Manchester")
        self.assertTrue(AuditLog.objects.filter(resource_type="patient", resource_id=str(patient.pk)).exists())

    def test_encounter_create_view_accepts_scribe_seed(self):
        membership = self.user.organisation_memberships.first()
        if membership is None:
            self.client.get(reverse("emr:dashboard"))
            membership = self.user.organisation_memberships.get(is_default=True)

        patient = Patient.objects.create(
            organisation=membership.organisation,
            legal_first_name="Jon",
            legal_last_name="Clarke",
            date_of_birth="1985-06-01",
            sex="male",
            created_by=self.user,
            updated_by=self.user,
        )
        session = ScribeSession.objects.create(
            doctor=self.user,
            title="HTN follow-up",
            patient_name="Jon Clarke",
            chief_complaint="BP review",
            transcript="Patient reports adherence to amlodipine and no headaches.",
            status="review",
            note_format="soap",
            length_mode="normal",
        )
        response = self.client.get(
            reverse("emr:encounter_create", args=[patient.pk]) + f"?scribe={session.pk}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "HTN follow-up")
