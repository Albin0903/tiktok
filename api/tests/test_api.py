import json

from fastapi.testclient import TestClient
import polars as pl
import pytest

from api.main import HouseholdProfile, create_app, simulate_profile
from engine.household_social import HouseholdInputs, simulate_social
from engine.reforms.plf2027_complet_demo import DETAIL_NAME, REFORM_ID, SUMMARY_NAME


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    processed = tmp_path_factory.mktemp("distribution")
    pl.DataFrame({"menage_id": [1], "decile": [3], "gain_ir_eur": [12.0], "poids": [10.0]}).write_parquet(
        processed / DETAIL_NAME
    )
    (processed / SUMMARY_NAME).write_text(json.dumps({"reform_id": REFORM_ID, "taille_echantillon": 1}), encoding="utf-8")
    app = create_app(processed)
    with TestClient(app) as http:
        yield http


def test_api_matches_openfisca_and_returns_social_lines(client):
    body = {"revenu_net_imposable_mensuel": 1400, "age": 35, "statut": "salarie_non_cadre", "enfants": 2}
    profile = HouseholdProfile.model_validate(body)
    expected = simulate_profile(profile, client.app.state.baseline, client.app.state.reform)
    response = client.post("/api/simulate", json=body)
    assert response.status_code == 200
    assert response.json() == expected
    lines = {line["poste"]: line for line in expected["lignes"]}
    assert lines["impot_revenu"]["gel_eur"] == 0
    for label in ("csg_crds", "cotisations", "prime_activite", "aide_logement", "allocations_familiales"):
        assert lines[label]["gel_eur"] > 0
    assert lines["revenu_disponible"]["gel_eur"] > 0
    assert expected["hypotheses_appliquees"]["loyer_mensuel"] == 650
    assert expected["hypotheses_appliquees"]["zone_apl"] == 2


def test_custom_housing_and_gross_assumptions(client):
    body = {
        "revenu_net_imposable_mensuel": 1300, "age": 31, "statut": "salarie_non_cadre",
        "zone_apl": 1, "loyer_mensuel": 450, "logement_conventionne": True, "revenu_brut_mensuel": 1650,
    }
    response = client.post("/api/simulate", json=body)
    assert response.status_code == 200
    assumptions = response.json()["hypotheses_appliquees"]
    assert assumptions["loyer_mensuel"] == 450
    assert assumptions["zone_apl"] == 1
    assert assumptions["logement_conventionne"]
    assert assumptions["brut_saisi"]
    assert assumptions["revenu_brut_mensuel"] == 1650
    lines = {line["poste"]: line for line in response.json()["lignes"]}
    assert lines["aide_logement"]["gel_eur"] > 0


@pytest.mark.parametrize("profile", [
    HouseholdInputs(1400, 35, "salarie_non_cadre", children=2),
    HouseholdInputs(6700, 49, "salarie_cadre", couple=True, children=2, housing="proprietaire"),
    HouseholdInputs(1650, 70, "retraite"),
    HouseholdInputs(1850, 40, "independant", children=1),
])
def test_optimized_profile_agrees_with_both_full_scenarios(client, profile):
    state = client.app.state
    fast = simulate_social(profile, state.baseline, state.reform)
    reference = simulate_social(profile, state.baseline, state.reform, prune_ineligible=False)
    for result, expected in zip(fast[:2], reference[:2]):
        assert result == pytest.approx(expected, rel=0, abs=0.01)
    assert fast[2] == reference[2]


def test_unemployment_fast_gross_preserves_full_social_results(client):
    profile = HouseholdInputs(1000, 37, "chomeur", children=1)
    state = client.app.state
    fast = simulate_social(profile, state.baseline, state.reform)
    reference = simulate_social(profile, state.baseline, state.reform, fast_unemployment=False)
    assert fast == reference


def test_distribution_and_local_cors(client):
    response = client.get(f"/api/distribution/{REFORM_ID}?limit=1")
    assert response.status_code == 200
    assert response.json()["points"] == [{"menage_id": 1, "decile": 3, "gain_ir_eur": 12.0, "poids": 10.0}]
    assert client.get("/api/distribution/inconnue").status_code == 404
    preflight = client.options("/api/simulate", headers={
        "Origin": "http://127.0.0.1:3000", "Access-Control-Request-Method": "POST",
    })
    assert preflight.headers["access-control-allow-origin"] == "http://127.0.0.1:3000"


def test_invalid_income_is_rejected(client):
    response = client.post("/api/simulate", json={
        "revenu_net_imposable_mensuel": 100, "age": 37, "statut": "inactif",
    })
    assert response.status_code == 422
