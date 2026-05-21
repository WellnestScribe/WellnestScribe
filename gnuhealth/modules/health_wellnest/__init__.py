from trytond.pool import Pool
from . import health_wellnest


def register():
    Pool.register(
        health_wellnest.Patient,
        health_wellnest.WellnestSession,
        module="health_wellnest",
        type_="model",
    )
    Pool.register(
        health_wellnest.OpenWellnestWizard,
        module="health_wellnest",
        type_="wizard",
    )
