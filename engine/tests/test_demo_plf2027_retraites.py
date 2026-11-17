"""Suite pytest rigoureuse pour la simulation PLF 2027 art. 3 vs Suppression 10 % retraites.

Couvre :
  1. Chargement Windows ARM64 des paramètres à chemin long (aides_logement) et seuils 2025.
  2. Périmètre exact de PLF 2027 art. 3 (sous-plafond 3 000 € limité aux retraites seules ;
     pensions alimentaires, invalidité et foyer mixte protégés).
  3. Séparation `horizon="annee_1"` vs `horizon="regime_permanent"` et franchissement
     du seuil CSG 6,6 % -> 8,3 % (26 004 € RFR N-2 pour 1 part).
  4. Cas test dédié autour du seuil CSG 3,8 % (`16 755 €`) documentant l'absence de lissage N-3
     dans `openfisca-france` natif (CSS art. L. 136-8, III).
  5. Interaction avec `abat_spe` (< 65 ans vs >= 65 ans), bornes `abatpen` (454 € / 4 439 € / 3 000 €)
     et sortie complète de décote.
  6. Invariance stricte des actifs et vérification explicite de `categorie_salarie == prive_cadre`.
  7. Indépendance vis-à-vis de l'ordre des entités grâce à l'indexation explicite par ID.
  8. Verrouillage des métadonnées dans `evaluate_households()` (ValueError sur incohérence/omission).
  9. Robustesse CP1252 / non-UTF-8 de la CLI (aucun `UnicodeEncodeError` sans `PYTHONUTF8=1`).
 10. Contre-vérification analytique DGFiP 2042 (barème IR 2025, tranches, décote et arrondis).
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from openfisca_core.simulations import SimulationBuilder
from openfisca_france.model.base import TypesCategorieSalarie

from engine.reforms import get_tax_benefit_system
from engine.reforms.demo_plf2027_retraites import (
    ABATPEN_MAX_2025,
    ABATPEN_MIN_2025,
    ABATPEN_TAUX_2025,
    CSG_SEUIL_EXO_1_PART_2025,
    CSG_SEUIL_MEDIAN_1_PART_2025,
    CSG_SEUIL_PLEIN_1_PART_2025,
    DEFAULT_MAX_SPIRAL_LOOPS,
    HISTORY_YEARS,
    PLAFOND_ABATPEN_RETRAITE_3000,
    LoiEnVigueurBaseline,
    PlafonnementAbattementRetraites3000,
    SuppressionAbattementRetraites10Pct,
    _spec,
    build_active_control_households_payload,
    build_retiree_households_payload,
    evaluate_households,
    format_comparison_table,
    run_comparison_suite,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


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
    assert abatpen.min == ABATPEN_MIN_2025
    assert abatpen.max == ABATPEN_MAX_2025
    assert abatpen.taux == ABATPEN_TAUX_2025

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

    assert plaf_ret["intermediaire"].ir_paye - base_ret["intermediaire"].ir_paye == pytest.approx(184.0, abs=1.0)
    for hid in ("pension_alimentaire_seule", "pension_invalidite_seule"):
        assert plaf_act[hid].ir_paye == pytest.approx(base_act[hid].ir_paye, abs=0.01)
        assert plaf_act[hid].revenu_disponible == pytest.approx(base_act[hid].revenu_disponible, abs=0.01)
        assert supp_act[hid].ir_paye == pytest.approx(base_act[hid].ir_paye, abs=0.01)

    delta_ir_mixte = plaf_act["mixte_retraite_pension_alim"].ir_paye - base_act["mixte_retraite_pension_alim"].ir_paye
    assert delta_ir_mixte == pytest.approx(117.0, abs=1.0)

    tbs = get_tax_benefit_system()
    payload, specs = build_active_control_households_payload()
    supp_global_sys = SuppressionAbattementRetraites10Pct(tbs, horizon="annee_1", scope="global_158_5_a")
    supp_global = evaluate_households(
        supp_global_sys,
        payload,
        specs,
        scenario_name="suppression_globale",
    )
    assert supp_global["pension_alimentaire_seule"].ir_paye > base_act["pension_alimentaire_seule"].ir_paye
    assert supp_global["pension_invalidite_seule"].ir_paye > base_act["pension_invalidite_seule"].ir_paye


def test_horizon_annee_1_vs_regime_permanent_csg_threshold_jump(
    suite_annee_1: dict[str, dict[str, dict[str, Any]]],
    suite_regime_permanent: dict[str, dict[str, dict[str, Any]]],
) -> None:
    """Vérifie le franchissement immédiat 6,6 % -> 8,3 % (pas de lissage entre 6,6 % et 8,3 %)."""
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

    # En Régime Permanent : RFR N-2 (2023) franchit 26 004 € -> CSG passe immédiatement de 6,6 % à 8,3 %
    assert s_rp.rfr_n_2 > CSG_SEUIL_PLEIN_1_PART_2025
    assert s_rp.csg_retraite == pytest.approx(28800.0 * 0.083, abs=0.2)
    assert s_rp.csg_retraite - b_rp.csg_retraite == pytest.approx(28800.0 * (0.083 - 0.066), abs=0.5)
    assert (s_rp.revenu_disponible - b_rp.revenu_disponible) < (s_a1.revenu_disponible - b_a1.revenu_disponible) - 400.0


def test_csg_3_8_pct_smoothing_limit_n_3_vs_n_2() -> None:
    """Vérifie le lissage CSS art. L. 136-8, III (N-3/N-2) sur la CSG (3,8 %) et la CASA (0 €).

    Un pensionné au taux réduit (3,8 % en N-1 car RFR(2022) <= 15 988 €) dont le RFR(2023)
    dépasse 16 755 € pour la première fois reste maintenu à 3,8 % (684 €) et exonéré de
    CASA (0 €) en 2025, contrairement au comportement natif d'OpenFisca-France.
    """
    tbs = get_tax_benefit_system()
    payload = {
        "individus": {
            "ind_38": {
                "date_naissance": {"ETERNITY": "1962-01-01"},
                "retraite_brute": {
                    "2021": 15500.0,
                    "2022": 15500.0,
                    "2023": 18000.0,
                    "2024": 18000.0,
                    "2025": 18000.0,
                },
            }
        },
        "foyers_fiscaux": {"ff_38": {"declarants": ["ind_38"]}},
        "familles": {"fam_38": {"parents": ["ind_38"]}},
        "menages": {"men_38": {"personne_de_reference": ["ind_38"]}},
    }

    sim_base = SimulationBuilder().build_from_entities(LoiEnVigueurBaseline(tbs, horizon="regime_permanent"), payload)
    sim_base.max_spiral_loops = DEFAULT_MAX_SPIRAL_LOOPS
    sim_supp = SimulationBuilder().build_from_entities(
        SuppressionAbattementRetraites10Pct(tbs, horizon="regime_permanent"),
        payload,
    )
    sim_supp.max_spiral_loops = DEFAULT_MAX_SPIRAL_LOOPS

    # Base : RFR(N-3=2022) <= 15 988 et RFR(N-2=2023) <= 16 755 -> 3,8 % (684 €), CASA = 0 €
    assert sim_base.calculate("rfr", "2022")[0] <= 15988.0
    assert sim_base.calculate("rfr", "2023")[0] <= CSG_SEUIL_MEDIAN_1_PART_2025
    csg_base_2025 = float(
        -(sim_base.calculate_add("csg_deductible_retraite", "2025")[0] + sim_base.calculate_add("csg_imposable_retraite", "2025")[0])
    )
    assert csg_base_2025 == pytest.approx(18000.0 * 0.038, abs=0.2)
    assert float(-sim_base.calculate_add("casa", "2025")[0]) == 0.0

    # Sous réforme : RFR(N-3=2022) = 15 500 € <= 15 988 €, mais RFR(N-2=2023) = 17 244 € > 16 755 €
    # Le lissage CSS art. L. 136-8, III maintient CSG à 3,8 % (684 €) et CASA à 0 € en 2025.
    assert sim_supp.calculate("rfr", "2022")[0] <= 15988.0
    assert sim_supp.calculate("rfr", "2023")[0] > CSG_SEUIL_MEDIAN_1_PART_2025
    csg_supp_2025 = float(
        -(sim_supp.calculate_add("csg_deductible_retraite", "2025")[0] + sim_supp.calculate_add("csg_imposable_retraite", "2025")[0])
    )
    casa_supp_2025 = float(-sim_supp.calculate_add("casa", "2025")[0])
    assert csg_supp_2025 == pytest.approx(18000.0 * 0.038, abs=0.2)
    assert casa_supp_2025 == 0.0


def test_csg_exact_boundary_26004_taux_plein() -> None:
    """Vérifie la borne exacte 26 004 € (1 part) : 8,3 % à 26 004 € vs 6,6 % à 26 003 €."""
    tbs = get_tax_benefit_system()
    sys_exact = LoiEnVigueurBaseline(tbs, horizon="regime_permanent")

    def _payload_at_rfr2023(rfr_2023_target: float, parts: float = 1.0) -> dict[str, Any]:
        payload = {
            "individus": {
                "ind_b": {
                    "date_naissance": {"ETERNITY": "1962-01-01"},
                    "retraite_brute": {"2025": 28800.0},
                }
            },
            "foyers_fiscaux": {
                "ff_b": {
                    "declarants": ["ind_b"],
                    "rfr": {"2022": 20000.0, "2023": rfr_2023_target},
                    "nbptr": {"2023": parts},
                }
            },
            "familles": {"fam_b": {"parents": ["ind_b"]}},
            "menages": {"men_b": {"personne_de_reference": ["ind_b"]}},
        }
        return payload

    for rfr, taux in (
        (12817.49, 0.0),
        (12817.50, 0.038),
        (16755.49, 0.038),
        (16755.50, 0.066),
        (26003.49, 0.066),
        (26003.50, 0.083),
        (26003.60, 0.083),
        (26004.00, 0.083),
    ):
        sim = SimulationBuilder().build_from_entities(sys_exact, _payload_at_rfr2023(rfr))
        sim.max_spiral_loops = DEFAULT_MAX_SPIRAL_LOOPS
        csg = -(sim.calculate_add("csg_deductible_retraite", "2025")[0] + sim.calculate_add("csg_imposable_retraite", "2025")[0])
        assert csg == pytest.approx(28800.0 * taux, abs=0.2), rfr

    # Le seuil à 1,5 part est de 32 945 €. Un arrondi au pair donnerait 32 944 €.
    result = evaluate_households(
        sys_exact,
        _payload_at_rfr2023(32944.50, parts=1.5),
        [_spec("b", "Foyer de 1,5 part", ("ind_b",))],
        scenario_name="base",
    )["b"]
    assert result.rfr_n_2 == 32945.0
    assert result.csg_retraite == pytest.approx(28800.0 * 0.083, abs=0.2)


@pytest.mark.parametrize(
    ("rfr_n_3", "taux_csg", "taux_casa"),
    [(16300.0, 0.038, 0.0), (16755.49, 0.038, 0.0), (16755.50, 0.066, 0.003)],
)
def test_csg_smoothing_uses_year_n_threshold_for_rfr_n_3(
    rfr_n_3: float, taux_csg: float, taux_casa: float
) -> None:
    """Non-régression [P1] : RFR(N-3) est comparé au seuil de l'année N (16 755 € en 2025).

    Cas exact : 1 part, RFR 2022 = 16 300 € (> 15 988 € de N-1 mais <= 16 755 € de 2025),
    RFR 2023 = 18 000 €, retraite brute 2025 = 18 000 € -> CSG 2025 = 684 € (3,8 %) et CASA = 0 €.
    """
    tbs = get_tax_benefit_system()
    sys_exact = LoiEnVigueurBaseline(tbs, horizon="regime_permanent")
    payload = {
        "individus": {
            "ind_n3": {
                "date_naissance": {"ETERNITY": "1962-01-01"},
                "retraite_brute": {"2025": 18000.0},
            }
        },
        "foyers_fiscaux": {
            "ff_n3": {
                "declarants": ["ind_n3"],
                "rfr": {"2022": rfr_n_3, "2023": 18000.0},
            }
        },
        "familles": {"fam_n3": {"parents": ["ind_n3"]}},
        "menages": {"men_n3": {"personne_de_reference": ["ind_n3"]}},
    }
    sim = SimulationBuilder().build_from_entities(sys_exact, payload)
    sim.max_spiral_loops = DEFAULT_MAX_SPIRAL_LOOPS
    csg_2025 = float(
        -(sim.calculate_add("csg_deductible_retraite", "2025")[0] + sim.calculate_add("csg_imposable_retraite", "2025")[0])
    )
    casa_2025 = float(-sim.calculate_add("casa", "2025")[0])
    assert csg_2025 == pytest.approx(18000.0 * taux_csg, abs=0.2)
    assert casa_2025 == pytest.approx(18000.0 * taux_casa, abs=0.01)


def test_csg_smoothing_active_before_2024() -> None:
    """Non-régression [P2] : le lissage CSG/CASA s'applique aussi avant 2024 (ex. en 2023).

    Cas exact : 1 part, RFR 2020 = 14 000 €, RFR 2021 = 16 000 €, retraite brute 2023 = 18 000 €
    -> CSG 2023 = 684 € (3,8 %) et CASA 2023 = 0 €.
    """
    tbs = get_tax_benefit_system()
    sys_exact = LoiEnVigueurBaseline(tbs, horizon="regime_permanent")
    payload = {
        "individus": {
            "ind_2023": {
                "date_naissance": {"ETERNITY": "1960-01-01"},
                "retraite_brute": {"2023": 18000.0},
            }
        },
        "foyers_fiscaux": {
            "ff_2023": {
                "declarants": ["ind_2023"],
                "rfr": {"2020": 14000.0, "2021": 16000.0},
            }
        },
        "familles": {"fam_2023": {"parents": ["ind_2023"]}},
        "menages": {"men_2023": {"personne_de_reference": ["ind_2023"]}},
    }
    sim = SimulationBuilder().build_from_entities(sys_exact, payload)
    sim.max_spiral_loops = DEFAULT_MAX_SPIRAL_LOOPS
    csg_2023 = float(
        -(sim.calculate_add("csg_deductible_retraite", "2023")[0] + sim.calculate_add("csg_imposable_retraite", "2023")[0])
    )
    casa_2023 = float(-sim.calculate_add("casa", "2023")[0])
    assert csg_2023 == pytest.approx(684.0, abs=0.2)
    assert casa_2023 == 0.0


def test_abat_spe_senior_65_interaction_and_abatpen_bounds(
    suite_regime_permanent: dict[str, dict[str, dict[str, Any]]],
) -> None:
    """Vérifie l'interaction abat_spe (<65 vs >=65 ans), les bornes 454 / 3000 / 4439 et la sortie de décote."""
    base_rp = suite_regime_permanent["retirees"]["base"]
    plaf_rp = suite_regime_permanent["retirees"]["plafond_3000"]
    supp_rp = suite_regime_permanent["retirees"]["suppression_10pct"]

    assert base_rp["median_68ans"].ir_paye < base_rp["median_63ans"].ir_paye
    assert base_rp["median_68ans"].rfr_n_2 < base_rp["median_63ans"].rfr_n_2
    assert supp_rp["median_68ans"].rfr_n_2 <= CSG_SEUIL_PLEIN_1_PART_2025
    assert supp_rp["median_68ans"].csg_retraite == pytest.approx(base_rp["median_68ans"].csg_retraite, abs=0.01)

    assert plaf_rp["modeste"].ir_paye == 0.0
    assert plaf_rp["median_68ans"].ir_paye == base_rp["median_68ans"].ir_paye
    expected_max_loss = (ABATPEN_MAX_2025 - PLAFOND_ABATPEN_RETRAITE_3000) * 0.30
    assert plaf_rp["aise"].ir_paye - base_rp["aise"].ir_paye == pytest.approx(expected_max_loss, abs=1.0)
    assert supp_rp["aise"].ir_paye - base_rp["aise"].ir_paye == pytest.approx(ABATPEN_MAX_2025 * 0.30, abs=1.0)
    assert plaf_rp["couple_aise"].ir_paye > base_rp["couple_aise"].ir_paye

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

    assert sim_base.calculate("revenu_assimile_pension_apres_abattements", "2025")[ind_idx_petite] == pytest.approx(2546.0)
    assert sim_plaf.calculate("revenu_assimile_pension_apres_abattements", "2025")[ind_idx_petite] == pytest.approx(2546.0)
    assert sim_supp.calculate("revenu_assimile_pension_apres_abattements", "2025")[ind_idx_petite] == pytest.approx(3000.0)

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
    baseline_sys = LoiEnVigueurBaseline(tbs, horizon="annee_1")
    baseline_res = evaluate_households(baseline_sys, payload, specs, scenario_name="base")

    reversed_payload = {
        "individus": dict(reversed(list(payload["individus"].items()))),
        "foyers_fiscaux": dict(reversed(list(payload["foyers_fiscaux"].items()))),
        "familles": dict(reversed(list(payload["familles"].items()))),
        "menages": dict(reversed(list(payload["menages"].items()))),
    }
    reversed_res = evaluate_households(baseline_sys, reversed_payload, specs, scenario_name="base")

    for hid, expected in baseline_res.items():
        actual = reversed_res[hid]
        assert actual.ir_paye == pytest.approx(expected.ir_paye, abs=0.01)
        assert actual.csg_retraite == pytest.approx(expected.csg_retraite, abs=0.01)
        assert actual.revenu_disponible == pytest.approx(expected.revenu_disponible, abs=0.01)
        assert actual.rfr == pytest.approx(expected.rfr, abs=0.01)


