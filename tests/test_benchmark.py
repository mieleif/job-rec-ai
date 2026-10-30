from job_rec_ai.benchmark import company_key, compare


def test_company_key_ignore_la_forme_juridique():
    assert company_key("Rolex SA") == company_key("rolex") == "rolex"
    assert company_key("Philip Morris International") == "philip morris"


def test_compare_rappel_et_entreprises_non_suivies():
    leaderboard = [("Rolex SA", 40), ("Hays", 120), ("CERN", 10)]
    rows = compare(leaderboard, ours={"Rolex": 30}, tracked=["Rolex", "CERN"])
    by_name = {r.company: r for r in rows}
    assert by_name["Rolex"].recall == 0.75
    assert by_name["CERN"].ours == 0 and by_name["CERN"].recall == 0
    assert by_name["Hays"].ours is None  # un cabinet de recrutement : à ne PAS suivre
