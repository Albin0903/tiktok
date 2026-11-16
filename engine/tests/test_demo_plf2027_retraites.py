"""Suite pytest rigoureuse pour la simulation PLF 2027 art. 3 vs Suppression 10 % retraites.

Couvre :
  1. Chargement Windows ARM64 des paramètres à chemin long (aides_logement) et seuils 2025.
  2. Périmètre exact de PLF 2027 art. 3 (sous-plafond 3 000 € limité aux retraites seules ;
     pensions alimentaires, invalidité et foyer mixte protégés).
  3. Séparation `horizon="annee_1"` vs `horizon="regime_permanent"` et franchissement
     du seuil CSG 6,6 % -> 8,3 % (26 004 € RFR N-2 pour 1 part).
  4. Interaction avec `abat_spe` (< 65 ans vs >= 65 ans), bornes `abatpen` (454 € / 4 439 € / 3 000 €)
     et sortie de décote.
  5. Invariance stricte des actifs et vérification explicite de `categorie_salarie == prive_cadre`.
  6. Indépendance vis-à-vis de l'ordre des entités grâce à l'indexation explicite par ID.
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

import pytest

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from openfisca_core.simulations import SimulationBuilder
from openfisca_france.model.base import TypesCategorieSalarie

from engine.reforms import get_tax_benefit_system
from engine.reforms.demo_plf2027_retraites import (
    CSG_SEUIL_EXO_1_PART_2025,
    CSG_SEUIL_MEDIAN_1_PART_2025,
    CSG_SEUIL_PLEIN_1_PART_2025,
    DEFAULT_MAX_SPIRAL_LOOPS,
    HISTORY_YEARS,
    PLAFOND_ABATPEN_RETRAITE_3000,
    PlafonnementAbattementRetraites3000,
    SuppressionAbattementRetraites10Pct,
    build_active_control_households_payload,
    build_retiree_households_payload,
    evaluate_households,
    format_comparison_table,
    run_comparison_suite,
)


@pytest.fixture(scope="module")
def suite_annee_1() -> dict[str, dict[str, dict[str, Any]]]:
    return run_comparison_suite(horizon="annee_1")


@pytest.fixture(scope="module")
def suite_regime_permanent() -> dict[str, dict[str, dict[str, Any]]]:
    return run_comparison_suite(horizon="regime_permanent")


def test_openfisca_long_path_parameters_loaded() -> None:
    """Vérifie le contournement MAX_PATH Windows et les barèmes 2025 de référence."""
    tbs = get_tax_benefit_system()
    p2025 = tbs.parameters("2025-01-01")

    abatpen = p2025.impot_revenu.calcul_revenus_imposables.deductions.abatpen
    assert abatpen.min == 454
    assert abatpen.max == 4439
    assert abatpen.taux == 0.1

    seuils = p2025.prelevements_sociaux.contributions_sociales.csg.remplacement.seuils
    assert seuils.seuil_rfr1.seuil_rfr1 == CSG_SEUIL_EXO_1_PART_2025
    assert seuils.seuil_rfr2.seuil_rfr2 == CSG_SEUIL_MEDIAN_1_PART_2025
    assert seuils.seuil_rfr3.seuil_rfr3 == CSG_SEUIL_PLEIN_1_PART_2025

    assert (
        p2025.prestations_sociales.aides_logement.allocations_logement.locatif.formule.pp_particip_perso.tp_taux.tf_taille_famille.metropole.personnes_isolees
        is not None
    )


def test_plf2027_art3_subceiling_scope_excludes_alimony_and_disability(
    suite_annee_1: dict[str, dict[str, dict[str, Any]]],
) -> None:
    """Prouve que le sous-plafond 3 000 € de l'art. 3 ne s'applique qu'aux pensions de retraite."""
    base_act = suite_annee_1["actives"]["base"]
    plaf_act = suite_annee_1["actives"]["plafond_3000"]
    supp_act = suite_annee_1["actives"]["suppression_10pct"]

    base_ret = suite_annee_1["retirees"]["base"]
    plaf_ret = suite_annee_1["retirees"]["plafond_3000"]

    # 1. À montant égal (38 400 €/an), le retraité est plafonné (+184 € IR), pas le bénéficiaire d'une
    #    pension alimentaire ou d'invalidité (abattement 3 840 € <= plafond général 4 439 € préservé).
    assert plaf_ret["intermediaire"].ir_paye - base_ret["intermediaire"].ir_paye == pytest.approx(184.0, abs=1.0)
    for hid in ("pension_alimentaire_seule", "pension_invalidite_seule"):
        assert plaf_act[hid].ir_paye == pytest.approx(base_act[hid].ir_paye, abs=0.01)
        assert plaf_act[hid].revenu_disponible == pytest.approx(base_act[hid].revenu_disponible, abs=0.01)
        # À périmètre constant ("retraites_seules"), la suppression ciblée ne touche pas non plus ces foyers
        assert supp_act[hid].ir_paye == pytest.approx(base_act[hid].ir_paye, abs=0.01)

    # 2. Foyer mixte (36 000 € retraite + 10 000 € pension alimentaire) :
    #    La part retraite (~3 388 € d'abattement) est plafonnée à 3 000 € (reprise 388 € -> +117 € IR à TMI 30 %),
    #    mais les 1 000 € d'abattement sur la pension alimentaire restent intacts (total 4 000 € <= 4 439 €).
    delta_ir_mixte = plaf_act["mixte_retraite_pension_alim"].ir_paye - base_act["mixte_retraite_pension_alim"].ir_paye
    assert delta_ir_mixte == pytest.approx(117.0, abs=1.0)

    # 3. En scope global CGI art. 158, 5-a, la suppression touche bien la pension alimentaire seule.
    tbs = get_tax_benefit_system()
    payload, specs = build_active_control_households_payload()
    supp_global = evaluate_households(
        SuppressionAbattementRetraites10Pct(tbs, horizon="annee_1", scope="global_158_5_a"),
        payload,
        specs,
        scenario_name="suppression_globale",
        horizon="annee_1",
    )
    assert supp_global["pension_alimentaire_seule"].ir_paye > base_act["pension_alimentaire_seule"].ir_paye
    assert supp_global["pension_invalidite_seule"].ir_paye > base_act["pension_invalidite_seule"].ir_paye


