"""Deterministic safety + RBAC regression tests.

These cover the highest-risk, non-AI logic: diagnosis coding guards (a wrong
coded diagnosis can harm a patient) and plan-based EMR gating. They are pure
functions, so they run fast and need no database. Run with:

    python manage.py test emr.test_safety
"""

from django.test import SimpleTestCase

from emr.models import Organisation
from emr.services.scribe_import import (
    _classify_diagnosis,
    extract_imaging_and_investigations,
)


class DiagnosisSafetyTests(SimpleTestCase):
    """The diabetes-denial incident must never regress."""

    def test_denied_condition_is_skipped(self):
        # "Denies diabetes" must NOT be coded as a diagnosis.
        decision, _ = _classify_diagnosis("Denies diabetes.", "diabetes", "")
        self.assertEqual(decision, "skip")

    def test_do_not_have_across_clause_is_skipped(self):
        decision, _ = _classify_diagnosis(
            "I have hypertension but I do not have diabetes.", "diabetes", ""
        )
        self.assertEqual(decision, "skip")

    def test_family_history_is_skipped(self):
        decision, _ = _classify_diagnosis("Father has diabetes.", "diabetes", "")
        self.assertEqual(decision, "skip")

    def test_confirmed_condition_is_coded(self):
        decision, _ = _classify_diagnosis("Type 2 diabetes on metformin.", "diabetes", "")
        self.assertEqual(decision, "code")

    def test_cross_clause_negation_does_not_suppress_other_symptom(self):
        # "no chest pain but has cough" -> the cough still codes.
        decision, _ = _classify_diagnosis("No chest pain but has cough.", "cough", "")
        self.assertEqual(decision, "code")

    def test_uncertain_wording_is_suspected(self):
        decision, status = _classify_diagnosis("Possible fracture of the ankle.", "fracture", "")
        self.assertEqual(decision, "code")
        self.assertEqual(status, "suspected")


class ImagingExtractionTests(SimpleTestCase):
    def test_extracts_real_studies(self):
        studies = [i["study"] for i in extract_imaging_and_investigations(
            "Plan: order a chest x-ray and CBC. Arrange abdominal ultrasound."
        )]
        self.assertIn("Chest X-ray", studies)
        self.assertIn("Complete blood count (CBC)", studies)
        self.assertIn("Abdominal ultrasound", studies)

    def test_no_phantom_match_on_plain_text(self):
        # A note with no imaging/labs must yield nothing (no false positives).
        studies = extract_imaging_and_investigations("Swelling developed during work; advised rest.")
        self.assertEqual(studies, [])

    def test_specific_study_wins_over_generic(self):
        studies = [i["study"] for i in extract_imaging_and_investigations("Order a chest x-ray.")]
        self.assertIn("Chest X-ray", studies)
        self.assertNotIn("X-ray", studies)  # generic suppressed by the specific one


class PlanGateTests(SimpleTestCase):
    """org.has_emr must gate EMR by plan (Scribe-only = no EMR)."""

    def test_scribe_only_has_no_emr(self):
        self.assertFalse(Organisation(subscription_tier="scribe").has_emr)

    def test_practice_has_emr(self):
        self.assertTrue(Organisation(subscription_tier="practice").has_emr)

    def test_emr_tier_has_emr(self):
        self.assertTrue(Organisation(subscription_tier="emr").has_emr)

    def test_trial_has_emr(self):
        self.assertTrue(Organisation(subscription_tier="trial").has_emr)
