"""Tests pytest déterministes pour la démo PLF 2027 retraites (OpenFisca-France sur Win11 ARM64)."""

from __future__ import annotations

import pytest

from reforms import get_tax_benefit_system
from reforms.demo_plf2027_retraites import (
    PLAFOND_ABATPEN_3000,
    format_comparison_table,
    run_comparison_suite,
)


@pytest.fixture(scope="module")
def suite_results() -> dict[str, dict[str, list]]:
    return run_comparison_suite()


def test_openfisca_long_path_parameters_loaded() -> None:
    """Vérifie que les paramètres à chemin long (aides_logement) chargent sans erreur sous Windows."""
    tbs = get_tax_benefit_system()
    p2025 = tbs.parameters("2025-01-01")
    assert p2025.impot_revenu.calcul_revenus_imposables.deductions.abatpen.max == 4439
    assert p2025.impot_revenu.calcul_revenus_imposables.deductions.abatpen.min == 454
    assert p2025.impot_revenu.calcul_revenus_imposables.deductions.abatpen.taux == 0.1
    # Paramètres profonds ayant provoqué ParameterNotFoundError sans préfixe \\?\
    assert (
        p2025.prestations_sociales.aides_logement.allocations_logement.locatif.formule.pp_particip_perso.tp_taux.tf_taille_famille.metropole.personnes_isolees
        is not None
    )


def test_five_retiree_households_exact_impacts(suite_results: dict[str, dict[str, list]]) -> None:
    """Vérifie l'IR, la CSG et le Revenu Disponible sur les 5 profils de retraités."""
    base = {r.household_id: r for r in suite_results["retirees"]["base"]}
    plaf = {r.household_id: r for r in suite_results["retirees"]["plafond_3000"]}
    supp = {r.household_id: r for r in suite_results["retirees"]["suppression_10pct"]}

    # 1. Retraité modeste (14 400 €/an) : non imposable et exonéré CSG dans les 3 scénarios
    assert base["modeste"].ir_paye == 0.0
    assert base["modeste"].csg_retraite == 0.0
    assert plaf["modeste"].revenu_disponible == pytest.approx(base["modeste"].revenu_disponible, abs=0.01)
    assert supp["modeste"].revenu_disponible == pytest.approx(base["modeste"].revenu_disponible, abs=0.01)

    # 2. Retraité médian (28 800 €/an) : abattement initial 2 759 € < 3 000 € -> neutre sous plafond 3 000 €
    assert base["median"].csg_retraite > 0.0  # Vérifie que la boucle N-2 max_spiral_loops=3 est active
    assert base["median"].ir_paye == 991.0
    assert plaf["median"].ir_paye == base["median"].ir_paye
    assert plaf["median"].revenu_disponible == pytest.approx(base["median"].revenu_disponible, abs=0.01)
    # Sous suppression 10 % : perd 442 €/an d'IR (991 € -> 1 433 €)
    assert supp["median"].ir_paye > base["median"].ir_paye
    assert (supp["median"].revenu_disponible - base["median"].revenu_disponible) == pytest.approx(-442.0, abs=1.0)

    # 3. Retraité intermédiaire (38 400 €/an) : perd avec le plafonnement ET davantage avec la suppression
    assert plaf["intermediaire"].ir_paye > base["intermediaire"].ir_paye
    assert supp["intermediaire"].ir_paye > plaf["intermediaire"].ir_paye
    assert (
        supp["intermediaire"].revenu_disponible
        < plaf["intermediaire"].revenu_disponible
        < base["intermediaire"].revenu_disponible
    )

    # 4. Retraité aisé (54 000 €/an) : perte maximale plafonnée à (4439 - 3000) * 30 % = 432 € sous plafond 3000 €
    delta_plaf_aise = plaf["aise"].ir_paye - base["aise"].ir_paye
    expected_max_loss = (4439.0 - PLAFOND_ABATPEN_3000) * 0.30
    assert delta_plaf_aise == pytest.approx(expected_max_loss, abs=1.0)
    assert (supp["aise"].ir_paye - base["aise"].ir_paye) == pytest.approx(4439.0 * 0.30, abs=1.0)

    # 5. Couple retraités aisés (66 000 €/an) : le plafond s'applique au niveau du foyer fiscal
    assert plaf["couple_aise"].ir_paye > base["couple_aise"].ir_paye
    assert supp["couple_aise"].ir_paye > plaf["couple_aise"].ir_paye
    assert (
        supp["couple_aise"].revenu_disponible
        < plaf["couple_aise"].revenu_disponible
        < base["couple_aise"].revenu_disponible
    )


def test_active_control_households_invariant(suite_results: dict[str, dict[str, list]]) -> None:
    """Vérifie qu'aucun ménage d'actifs sans pension n'est affecté par la réforme retraites."""
    base = {r.household_id: r for r in suite_results["actives"]["base"]}
    plaf = {r.household_id: r for r in suite_results["actives"]["plafond_3000"]}
    supp = {r.household_id: r for r in suite_results["actives"]["suppression_10pct"]}

    for hid in ("smicard_isole", "couple_2_enfants", "cadre_proprietaire"):
        assert base[hid].pension_brute_annuelle == 0.0
        assert plaf[hid].ir_paye == pytest.approx(base[hid].ir_paye, abs=0.01)
        assert supp[hid].ir_paye == pytest.approx(base[hid].ir_paye, abs=0.01)
        assert plaf[hid].revenu_disponible == pytest.approx(base[hid].revenu_disponible, abs=0.01)
        assert supp[hid].revenu_disponible == pytest.approx(base[hid].revenu_disponible, abs=0.01)


def test_comparison_table_rendering(suite_results: dict[str, dict[str, list]]) -> None:
    """Vérifie que le rendu du tableau comparatif contient les 5 profils et les colonnes clés."""
    table = format_comparison_table(suite_results["retirees"])
    for keyword in ("Retraité isolé modeste", "Retraité isolé médian", "Couple retraités aisés", "Base CSG", "Plaf. 3000€"):
        assert keyword in table
