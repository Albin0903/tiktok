"""Simulation déterministe PLF 2027 (démo) : Abattement de 10 % sur les pensions de retraite.

Compare deux variantes paramétriques sur OpenFisca-France (année de référence 2025,
en régime permanent avec boucle RFR N-2 activée via ``max_spiral_loops=3``) :
  1. Plafonnement de l'abattement de 10 % (CGI art. 158-5-a) à 3 000 € par foyer fiscal
     (au lieu de 4 439 € en 2025).
  2. Suppression totale de l'abattement de 10 % sur les pensions (taux = 0 %, min = 0, max = 0).

SOURCE: CGI art. 158-5-a, https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000048801686
SOURCE: OpenFisca-France v177.0.0 parameters (impot_revenu.calcul_revenus_imposables.deductions.abatpen)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any

if __package__ in (None, ""):
    _engine_root = str(Path(__file__).resolve().parent.parent)
    if _engine_root not in sys.path:
        sys.path.insert(0, _engine_root)

from openfisca_core.reforms import Reform
from openfisca_core.simulations import SimulationBuilder
from openfisca_core.taxbenefitsystems import TaxBenefitSystem
from pydantic import BaseModel

from reforms import get_tax_benefit_system

# SOURCE: Législation fiscale 2025 intégrée à OpenFisca-France v177.0.0 (CGI art. 158-5-a)
REFERENCE_YEAR = "2025"
HISTORY_YEARS = ("2021", "2022", "2023", "2024", "2025")
# SOURCE: OpenFisca-France (csg_deductible_retraite dépend de rfr(N-2), lui-même fonction de csg_deductible_retraite(N-2))
DEFAULT_MAX_SPIRAL_LOOPS = 3
# SOURCE: Piste débattue PLF / Rapports CPO & IPP — abaissement du plafond foyer fiscal de 4 439 € à 3 000 €
PLAFOND_ABATPEN_3000 = 3000.0
# SOURCE: SMIC annuel brut 2025 approximatif (1 801,80 € x 12), Code du travail art. L3231-2
SMIC_ANNUEL_BRUT_2025 = 21621.60


class PlafonnementAbattementRetraites3000(Reform):
    """Plafonne l'abattement forfaitaire de 10 % sur les pensions à 3 000 € par foyer fiscal.

    Certitude : 🟢 CERTITUDE LÉGISLATIVE / CALCUL DIRECT (paramètre abatpen.max).
    """

    name = "Plafonnement abattement 10 % pensions à 3 000 €"

    def __init__(self, baseline: TaxBenefitSystem, start_date: str = "2021-01-01") -> None:
        self._start_date = start_date
        super().__init__(baseline)

    def apply(self) -> None:
        start_date = self._start_date

        def modify_params(parameters: Any) -> Any:
            # SOURCE: CGI art. 158-5-a — plafond annuel par foyer fiscal abaissé de 4 439 € (2025) à 3 000 €
            parameters.impot_revenu.calcul_revenus_imposables.deductions.abatpen.max.update(
                start=start_date,
                value=PLAFOND_ABATPEN_3000,
            )
            return parameters

        self.modify_parameters(modifier_function=modify_params)


class SuppressionAbattementRetraites10Pct(Reform):
    """Supprime intégralement l'abattement forfaitaire de 10 % sur les pensions de retraite.

    Certitude : 🟢 CERTITUDE LÉGISLATIVE / CALCUL DIRECT (paramètres abatpen.taux/min/max).
    """

    name = "Suppression abattement 10 % pensions"

    def __init__(self, baseline: TaxBenefitSystem, start_date: str = "2021-01-01") -> None:
        self._start_date = start_date
        super().__init__(baseline)

    def apply(self) -> None:
        start_date = self._start_date

        def modify_params(parameters: Any) -> Any:
            # SOURCE: CGI art. 158-5-a — suppression du taux de 10 %, du plancher (454 €) et du plafond (4 439 €)
            abatpen = parameters.impot_revenu.calcul_revenus_imposables.deductions.abatpen
            abatpen.taux.update(start=start_date, value=0.0)
            abatpen.min.update(start=start_date, value=0.0)
            abatpen.max.update(start=start_date, value=0.0)
            return parameters

        self.modify_parameters(modifier_function=modify_params)


class HouseholdResult(BaseModel):
    """Résultat socio-fiscal annuel (année 2025) pour un foyer type donné.

    Convention d'affichage comptable :
      - ``ir_paye`` >= 0 : impôt sur le revenu payé (opposé de ``impot_revenu_restant_a_payer``).
      - ``csg_retraite`` >= 0 : CSG totale sur pensions (déductible + imposable).
      - ``prelevements_sociaux_retraite`` >= 0 : CSG + CRDS + CASA sur pensions.
      - ``revenu_disponible`` : variable OpenFisca ``revenu_disponible`` (Menage, YEAR).
    """

    household_id: str
    label: str
    scenario: str
    pension_brute_annuelle: float
    salaire_brut_annuel: float
    ir_paye: float
    csg_retraite: float
    prelevements_sociaux_retraite: float
    revenu_disponible: float


@dataclass(frozen=True)
class HouseholdSpec:
    household_id: str
    label: str
    member_ids: tuple[str, ...]


def _const_years(value: Any) -> dict[str, Any]:
    return {year: value for year in HISTORY_YEARS}


def build_retiree_households_payload() -> tuple[dict[str, Any], list[HouseholdSpec]]:
    """Construit les 5 foyers types de retraités couvrant l'éventail des barèmes IR/CSG."""
    specs = [
        HouseholdSpec("modeste", "1. Retraité isolé modeste (1 200 €/mois brut)", ("ret_modeste",)),
        HouseholdSpec("median", "2. Retraité isolé médian (2 400 €/mois brut)", ("ret_median",)),
        HouseholdSpec("intermediaire", "3. Retraité isolé intermédiaire (3 200 €/mois brut)", ("ret_inter",)),
        HouseholdSpec("aise", "4. Retraité isolé aisé (4 500 €/mois brut)", ("ret_aise",)),
        HouseholdSpec(
            "couple_aise",
            "5. Couple retraités aisés (3 000 + 2 500 €/mois brut)",
            ("ret_couple_1", "ret_couple_2"),
        ),
    ]
    payload: dict[str, Any] = {
        "individus": {
            "ret_modeste": {
                "date_naissance": {"ETERNITY": "1958-01-01"},
                "retraite_brute": _const_years(14400.0),
            },
            "ret_median": {
                "date_naissance": {"ETERNITY": "1958-01-01"},
                "retraite_brute": _const_years(28800.0),
            },
            "ret_inter": {
                "date_naissance": {"ETERNITY": "1958-01-01"},
                "retraite_brute": _const_years(38400.0),
            },
            "ret_aise": {
                "date_naissance": {"ETERNITY": "1958-01-01"},
                "retraite_brute": _const_years(54000.0),
            },
            "ret_couple_1": {
                "date_naissance": {"ETERNITY": "1958-01-01"},
                "statut_marital": _const_years("marie"),
                "retraite_brute": _const_years(36000.0),
            },
            "ret_couple_2": {
                "date_naissance": {"ETERNITY": "1959-01-01"},
                "statut_marital": _const_years("marie"),
                "retraite_brute": _const_years(30000.0),
            },
        },
        "foyers_fiscaux": {
            "ff_modeste": {"declarants": ["ret_modeste"]},
            "ff_median": {"declarants": ["ret_median"]},
            "ff_inter": {"declarants": ["ret_inter"]},
            "ff_aise": {"declarants": ["ret_aise"]},
            "ff_couple_aise": {"declarants": ["ret_couple_1", "ret_couple_2"]},
        },
        "familles": {
            "fam_modeste": {"parents": ["ret_modeste"]},
            "fam_median": {"parents": ["ret_median"]},
            "fam_inter": {"parents": ["ret_inter"]},
            "fam_aise": {"parents": ["ret_aise"]},
            "fam_couple_aise": {"parents": ["ret_couple_1", "ret_couple_2"]},
        },
        "menages": {
            "men_modeste": {"personne_de_reference": ["ret_modeste"]},
            "men_median": {"personne_de_reference": ["ret_median"]},
            "men_inter": {"personne_de_reference": ["ret_inter"]},
            "men_aise": {"personne_de_reference": ["ret_aise"]},
            "men_couple_aise": {"personne_de_reference": ["ret_couple_1"], "conjoint": ["ret_couple_2"]},
        },
    }
    return payload, specs


