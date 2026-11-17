"""Compare le gel 2025 et les mesures IR des articles 2 et 3 du PLF déposé."""

from __future__ import annotations

import argparse
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path

import polars as pl
from openfisca_core.taxbenefitsystems import TaxBenefitSystem

from engine.reforms import get_tax_benefit_system
from engine.reforms.demo_plf2027_retraites import LoiEnVigueurBaseline, PlafonnementAbattementRetraites3000
from engine.synthetic.audit_macro import calculate_tax
from engine.synthetic.build_synthetic_france import HOUSEHOLDS, OUTPUT


PLF_SOURCE = "https://www.assemblee-nationale.fr/dyn/docs/PRJLANR5L17B3210.raw"
# SOURCE: Assemblée nationale, PLF 2027 déposé, art. 2, exposé des motifs, https://www.assemblee-nationale.fr/dyn/docs/PRJLANR5L17B3210.raw
INCOME_YEAR = "2026"
# SOURCE: Loi de finances 2026, art. 4 II-A, https://www.legifrance.gouv.fr/jorf/id/JORFTEXT000053508155
FROZEN_YEAR = "2025"
# SOURCE: Assemblée nationale, PLF 2027 déposé, art. 2 I-H 1°, https://www.assemblee-nationale.fr/dyn/docs/PRJLANR5L17B3210.raw
THRESHOLDS = (11_844, 30_200, 86_353, 185_737)
# SOURCE: Assemblée nationale, PLF 2027 déposé, art. 2 I-H 2°, https://www.assemblee-nationale.fr/dyn/docs/PRJLANR5L17B3210.raw
QUOTIENT_VALUES = {
    "general": 1845,
    "celib_enf": 4352,
    "celib": 1102,
    "reduc_postplafond": 1839,
    "reduc_postplafond_veuf": 2053,
}
# SOURCE: Assemblée nationale, PLF 2027 déposé, art. 2 I-H 3°, https://www.assemblee-nationale.fr/dyn/docs/PRJLANR5L17B3210.raw
DECOTE_VALUES = {"seuil_celib": 915, "seuil_couple": 1513}
# SOURCE: Assemblée nationale, PLF 2027 déposé, art. 2 I-G, https://www.assemblee-nationale.fr/dyn/docs/PRJLANR5L17B3210.raw
CHILD_DEDUCTION_LIMIT = 6999

REFORM_ID = "plf2027-bareme-retraites"
SCOPE = "Volet barème, décote et quotient de l’article 2 et sous-plafond retraites de l’article 3."
DETAIL_NAME = "sim_plf2027_10k.parquet"
SUMMARY_NAME = "sim_plf2027_summary.json"


def _update_params(parameters, reference, *, index: bool):
    ir = parameters.impot_revenu
    start = f"{INCOME_YEAR}-01-01"
    ref = reference.impot_revenu
    ref_scale = ref.bareme_ir_depuis_1945.bareme
    for i, (threshold, rate) in enumerate(zip(ref_scale.thresholds, ref_scale.rates, strict=True)):
        bracket = ir.bareme_ir_depuis_1945.bareme.brackets[i]
        if index and i:
            threshold = THRESHOLDS[i - 1]
        bracket.threshold.update(start=start, value=threshold)
        bracket.rate.update(start=start, value=rate)

    quotient = ir.calcul_impot_revenu.plaf_qf
    ref_quotient = ref.calcul_impot_revenu.plaf_qf
    for key, value in QUOTIENT_VALUES.items():
        quotient.plafond_avantages_procures_par_demi_part.children[key].update(
            start=start, value=value if index else ref_quotient.plafond_avantages_procures_par_demi_part[key],
        )
    for key, value in DECOTE_VALUES.items():
        quotient.decote.children[key].update(start=start, value=value if index else ref_quotient.decote[key])

    def linked(value):
        # SOURCE: CGI art. 158, 5-a et PLF 2027 art. 2 I-F, même proportion que la première tranche.
        ratio = Decimal(THRESHOLDS[0]) / Decimal(ref_scale.thresholds[1])
        return int((Decimal(value) * ratio).quantize(Decimal(1), rounding=ROUND_HALF_UP)) if index else value

    income = ir.calcul_revenus_imposables
    ref_income = ref.calcul_revenus_imposables
    income.abat_rni.enfant_marie.update(
        start=start, value=CHILD_DEDUCTION_LIMIT if index else ref_income.abat_rni.enfant_marie,
    )
    income.charges_deductibles.pensions_alimentaires.plafond.update(
        start=start, value=linked(ref_income.charges_deductibles.pensions_alimentaires.plafond),
    )
    for item in ("min", "max"):
        income.deductions.abatpen.children[item].update(start=start, value=linked(ref_income.deductions.abatpen[item]))
    return parameters


