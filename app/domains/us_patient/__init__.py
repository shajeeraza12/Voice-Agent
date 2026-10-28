"""US patient registration domain."""
from app.core.registry import Domain
from app.domains.us_patient import orm  # noqa: F401  (registers the table with the metadata)
from app.domains.us_patient.api import router
from app.domains.us_patient.tools import TOOLS

DOMAIN = Domain(name="us_patient", router=router, tools=TOOLS)