def build_active_control_households_payload() -> tuple[dict[str, Any], list[HouseholdSpec]]:
    """Construit les 3 foyers d'actifs du protocole AGENTS.md pour contrôler l'invariance."""
    specs = [
        HouseholdSpec("smicard_isole", "Actif A. SMICard isolé (21 622 €/an brut)", ("act_smic",)),
        HouseholdSpec(
            "couple_2_enfants",
            "Actif B. Couple salarié avec 2 enfants (54 000 €/an brut)",
            ("act_c1", "act_c2", "enf_1", "enf_2"),
        ),
        HouseholdSpec("cadre_proprietaire", "Actif C. Cadre propriétaire isolé (60 000 €/an brut)", ("act_cadre",)),
    ]
    payload: dict[str, Any] = {
        "individus": {
            "act_smic": {
                "date_naissance": {"ETERNITY": "1995-01-01"},
                "salaire_de_base": _const_years(SMIC_ANNUEL_BRUT_2025),
            },
            "act_c1": {
                "date_naissance": {"ETERNITY": "1986-01-01"},
                "statut_marital": _const_years("marie"),
                "salaire_de_base": _const_years(30000.0),
            },
            "act_c2": {
                "date_naissance": {"ETERNITY": "1988-01-01"},
                "statut_marital": _const_years("marie"),
                "salaire_de_base": _const_years(24000.0),
            },
            "enf_1": {"date_naissance": {"ETERNITY": "2015-05-01"}},
            "enf_2": {"date_naissance": {"ETERNITY": "2018-09-01"}},
            "act_cadre": {
                "date_naissance": {"ETERNITY": "1984-01-01"},
                "salaire_de_base": _const_years(60000.0),
            },
        },
        "foyers_fiscaux": {
            "ff_smic": {"declarants": ["act_smic"]},
            "ff_couple_2e": {"declarants": ["act_c1", "act_c2"], "personnes_a_charge": ["enf_1", "enf_2"]},
            "ff_cadre": {"declarants": ["act_cadre"]},
        },
        "familles": {
            "fam_smic": {"parents": ["act_smic"]},
            "fam_couple_2e": {"parents": ["act_c1", "act_c2"], "enfants": ["enf_1", "enf_2"]},
            "fam_cadre": {"parents": ["act_cadre"]},
        },
        "menages": {
            "men_smic": {"personne_de_reference": ["act_smic"]},
            "men_couple_2e": {
                "personne_de_reference": ["act_c1"],
                "conjoint": ["act_c2"],
                "enfants": ["enf_1", "enf_2"],
            },
            "men_cadre": {"personne_de_reference": ["act_cadre"], "statut_occupation_logement": _const_years("proprietaire")},
        },
    }
    return payload, specs


