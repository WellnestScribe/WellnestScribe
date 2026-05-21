"""Seed the DrugAlias table with common Jamaican brand <-> generic mappings.

Idempotent: re-running upserts. Run via:
    python manage.py seed_drug_aliases

These come from common pharmacy stock + Dr Adrian / pilot doctor feedback.
Extend in the Django admin — this seed only covers the bootstrap set.
"""

from django.core.management.base import BaseCommand

from scribe.models import DrugAlias


# (brand, generic, class, jamaican_common, notes)
SEED: list[tuple[str, str, str, bool, str]] = [
    # NSAIDs
    ("Voltarol", "Diclofenac", "NSAID", True, "Common OTC in Jamaica"),
    ("Vita-Cax", "Diclofenac", "NSAID", True, "Local brand"),
    ("Cataflam", "Diclofenac potassium", "NSAID", False, ""),
    ("Brufen", "Ibuprofen", "NSAID", True, ""),
    ("Advil", "Ibuprofen", "NSAID", True, ""),
    ("Motrin", "Ibuprofen", "NSAID", True, ""),
    ("Mobic", "Meloxicam", "NSAID", False, ""),
    ("Celebrex", "Celecoxib", "NSAID (COX-2)", False, ""),
    # Analgesics
    ("Panadol", "Paracetamol", "Analgesic / antipyretic", True, "Acetaminophen"),
    ("Tylenol", "Acetaminophen", "Analgesic / antipyretic", True, "Same as paracetamol"),
    ("Cafergot", "Ergotamine + caffeine", "Antimigraine", False, ""),
    ("Tramal", "Tramadol", "Opioid analgesic", True, ""),
    # Antihypertensives — ACE inhibitors
    ("Zestril", "Lisinopril", "ACE inhibitor", True, ""),
    ("Prinivil", "Lisinopril", "ACE inhibitor", False, ""),
    ("Tritace", "Ramipril", "ACE inhibitor", True, ""),
    ("Capoten", "Captopril", "ACE inhibitor", False, ""),
    # ARBs
    ("Cozaar", "Losartan", "ARB", True, ""),
    ("Diovan", "Valsartan", "ARB", True, ""),
    ("Micardis", "Telmisartan", "ARB", False, ""),
    ("Atacand", "Candesartan", "ARB", False, ""),
    # CCBs
    ("Norvasc", "Amlodipine", "Calcium channel blocker", True, ""),
    ("Adalat", "Nifedipine", "Calcium channel blocker", True, ""),
    ("Cardizem", "Diltiazem", "Calcium channel blocker", False, ""),
    # Beta blockers
    ("Tenormin", "Atenolol", "Beta blocker", True, ""),
    ("Lopressor", "Metoprolol", "Beta blocker", False, ""),
    ("Betaloc", "Metoprolol", "Beta blocker", True, ""),
    ("Inderal", "Propranolol", "Beta blocker (non-selective)", False, ""),
    # Diuretics
    ("Lasix", "Furosemide", "Loop diuretic", True, ""),
    ("HCTZ", "Hydrochlorothiazide", "Thiazide diuretic", True, ""),
    ("Aldactone", "Spironolactone", "K-sparing diuretic", True, ""),
    # Diabetes
    ("Glucophage", "Metformin", "Biguanide", True, ""),
    ("Diamicron", "Gliclazide", "Sulfonylurea", True, ""),
    ("Amaryl", "Glimepiride", "Sulfonylurea", True, ""),
    ("Januvia", "Sitagliptin", "DPP-4 inhibitor", False, ""),
    ("Jardiance", "Empagliflozin", "SGLT2 inhibitor", False, ""),
    ("Trulicity", "Dulaglutide", "GLP-1 agonist", False, ""),
    # Statins
    ("Lipitor", "Atorvastatin", "Statin", True, ""),
    ("Crestor", "Rosuvastatin", "Statin", True, ""),
    ("Zocor", "Simvastatin", "Statin", False, ""),
    # Anticoagulants / antiplatelet
    ("Aspirin", "Acetylsalicylic acid", "Antiplatelet", True, ""),
    ("Plavix", "Clopidogrel", "Antiplatelet", True, ""),
    ("Coumadin", "Warfarin", "Anticoagulant (VKA)", True, ""),
    ("Eliquis", "Apixaban", "DOAC", False, ""),
    ("Xarelto", "Rivaroxaban", "DOAC", False, ""),
    # PPIs / GI
    ("Losec", "Omeprazole", "PPI", True, ""),
    ("Nexium", "Esomeprazole", "PPI", True, ""),
    ("Pantoloc", "Pantoprazole", "PPI", False, ""),
    ("Zantac", "Ranitidine", "H2 blocker", True, "Withdrawn in many markets — flag"),
    # Antibiotics
    ("Amoxil", "Amoxicillin", "Penicillin antibiotic", True, ""),
    ("Augmentin", "Amoxicillin-clavulanate", "Penicillin + beta-lactamase inh", True, ""),
    ("Zithromax", "Azithromycin", "Macrolide", True, ""),
    ("Ciproxin", "Ciprofloxacin", "Fluoroquinolone", True, ""),
    ("Flagyl", "Metronidazole", "Nitroimidazole", True, ""),
    ("Bactrim", "Sulfamethoxazole-trimethoprim", "Sulfonamide", True, ""),
    # Asthma / COPD
    ("Ventolin", "Salbutamol", "SABA bronchodilator", True, ""),
    ("Seretide", "Salmeterol-fluticasone", "LABA + ICS", False, ""),
    # Antidepressants
    ("Prozac", "Fluoxetine", "SSRI", True, ""),
    ("Zoloft", "Sertraline", "SSRI", True, ""),
    # Thyroid
    ("Synthroid", "Levothyroxine", "Thyroid hormone", True, ""),
    ("Eltroxin", "Levothyroxine", "Thyroid hormone", True, ""),
]


class Command(BaseCommand):
    help = "Seed common Jamaican brand <-> generic drug aliases."

    def handle(self, *args, **opts):
        created, updated = 0, 0
        for brand, generic, klass, common, notes in SEED:
            obj, was_created = DrugAlias.objects.update_or_create(
                brand_name=brand,
                generic_name=generic,
                defaults={
                    "drug_class": klass,
                    "jamaican_common": common,
                    "notes": notes,
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1
        self.stdout.write(self.style.SUCCESS(
            f"Drug aliases: {created} created, {updated} updated. "
            f"Total now: {DrugAlias.objects.count()}."
        ))
