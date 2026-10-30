"""Faux serveurs ATS pour tester fetch sans réseau (httpx.MockTransport).

Les réponses sont SYNTHÉTIQUES : elles imitent la forme des API Workday et SmartRecruiters,
réduite aux champs que lisent nos connecteurs. Les vraies réponses, elles, vont dans
tests/fixtures/<ats>.json (commande `job-rec-ai fixture`).
"""

import json

import httpx

WD = "https://acme.wd3.myworkdayjobs.com"
WD_API = f"{WD}/wday/cxs/acme/Acme_Careers"


def workday_detail(path, title, location, extra=(), req="R1"):
    return {
        "jobPostingInfo": {
            "id": f"id-{req}", "title": title, "jobReqId": req,
            "jobDescription": "<p>We are looking for an <b>engineer</b> to join our team.</p>",
            "location": location, "additionalLocations": list(extra),
            "startDate": "2026-10-01", "timeType": "Full time",
            "externalUrl": f"{WD}/Acme_Careers{path}",
        },
        "hiringOrganization": {"name": "Acme Holding SA"},
    }


WORKDAY_LIST = [
    {"title": "Data Engineer", "externalPath": "/job/Geneva/Data-Engineer_R1",
     "locationsText": "Geneva"},
    {"title": "Plant Manager", "externalPath": "/job/Basel/Plant-Manager_R2",
     "locationsText": "Basel"},
    {"title": "Comptable 80-100%", "externalPath": "/job/Multi/Comptable_R3",
     "locationsText": "2 Locations"},
]
WORKDAY_DETAILS = {
    "/job/Geneva/Data-Engineer_R1": workday_detail("/job/Geneva/Data-Engineer_R1",
                                                   "Data Engineer", "Geneva", req="R1"),
    "/job/Multi/Comptable_R3": workday_detail("/job/Multi/Comptable_R3", "Comptable 80-100%",
                                              "Zürich", extra=["Lausanne"], req="R3"),
}


def workday_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/robots.txt":
        return httpx.Response(404)
    if path == "/wday/cxs/acme/Acme_Careers/jobs":
        body = json.loads(request.content)
        page = WORKDAY_LIST[body["offset"]:body["offset"] + body["limit"]]
        # Comme le vrai Workday : le total n'est renvoyé que sur la première page
        return httpx.Response(200, json={"total": len(WORKDAY_LIST) if body["offset"] == 0 else 0,
                                         "jobPostings": page})
    suffix = path.removeprefix("/wday/cxs/acme/Acme_Careers")
    if suffix in WORKDAY_DETAILS:
        return httpx.Response(200, json=WORKDAY_DETAILS[suffix])
    return httpx.Response(404)


SR_API = "https://api.smartrecruiters.com/v1/companies/ACME"


def sr_detail(pid, name, city, region="GE"):
    return {
        "id": pid, "name": name, "releasedDate": "2026-09-15T08:00:00.000Z",
        "location": {"city": city, "region": region, "country": "ch"},
        "typeOfEmployment": {"label": "Full-time"},
        "postingUrl": f"https://jobs.smartrecruiters.com/ACME/{pid}-x",
        "jobAd": {"sections": {
            "companyDescription": {"text": "<p>ACME est une entreprise genevoise.</p>"},
            "jobDescription": {"text": "<p>Vous développerez nos <b>pipelines</b>.</p>"},
            "qualifications": {"text": "<ul><li>Python</li><li>SQL</li></ul>"},
        }},
    }


SR_LIST = [
    {"id": "1", "name": "Ingénieur de données", "location": {"city": "Meyrin", "region": "GE",
                                                            "country": "ch"}},
    {"id": "2", "name": "Sales Manager", "location": {"city": "Zürich", "region": "ZH",
                                                     "country": "ch"}},
]
SR_DETAILS = {"1": sr_detail("1", "Ingénieur de données", "Meyrin"),
              "2": sr_detail("2", "Sales Manager", "Zürich", "ZH")}


def smartrecruiters_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/robots.txt":
        return httpx.Response(200, text="User-agent: *\nAllow: /\n")
    if path == "/v1/companies/ACME/postings":
        offset = int(request.url.params["offset"])
        return httpx.Response(200, json={"totalFound": len(SR_LIST),
                                         "content": SR_LIST[offset:offset + 100]})
    pid = path.rsplit("/", 1)[-1]
    return httpx.Response(200, json=SR_DETAILS[pid])


def router(request: httpx.Request) -> httpx.Response:
    if request.url.host == "acme.wd3.myworkdayjobs.com":
        return workday_handler(request)
    if request.url.host == "api.smartrecruiters.com":
        return smartrecruiters_handler(request)
    return httpx.Response(503)  # tout autre hôte : « serveur en panne »


def transport(handler=router) -> httpx.MockTransport:
    return httpx.MockTransport(handler)
