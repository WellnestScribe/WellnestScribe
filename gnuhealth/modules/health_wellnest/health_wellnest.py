from trytond.model import ModelSQL, ModelView, fields
from trytond.pool import Pool, PoolMeta
from trytond.transaction import Transaction
from trytond.wizard import Wizard, StateAction

WELLNEST_BASE_URL = "http://localhost:9093"


class Patient(metaclass=PoolMeta):
    "Extend GNU Health patient with WellnestScribe sessions"
    __name__ = "gnuhealth.patient"

    wellnest_sessions = fields.One2Many(
        "gnuhealth.wellnest.session",
        "patient",
        "WellnestScribe Sessions",
    )

    @classmethod
    @ModelView.button_action("health_wellnest.act_open_wellnest_wizard")
    def open_wellnest(cls, patients):
        pass


class WellnestSession(ModelSQL, ModelView):
    "WellnestScribe Session"
    __name__ = "gnuhealth.wellnest.session"

    patient = fields.Many2One(
        "gnuhealth.patient", "Patient", required=True, ondelete="CASCADE"
    )
    session_date = fields.Date("Session Date")
    chief_complaint = fields.Char("Chief Complaint")
    django_session_id = fields.Integer(
        "WellnestScribe Session ID",
        readonly=True,
    )
    encounter_id = fields.Char(
        "GNU Health Encounter ID",
        readonly=True,
    )
    status = fields.Selection(
        [
            ("draft", "Draft"),
            ("pushed", "Pushed to Encounter"),
            ("error", "Push Error"),
        ],
        "Status",
        required=True,
    )
    notes = fields.Text("Notes")
    review_url = fields.Function(
        fields.Char("Review in WellnestScribe"),
        "get_review_url",
    )

    @classmethod
    def default_status(cls):
        return "draft"

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._order = [("session_date", "DESC"), ("id", "DESC")]

    def get_review_url(self, name):
        if self.django_session_id:
            return f"{WELLNEST_BASE_URL}/scribe/sessions/{self.django_session_id}/review/"
        return ""


class OpenWellnestWizard(Wizard):
    "Open WellnestScribe for this patient"
    __name__ = "health_wellnest.open_wellnest"

    start_state = "open"
    open = StateAction("health_wellnest.act_wellnest_url")

    def do_open(self, action):
        patient_id = Transaction().context.get("active_id")
        action["url"] = f"{WELLNEST_BASE_URL}/scribe/new/?gnuhealth_patient_id={patient_id}"
        return action, {}