def test_horizon_annee_1_vs_regime_permanent_csg_threshold_jump(
    suite_annee_1: dict[str, dict[str, dict[str, Any]]],
    suite_regime_permanent: dict[str, dict[str, dict[str, Any]]],
) -> None:
    """Vérifie le franchissement du seuil CSG 6,6 % -> 8,3 % en régime permanent vs stabilité en année 1."""
    b_a1 = suite_annee_1["retirees"]["base"]["median_63ans"]
    s_a1 = suite_annee_1["retirees"]["suppression_10pct"]["median_63ans"]

    b_rp = suite_regime_permanent["retirees"]["base"]["median_63ans"]
    s_rp = suite_regime_permanent["retirees"]["suppression_10pct"]["median_63ans"]

    # En Année 1 : RFR N-2 (2023) reste sous 26 004 € -> aucune bascule CSG
    assert b_a1.rfr_n_2 < CSG_SEUIL_PLEIN_1_PART_2025
    assert s_a1.rfr_n_2 == pytest.approx(b_a1.rfr_n_2, abs=0.01)
    assert s_a1.csg_retraite == pytest.approx(b_a1.csg_retraite, abs=0.01)
    assert s_a1.csg_retraite == pytest.approx(28800.0 * 0.066, abs=0.2)
    assert s_a1.revenu_disponible - b_a1.revenu_disponible == pytest.approx(-441.0, abs=1.0)

    # En Régime Permanent : RFR N-2 (2023) franchit 26 004 € -> CSG passe de 6,6 % (1 900,80 €) à 8,3 % (2 390,40 €)
    assert s_rp.rfr_n_2 > CSG_SEUIL_PLEIN_1_PART_2025
    assert s_rp.csg_retraite == pytest.approx(28800.0 * 0.083, abs=0.2)
    assert s_rp.csg_retraite - b_rp.csg_retraite == pytest.approx(28800.0 * (0.083 - 0.066), abs=0.5)
    # Double peine IR + CSG + CASA en régime permanent (-852,60 € vs -441,00 € en année 1)
    assert (s_rp.revenu_disponible - b_rp.revenu_disponible) < (s_a1.revenu_disponible - b_a1.revenu_disponible) - 400.0


