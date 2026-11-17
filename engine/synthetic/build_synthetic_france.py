"""Construit un échantillon de ménages par calage sur marges publiques."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Mapping

import numpy as np
import polars as pl

from engine.synthetic.fetch_official_data import RAW_DIR
from engine.synthetic.official_margins import read_census, read_consumption, read_erfs_by_household


OUTPUT = RAW_DIR.parent / "processed" / "france_synthetique.parquet"
HOUSEHOLDS = 10_000  # Taille demandée du démonstrateur.


def rake(
    records: pl.DataFrame,
    margins: Mapping[str, Mapping],
    total: float,
    *,
    tolerance: float = 1e-8,
    max_iterations: int = 250,
) -> np.ndarray:
    """Calage IPF sur des marges catégorielles de même total."""
    if not records.height or not np.isfinite(total) or total <= 0 or not margins:
        raise ValueError("Il faut des observations, des marges et un total positif")
    weights = np.full(records.height, total / records.height, dtype=float)
    groups = []
    for column, counts in margins.items():
        observed = records[column].to_numpy()
        keys = list(counts)
        if set(observed) != set(keys):
            raise ValueError(f"{column} : les modalités de la marge et de l'échantillon diffèrent")
        targets = np.asarray([counts[key] for key in keys], dtype=float)
        if not np.isfinite(targets).all() or (targets <= 0).any():
            raise ValueError(f"{column} : chaque effectif doit être positif et fini")
        targets *= total / targets.sum()
        codes = np.empty(records.height, dtype=int)
        for index, key in enumerate(keys):
            codes[observed == key] = index
        groups.append((codes, targets))

    for _ in range(max_iterations):
        for codes, targets in groups:
            weights *= (targets / np.bincount(codes, weights=weights, minlength=len(targets)))[codes]
        if all(
            np.allclose(np.bincount(codes, weights=weights, minlength=len(targets)), targets, rtol=tolerance, atol=0)
            for codes, targets in groups
        ):
            return weights
    raise ValueError("Le calage IPF n'a pas convergé")


def _draw(generator: np.random.Generator, counts: Mapping, size: int) -> np.ndarray:
    categories = list(counts)
    shares = np.array(list(counts.values()), dtype=float)
    return generator.choice(categories, size=size, p=shares / shares.sum())


def build_synthetic_france(
    raw_dir: Path = RAW_DIR,
    output: Path = OUTPUT,
    *,
    seed: int = 2027,  # Graine de reproductibilité, sans interprétation statistique.
    income_year: int = 2023,  # SOURCE: INSEE ERFS 2023, https://www.insee.fr/fr/statistiques/8731692
) -> pl.DataFrame:
    census = read_census(raw_dir)
    income = read_erfs_by_household(raw_dir)
    consumption = read_consumption(raw_dir)
    generator = np.random.default_rng(seed)

    # SOURCE: INSEE RP 2023, tableau POP T1, https://www.insee.fr/fr/statistiques/2011101?geo=METRO-1
    # La structure d'âge adulte sert d'approximation de la structure d'âge
    # des personnes de référence. La tranche 15–24 est limitée aux majeurs
    # en supposant des effectifs constants par âge à l'intérieur de la tranche.
    age_ranges = {
        "De 15 à 24 ans": (18, 24),
        "De 25 à 39 ans": (25, 39),
        "De 40 à 54 ans": (40, 54),
        "De 55 à 64 ans": (55, 64),
        "De 65 à 79 ans": (65, 79),
        "80 ans ou plus": (80, 99),
    }
    age_counts = {label: census["age"][label] for label in age_ranges}
    age_counts["De 15 à 24 ans"] *= 7 / 10
    margins = {
        "age_groupe": age_counts,
        "activite": census["activite"],
        "structure": census["structure"],
        "logement": census["logement"],
    }
    seed_data = {name: _draw(generator, targets, HOUSEHOLDS) for name, targets in margins.items()}
    # SOURCE: INSEE ERFS 2023, DIS01MO, https://www.insee.fr/fr/statistiques/8731692
    # Les tranches de niveau de vie sont propres à chaque type de ménage.
    # On conserve ces rangs relatifs et on cale leurs fréquences conditionnelles au RP.
    erfs_weights = {}
    erfs_strata = np.empty(HOUSEHOLDS, dtype=object)
    for structure, count in census["structure"].items():
        subset = income.filter(pl.col("structure") == structure)
        counts = dict(zip(subset["tranche_erfs"], subset["part_menages_pct"]))
        indices = seed_data["structure"] == structure
        selected = _draw(generator, counts, int(indices.sum()))
        erfs_strata[indices] = [f"{structure}/{band}" for band in selected]
        erfs_weights.update({f"{structure}/{band}": count * share / sum(counts.values()) for band, share in counts.items()})
    seed_data["strate_erfs"] = erfs_strata.tolist()
    margins["strate_erfs"] = erfs_weights
    # Hypothèse de génération du support. Retraites jeunes et activité après
    # 79 ans restent hors de cette première représentation des cas-types.
    ages = seed_data["age_groupe"]
    activities = seed_data["activite"]
    is_senior = np.isin(ages, ["De 65 à 79 ans", "80 ans ou plus"])
    allowed = (activities == "retraite") == is_senior
    # Une retraite dès 55 ans et des seniors actifs jusqu'à 79 ans permettent
    # de caler séparément les marges d'âge et d'activité.
    allowed |= (activities == "retraite") & (ages == "De 55 à 64 ans")
    allowed |= (activities != "retraite") & (ages == "De 65 à 79 ans")
    while not allowed.all():
        activities[~allowed] = _draw(generator, margins["activite"], int((~allowed).sum()))
        allowed = (
            ((activities == "retraite") == is_senior)
            | ((activities == "retraite") & (ages == "De 55 à 64 ans"))
            | ((activities != "retraite") & (ages == "De 65 à 79 ans"))
        )

    children = np.zeros(HOUSEHOLDS, dtype=int)
    family = np.isin(seed_data["structure"], ["couple_enfants", "monoparental"])
    children[family] = _draw(generator, {n: count for n, count in census["enfants"].items() if n}, int(family.sum()))
    second_adult = np.isin(seed_data["structure"], ["couple", "couple_enfants", "colocation"])
    couple = second_adult & (seed_data["structure"] != "colocation")
    union_libre = generator.random(HOUSEHOLDS) < census["part_union_libre_parmi_couples"]
    records = pl.DataFrame({
        **seed_data,
        "menage_id": np.arange(1, HOUSEHOLDS + 1),
        "age_reference": [generator.integers(age_ranges[label][0], age_ranges[label][1] + 1) for label in ages],
        "adultes": 1 + second_adult.astype(int),
        "enfants": children,
        "imposition_commune": couple & ~union_libre,
    })
    weights = rake(records, margins, census["menages"])
    budget = (
        consumption.filter(pl.col("coicop").is_in(["CTOTALE", "045", "0722"]))
        .pivot(on="coicop", index="decile", values="depense_eur")
        .rename({"CTOTALE": "consommation_eur_2017", "045": "energie_logement_eur_2017", "0722": "carburant_eur_2017"})
    )
    records = (
        records.with_columns(pl.Series("poids", weights))
        .join(
            income.with_columns(pl.concat_str("structure", "tranche_erfs", separator="/").alias("strate_erfs"))
            .drop("structure", "part_menages_pct"),
            on="strate_erfs", validate="m:1",
        )
        .join(budget, on="decile", validate="m:1")
        .sort("menage_id")
    )
    if records.height != HOUSEHOLDS or records.null_count().row(0) != (0,) * records.width:
        raise ValueError("L'échantillon contient des ménages ou des budgets manquants")
    from engine.synthetic.fiscal_calibration import calibrate_fiscal_population

    records = calibrate_fiscal_population(records, raw_dir, census, income_year, generator)
    output.parent.mkdir(parents=True, exist_ok=True)
    records.write_parquet(output)
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--income-year", type=int, choices=(2023, 2024), default=2023)
    args = parser.parse_args()
    records = build_synthetic_france(args.raw_dir, args.output, income_year=args.income_year)
    print(f"{records.height} ménages synthétiques écrits dans {args.output}")


if __name__ == "__main__":
    main()
