"""Compare les agrégats de France Synthétique aux références RP et IRCOM."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import polars as pl
from openfisca_core.simulations import SimulationBuilder

from engine.reforms import get_tax_benefit_system
from engine.reforms.demo_plf2027_retraites import DEFAULT_MAX_SPIRAL_LOOPS
from engine.synthetic.build_synthetic_france import OUTPUT
from engine.synthetic.fetch_official_data import RAW_DIR
from engine.synthetic.official_margins import RFR_PER_PART_MEANS_2024, rank_groups, read_census, read_ircom, read_ircom_bands, read_ircom_tail


# SOURCE: INSEE RP 2023 et DGFiP IRCOM 2024, revenus 2023.
# https://www.data.gouv.fr/datasets/limpot-sur-le-revenu-par-collectivite-territoriale-ircom
AUDIT_YEAR = "2023"

TAXABLE_INPUTS = {
    "salarie_cadre": "salaire_imposable",
    "salarie_non_cadre": "salaire_imposable",
    "retraite": "retraite_imposable",
    "independant": "rpns_imposables",
    "chomeur": "chomage_imposable",
}
INCOME_VARIABLES = tuple(dict.fromkeys(TAXABLE_INPUTS.values()))
INDIVIDUAL_TAX_CASES = {
    "f6ns", "f6rs", "abnc_impo", "abic_impn",
}


def make_tax_payload(
    records: pl.DataFrame, year: str
) -> tuple[dict[str, Any], dict[str, int], float]:
    payload: dict[str, Any] = {name: {} for name in ("individus", "foyers_fiscaux", "familles", "menages")}
    tax_households = {}
    unallocated_income = 0.0
    for row in records.iter_rows(named=True):
        household_id = row["menage_id"]
        prefix = f"m{household_id}"
        adults = [f"{prefix}_a{i}" for i in range(row["adultes"])]
        children = [f"{prefix}_e{i}" for i in range(row["enfants"])]
        autonomous = children[:row.get("cohabitants_fiscaux", 0)]
        dependants = children[len(autonomous):]
        common_tax = row["imposition_commune"]
        colocation = row["structure"] == "colocation"
        taxable_input = TAXABLE_INPUTS.get(row["activite"])
        income = row["revenu_declare_moyen"]
        cohabitant_income = row.get("revenu_cohabitant_eur", 0)
        income_per_adult = (income - cohabitant_income * len(autonomous)) / len(adults)
        income_years = [str(income_year) for income_year in range(int(year) - 4, int(year) + 1)]

        # Hypothèses de reconstruction ERFS : revenus répartis entre adultes,
        # activité et âge communs aux adultes, enfants mineurs à charge.
        # Les revenus de catégorie inconnue restent chiffrés dans l'audit.
        for adult in adults:
            person = {
                "date_naissance": {"ETERNITY": f"{int(year) - row['age_reference']}-01-01"},
            }
            for variable in INCOME_VARIABLES:
                person[variable] = dict.fromkeys(income_years, income_per_adult if variable == taxable_input else 0)
            if not taxable_input:
                unallocated_income += row["poids"] * income_per_adult
            if common_tax:
                person["statut_marital"] = {year: "marie"}
            payload["individus"][adult] = person
        for child in children:
            age = 22 if child in autonomous else row.get("age_enfant_impute", 10)
            payload["individus"][child] = {
                "date_naissance": {"ETERNITY": f"{int(year) - age}-01-01"},
                **{
                    variable: dict.fromkeys(income_years, cohabitant_income if child in autonomous and variable == "salaire_imposable" else 0)
                    for variable in INCOME_VARIABLES
                },
            }

        tax_groups = [adults] if common_tax else [[adult] for adult in adults]
        tax_groups.extend([person] for person in autonomous)
        statuses = row.get("situations_fiscales") or []
        imputed_cases = row.get("cases_fiscales") or []
        for index, group in enumerate(tax_groups):
            tax_id = f"{prefix}_f{index}"
            if index < len(statuses):
                for member in group:
                    payload["individus"][member]["statut_marital"] = dict.fromkeys(income_years, statuses[index])
            payload["foyers_fiscaux"][tax_id] = {
                "declarants": group,
                "personnes_a_charge": dependants if index == 0 else [],
            }
            if index == 0 and row["structure"] == "monoparental" and dependants:
                payload["foyers_fiscaux"][tax_id]["caseT"] = {year: True}
            if index < len(imputed_cases):
                cases = imputed_cases[index]
                for name, value in cases.items():
                    if not value:
                        continue
                    variable = name.removesuffix("_partenaire")
                    if variable in INDIVIDUAL_TAX_CASES:
                        member = group[1 if variable != name else 0]
                        inputs = payload["individus"][member]
                        if variable in {"abnc_impo", "abic_impn"}:
                            inputs["rpns_imposables"].pop(year, None)
                        inputs[variable] = {year: value}
                    else:
                        is_checkbox = name.startswith("case") or name == "f2op"
                        payload["foyers_fiscaux"][tax_id][name] = {year: bool(value) if is_checkbox else value}
            tax_households[tax_id] = household_id
        family_groups = [[adult] for adult in adults] if colocation else [adults]
        for index, group in enumerate(family_groups):
            payload["familles"][f"{prefix}_fam{index}"] = {
                "parents": group,
                "enfants": dependants if index == 0 else [],
            }
        for index, person in enumerate(autonomous, start=len(family_groups)):
            payload["familles"][f"{prefix}_fam{index}"] = {"parents": [person]}
        payload["menages"][prefix] = {
            "personne_de_reference": adults[:1],
            "conjoint": [] if colocation else adults[1:],
            "autres": [*(adults[1:] if colocation else []), *autonomous],
            "enfants": dependants,
            "statut_occupation_logement": {
                year: "locataire_vide" if row["logement"] == "locataire" else row["logement"]
            },
        }
    return payload, tax_households, unallocated_income


def calculate_tax(
    records: pl.DataFrame, system: Any, year: str, *, include_rfr: bool = True
) -> tuple[pl.DataFrame, float]:
    payload, tax_households, unallocated_income = make_tax_payload(records, year)
    simulation = SimulationBuilder().build_from_entities(system, payload)
    simulation.max_spiral_loops = DEFAULT_MAX_SPIRAL_LOOPS
    # SOURCE: DGFiP IRCOM 2024 (note sous les tableaux régionaux) et OpenFisca-France 177.
    # L'IRCOM vise la mise en rôle. Le prélèvement déjà versé sur les RCM est
    # imputé en 2CK, compensé par OpenFisca. Les plus-values PFU restent au rôle.
    tax = -simulation.calculate("impot_revenu_restant_a_payer", year).astype(np.float64)
    results = {
        "foyer_fiscal_id": simulation.foyer_fiscal.ids,
        "menage_id": [tax_households[identifier] for identifier in simulation.foyer_fiscal.ids],
        "impot_net_eur": tax,
        "impose": tax > 0,
        "imposition_commune": simulation.calculate("maries_ou_pacses", year),
    }
    if include_rfr:
        def declared_income(*variables):
            return sum(simulation.foyer_fiscal.sum(simulation.calculate_add(name, year)) for name in variables)

        results["salaires_declares_eur"] = declared_income("salaire_imposable", "chomage_imposable")
        results["pensions_declarees_eur"] = declared_income("retraite_imposable")
        # OpenFisca comptabilise 2CK dans acomptes_ir, à part de credits_impot.
        results["rici_hors_pfu_eur"] = simulation.calculate("reductions", year) + simulation.calculate("credits_impot", year)
        results["rfr_eur"] = simulation.calculate("rfr", year).astype(np.float64)
        results["parts_fiscales"] = simulation.calculate("nbptr", year).astype(np.float64)
        results["tmi"] = simulation.calculate("ir_taux_marginal", year)
        results["statut_marital"] = [
            payload["individus"][payload["foyers_fiscaux"][identifier]["declarants"][0]]
            .get("statut_marital", {}).get(year, "celibataire")
            for identifier in simulation.foyer_fiscal.ids
        ]
    return pl.DataFrame(results), unallocated_income


def audit_macro(population: Path = OUTPUT, raw_dir: Path = RAW_DIR, year: int | None = None) -> dict:
    census = read_census(raw_dir)
    with duckdb.connect() as connection:
        sample_size, households, people = connection.execute(
            "select count(*), sum(poids), sum(poids * (adultes + enfants)) from read_parquet(?)",
            [str(population)],
        ).fetchone()
    records = pl.read_parquet(population)
    source_year = int(records["annee_calage"][0]) if "annee_calage" in records.columns else int(AUDIT_YEAR)
    if year is not None and year != source_year:
        raise ValueError(f"Population calée sur {source_year}. La régénérer pour auditer {year}.")
    ircom = read_ircom(raw_dir, source_year)
    tax, unallocated_income = calculate_tax(records, get_tax_benefit_system(), str(source_year))
    weighted = tax.join(records.select("menage_id", "poids"), on="menage_id", validate="m:1")
    aggregations = [
        pl.col("poids").sum().alias("foyers_fiscaux"),
        (pl.col("poids") * pl.col("impose")).sum().alias("foyers_imposes"),
        (pl.col("poids") * pl.col("impot_net_eur")).sum().alias("impot_net_eur"),
        (pl.col("poids") * pl.col("rfr_eur")).sum().alias("rfr_eur"),
        (pl.col("poids") * pl.col("salaires_declares_eur")).sum().alias("salaires_declares_eur"),
        (pl.col("poids") * pl.col("pensions_declarees_eur")).sum().alias("pensions_declarees_eur"),
    ]
    totals = weighted.select(aggregations).row(0, named=True)
    bands = read_ircom_bands(raw_dir, source_year)
    cutpoints = bands["rfr_max"].drop_nulls().to_list()
    band_indices = np.searchsorted(cutpoints, weighted["rfr_eur"].to_numpy(), side="left")
    simulated_bands = (
        weighted.with_columns(
            pl.Series("tranche", np.asarray(bands["tranche"].to_list())[band_indices])
        )
        .group_by("tranche")
        .agg(
            *aggregations,
            (pl.col("poids") * pl.col("parts_fiscales")).sum().truediv(pl.col("poids").sum()).alias("parts_fiscales_moyennes"),
            (pl.col("poids") * pl.col("imposition_commune")).sum().truediv(pl.col("poids").sum()).alias("part_imposition_commune"),
        )
    )
    totals["proportion_imposes"] = totals["foyers_imposes"] / totals["foyers_fiscaux"]
    simulated = {"menages": households, "population_des_menages": people, **totals}
    reference = {"menages": census["menages"], "population_des_menages": census["population_des_menages"], **ircom}
    comparison = {
        key: {"modele": value, "reference": reference[key], "ecart_relatif": value / reference[key] - 1}
        for key, value in simulated.items()
    }
    marital_counts = (
        weighted.group_by("statut_marital").agg(pl.col("poids").sum().alias("foyers"))
        .sort("statut_marital").to_dicts()
    )
    case_totals = {}
    if "cases_fiscales" in records.columns:
        cases = records.select("poids", "cases_fiscales").explode("cases_fiscales").unnest("cases_fiscales")
        case_totals = cases.select(
            (pl.exclude("poids") * pl.col("poids")).sum()
        ).row(0, named=True)
    before = {}
    if "poids_avant_calage_resultats" in records.columns:
        prior = tax.join(records.select("menage_id", pl.col("poids_avant_calage_resultats").alias("poids")), on="menage_id", validate="m:1")
        before = prior.select(aggregations).row(0, named=True)
    split_tail = read_ircom_tail(raw_dir, source_year)
    rank = np.searchsorted(split_tail["rfr_max"].drop_nulls(), weighted["rfr_eur"].to_numpy(), side="left")
    tail_summary = []
    for index, band in enumerate(split_tail.iter_rows(named=True)):
        observed = weighted.filter((pl.col("rfr_eur") > cutpoints[-1]) & pl.Series(rank == index)).select(aggregations).row(0, named=True)
        tail_summary.append({"rfr_max": band["rfr_max"], "modele_metropole": observed, "reference_nationale": band})
    deciles = []
    if source_year == 2024:
        per_part = (weighted["rfr_eur"] / weighted["parts_fiscales"]).to_numpy()
        weights = weighted["poids"].to_numpy()
        values = np.column_stack((per_part, weighted["impot_net_eur"], weighted["rici_hors_pfu_eur"]))
        names = [*(f"D{i}" for i in range(1, 11)), "1%", "0,1%"]
        for name, (membership, _), means in zip(names, rank_groups(per_part, weights), RFR_PER_PART_MEANS_2024):
            averages = (weights * membership) @ values / (weights @ membership)
            deciles.append({"groupe": name, "modele_metropole": averages.tolist(), "reference_nationale": means})
    effective_sample = float(records["poids"].sum() ** 2 / (records["poids"] ** 2).sum())
    return {
        "annee_revenus": str(source_year),
        "calc_certainty": "yellow",
        "taille_echantillon": sample_size,
        "population_municipale_hors_comparaison_directe": census["population_municipale"],
        "revenu_declare_sans_categorie_fiscale_eur": unallocated_income,
        "tranches_rfr": bands.join(simulated_bands, on="tranche", how="left", suffix="_modele")
        .with_columns(pl.selectors.ends_with("_modele").fill_null(0)).to_dicts(),  # Les moyennes d'une tranche vide restent indéfinies.
        "comparaison": comparison,
        "foyers_par_statut": marital_counts,
        "totaux_cases_2042_imputees": case_totals,
        "avant_calage_sur_rfr_ir_et_foyers_imposes": before,
        "queue_rfr": tail_summary,
        "deciles_rfr_par_part_2024": deciles,
        "effectif_echantillon_effectif": effective_sample,
        "ratio_poids_max_min": records["poids"].max() / records["poids"].min(),
        "profils_support_pareto": records["support_pareto"].sum() if "support_pareto" in records.columns else 0,
        "cibles_cloture_phase_2": {
            "kish_au_moins_3500": effective_sample >= 3500,
            "foyers_a_un_pour_cent": abs(comparison["foyers_fiscaux"]["ecart_relatif"]) <= 0.01,
            "ir_net_a_moins_de_quatre_pour_cent": abs(comparison["impot_net_eur"]["ecart_relatif"]) < 0.04,
        },
        "cibles_phase_2c": {
            # Seuils de validation demandés pour la phase 2C.
            "foyers_a_un_pour_cent": abs(comparison["foyers_fiscaux"]["ecart_relatif"]) <= 0.01,
            "foyers_imposes_a_trois_pour_cent": abs(comparison["foyers_imposes"]["ecart_relatif"]) <= 0.03,
            "rfr_a_trois_pour_cent": abs(comparison["rfr_eur"]["ecart_relatif"]) <= 0.03,
            "ir_net_a_moins_de_cinq_pour_cent": abs(comparison["impot_net_eur"]["ecart_relatif"]) < 0.05,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--population", type=Path, default=OUTPUT)
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--income-year", type=int, choices=(2023, 2024))
    parser.add_argument("--output", type=Path, help="Écrit aussi le rapport JSON dans ce fichier.")
    args = parser.parse_args()
    report = json.dumps(audit_macro(args.population, args.raw_dir, args.income_year), ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report + "\n", encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
