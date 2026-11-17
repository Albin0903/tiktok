"""Lit les marges et références d'audit des fichiers sources mis en cache."""

from __future__ import annotations

from html import unescape
from io import BytesIO
from pathlib import Path
import re
from zipfile import ZipFile

import numpy as np
import openpyxl
import polars as pl
import xlrd


# SOURCE: DGFiP Statistiques n° 41, tableaux 2 et 4, p. 4 et 7.
# https://www.impots.gouv.fr/sites/default/files/media/9_statistiques/0_etudes_et_stats/0_publications/dgfip_statistiques/2025/num41_11/dgfip_stat_41.pdf
# Les colonnes sont la moyenne du RFR/part, de l'IR net et des RICI hors PFU.
RFR_PER_PART_MEANS_2024 = (
    (None, -31, 49), (5093, -73, 93), (9548, -112, 126), (12705, -139, 155),
    (15523, -73, 182), (18224, 280, 223), (21128, 843, 286), (24862, 1650, 397),
    (31043, 3320, 647), (65532, 16395, 2538), (213672, 73078, 8999), (916590, 312098, 33214),
)


def rank_groups(values: np.ndarray, weights: np.ndarray):
    """Fraction du poids de chaque foyer dans chaque dixième et sous-groupe supérieur."""
    order = np.argsort(values, kind="stable")
    tie_starts = np.r_[0, np.flatnonzero(np.diff(values[order]) != 0) + 1]
    tie_sizes = np.diff(np.r_[tie_starts, len(values)])
    tie_weights = np.add.reduceat(weights[order], tie_starts)
    total = weights.sum()
    end = tie_weights.cumsum() / total
    start = end - tie_weights / total
    ranges = [(i / 10, (i + 1) / 10) for i in range(10)] + [(0.99, 1.0), (0.999, 1.0)]
    for low, high in ranges:
        fraction = np.empty(len(weights))
        tie_fraction = (np.minimum(end, high) - np.maximum(start, low)) * total / tie_weights
        fraction[order] = np.repeat(np.clip(tie_fraction, 0, 1), tie_sizes)
        yield fraction, high - low


