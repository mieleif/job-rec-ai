"""Un connecteur par ATS, et non un scraper par site : 1 connecteur = N entreprises."""

from job_rec_ai.connectors.base import Connector
from job_rec_ai.connectors.smartrecruiters import SmartRecruitersConnector
from job_rec_ai.connectors.workday import WorkdayConnector

REGISTRY: dict[str, Connector] = {
    c.name: c for c in (WorkdayConnector(), SmartRecruitersConnector())
}

__all__ = ["REGISTRY", "Connector"]