def evaluate_households(
    tax_benefit_system: TaxBenefitSystem,
    payload: dict[str, Any],
    specs: list[HouseholdSpec],
    scenario_name: str,
    period: str = REFERENCE_YEAR,
) -> list[HouseholdResult]:
    """Exécute une simulation OpenFisca déterministe et retourne les indicateurs par foyer."""
    sim = SimulationBuilder().build_from_entities(tax_benefit_system, payload)
    sim.max_spiral_loops = DEFAULT_MAX_SPIRAL_LOOPS

    ir_arr = sim.calculate("impot_revenu_restant_a_payer", period)
    rev_disp_arr = sim.calculate("revenu_disponible", period)

    csg_ded = sim.calculate_add("csg_deductible_retraite", period)
    csg_imp = sim.calculate_add("csg_imposable_retraite", period)
    crds_ret = sim.calculate_add("crds_retraite", period)
    casa_ret = sim.calculate_add("casa", period)
    retraite_brute = sim.calculate_add("retraite_brute", period)
    salaire_brut = sim.calculate_add("salaire_de_base", period)

    person_ids = list(sim.persons.ids)
    person_index = {pid: idx for idx, pid in enumerate(person_ids)}

    results: list[HouseholdResult] = []
    for h_idx, spec in enumerate(specs):
        member_indices = [person_index[pid] for pid in spec.member_ids]
        # En OpenFisca-France, l'IR et les prélèvements sociaux calculés sont négatifs.
        # L'addition `+ 0.0` normalise IEEE-754 `-0.0` en `0.0` pour un affichage comptable propre.
        ir_paye = round(float(-ir_arr[h_idx]), 2) + 0.0
        csg_tot = round(float(-sum(csg_ded[i] + csg_imp[i] for i in member_indices)), 2) + 0.0
        ps_tot = round(
            float(-sum(csg_ded[i] + csg_imp[i] + crds_ret[i] + casa_ret[i] for i in member_indices)),
            2,
        ) + 0.0
        rev_disp = round(float(rev_disp_arr[h_idx]), 2) + 0.0
        pens_brute = round(float(sum(retraite_brute[i] for i in member_indices)), 2) + 0.0
        sal_brut = round(float(sum(salaire_brut[i] for i in member_indices)), 2) + 0.0

        results.append(
            HouseholdResult(
                household_id=spec.household_id,
                label=spec.label,
                scenario=scenario_name,
                pension_brute_annuelle=pens_brute,
                salaire_brut_annuel=sal_brut,
                ir_paye=ir_paye,
                csg_retraite=csg_tot,
                prelevements_sociaux_retraite=ps_tot,
                revenu_disponible=rev_disp,
            )
        )
    return results