def test_evaluate_households_metadata_validation_raises() -> None:
    """Vérifie que evaluate_households verrouille les métadonnées et refuse tout défaut silencieux."""
    tbs = get_tax_benefit_system()
    payload, specs = build_retiree_households_payload()
    reform_rp = PlafonnementAbattementRetraites3000(tbs, horizon="regime_permanent")

    # 1. Système brut sans métadonnées et sans arguments explicites -> ValueError
    with pytest.raises(ValueError, match="Métadonnées manquantes"):
        evaluate_households(tbs, payload, specs, scenario_name="base")

    # 2. Incohérence d'horizon sur une Reform -> ValueError
    with pytest.raises(ValueError, match="Incohérence horizon"):
        evaluate_households(reform_rp, payload, specs, scenario_name="plafond_3000", horizon="annee_1")

    # 3. Mauvais legal_status (ex. "en_vigueur" passé pour un projet de loi en navette) -> ValueError
    with pytest.raises(ValueError, match="Incohérence legal_status"):
        evaluate_households(reform_rp, payload, specs, scenario_name="plafond_3000", legal_status="en_vigueur")

    # 4. Mauvaise certitude -> ValueError
    with pytest.raises(ValueError, match="Incohérence calc_certainty"):
        evaluate_households(reform_rp, payload, specs, scenario_name="plafond_3000", calc_certainty="red")


