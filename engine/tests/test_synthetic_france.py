import numpy as np
import polars as pl
import pytest

from engine.reforms import get_tax_benefit_system
from engine.second_round.tes_passthrough import InputOutput, PriceShock, estimate_consumption_cost, read_input_output
from engine.synthetic.audit_macro import AUDIT_YEAR, calculate_tax
from engine.synthetic.build_synthetic_france import HOUSEHOLDS, OUTPUT, rake
from engine.synthetic.fetch_official_data import RAW_DIR, SOURCES
from engine.synthetic.fiscal_calibration import _impute_expenses, calibrate_moments
from engine.synthetic.official_margins import rank_groups, read_2042, read_census, read_ircom, read_ircom_bands, read_ircom_tail


def test_entropy_calibration_handles_multiple_tax_households() -> None:
    features = np.array([[1, 1, 0], [1, 1, 1], [1, 2, 0], [1, 3, 1]], dtype=float)
    targets = np.array([100, 157, 42], dtype=float)
    weights = calibrate_moments(np.full(4, 25.0), features, targets)
    assert (weights > 0).all()
    np.testing.assert_allclose(features.T @ weights, targets, rtol=1e-7)


def test_weighted_deciles_split_a_household_weight_at_boundaries() -> None:
    weights = np.array([90.0, 10.0])
    groups = list(rank_groups(np.array([20.0, 10.0]), weights))
    assert groups[0][0].tolist() == pytest.approx([0, 1])
    assert groups[-1][0].tolist() == pytest.approx([1 / 900, 0])
    for shares, fraction in groups:
        assert shares @ weights == pytest.approx(100 * fraction)
    tied = np.array([10.0, 10.0])
    weights = np.array([75.0, 25.0])
    for shares, fraction in rank_groups(tied, weights):
        assert shares.tolist() == pytest.approx([fraction, fraction])


def test_expense_imputation_uses_household_ids_and_numeric_foyer_indexes() -> None:
    records = pl.DataFrame({
        "menage_id": [24, 7], "enfants": [0, 11], "cohabitants_fiscaux": [0, 0],
        "age_enfant_impute": [10, 4], "age_reference": [30, 40], "poids": [3.0, 1.0],
    })
    indexes = sorted(range(11), key=str)
    tax = pl.DataFrame({
        "menage_id": [7] * 11 + [24],
        "foyer_fiscal_id": [f"m7_f{i}" for i in indexes] + ["m24_f0"],
        "imposition_commune": [i == 10 for i in indexes] + [False],
        "rfr_eur": [20_000.0] * 12,
    })
    imputed = _impute_expenses(
        records, tax, {"0AF": {"nombre": 1, "montant": 1}}, 4, 4, np.random.default_rng(0),
    )
    assert [case["caseF"] for case in imputed["cases_fiscales"][0]] == [0]
    assert [case["caseF"] for case in imputed["cases_fiscales"][1]] == [0] * 10 + [1]


def test_rake_reproduces_two_margins() -> None:
    records = pl.DataFrame({"age": ["jeune", "jeune", "jeune", "senior", "senior"], "housing": ["loué", "loué", "occupé", "loué", "occupé"]})
    margins = {"age": {"jeune": 60, "senior": 40}, "housing": {"loué": 30, "occupé": 70}}
    weights = rake(records, margins, 100)
    assert sum(weights) == pytest.approx(100)
    for column, targets in margins.items():
        for category, expected in targets.items():
            assert weights[(records[column] == category).to_numpy()].sum() == pytest.approx(expected)


def test_tes_propagates_a_cost_and_orders_the_range_for_a_reduction() -> None:
    model = InputOutput(("A", "B"), np.array([[0.0, 0.25], [0.0, 0.0]]))
    # Coefficients arbitraires pour ce test algébrique uniquement.
    shock = PriceShock("energie", {"A": -0.1}, {}, 0.5, 1.0, "Cas de test")
    result = estimate_consumption_cost(model, {"x": 100}, {"x": {"B": 1.0}}, [shock])
    assert result["cout_annuel_bas_eur"] == pytest.approx(-2.5)
    assert result["cout_annuel_haut_eur"] == pytest.approx(-1.25)
    assert result["calc_certainty"] == "yellow"