def test_abat_spe_senior_65_interaction_and_abatpen_bounds(
    suite_regime_permanent: dict[str, dict[str, dict[str, Any]]],
) -> None:
    """Vérifie l'interaction abat_spe (<65 vs >=65 ans), les bornes 454 / 3000 / 4439 et la sortie de décote."""
    base_rp = suite_regime_permanent["retirees"]["base"]
    plaf_rp = suite_regime_permanent["retirees"]["plafond_3000"]
    supp_rp = suite_regime_permanent["retirees"]["suppression_10pct"]

    # 1. Comparaison 63 ans (<65) vs 68 ans (>=65) à pension identique (28 800 €/an) :
    #    Grâce à abat_spe (1 411 €), le 68 ans paie moins d'IR et son RFR 2023 reste <= 26 004 € sous suppression.
    assert base_rp["median_68ans"].ir_paye < base_rp["median_63ans"].ir_paye
    assert base_rp["median_68ans"].rfr_n_2 < base_rp["median_63ans"].rfr_n_2
    assert supp_rp["median_68ans"].rfr_n_2 <= CSG_SEUIL_PLEIN_1_PART_2025
    assert supp_rp["median_68ans"].csg_retraite == pytest.approx(base_rp["median_68ans"].csg_retraite, abs=0.01)

    # 2. Plafonnement à 3 000 € neutre sous ~30 000 € imposables, puis plafonné à (4 439 - 3 000) * 30 % = 432 €
    assert plaf_rp["modeste"].ir_paye == 0.0
    assert plaf_rp["median_68ans"].ir_paye == base_rp["median_68ans"].ir_paye
    expected_max_loss = (4439.0 - PLAFOND_ABATPEN_RETRAITE_3000) * 0.30
    assert plaf_rp["aise"].ir_paye - base_rp["aise"].ir_paye == pytest.approx(expected_max_loss, abs=1.0)
    assert supp_rp["aise"].ir_paye - base_rp["aise"].ir_paye == pytest.approx(4439.0 * 0.30, abs=1.0)
    assert plaf_rp["couple_aise"].ir_paye > base_rp["couple_aise"].ir_paye

    # 3. Borne minimum (454 €) sur petite pension (3 000 €/an) et sortie complète de décote (32 000 €/an)
    tbs = get_tax_benefit_system()
    const_years = {y: 3000.0 for y in HISTORY_YEARS}
    const_decote = {y: 32000.0 for y in HISTORY_YEARS}
    extra_payload = {
        "individus": {
            "ind_petite": {"date_naissance": {"ETERNITY": "1958-01-01"}, "retraite_brute": const_years},
            "ind_decote": {"date_naissance": {"ETERNITY": "1962-01-01"}, "retraite_brute": const_decote},
        },
        "foyers_fiscaux": {"ff_petite": {"declarants": ["ind_petite"]}, "ff_decote": {"declarants": ["ind_decote"]}},
        "familles": {"fam_petite": {"parents": ["ind_petite"]}, "fam_decote": {"parents": ["ind_decote"]}},
        "menages": {
            "men_petite": {"personne_de_reference": ["ind_petite"]},
            "men_decote": {"personne_de_reference": ["ind_decote"]},
        },
    }
    sim_base = SimulationBuilder().build_from_entities(tbs, extra_payload)
    sim_base.max_spiral_loops = DEFAULT_MAX_SPIRAL_LOOPS
    sim_plaf = SimulationBuilder().build_from_entities(PlafonnementAbattementRetraites3000(tbs, "annee_1"), extra_payload)
    sim_plaf.max_spiral_loops = DEFAULT_MAX_SPIRAL_LOOPS
    sim_supp = SimulationBuilder().build_from_entities(SuppressionAbattementRetraites10Pct(tbs, "annee_1"), extra_payload)
    sim_supp.max_spiral_loops = DEFAULT_MAX_SPIRAL_LOOPS

    ind_idx_petite = sim_base.individu.ids.index("ind_petite")
    ff_idx_decote = sim_base.foyer_fiscal.ids.index("ff_decote")

    # Plancher 454 € appliqué en base et sous plafonnement 3 000 €, supprimé en suppression 10 %
    assert sim_base.calculate("revenu_assimile_pension_apres_abattements", "2025")[ind_idx_petite] == pytest.approx(2546.0)
    assert sim_plaf.calculate("revenu_assimile_pension_apres_abattements", "2025")[ind_idx_petite] == pytest.approx(2546.0)
    assert sim_supp.calculate("revenu_assimile_pension_apres_abattements", "2025")[ind_idx_petite] == pytest.approx(3000.0)

    # Sortie complète de décote sous suppression 10 % pour 32 000 €/an (décote 125 € -> 0 €)
    assert sim_base.calculate("decote", "2025")[ff_idx_decote] == pytest.approx(125.0)
    assert sim_supp.calculate("decote", "2025")[ff_idx_decote] == 0.0


