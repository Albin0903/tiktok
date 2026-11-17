from copy import deepcopy

from openfisca_core.simulations import SimulationBuilder
import pytest

from engine.reforms import get_tax_benefit_system
from engine.reforms.demo_plf2027_retraites import (
    build_active_control_households_payload,
    build_retiree_households_payload,
    DEFAULT_MAX_SPIRAL_LOOPS,
    evaluate_households,
)
from engine.reforms.plf2027_complet_demo import (
    DECOTE_VALUES,
    FROZEN_YEAR,
    INCOME_YEAR,
    QUOTIENT_VALUES,
    THRESHOLDS,
    GelBaremeRevenus2026,
    PLF2027BaremeEtRetraites,
)


def test_bareme_and_linked_parameters_follow_the_deposited_text() -> None:
    baseline = get_tax_benefit_system()
    frozen = GelBaremeRevenus2026(baseline, "annee_1")
    reform = PLF2027BaremeEtRetraites(baseline)
    base = baseline.parameters(FROZEN_YEAR).impot_revenu
    gel = frozen.parameters(INCOME_YEAR).impot_revenu
    after = reform.parameters(INCOME_YEAR).impot_revenu
    assert gel.bareme_ir_depuis_1945.bareme.thresholds == base.bareme_ir_depuis_1945.bareme.thresholds
    # Loi de finances 2026 (n° 2026-103, art. 4), applicable aux revenus 2025.
    assert gel.bareme_ir_depuis_1945.bareme.thresholds == [0, 11600, 29579, 84577, 181917]
    assert gel.bareme_ir_depuis_1945.bareme.rates == [0, 0.11, 0.30, 0.41, 0.45]
    assert [gel.calcul_impot_revenu.plaf_qf.decote[key] for key in DECOTE_VALUES] == [897, 1483]
    gel_quotient = gel.calcul_impot_revenu.plaf_qf.plafond_avantages_procures_par_demi_part
    assert [gel_quotient[key] for key in QUOTIENT_VALUES] == [1807, 4262, 1079, 1801, 2011]
    gel_income = gel.calcul_revenus_imposables
    assert gel_income.abat_rni.enfant_marie == gel_income.charges_deductibles.pensions_alimentaires.plafond == 6855
    assert (gel_income.deductions.abatpen.min, gel_income.deductions.abatpen.max) == (454, 4439)
    assert after.bareme_ir_depuis_1945.bareme.thresholds == [0, *THRESHOLDS]
    assert after.bareme_ir_depuis_1945.bareme.rates == gel.bareme_ir_depuis_1945.bareme.rates
    assert reform.parameters(FROZEN_YEAR).impot_revenu.bareme_ir_depuis_1945.bareme.thresholds == (
        base.bareme_ir_depuis_1945.bareme.thresholds
    )
    quotient = after.calcul_impot_revenu.plaf_qf
    for key, value in QUOTIENT_VALUES.items():
        assert quotient.plafond_avantages_procures_par_demi_part[key] == value
    for key, value in DECOTE_VALUES.items():
        assert quotient.decote[key] == value
    income = after.calcul_revenus_imposables
    assert income.abat_rni.enfant_marie == income.charges_deductibles.pensions_alimentaires.plafond == 6999
    assert (income.deductions.abatpen.min, income.deductions.abatpen.max) == (464, 4532)


def test_retirement_subceiling_applies_per_fiscal_household_and_preserves_other_pensions() -> None:
    tbs = PLF2027BaremeEtRetraites(get_tax_benefit_system())
    payload = {
        "individus": {
            "r1": {"retraite_imposable": {INCOME_YEAR: 20_000}, "pensions_alimentaires_percues": {INCOME_YEAR: 10_000}},
            "r2": {"retraite_imposable": {INCOME_YEAR: 20_000}},
        },
        "foyers_fiscaux": {"foyer": {"declarants": ["r1", "r2"]}},
        "familles": {"famille": {"parents": ["r1", "r2"]}},
        "menages": {"menage": {"personne_de_reference": ["r1"], "conjoint": ["r2"]}},
    }
    simulation = SimulationBuilder().build_from_entities(tbs, payload)
    simulation.max_spiral_loops = DEFAULT_MAX_SPIRAL_LOOPS
    assert simulation.calculate("indu_plaf_abat_pen", INCOME_YEAR)[0] == pytest.approx(1000)


def test_combined_reform_on_canonical_households() -> None:
    tbs = get_tax_benefit_system()
    frozen = GelBaremeRevenus2026(tbs, "annee_1")
    reform = PLF2027BaremeEtRetraites(tbs)
    active, active_specs = build_active_control_households_payload()
    retirees, retiree_specs = build_retiree_households_payload()

    def compare(payload, specs):
        payload = deepcopy(payload)
        for entities in payload.values():
            for entity in entities.values():
                for values in entity.values():
                    if isinstance(values, dict) and FROZEN_YEAR in values:
                        values[INCOME_YEAR] = values[FROZEN_YEAR]
        before = evaluate_households(frozen, payload, specs, "gel", period=INCOME_YEAR)
        after = evaluate_households(reform, payload, specs, "plf", period=INCOME_YEAR)
        return before, after

    old, new = compare(active, active_specs)
    for name in ("smicard_isole", "couple_2_enfants", "cadre_proprietaire"):
        assert new[name].ir_paye <= old[name].ir_paye
        assert new[name].csg_retraite == old[name].csg_retraite == 0
    assert new["cadre_proprietaire"].ir_paye < old["cadre_proprietaire"].ir_paye

    old, new = compare(retirees, retiree_specs)
    assert new["modeste"].ir_paye == old["modeste"].ir_paye == 0
    assert new["aise"].ir_paye > old["aise"].ir_paye
    for name in ("modeste", "aise"):
        assert new[name].csg_retraite == old[name].csg_retraite
        assert new[name].rfr_n_2 == old[name].rfr_n_2
