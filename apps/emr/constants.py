"""Choice sets and lightweight catalogs for the EMR MVP.

The goal here is to keep common clinical and Jamaican-specific data close to
the app, readable in plain Python, and easy to extend without hunting through
templates or views.
"""

from __future__ import annotations


PARISH_CHOICES = [
    ("Kingston", "Kingston"),
    ("St. Andrew", "St. Andrew"),
    ("St. Thomas", "St. Thomas"),
    ("Portland", "Portland"),
    ("St. Mary", "St. Mary"),
    ("St. Ann", "St. Ann"),
    ("Trelawny", "Trelawny"),
    ("St. James", "St. James"),
    ("Hanover", "Hanover"),
    ("Westmoreland", "Westmoreland"),
    ("St. Elizabeth", "St. Elizabeth"),
    ("Manchester", "Manchester"),
    ("Clarendon", "Clarendon"),
    ("St. Catherine", "St. Catherine"),
]

ORGANISATION_TYPE_CHOICES = [
    ("private_clinic", "Private clinic"),
    ("public_health_centre", "Public health centre"),
    ("private_hospital", "Private hospital"),
    ("community_health", "Community health service"),
]

MEMBERSHIP_ROLE_CHOICES = [
    ("doctor", "Doctor"),
    ("nurse", "Nurse"),
    ("receptionist", "Receptionist"),
    ("admin", "Organisation admin"),
    ("system_admin", "System admin"),
]

PATIENT_SEX_CHOICES = [
    ("male", "Male"),
    ("female", "Female"),
    ("intersex", "Intersex"),
    ("unknown", "Unknown"),
]

LANGUAGE_CHOICES = [
    ("English", "English"),
    ("Jamaican Patois", "Jamaican Patois"),
]

CONSENT_METHOD_CHOICES = [
    ("written", "Written"),
    ("verbal", "Verbal"),
    ("electronic", "Electronic"),
]

APPOINTMENT_STATUS_CHOICES = [
    ("scheduled", "Scheduled"),
    ("checked_in", "Checked in"),
    ("triage", "In triage"),
    ("with_doctor", "With doctor"),
    ("complete", "Complete"),
    ("cancelled", "Cancelled"),
]

ENCOUNTER_TYPE_CHOICES = [
    ("acute", "Acute"),
    ("chronic_followup", "Chronic follow-up"),
    ("antenatal", "Antenatal"),
    ("well_child", "Well child"),
    ("emergency", "Emergency"),
    ("immunisation", "Immunisation"),
    ("school_health", "School health"),
    ("home_visit", "Home visit"),
    ("telehealth", "Telehealth"),
]

ENCOUNTER_STATUS_CHOICES = [
    ("draft", "Draft"),
    ("signed", "Signed"),
    ("amended", "Amended"),
]

ALLERGY_TYPE_CHOICES = [
    ("drug", "Drug"),
    ("food", "Food"),
    ("environmental", "Environmental"),
    ("other", "Other"),
]

ALLERGY_SEVERITY_CHOICES = [
    ("mild", "Mild"),
    ("moderate", "Moderate"),
    ("severe", "Severe"),
    ("anaphylaxis", "Anaphylaxis"),
]

ALLERGY_STATUS_CHOICES = [
    ("active", "Active"),
    ("inactive", "Inactive"),
    ("unconfirmed", "Unconfirmed"),
]

DIAGNOSIS_STATUS_CHOICES = [
    ("active", "Active"),
    ("resolved", "Resolved"),
    ("chronic", "Chronic"),
    ("suspected", "Suspected"),
]

MEDICATION_STATUS_CHOICES = [
    ("active", "Active"),
    ("discontinued", "Discontinued"),
    ("completed", "Completed"),
    ("on_hold", "On hold"),
]

ROUTE_CHOICES = [
    ("oral", "Oral"),
    ("IV", "IV"),
    ("IM", "IM"),
    ("SC", "SC"),
    ("topical", "Topical"),
    ("inhaled", "Inhaled"),
    ("sublingual", "Sublingual"),
    ("rectal", "Rectal"),
    ("ophthalmic", "Ophthalmic"),
]

REFERRAL_URGENCY_CHOICES = [
    ("routine", "Routine"),
    ("urgent", "Urgent"),
    ("emergency", "Emergency"),
]

REFERRAL_STATUS_CHOICES = [
    ("draft", "Draft"),
    ("sent", "Sent"),
    ("received", "Received"),
    ("responded", "Responded"),
    ("cancelled", "Cancelled"),
]

IMMUNISATION_SITE_CHOICES = [
    ("left_arm", "Left arm"),
    ("right_arm", "Right arm"),
    ("left_thigh", "Left thigh"),
    ("right_thigh", "Right thigh"),
]

IMMUNISATION_ROUTE_CHOICES = [
    ("IM", "IM"),
    ("SC", "SC"),
    ("oral", "Oral"),
]

COMMON_ICD10_CODES = [
    ("I10", "Essential (primary) hypertension"),
    ("E11.9", "Type 2 diabetes mellitus without complications"),
    ("J06.9", "Acute upper respiratory infection, unspecified"),
    ("K52.9", "Noninfective gastroenteritis and colitis, unspecified"),
    ("J45.909", "Asthma, unspecified"),
    ("E78.5", "Hyperlipidaemia, unspecified"),
    ("N39.0", "Urinary tract infection, site not specified"),
    ("Z34.9", "Supervision of normal pregnancy, unspecified"),
]

COMMON_DRUGS = [
    {"generic": "Amlodipine", "brand": "Calchek", "ven": True},
    {"generic": "Metformin", "brand": "Glucophage", "ven": True},
    {"generic": "Losartan", "brand": "Cozaar", "ven": True},
    {"generic": "Hydrochlorothiazide", "brand": "Hydrodiuril", "ven": True},
    {"generic": "Paracetamol", "brand": "Panadol", "ven": True},
    {"generic": "Salbutamol", "brand": "Ventolin", "ven": True},
    {"generic": "Atorvastatin", "brand": "Apo-Atorvastatin", "ven": True},
    {"generic": "Aspirin", "brand": "Aspirin-Mac", "ven": True},
]

COMMON_SPECIALTIES = [
    "General Practice",
    "Internal Medicine",
    "Paediatrics",
    "Obstetrics & Gynaecology",
    "Cardiology",
    "Family Medicine",
]
