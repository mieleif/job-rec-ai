"""Un connecteur par ATS, et non un scraper par site : 1 connecteur = N entreprises."""

from job_rec_ai.connectors.base import Connector
from job_rec_ai.connectors.cern import CernConnector
from job_rec_ai.connectors.cornerstone import CornerstoneConnector
from job_rec_ai.connectors.greenhouse import GreenhouseConnector
from job_rec_ai.connectors.jsonld import JsonLdConnector
from job_rec_ai.connectors.oracle import OracleConnector
from job_rec_ai.connectors.phenom import PhenomConnector
from job_rec_ai.connectors.prospective import ProspectiveConnector
from job_rec_ai.connectors.smartrecruiters import SmartRecruitersConnector
from job_rec_ai.connectors.successfactors import SuccessFactorsConnector
from job_rec_ai.connectors.taleo import TaleoConnector
from job_rec_ai.connectors.uncareers import UnCareersConnector
from job_rec_ai.connectors.workable import WorkableConnector
from job_rec_ai.connectors.workday import WorkdayConnector

REGISTRY: dict[str, Connector] = {
    c.name: c for c in (WorkdayConnector(), SmartRecruitersConnector(), GreenhouseConnector(),
                        SuccessFactorsConnector(), JsonLdConnector(), OracleConnector(),
                        TaleoConnector(), PhenomConnector(), UnCareersConnector(),
                        CernConnector(), WorkableConnector(), CornerstoneConnector(),
                        ProspectiveConnector())
}

__all__ = ["REGISTRY", "Connector"]
