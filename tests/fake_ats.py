"""Faux serveurs ATS pour tester fetch sans réseau (httpx.MockTransport).

Les réponses sont SYNTHÉTIQUES : elles imitent la forme de l'API Workday et des pages
publiques SmartRecruiters, réduite à ce que lisent nos connecteurs. Les vraies réponses,
elles, vont dans tests/fixtures/<ats>.json (commande `job-rec-ai fixture`).
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


SR_JOBS = "https://jobs.smartrecruiters.com/ACME"


def sr_link(pid, title, *details):
    spans = "".join(f"<span>{d}</span>" for d in details)
    return (f'<li><a href="{SR_JOBS}/{pid}-x" class="details js-job-ad-link">'
            f'<h4 class="job-title">{title}</h4><p class="job-desc">{spans}</p></a></li>')


def sr_group(title, *links):
    return (f'<section class="opening"><h3 class="opening-title">{title}</h3>'
            f'<ul>{"".join(links)}</ul></section>')


def sr_ad(title, city, region):
    """Une annonce telle que la sert jobs.smartrecruiters.com, réduite aux microdonnées."""
    return f"""<html><body><header>gabarit de page</header><main>
<h1 itemprop="title">{title}</h1>
<li itemprop="jobLocation"><span itemprop="address">
<meta itemprop="addressCountry" content="Switzerland">
<meta itemprop="addressLocality" content="{city}">
<meta itemprop="addressRegion" content="{region}"></span></li>
<li itemprop="employmentType">Temps complet</li>
<meta itemprop="datePosted" content="2026-09-15T08:00:00.000Z">
<div itemprop="description">
<section id="st-jobDescription"><p>Vous développerez nos <b>pipelines</b>.</p></section>
<section id="st-qualifications"><ul><li>Python</li><li>SQL</li></ul></section>
<section id="st-videos"><p>Regardez notre vidéo</p></section>
</div></main></body></html>"""


# Liste sur deux pages, groupées des deux façons rencontrées en vrai : page 1 par service
# (le lieu est sur l'offre, comme HUG), page 2 par lieu (le lieu est l'en-tête, comme Vitol).
# Zurich est écarté par le filtre de lieu sans télécharger l'annonce.
SR_PAGES = {
    "/ACME": '<div data-groups-pages="2">' + sr_group(
        "Data", sr_link("1", "Ingénieur de données", "Meyrin, GE", "Full-time")) + "</div>",
    "/ACME/api/groups": sr_group("Zürich, Switzerland", sr_link("2", "Sales Manager", "Full-time"))
    + sr_group("Lausanne, Switzerland", sr_link("3", "Contrôleur de gestion", "Full-time"))
    # La même offre listée sous deux lieux : Lausanne d'abord, puis Londres (dernier vu)
    + sr_group("London, United Kingdom", sr_link("3", "Contrôleur de gestion", "Full-time")),
    "/AUTRE": "<html><body>Le site carrière maison d'Autre SA</body></html>",
}
SR_ADS = {"/ACME/1-x": sr_ad("Ingénieur de données", "Meyrin", "Geneva"),
          "/ACME/2-x": sr_ad("Sales Manager", "Zürich", "Zurich"),
          "/ACME/3-x": sr_ad("Contrôleur de gestion", "Lausanne", "Vaud")}


def smartrecruiters_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/robots.txt":
        return httpx.Response(404)  # comme les vrais sites publics : pas de robots.txt
    pages = SR_PAGES if request.url.host == "careers.smartrecruiters.com" else SR_ADS
    if path in pages:
        return httpx.Response(200, text=pages[path])
    return httpx.Response(404)


def router(request: httpx.Request) -> httpx.Response:
    if request.url.host == "acme.wd3.myworkdayjobs.com":
        return workday_handler(request)
    if request.url.host in ("careers.smartrecruiters.com", "jobs.smartrecruiters.com"):
        return smartrecruiters_handler(request)
    return httpx.Response(503)  # tout autre hôte : « serveur en panne »


def transport(handler=router) -> httpx.MockTransport:
    return httpx.MockTransport(handler)
