"""Construction et simulation OpenFisca d'un profil simplifié."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np
import polars as pl
from openfisca_core import periods
from openfisca_core.simulations import SimulationBuilder

from engine.reforms.demo_plf2027_retraites import DEFAULT_MAX_SPIRAL_LOOPS
from engine.reforms.plf2027_complet_demo import GelBaremeRevenus2026, INCOME_YEAR, PLF2027BaremeEtRetraites
from engine.synthetic.audit_macro import make_tax_payload


# SOURCE: Observatoire local des loyers Bayonne–Pays basque, chiffres clés 2024,
# https://www.observatoires-des-loyers.org/decouvrir-le-reseau/publications/details/observatoire-local-des-loyers-prives-bayonne-pays-basque-sud-landes-les-chiffres-cles-2024
RENT_SOURCE = "https://www.observatoires-des-loyers.org/decouvrir-le-reseau/publications/details/observatoire-local-des-loyers-prives-bayonne-pays-basque-sud-landes-les-chiffres-cles-2024"
DEFAULT_RENT = 650
# SOURCE: OpenFisca-France 177.0.0, valeur par défaut de zone_apl.
DEFAULT_ZONE = 2


@dataclass(frozen=True)
class HouseholdInputs:
    net_taxable_monthly: float
    age: int
    status: str
    couple: bool = False
    children: int = 0
    housing: str = "locataire"
    rent: float | None = None
    zone: int = DEFAULT_ZONE
    child_age: int = 10  # Âge conventionnel explicite pour le profil simplifié.
    gross_monthly: float | None = None
    subsidized_housing: bool = False


# Variables Individu de période mensuelle, inspectées dans OpenFisca-France 177.0.0.
PAYROLL = {
    "salarie_non_cadre": ("salaire_de_base", "salaire_imposable", ("csg_deductible_salaire", "csg_imposable_salaire", "crds_salaire"), ("cotisations_salariales",)),
    "salarie_cadre": ("salaire_de_base", "salaire_imposable", ("csg_deductible_salaire", "csg_imposable_salaire", "crds_salaire"), ("cotisations_salariales",)),
    "retraite": ("retraite_brute", "retraite_imposable", ("csg_deductible_retraite", "csg_imposable_retraite", "crds_retraite"), ("casa",)),
    "chomeur": ("chomage_brut", "chomage_imposable", ("csg_deductible_chomage", "csg_imposable_chomage", "crds_chomage"), ("chomage_cotisation_retraite_complementaire",)),
}


def cache_social_parameters(system, *, prepare_payroll=False) -> None:
    """Garde les instantanés du système local entre les requêtes sociales."""
    @lru_cache(maxsize=192)
    def by_date(date):
        return system.parameters.get_at_instant(date)

    def by_period(value):
        date = value.start if isinstance(value, periods.Period) else periods.instant(value)
        return by_date(date)

    system.get_parameters_at_instant = by_period
    if prepare_payroll:
        system.simple_payroll_tables = _salary_tables(system)


def _salary_tables(system):
    # Échantillonnage numérique du brut annuel OpenFisca. Pas de taux de
    # cotisation recopié. La grille est plus dense près des seuils usuels.
    gross = np.unique(np.r_[np.arange(0, 120_001, 600), np.geomspace(120_000, 12_000_000, 120)])
    tables = {}
    for status, category in (("salarie_non_cadre", "prive_non_cadre"), ("salarie_cadre", "prive_cadre")):
        sim = SimulationBuilder.build_default_simulation(system, len(gross))
        sim.max_spiral_loops = DEFAULT_MAX_SPIRAL_LOOPS
        sim.set_input("categorie_salarie", INCOME_YEAR, np.full(gross.size, category))
        sim.set_input("salaire_de_base", INCOME_YEAR, gross)
        taxable = sim.calculate_add("salaire_imposable", INCOME_YEAR)
        if (np.diff(taxable) > 0).all():
            tables[status] = (taxable, gross)
    return tables


def _simulation(system, payload):
    simulation = SimulationBuilder().build_from_entities(system, payload)
    simulation.max_spiral_loops = DEFAULT_MAX_SPIRAL_LOOPS
    return simulation


def _profile_payload(profile: HouseholdInputs, *, prune_ineligible=True):
    structure = "couple_enfants" if profile.couple and profile.children else "couple" if profile.couple else (
        "monoparental" if profile.children else "seul"
    )
    records = pl.DataFrame([{
        "menage_id": 1, "revenu_declare_moyen": profile.net_taxable_monthly * 12, "age_reference": profile.age,
        "activite": profile.status, "adultes": 1 + profile.couple, "enfants": profile.children,
        "imposition_commune": profile.couple, "structure": structure, "logement": profile.housing, "poids": 1.0,
    }])
    payload, _, _ = make_tax_payload(records, INCOME_YEAR)
    if prune_ineligible:
        # SOURCE: OpenFisca-France 177, isf.py, isf_ifi. Le profil simplifié ne
        # déclare aucune assiette de patrimoine, même pour les propriétaires.
        payload["foyers_fiscaux"]["m1_f0"]["isf_ifi"] = {INCOME_YEAR: 0}
    year = int(INCOME_YEAR)
    years = tuple(map(str, range(year - 4, year + 1)))
    adults = payload["foyers_fiscaux"]["m1_f0"]["declarants"]
    for person_id, person in payload["individus"].items():
        if prune_ineligible:
            # SOURCE: OpenFisca-France 177, minima_sociaux/{aah,asi_aspa,ass}.py.
            # Le profil ne renseigne ni incapacité, ni pension d'invalidité,
            # ni historique permettant de remplir la précondition de l'ASS.
            for variable in ("aah", "asi", "ass"):
                person[variable] = dict.fromkeys(years, 0)
            if profile.status != "retraite" or person_id not in adults:
                person["retraite_nette"] = dict.fromkeys(years, 0)
            if profile.status != "chomeur" or person_id not in adults:
                person["chomage_net"] = dict.fromkeys(years, 0)
        if person_id not in adults:
            person["date_naissance"] = {"ETERNITY": f"{year - profile.child_age}-01-01"}
            person["activite"] = dict.fromkeys(years, "etudiant")
            continue
        activity = {"retraite": "retraite", "chomeur": "chomeur", "inactif": "inactif"}.get(profile.status, "actif")
        person["activite"] = dict.fromkeys(years, activity)
        if profile.status.startswith("salarie"):
            category = "prive_cadre" if profile.status == "salarie_cadre" else "prive_non_cadre"
            person["categorie_salarie"] = dict.fromkeys(years, category)
        if profile.status == "independant":
            person["categorie_non_salarie"] = dict.fromkeys(years, "commercant")
        if profile.couple:
            person["statut_marital"] = dict.fromkeys(years, "marie")
    if not profile.couple and profile.children:
        payload["foyers_fiscaux"]["m1_f0"]["caseT"] = dict.fromkeys(years, True)
    rent = 0 if profile.housing != "locataire" else DEFAULT_RENT if profile.rent is None else profile.rent
    household = payload["menages"]["m1"]
    housing = household["statut_occupation_logement"][INCOME_YEAR]
    household["statut_occupation_logement"] = dict.fromkeys(years, housing)
    household["loyer"] = {f"{y}-{month:02d}": rent for y in years for month in range(1, 13)}
    household["zone_apl"] = dict.fromkeys(years, f"zone_{profile.zone}")
    household["logement_conventionne"] = dict.fromkeys(years, profile.subsidized_housing and profile.housing == "locataire")
    # SOURCE: OpenFisca-France 177, minima_sociaux/asi_aspa.py, aspa_eligibilite.
    # En l'absence d'inaptitude, l'ASPA est nulle en deçà de l'âge normal.
    if prune_ineligible and profile.age < 65:
        payload["familles"]["m1_fam0"]["aspa"] = dict.fromkeys(years, 0)
    return payload, adults, years, rent


def _estimate_gross(system, payload, adults, years, gross_var, taxable_var, net_taxable, *, table=None):
    if not net_taxable:
        return 0.0
    yearly_taxable = net_taxable * 12 / len(adults)
    low = 0.0
    low_value = 0.0
    high = yearly_taxable * 2
    def evaluate(candidate):
        # Le candidat n'est renseigné que sur N. L'inversion garde les revenus
        # imposables historiques de N-4 à N-1 au niveau fourni.
        for person_id in adults:
            person = payload["individus"][person_id]
            person[gross_var] = {INCOME_YEAR: candidate}
            person[taxable_var] = dict.fromkeys(years[:-1], yearly_taxable)
        simulation = _simulation(system, payload)
        return float(simulation.calculate_add(taxable_var, INCOME_YEAR)[0])

    if table is not None and table[0][0] < yearly_taxable < table[0][-1]:
        taxable_grid, gross_grid = table
        index = np.searchsorted(taxable_grid, yearly_taxable)
        inverse_slope = (gross_grid[index] - gross_grid[index - 1]) / (taxable_grid[index] - taxable_grid[index - 1])
        candidate = float(np.interp(yearly_taxable, taxable_grid, gross_grid))
        if 1 < index < len(gross_grid) - 1:
            nearby = slice(index - 2, index + 2)
            slopes = np.diff(gross_grid[nearby]) / np.diff(taxable_grid[nearby])
            if np.allclose(slopes, inverse_slope, rtol=1e-5, atol=0):
                return candidate * len(adults) / 12
        value = evaluate(candidate)
        if abs(value - yearly_taxable) <= 0.05:
            return candidate * len(adults) / 12
        adjusted = candidate + inverse_slope * (yearly_taxable - value)
        if abs(evaluate(adjusted) - yearly_taxable) <= 0.05:
            return adjusted * len(adults) / 12
        # Aux ruptures de pente, conserver l'inversion de référence.
    high_value = evaluate(high)
    while high_value < yearly_taxable:
        high *= 2
        if high > yearly_taxable * 8:
            raise ValueError("Le revenu brut ne peut pas être estimé pour ce profil")
        high_value = evaluate(high)
    # L'IR conserve le montant saisi. Cette inversion sert au calcul des cotisations et du net payé.
    for _ in range(12):
        middle = low + (high - low) * (yearly_taxable - low_value) / (high_value - low_value)
        value = evaluate(middle)
        if abs(value - yearly_taxable) <= 0.05:
            return middle * len(adults) / 12
        if value < yearly_taxable:
            low, low_value = middle, value
        else:
            high, high_value = middle, value
    return middle * len(adults) / 12


def _estimate_unemployment_gross(system, payload, adults, years, net_taxable):
    if not net_taxable:
        return 0.0
    # SOURCE: OpenFisca-France 177, remplacement.py, csg_deductible_chomage.
    # Avec l'ARE seule, le RFR historique est au plus le net imposable saisi.
    # Le seuil pour une part suffit à garantir l'exonération de toute CSG.
    months = [system.get_parameters_at_instant(f"{INCOME_YEAR}-{month:02d}") for month in range(1, 13)]
    laws = [month.prelevements_sociaux.contributions_sociales.csg.remplacement for month in months]
    if net_taxable * 12 <= min(law.seuils.seuil_rfr1.seuil_rfr1 for law in laws):
        return net_taxable
    target = net_taxable * 12 / len(adults)
    for identifier in adults:
        payload["individus"][identifier]["chomage_imposable"] = dict.fromkeys(years[:-1], target)

    def sample(lower, upper, count):
        axes = [[{"name": "chomage_brut", "period": INCOME_YEAR, "index": i, "count": count,
                  "min": lower, "max": upper} for i in range(len(adults))]]
        sim = _simulation(system, {**payload, "axes": axes})
        taxable = sim.calculate_add("chomage_imposable", INCOME_YEAR)[::len(payload["individus"])]
        return np.linspace(lower, upper, count), taxable

    # Le taux et l'écrêtement dépendent des parts et ressources historiques.
    # Une première courbe borne la solution, puis la seconde affine le segment.
    gross, taxable = sample(target, 2 * target, 33)
    if taxable[0] >= target - 0.05:
        return net_taxable
    index = int(np.searchsorted(taxable, target))
    if index >= gross.size:
        raise ValueError("Le revenu brut ne peut pas être estimé pour ce profil")
    gross, taxable = sample(gross[index - 1], gross[index], 33)
    return float(np.interp(target, taxable, gross)) * len(adults) / 12


def simulate_social(profile: HouseholdInputs, baseline, reform, *, prune_ineligible=True, fast_unemployment=True) -> tuple[dict, dict, dict]:
    if profile.status == "inactif" and profile.net_taxable_monthly:
        raise ValueError("Pour un revenu imposable positif, renseigner sa catégorie fiscale")
    if profile.gross_monthly is not None and profile.status not in PAYROLL:
        raise ValueError("Le brut est ajustable pour les salariés, les retraités et les personnes au chômage")
    # Le chômage peut traverser des cycles de ressources OpenFisca. Conserver
    # son parcours de référence, y compris l'ordre d'évaluation des prestations.
    optimize = prune_ineligible and profile.status != "chomeur"
    payload, adults, years, rent = _profile_payload(profile, prune_ineligible=optimize)
    payroll = PAYROLL.get(profile.status)
    gross = profile.gross_monthly
    if payroll:
        gross_var, taxable_var, _, _ = payroll
        for person in payload["individus"].values():
            person[taxable_var].pop(INCOME_YEAR, None)
        if gross is None:
            if profile.status == "chomeur" and fast_unemployment:
                gross = _estimate_unemployment_gross(baseline, payload, adults, years, profile.net_taxable_monthly)
            else:
                tables = getattr(baseline, "simple_payroll_tables", {}) if optimize else {}
                gross = _estimate_gross(baseline, payload, adults, years, gross_var, taxable_var,
                                        profile.net_taxable_monthly, table=tables.get(profile.status))
        for person_id in adults:
            person = payload["individus"][person_id]
            person[gross_var] = dict.fromkeys(years, gross * 12 / len(adults))
            if profile.gross_monthly is None:
                person[taxable_var] = dict.fromkeys(years, profile.net_taxable_monthly * 12 / len(adults))
            else:
                person.pop(taxable_var, None)

    def scenario(sim):
        def total(name, monthly=False):
            calculation = sim.calculate_add if monthly else sim.calculate
            return float(calculation(name, INCOME_YEAR).sum(dtype="float64"))
        csg = cotisations = 0.0
        if payroll:
            csg = -sum(total(name, True) for name in payroll[2])
            cotisations = -sum(total(name, True) for name in payroll[3])
        if profile.status == "independant":
            csg = -sum(total(name) for name in ("csg_deductible_non_salarie", "csg_imposable_non_salarie", "crds_non_salarie"))
            cotisations = -total("cotisations_non_salarie")
        return {
            "impot_revenu": -total("impot_revenu_restant_a_payer"),
            "csg_crds": csg,
            "cotisations": cotisations,
            "prime_activite": total("ppa", True),
            "aide_logement": total("aide_logement", True),
            "allocations_familiales": total("af_nettes_crds", True),
            "prestations_sociales": total("prestations_sociales"),
            "revenu_disponible": total("revenu_disponible"),
        }
    assumptions = {
        "loyer_mensuel": rent, "zone_apl": profile.zone, "age_enfant": profile.child_age,
        "revenu_brut_mensuel": None if gross is None else round(gross, 2),
        "brut_saisi": profile.gross_monthly is not None,
        "logement_conventionne": profile.subsidized_housing and profile.housing == "locataire",
    }
    reference = _simulation(baseline, payload)
    proposed = _simulation(reform, payload)
    before = scenario(reference)
    shared_social = (
        optimize and profile.status != "retraite"
        and type(baseline) is GelBaremeRevenus2026 and type(reform) is PLF2027BaremeEtRetraites
    )
    if not shared_social:
        return before, scenario(proposed), assumptions

    # SOURCE: PLF 2027 déposé, art. 2–3, et OpenFisca-France 177, mesures.py.
    # Ce profil ne comporte ni pension, ni charge déductible, ni enfant marié.
    # Les articles 2–3 laissent ses prestations et ses revenus nets inchangés.
    # Le scénario proposé recalcule ses impôts directs et le revenu disponible.
    for variable in ("revenus_nets_du_travail", "pensions_nettes", "revenus_nets_du_capital", "prestations_sociales"):
        proposed.set_input(variable, INCOME_YEAR, reference.calculate(variable, INCOME_YEAR))
    after = {
        **before,
        "impot_revenu": -float(proposed.calculate("impot_revenu_restant_a_payer", INCOME_YEAR)[0]),
        "revenu_disponible": float(proposed.calculate("revenu_disponible", INCOME_YEAR)[0]),
    }
    return before, after, assumptions