def run_comparison_suite() -> dict[str, dict[str, list[HouseholdResult]]]:
    """Lance la comparaison complète (Base vs Plafond 3 000 € vs Suppression 10 %)."""
    baseline = get_tax_benefit_system()
    systems: dict[str, TaxBenefitSystem] = {
        "base": baseline,
        "plafond_3000": PlafonnementAbattementRetraites3000(baseline),
        "suppression_10pct": SuppressionAbattementRetraites10Pct(baseline),
    }

    retiree_payload, retiree_specs = build_retiree_households_payload()
    active_payload, active_specs = build_active_control_households_payload()

    retirees: dict[str, list[HouseholdResult]] = {}
    actives: dict[str, list[HouseholdResult]] = {}
    for scenario_name, tbs in systems.items():
        retirees[scenario_name] = evaluate_households(tbs, retiree_payload, retiree_specs, scenario_name)
        actives[scenario_name] = evaluate_households(tbs, active_payload, active_specs, scenario_name)

    return {"retirees": retirees, "actives": actives}


def format_comparison_table(retirees_by_scenario: dict[str, list[HouseholdResult]]) -> str:
    """Formate un tableau Markdown clair comparant IR, CSG et Revenu Disponible."""
    base_rows = retirees_by_scenario["base"]
    plaf_rows = retirees_by_scenario["plafond_3000"]
    supp_rows = retirees_by_scenario["suppression_10pct"]

    header = (
        "| Foyer type (2025, €/an) | Brut/an | Base IR | Base CSG | Base RevDisp | "
        "Plaf. 3000€ IR (Δ) | Plaf. 3000€ RevDisp (Δ) | Suppr. 10% IR (Δ) | Suppr. 10% RevDisp (Δ) |"
    )
    sep = "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
    lines = [header, sep]

    for b, p, s in zip(base_rows, plaf_rows, supp_rows, strict=True):
        d_ir_p = p.ir_paye - b.ir_paye
        d_rd_p = p.revenu_disponible - b.revenu_disponible
        d_ir_s = s.ir_paye - b.ir_paye
        d_rd_s = s.revenu_disponible - b.revenu_disponible
        lines.append(
            f"| {b.label} | {b.pension_brute_annuelle:,.0f} € | "
            f"{b.ir_paye:,.0f} € | {b.csg_retraite:,.0f} € | {b.revenu_disponible:,.2f} € | "
            f"{p.ir_paye:,.0f} € ({d_ir_p:+,.0f} €) | {p.revenu_disponible:,.2f} € ({d_rd_p:+,.2f} €) | "
            f"{s.ir_paye:,.0f} € ({d_ir_s:+,.0f} €) | {s.revenu_disponible:,.2f} € ({d_rd_s:+,.2f} €) |"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    suite = run_comparison_suite()
    print("=== VERITE FISCALE 2027 :: DEMO PLF RETRAITES (OPENFISCA-FRANCE 2025) ===\n")
    print(format_comparison_table(suite["retirees"]))
    print("\n=== CONTROLE INVARIANCE ACTIFS (AGENTS.md) ===")
    for b, p, s in zip(
        suite["actives"]["base"],
        suite["actives"]["plafond_3000"],
        suite["actives"]["suppression_10pct"],
        strict=True,
    ):
        print(
            f"- {b.label}: Base RevDisp={b.revenu_disponible:,.2f} € | "
            f"Δ Plaf3000={p.revenu_disponible - b.revenu_disponible:+.2f} € | "
            f"Δ Suppr10%={s.revenu_disponible - b.revenu_disponible:+.2f} €"
        )