@pytest.mark.skipif(
    not all((RAW_DIR / source.filename).exists() for source in SOURCES) or not OUTPUT.exists(),
    reason="Ressources locales à générer avec fetch_official_data et build_synthetic_france",
)
def test_population_and_fiscal_reference_files() -> None:
    records = pl.read_parquet(OUTPUT)
    census = read_census(RAW_DIR)
    reference = read_ircom(RAW_DIR)
    assert records.height == HOUSEHOLDS
    assert records["menage_id"].n_unique() == HOUSEHOLDS
    assert records["poids"].sum() == pytest.approx(census["menages"])
    assert (records["poids"] * (records["adultes"] + records["enfants"])).sum() == pytest.approx(
        census["population_des_menages"], rel=0.02,
    )
    # SOURCE: IRCOM 2024, revenus 2023, totaux des 13 régions métropolitaines.
    assert reference["foyers_fiscaux"] == 39_626_015
    assert reference["impot_net_eur"] == pytest.approx(81_584_777_545, abs=1)
    fiscal_units = records["adultes"] + records["cohabitants_fiscaux"] - records["imposition_commune"].cast(pl.Int64)
    assert (records["poids"] * fiscal_units).sum() == pytest.approx(reference["foyers_fiscaux"])
    assert read_ircom_bands(RAW_DIR, 2024)["foyers_fiscaux"].sum() == read_ircom(RAW_DIR, 2024)["foyers_fiscaux"]
    assert read_ircom_tail(RAW_DIR, 2024)["foyers_fiscaux"].sum() == 1_414_342
    for code in ("7DB", "7GA", "7UF", "6NS"):
        assert read_2042(RAW_DIR, 2023)[code]["montant"] > 0
    tes = read_input_output(RAW_DIR / "tes_symetrique_a38_2022.xlsx")
    assert tes.domestic_coefficients.shape == (len(tes.branches), len(tes.branches))


def test_tax_audit_distinguishes_household_and_tax_units() -> None:
    records = pl.DataFrame({
        "menage_id": [1, 2],
        "activite": ["salarie_non_cadre", "retraite"],
        "revenu_declare_moyen": [100_000.0, 30_000.0],
        "adultes": [2, 2],
        "enfants": [1, 0],
        "structure": ["couple_enfants", "couple"],
        "age_reference": [40, 69],
        "imposition_commune": [False, True],
        "logement": ["locataire", "proprietaire"],
        "poids": [1.0, 1.0],
    })
    tax, unallocated = calculate_tax(records, get_tax_benefit_system(), AUDIT_YEAR)
    counts = tax.group_by("menage_id").len().sort("menage_id")
    assert counts["len"].to_list() == [2, 1]
    assert tax.filter(pl.col("menage_id") == 1)["impot_net_eur"].sum() > 0
    assert unallocated == 0


def test_capital_withheld_increases_rfr_without_adding_the_same_tax_twice() -> None:
    records = pl.DataFrame({
        "menage_id": [1], "activite": ["salarie_non_cadre"], "revenu_declare_moyen": [50_000.0],
        "adultes": [1], "enfants": [0], "structure": ["seul"], "age_reference": [43],
        "imposition_commune": [False], "logement": ["locataire"], "poids": [1.0],
    })
    system = get_tax_benefit_system()
    reference, _ = calculate_tax(records, system, AUDIT_YEAR)
    rules = system.parameters(AUDIT_YEAR).taxation_capital.prelevement_forfaitaire.partir_2018
    rate = rules.taux_prelevement_forfaitaire_rev_capital_eligibles_pfu_interets_dividendes_etc
    records = records.with_columns(pl.Series("cases_fiscales", [[{"f2dc": 10_000, "f2ck": round(10_000 * rate)}]]))
    enriched, _ = calculate_tax(records, system, AUDIT_YEAR)
    assert enriched["rfr_eur"][0] == pytest.approx(reference["rfr_eur"][0] + 10_000)
    assert enriched["impot_net_eur"][0] == pytest.approx(reference["impot_net_eur"][0], abs=0.01)
    assert enriched["rici_hors_pfu_eur"][0] == pytest.approx(reference["rici_hors_pfu_eur"][0])
