from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import DoctorProfile
from emr.models import AuditLog, OrganisationMembership, Patient
from emr.services.scribe_import import build_scribe_import_bundle
from scribe.models import SOAPNote, ScribeSession


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

    def test_scribe_import_bundle_extracts_structured_fields(self):
        session = ScribeSession.objects.create(
            doctor=self.user,
            title="Chronic disease follow-up",
            chief_complaint="BP review",
            transcript=(
                "Blood pressure 140 over 90. Pulse 78. Temperature 37.2 celsius. "
                "Oxygen saturation 98 percent. Blood sugar 126 mg/dL. "
                "Weight 70 kg. Height 170 cm. Pain score 3 out of 10. "
                "Follow up in 2 weeks. Give 3 days sick leave. "
                "Patient uses cerasee tea."
            ),
            active_conditions="htn,dm",
            status="review",
            note_format="soap",
            length_mode="normal",
        )
        SOAPNote.objects.create(
            session=session,
            subjective="Patient is here for chronic follow-up and denies chest pain.",
            objective="Blood pressure 140 over 90. Pulse 78. SpO2 98 percent.",
            assessment="Essential hypertension. Type 2 diabetes mellitus without complications.",
            plan="Continue Amlodipine 5 mg oral once daily for 30 days.",
        )

        bundle = build_scribe_import_bundle(session, encounter_date=date(2026, 5, 13))

        self.assertEqual(bundle.encounter_initial["encounter_type"], "chronic_followup")
        self.assertEqual(bundle.encounter_initial["follow_up_date"].isoformat(), "2026-05-27")
        self.assertEqual(bundle.encounter_initial["sick_leave_start"].isoformat(), "2026-05-13")
        self.assertEqual(bundle.encounter_initial["sick_leave_end"].isoformat(), "2026-05-15")
        self.assertIn("cerasee tea", bundle.encounter_initial["herbal_remedies"].lower())
        self.assertEqual(bundle.vitals_initial["bp_systolic"], 140)
        self.assertEqual(bundle.vitals_initial["bp_diastolic"], 90)
        self.assertEqual(str(bundle.vitals_initial["blood_glucose_mmol"]), "7.0")
        self.assertEqual(bundle.diagnosis_initial[0]["icd10_code"], "I10")
        self.assertEqual(bundle.medication_initial[0]["drug_name_generic"], "Amlodipine")
        self.assertEqual(str(bundle.medication_initial[0]["dose_amount"]), "5")
        self.assertIn("converted to mmol/L", " ".join(bundle.flags))

    def test_encounter_create_prefills_vitals_diagnoses_and_medications_from_scribe(self):
        self.client.get(reverse("emr:dashboard"))
        membership = self.user.organisation_memberships.get(is_default=True)
        patient = Patient.objects.create(
            organisation=membership.organisation,
            legal_first_name="Tara",
            legal_last_name="Brown",
            date_of_birth="1988-03-10",
            sex="female",
            created_by=self.user,
            updated_by=self.user,
        )
        session = ScribeSession.objects.create(
            doctor=self.user,
            title="Diabetes review",
            chief_complaint="Blood sugar review",
            transcript=(
                "Blood pressure 138 over 84. Pulse 76. Glucose 7.4 mmol. "
                "Continue Metformin 500 mg oral twice daily for 30 days. "
                "Follow up in 1 month."
            ),
            active_conditions="dm",
            status="review",
            note_format="soap",
            length_mode="normal",
        )
        SOAPNote.objects.create(
            session=session,
            subjective="Patient attends for diabetes follow-up.",
            objective="Pulse 76. Blood pressure 138 over 84.",
            assessment="Type 2 diabetes mellitus without complications.",
            plan="Continue Metformin 500 mg oral twice daily for 30 days.",
        )

        response = self.client.get(
            reverse("emr:encounter_create", args=[patient.pk]) + f"?scribe={session.pk}"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["vitals_form"].initial["bp_systolic"], 138)
        self.assertEqual(str(response.context["vitals_form"].initial["blood_glucose_mmol"]), "7.4")
        self.assertEqual(
            response.context["diagnosis_formset"].forms[0].initial["icd10_code"],
            "E11.9",
        )
        self.assertEqual(
            response.context["medication_formset"].forms[0].initial["drug_name_generic"],
            "Metformin",
        )
        self.assertContains(response, "Auto-detected from the scribe transcript")