def _table(document: str, name: str) -> dict[str, list[str]]:
    table = re.search(rf'<table id="produit-tableau-{name}"[^>]*>(.*?)</table>', document, re.S)
    if table is None:
        raise ValueError(f"Tableau INSEE absent : {name}")
    rows = {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", table[1], re.S):
        cells = re.findall(r"<t[dh](?:\s[^>]*)?>(.*?)</t[dh]>", row, re.S)
        clean = [" ".join(unescape(re.sub(r"<[^>]+>", " ", cell)).split()) for cell in cells]
        if clean:
            rows[clean[0]] = clean[1:]
    return rows


def _number(value: str) -> float:
    return float(value.replace(" ", "").replace(",", "."))


def read_census(raw_dir: Path) -> dict:
    # SOURCE: INSEE RP 2023, France métropolitaine, tableaux POP T1, FAM T1/T5,
    # LOG T10, EMP T3/T4/T6 et POP T8, https://www.insee.fr/fr/statistiques/2011101?geo=METRO-1
    document = (raw_dir / "rp2023_metropole.html").read_text(encoding="utf-8")
    population = _table(document, "POP_T1")
    households = _table(document, "FAM_T1")
    children = _table(document, "FAM_T5")
    housing = _table(document, "LOG_T10")
    civil_status = _table(document, "FAM_G4")
    social = _table(document, "POP_T8")
    employment = _table(document, "EMP_T6")
    salaried = _number(employment["Salariés"][-2])
    independent = _number(employment["Non-salariés"][-2])
    cadres_pcs = _number(_table(document, "EMP_T3")["Cadres et professions intellectuelles supérieures"][-1])
    retired = sum(_number(social["Retraités"][col]) for col in (0, 2))
    unemployed = _number(_table(document, "EMP_T4")["Nombre de chômeurs"][-1])
    others = sum(_number(social["Autres personnes sans activité professionnelle"][col]) for col in (0, 2))
    # Les PCS cadres ne sont pas croisées avec le statut salarié dans ce tableau.
    # La part salariée de l'emploi sert d'approximation déclarée.
    cadres = cadres_pcs * salaried / (salaried + independent)
    return {
        "population_municipale": _number(population["Ensemble"][-2]),
        "population_des_menages": _number(households["Ensemble"][-1]),
        "menages": _number(households["Ensemble"][4]),
        "part_union_libre_parmi_couples": (
            _number(civil_status["En concubinage ou union libre"][0])
            / sum(_number(civil_status[label][0]) for label in ("Marié(e)", "Pacsé(e)", "En concubinage ou union libre"))
        ),
        "age": {
            label: _number(values[-2])
            for label, values in population.items()
            if label not in {"Âge", "Ensemble"}
        },
        "structure": {
            "seul": _number(households["Ménages d'une personne"][4]),
            "colocation": _number(households["Autres ménages sans famille"][4]),
            "couple": _number(households["Un couple sans enfant"][4]),
            "couple_enfants": _number(households["Un couple avec enfant(s)"][4]),
            "monoparental": _number(households["Une famille monoparentale"][4]),
        },
        "enfants": {
            count: _number(children[label][-2])
            for count, label in enumerate(("Aucun enfant", "1 enfant", "2 enfants", "3 enfants", "4 enfants ou plus"))
        },
        "logement": {
            key: _number(housing[label][4])
            for key, label in (("proprietaire", "Propriétaire"), ("locataire", "Locataire"), ("loge_gratuitement", "Logé gratuitement"))
        },
        "activite": {
            "salarie_non_cadre": salaried - cadres,
            "salarie_cadre": cadres,
            "independant": independent,
            "retraite": retired,
            "chomeur": unemployed,
            "inactif": others - unemployed,
        },
    }


def _read_erfs_table(raw_dir: Path, table: str) -> list[tuple]:
    with ZipFile(raw_dir / "erfs2023_deciles.zip") as archive:
        workbook_data = archive.read(f"irsocerfs2023_{table.lower()}.xlsx")
    with BytesIO(workbook_data) as data:
        workbook = openpyxl.load_workbook(data, read_only=True, data_only=True)
        try:
            return list(workbook[f"ERFS_{table}MO"].values)
        finally:
            workbook.close()


def _erfs_bands(rows: list[tuple], label: str) -> pl.DataFrame:
    start = next(i for i, row in enumerate(rows) if row[0] == label and row[1] == "p10")
    bands = rows[start : start + 11]
    if [row[1] for row in bands] != [f"p{rank}" for rank in range(10, 100, 10)] + ["p95", ">p95"]:
        raise ValueError("Tranches ERFS 2023 inattendues")
    return pl.DataFrame([
        {
            "tranche_erfs": row[1],
            "decile": min(i, 10),
            "part_menages_pct": row[4],
            "revenu_declare_moyen": row[5],
            "revenu_disponible_moyen": row[8],
        }
        for i, row in enumerate(bands, start=1)
    ])


def read_erfs(raw_dir: Path) -> pl.DataFrame:
    # SOURCE: INSEE / DGFiP, ERFS 2023, tableau DIS03MO, https://www.insee.fr/fr/statistiques/8731692
    return _erfs_bands(_read_erfs_table(raw_dir, "DIS03"), "Ensemble")


def read_erfs_by_household(raw_dir: Path) -> pl.DataFrame:
    # SOURCE: INSEE / DGFiP, ERFS 2023, tableau DIS01MO, https://www.insee.fr/fr/statistiques/8731692
    rows = _read_erfs_table(raw_dir, "DIS01")
    labels = {
        "seul": "Ménages d'une seule personne",
        "colocation": "Ménages complexes (1)",
        "couple": "Couples sans enfant",
        "couple_enfants": "Couples avec enfant(s)",
        "monoparental": "Familles monoparentales",
    }
    return pl.concat([
        _erfs_bands(rows, label).with_columns(pl.lit(structure).alias("structure"))
        for structure, label in labels.items()
    ])


def _ircom_regions(raw_dir: Path, year: int) -> list[list[list]]:
    with ZipFile(raw_dir / f"ircom{year + 1}_revenus{year}.zip") as archive:
        regions = []
        for name in archive.namelist():
            region = Path(name).name
            if "/regional/" not in name or not region.endswith(".xls") or region in {"dom.xls", "b31.xls"}:
                continue
            sheet = xlrd.open_workbook(file_contents=archive.read(name)).sheet_by_index(0)
            regions.append([sheet.row_values(i) for i in range(sheet.nrows)])
    if len(regions) != 13:
        raise ValueError(f"IRCOM : 13 régions métropolitaines attendues, {len(regions)} trouvées")
    return regions


def read_ircom(raw_dir: Path, year: int = 2023) -> dict[str, float]:
    # SOURCE: DGFiP, IRCOM 2024, revenus 2023, totaux des 13 régions métropolitaines.
    # https://www.data.gouv.fr/datasets/limpot-sur-le-revenu-par-collectivite-territoriale-ircom
    totals = [next(row for row in region if row[1] == "Total") for region in _ircom_regions(raw_dir, year)]
    foyers = sum(row[2] for row in totals)
    imposes = sum(row[5] for row in totals)
    return {
        "foyers_fiscaux": foyers,
        "foyers_imposes": imposes,
        "proportion_imposes": imposes / foyers,
        "impot_net_eur": sum(row[4] for row in totals) * 1000,
        "rfr_eur": sum(row[3] for row in totals) * 1000,
        "salaires_declares_eur": sum(row[8] for row in totals) * 1000,
        "pensions_declarees_eur": sum(row[10] for row in totals) * 1000,
    }


def read_ircom_bands(raw_dir: Path, year: int = 2023) -> pl.DataFrame:
    # SOURCE: DGFiP, IRCOM 2024, revenus 2023, huit tranches régionales de RFR.
    # https://www.data.gouv.fr/datasets/limpot-sur-le-revenu-par-collectivite-territoriale-ircom
    bands = {
        "0 à 10 000": 10_000,
        "10 001 à 12 000": 12_000,
        "12 001 à 15 000": 15_000,
        "15 001 à 20 000": 20_000,
        "20 001 à 30 000": 30_000,
        "30 001 à 50 000": 50_000,
        "50 001 à 100 000": 100_000,
        "+ de 100 000": None,
    }
    regions = [
        {row[1]: row for row in region if row[1] in bands}
        for region in _ircom_regions(raw_dir, year)
    ]
    if any(set(region) != bands.keys() for region in regions):
        raise ValueError("Découpage régional des tranches IRCOM inattendu")
    return pl.DataFrame([
        {
            "tranche": label,
            "rfr_max": high,
            "foyers_fiscaux": sum(region[label][2] for region in regions),
            "rfr_eur": sum(region[label][3] for region in regions) * 1000,
            "impot_net_eur": sum(region[label][4] for region in regions) * 1000,
            "foyers_imposes": sum(region[label][5] for region in regions),
            "salaires_declares_eur": sum(region[label][8] for region in regions) * 1000,
            "pensions_declarees_eur": sum(region[label][10] for region in regions) * 1000,
        }
        for label, high in bands.items()
    ])


def read_ircom_tail(raw_dir: Path, year: int) -> pl.DataFrame:
    # SOURCE: DGFiP, IRCOM 2024–2025, onglet nat, sous-tranches de RFR supérieures à 100 000 €.
    # https://www.data.gouv.fr/datasets/limpot-sur-le-revenu-par-collectivite-territoriale-ircom
    with ZipFile(raw_dir / f"ircom{year + 1}_revenus{year}.zip") as archive:
        name = next(name for name in archive.namelist() if name.endswith("/national/national.xls"))
        sheet = xlrd.open_workbook(file_contents=archive.read(name)).sheet_by_name("nat")
    groups = [([], 200_000), ([], 300_000), ([], 500_000), ([], None)]
    found = False
    for i in range(sheet.nrows):
        row = sheet.row_values(i)
        if str(row[1]).startswith("Plus de 100 000 dont"):
            found = True
            continue
        if found and row[1] == "Total":
            break
        if not found:
            continue
        upper = int(row[1].rsplit(" à ", 1)[1].replace(" ", "")) if " à " in row[1] else float("inf")
        group = next(entries for entries, limit in groups if limit is None or upper <= limit)
        group.append(row)
    if not all(entries for entries, _ in groups):
        raise ValueError("Sous-tranches nationales de RFR IRCOM manquantes")
    return pl.DataFrame([
        {"rfr_max": limit, "foyers_fiscaux": sum(row[2] for row in entries),
         "rfr_eur": sum(row[3] for row in entries) * 1000}
        for entries, limit in groups
    ])


def read_2042(raw_dir: Path, year: int) -> dict[str, dict]:
    # SOURCE: DGFiP, déclarations nationales, https://data.economie.gouv.fr/explore/dataset/ir-declarations-2042-nat/
    data = pl.read_csv(raw_dir / "2042_nat_2023_2024.csv", separator=";", schema_overrides={"nom": pl.String})
    rows = list(data.filter(pl.col("annee") == year).iter_rows(named=True))
    result = {row["nom"]: row for row in rows}
    if len(result) != len(rows) or not result:
        raise ValueError(f"2042 national : aucune donnée ou cases dupliquées pour {year}")
    return result


def read_consumption(raw_dir: Path) -> pl.DataFrame:
    # SOURCE: INSEE, Budget de famille 2017, TF106 (euros) et TF206 (%),
    # https://www.insee.fr/fr/statistiques/4648335
    expenditure = pl.read_csv(
        raw_dir / "bdf2017_tf106.csv", separator=";",
        schema_overrides={"NOMENCLATURE": pl.String, "DECUC": pl.String, "CONSO": pl.String},
    )
    shares = pl.read_csv(
        raw_dir / "bdf2017_tf206.csv", separator=";",
        schema_overrides={"NOMENCLATURE2": pl.String, "DECUC": pl.String, "COEFF_BUDG": pl.String},
    )
    return (
        expenditure.filter(pl.col("DECUC").cast(pl.Int64, strict=False).is_between(1, 10))
        .rename({"DECUC": "decile", "NOMENCLATURE": "coicop", "CONSO": "depense_eur"})
        .join(
            shares.rename({"DECUC": "decile", "NOMENCLATURE2": "coicop", "COEFF_BUDG": "part_pct"}),
            on=["decile", "coicop"], how="left", validate="1:1",
        )
        .with_columns(
            pl.col("decile").cast(pl.Int64),
            pl.col("depense_eur", "part_pct").cast(pl.Float64, strict=False),
        )
    )