def test_active_control_households_and_cadre_enum(
    suite_annee_1: dict[str, dict[str, dict[str, Any]]],
    suite_regime_permanent: dict[str, dict[str, dict[str, Any]]],
) -> None:
    """Vérifie l'invariance stricte sur les 3 actifs et le statut prive_cadre de act_cadre."""
    for suite in (suite_annee_1, suite_regime_permanent):
        base = suite["actives"]["base"]
        plaf = suite["actives"]["plafond_3000"]
        supp = suite["actives"]["suppression_10pct"]
        for hid in ("smicard_isole", "couple_2_enfants", "cadre_proprietaire"):
            assert base[hid].pension_brute_annuelle == 0.0
            for reform_map in (plaf, supp):
                assert reform_map[hid].ir_paye == pytest.approx(base[hid].ir_paye, abs=0.01)
                assert reform_map[hid].csg_retraite == pytest.approx(base[hid].csg_retraite, abs=0.01)
                assert reform_map[hid].revenu_disponible == pytest.approx(base[hid].revenu_disponible, abs=0.01)

    tbs = get_tax_benefit_system()
    active_payload, _ = build_active_control_households_payload()
    sim = SimulationBuilder().build_from_entities(tbs, active_payload)
    sim.max_spiral_loops = DEFAULT_MAX_SPIRAL_LOOPS
    cadre_idx = sim.individu.ids.index("ind_cadre_1")
    cat_values = sim.calculate("categorie_salarie", "2025-01")
    assert cat_values.decode()[cadre_idx] == TypesCategorieSalarie.prive_cadre


def test_explicit_entity_id_mapping_order_independence() -> None:
    """Vérifie que l'inversion d'ordre des dictionnaires d'entités ne fausse jamais le mapping."""
    tbs = get_tax_benefit_system()
    payload, specs = build_retiree_households_payload()
    baseline_res = evaluate_households(tbs, payload, specs, scenario_name="base", horizon="annee_1")

    reversed_payload = {
        "individus": dict(reversed(list(payload["individus"].items()))),
        "foyers_fiscaux": dict(reversed(list(payload["foyers_fiscaux"].items()))),
        "familles": dict(reversed(list(payload["familles"].items()))),
        "menages": dict(reversed(list(payload["menages"].items()))),
    }
    reversed_res = evaluate_households(tbs, reversed_payload, specs, scenario_name="base", horizon="annee_1")

    for hid, expected in baseline_res.items():
        actual = reversed_res[hid]
        assert actual.ir_paye == pytest.approx(expected.ir_paye, abs=0.01)
        assert actual.csg_retraite == pytest.approx(expected.csg_retraite, abs=0.01)
        assert actual.revenu_disponible == pytest.approx(expected.revenu_disponible, abs=0.01)
        assert actual.rfr == pytest.approx(expected.rfr, abs=0.01)


def test_reform_metadata_and_table_rendering(
    suite_annee_1: dict[str, dict[str, dict[str, Any]]],
    suite_regime_permanent: dict[str, dict[str, dict[str, Any]]],
) -> None:
    """Vérifie les attributs DESIGN.md (calc_certainty / legal_status) et les colonnes RFR / CSG (Δ)."""
    assert PlafonnementAbattementRetraites3000.calc_certainty == "green"
    assert PlafonnementAbattementRetraites3000.legal_status == "projet_de_loi_en_navette"
    assert SuppressionAbattementRetraites10Pct.calc_certainty == "green"
    assert SuppressionAbattementRetraites10Pct.legal_status == "proposition_programme"

    t_a1 = format_comparison_table(suite_annee_1["retirees"], horizon="annee_1")
    t_rp = format_comparison_table(suite_regime_permanent["retirees"], horizon="regime_permanent")
    assert "Base RFR 2025" in t_a1
    assert "Art.3 CSG (Δ)" in t_a1
    assert "Suppr.10% CSG (Δ)" in t_a1
    assert "Base RFR 23 (N-2)" in t_rp
    assert "63 ans <65" in t_rp
    assert "68 ans >=65" in t_rp