def test_evaluate_households_mismatched_menage_raises() -> None:
    """Vérifie qu'une incohérence de membres entre Menage/Famille et spec lève ValueError."""
    tbs = get_tax_benefit_system()
    payload, specs = build_retiree_households_payload()
    baseline_sys = LoiEnVigueurBaseline(tbs, horizon="annee_1")

    # Échange les membres entre men_modeste et men_aise -> situation OpenFisca valide mais incohérente
    corrupted_payload = {
        **payload,
        "menages": {
            **payload["menages"],
            "men_modeste": dict(payload["menages"]["men_aise"]),
            "men_aise": dict(payload["menages"]["men_modeste"]),
        },
    }
    with pytest.raises(ValueError, match="Incohérence membres Menage"):
        evaluate_households(baseline_sys, corrupted_payload, specs, scenario_name="base")


@pytest.mark.parametrize(
    ("depcom", "month"),
    [
        ({"2025": "97105"}, "2025-01"),
        ({"2023": "97105", "2025": "75056"}, "2023-01"),
        ({"2023-12": "97105", "2025": "75056"}, "2023-12"),
        ({"2025-07": "97105"}, "2025-07"),
        ({"2021": "97105", "2023": "75056", "2025": "75056"}, "2021-01"),
    ],
)
def test_ultramarine_residence_raises_value_error(depcom: dict[str, str], month: str) -> None:
    """Vérifie le rejet explicite des résidents ultramarins (périmètre métropole uniquement)."""
    tbs = get_tax_benefit_system()
    sys_exact = LoiEnVigueurBaseline(tbs, horizon="regime_permanent")
    payload = {
        "individus": {
            "ind_dom": {
                "date_naissance": {"ETERNITY": "1962-01-01"},
                "retraite_brute": {year: 18000.0 for year in HISTORY_YEARS},
            }
        },
        "foyers_fiscaux": {
            "ff_dom": {
                "declarants": ["ind_dom"],
            }
        },
        "familles": {"fam_dom": {"parents": ["ind_dom"]}},
        "menages": {"men_dom": {"personne_de_reference": ["ind_dom"], "depcom": depcom}},
    }
    specs = [_spec("dom", "Guadeloupe 97105", ("ind_dom",))]
    with pytest.raises(ValueError, match=f"Périmètre métropole uniquement.*{month}"):
        evaluate_households(sys_exact, payload, specs, scenario_name="base")