class GelBaremeRevenus2026(LoiEnVigueurBaseline):
    name = "Contrefactuel de gel des paramètres IR 2025"
    legal_status = "proposition_programme"
    source_ref = PLF_SOURCE

    def apply(self) -> None:
        reference = self.baseline.parameters(FROZEN_YEAR)
        super().apply()
        self.modify_parameters(modifier_function=lambda parameters: _update_params(parameters, reference, index=False))


class PLF2027BaremeEtRetraites(PlafonnementAbattementRetraites3000):
    """Volets barème IR, décote, quotient et pensions du projet initial."""

    name = "PLF 2027 déposé — barème IR et abattement retraites"
    source_ref = PLF_SOURCE

    def __init__(self, baseline: TaxBenefitSystem) -> None:
        super().__init__(baseline, first_year=int(INCOME_YEAR))

    def apply(self) -> None:
        reference = self.baseline.parameters(FROZEN_YEAR)
        super().apply()
        self.modify_parameters(modifier_function=lambda parameters: _update_params(parameters, reference, index=True))


def run_distribution(population: Path, output_dir: Path) -> dict:
    records = pl.read_parquet(population)
    if records.height != HOUSEHOLDS or records["menage_id"].n_unique() != HOUSEHOLDS:
        raise ValueError(f"L’export exige {HOUSEHOLDS} ménages distincts")
    tbs = get_tax_benefit_system()
    baseline = GelBaremeRevenus2026(tbs, "annee_1")
    reform = PLF2027BaremeEtRetraites(tbs)
    before, unallocated = calculate_tax(records, baseline, INCOME_YEAR)
    after, _ = calculate_tax(records, reform, INCOME_YEAR)
    identifiers = ["foyer_fiscal_id", "menage_id"]
    if not before.select(identifiers).sort(identifiers).equals(after.select(identifiers).sort(identifiers)):
        raise ValueError("Les foyers fiscaux diffèrent entre les deux scénarios")
    details = (
        before.select("foyer_fiscal_id", "menage_id", pl.col("impot_net_eur").alias("ir_gel_eur"))
        .join(
            after.select("foyer_fiscal_id", pl.col("impot_net_eur").alias("ir_plf_eur")),
            on="foyer_fiscal_id", validate="1:1",
        )
        .group_by("menage_id").agg(pl.col("ir_gel_eur", "ir_plf_eur").sum())
        .join(
            records.select("menage_id", "poids", "decile", "structure", "activite", "revenu_declare_moyen"),
            on="menage_id", validate="1:1",
        )
        .with_columns((pl.col("ir_gel_eur") - pl.col("ir_plf_eur")).alias("gain_ir_eur"))
        .sort("menage_id")
    )
    if details.height != records.height:
        raise ValueError("Des ménages sont absents de la comparaison")
    bands = details.group_by("decile").agg(
        pl.len().alias("effectif_echantillon"),
        pl.col("poids").sum().alias("poids_menages"),
        ((pl.col("gain_ir_eur") * pl.col("poids")).sum() / pl.col("poids").sum()).alias("gain_ir_moyen_eur"),
    ).sort("decile")
    summary = {
        "reform_id": REFORM_ID,
        "calc_certainty": "yellow",
        "legal_status": reform.legal_status,
        "horizon": reform.horizon,
        "source_ref": PLF_SOURCE,
        "perimetre": SCOPE,
        "annee_revenus_simulee": INCOME_YEAR,
        "annee_donnees_revenus": "2023",  # SOURCE: ERFS 2023, https://www.insee.fr/fr/statistiques/8731692
        "annee_calage_fiscal": int(records["annee_calage"][0]) if "annee_calage" in records.columns else None,
        "statut_calage": "experimental",
        "definition_deciles": "Rangs de niveau de vie au sein de chaque type de ménage ERFS 2023.",
        "taille_echantillon": details.height,
        "gain_ir_max_eur": max(0.0, details["gain_ir_eur"].max()),
        "gain_ir_min_eur": min(0.0, details["gain_ir_eur"].min()),
        "revenu_declare_sans_categorie_fiscale_eur": unallocated,
        "deciles": bands.to_dicts(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    details.write_parquet(output_dir / DETAIL_NAME)
    (output_dir / SUMMARY_NAME).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--population", type=Path, default=OUTPUT)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT.parent)
    args = parser.parse_args()
    summary = run_distribution(args.population, args.output_dir)
    print(f"{summary['taille_echantillon']} ménages simulés. Calage expérimental.")


if __name__ == "__main__":
    main()