def test_suppression_invalid_scope_raises_value_error() -> None:
    """Vérifie qu'un scope invalide (ex. typo 'global_158_5a') lève immédiatement ValueError."""
    tbs = get_tax_benefit_system()
    with pytest.raises(ValueError, match="Scope invalide"):
        SuppressionAbattementRetraites10Pct(tbs, horizon="annee_1", scope="global_158_5a")  # type: ignore[arg-type]


def test_mixed_small_pension_triggers_yellow_certainty() -> None:
    """Vérifie la doctrine petites pensions mixtes : déclassement automatique en calc_certainty='yellow'."""
    tbs = get_tax_benefit_system()
    plaf_sys = PlafonnementAbattementRetraites3000(tbs, horizon="annee_1")

    # Cas 1 : petite pension mixte (2 000 € retraite + 2 000 € pension alimentaire -> 10 % < 454 €)
    payload_small = {
        "individus": {
            "ind_mix_small": {
                "date_naissance": {"ETERNITY": "1958-01-01"},
                "retraite_brute": {y: 2000.0 for y in HISTORY_YEARS},
                "pensions_alimentaires_percues": {y: 2000.0 for y in HISTORY_YEARS},
            }
        },
        "foyers_fiscaux": {"ff_mix_small": {"declarants": ["ind_mix_small"]}},
        "familles": {"fam_mix_small": {"parents": ["ind_mix_small"]}},
        "menages": {"men_mix_small": {"personne_de_reference": ["ind_mix_small"]}},
    }
    res_small = evaluate_households(
        plaf_sys,
        payload_small,
        [_spec("mix_small", "Petite pension mixte", ("ind_mix_small",))],
        scenario_name="plafond_3000",
    )
    assert res_small["mix_small"].calc_certainty == "yellow"
    assert res_small["mix_small"].ir_paye == 0.0

    payload_small["individus"]["ind_mix_small"]["pensions_alimentaires_percues_decl"] = {"2025": False}
    res_non_decl = evaluate_households(
        plaf_sys,
        payload_small,
        [_spec("mix_small", "Petite pension mixte", ("ind_mix_small",))],
        scenario_name="plafond_3000",
    )
    assert res_non_decl["mix_small"].calc_certainty == "green"

    # Cas 2 : grande pension mixte (36 000 € + 10 000 €) -> non ambigu, reste 'green'
    active_payload, active_specs = build_active_control_households_payload()
    res_large = evaluate_households(plaf_sys, active_payload, active_specs, scenario_name="plafond_3000")
    assert res_large["mixte_retraite_pension_alim"].calc_certainty == "green"

    # En régime permanent, le sous-plafond est atteint en 2023 et le RFR
    # reconstruit dépend de l'imputation du minimum à la pension mixte.
    active_payload["individus"]["ind_mixte_1"]["pensions_alimentaires_percues"] = {"2023": 2000.0}
    plaf_permanent = PlafonnementAbattementRetraites3000(tbs, horizon="regime_permanent")
    res_historic = evaluate_households(
        plaf_permanent,
        active_payload,
        active_specs,
        scenario_name="plafond_3000",
    )
    assert res_historic["mixte_retraite_pension_alim"].calc_certainty == "yellow"


def test_external_dgfip_2042_analytical_cross_check(
    suite_annee_1: dict[str, dict[str, dict[str, Any]]],
) -> None:
    """Contre-vérification analytique indépendante DGFiP 2042 (barème IR 2025 + décote) sur 2 foyers."""

    def ir_dgfip_1part_2025(rni: float) -> float:
        # Barème 2025 (1 part, CGI art. 197) : 0% <= 11 600 ; 11% [11 600, 29 579] ; 30% [29 579, 84 577]
        droits_simples = max(0.0, min(rni, 29579.0) - 11600.0) * 0.11 + max(0.0, rni - 29579.0) * 0.30
        if droits_simples < (897.0 / 0.4525):
            decote = max(0.0, round(897.0 - 0.4525 * droits_simples))
        else:
            decote = 0.0
        return float(round(max(0.0, droits_simples - decote)))

    # Cas 1 : median_63ans (28 800 € brut, <65 ans -> aucun abat_spe)
    # CSG médiane 6,6 % dont 4,2 % déductible = 1 209,60 € ; retraite imposable = 27 590,40 €
    ret_imp_median = 28800.0 * (1.0 - 0.042)
    abat_median = round(ret_imp_median * ABATPEN_TAUX_2025)
    rni_median_base = ret_imp_median - abat_median
    rni_median_suppr = ret_imp_median
    assert suite_annee_1["retirees"]["base"]["median_63ans"].ir_paye == pytest.approx(
        ir_dgfip_1part_2025(rni_median_base), abs=0.01
    )
    assert suite_annee_1["retirees"]["suppression_10pct"]["median_63ans"].ir_paye == pytest.approx(
        ir_dgfip_1part_2025(rni_median_suppr), abs=0.01
    )

    # Cas 2 : aise (54 000 € brut, 67 ans -> RNI trop élevé pour abat_spe)
    # CSG taux plein 8,3 % dont 5,9 % déductible = 3 186,00 € ; retraite imposable = 50 814,00 €
    ret_imp_aise = 54000.0 * (1.0 - 0.059)
    rni_aise_base = ret_imp_aise - ABATPEN_MAX_2025
    rni_aise_art3 = ret_imp_aise - PLAFOND_ABATPEN_RETRAITE_3000
    rni_aise_suppr = ret_imp_aise
    assert suite_annee_1["retirees"]["base"]["aise"].ir_paye == pytest.approx(ir_dgfip_1part_2025(rni_aise_base), abs=0.01)
    assert suite_annee_1["retirees"]["plafond_3000"]["aise"].ir_paye == pytest.approx(
        ir_dgfip_1part_2025(rni_aise_art3), abs=0.01
    )
    assert suite_annee_1["retirees"]["suppression_10pct"]["aise"].ir_paye == pytest.approx(
        ir_dgfip_1part_2025(rni_aise_suppr), abs=0.01
    )


def test_cli_cp1252_no_unicode_encode_error() -> None:
    """Vérifie que la CLI s'exécute sans UnicodeEncodeError même sous PYTHONIOENCODING=cp1252."""
    env = os.environ.copy()
    env.pop("PYTHONUTF8", None)
    env["PYTHONIOENCODING"] = "cp1252"
    proc = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "engine.reforms.demo_plf2027_retraites",
            "--horizon",
            "annee_1",
        ],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="cp1252",
        errors="replace",
        check=False,
    )
    assert proc.returncode == 0, f"Échec CLI sous CP1252 : {proc.stderr}"
    assert "VERITE FISCALE 2027" in proc.stdout
    assert "Art.3" in proc.stdout


def test_reform_metadata_and_table_rendering(
    suite_annee_1: dict[str, dict[str, dict[str, Any]]],
    suite_regime_permanent: dict[str, dict[str, dict[str, Any]]],
) -> None:
    """Vérifie les attributs DESIGN.md (calc_certainty / legal_status) et les colonnes RFR / CSG (Δ)."""
    assert LoiEnVigueurBaseline.calc_certainty == "green"
    assert LoiEnVigueurBaseline.legal_status == "en_vigueur"
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

    t_ascii = format_comparison_table(suite_annee_1["retirees"], horizon="annee_1", ascii_safe=True)
    assert "EUR" in t_ascii
    assert "Delta" in t_ascii
    t_ascii.encode("ascii")
