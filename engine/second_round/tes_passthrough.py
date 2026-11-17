"""Modèle de prix entrées-sorties à coefficients fixes, hors boucles macroéconomiques."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import numpy as np
import openpyxl

from engine.synthetic.fetch_official_data import RAW_DIR


# SOURCE: INSEE, comptes nationaux, TES symétrique A38, tableau 9.400, 2022,
# https://www.insee.fr/fr/statistiques/8068640?sommaire=8068749
TES_SOURCE = "https://www.insee.fr/fr/statistiques/8068640?sommaire=8068749"


@dataclass(frozen=True)
class InputOutput:
    branches: tuple[str, ...]
    domestic_coefficients: np.ndarray


@dataclass(frozen=True)
class PriceShock:
    """Variations en fraction de prix ou de coût initial, par branche et poste."""

    kind: str
    cost_by_branch: Mapping[str, float]
    direct_by_coicop: Mapping[str, float]
    transmission_low: float
    transmission_high: float
    source_ref: str

    def __post_init__(self) -> None:
        if self.kind not in {"tva", "energie", "cotisations"}:
            raise ValueError(f"Type de choc non pris en charge : {self.kind}")
        if not 0 <= self.transmission_low <= self.transmission_high:
            raise ValueError("Les bornes de transmission doivent être ordonnées et positives")
        if not np.isfinite(self.transmission_high) or not self.source_ref.strip():
            raise ValueError("Les bornes doivent être finies et rattachées à une source")
        if not all(np.isfinite(value) for value in (*self.cost_by_branch.values(), *self.direct_by_coicop.values())):
            raise ValueError("Les chocs doivent être finis")


def read_input_output(path: Path = RAW_DIR / "tes_symetrique_a38_2022.xlsx") -> InputOutput:
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        rows = list(workbook["TES de production domestique"].values)
    finally:
        workbook.close()

    header = rows[8]
    resources, intermediate = [i for i, value in enumerate(header) if value == "BRANCHES"]
    branches = tuple(value for value in header[resources + 1 : intermediate] if value is not None)
    assets = rows[10 : 10 + len(branches)]
    if tuple(header[intermediate + 1 : intermediate + 1 + len(branches)]) != branches:
        raise ValueError("L'ordre des branches du TES a changé")
    if any(tuple(row[start] for row in assets) != branches for start in (resources, intermediate)):
        raise ValueError("L'ordre des produits du TES a changé")

    def block(start: int) -> np.ndarray:
        return np.asarray([row[start + 1 : start + 1 + len(branches)] for row in assets], dtype=float)

    output = block(resources).sum(axis=0)
    transactions = block(intermediate)
    if not np.isfinite(output).all() or (output <= 0).any() or not np.isfinite(transactions).all():
        raise ValueError("Les productions et emplois intermédiaires doivent être renseignés")
    return InputOutput(branches, transactions / output)


def estimate_consumption_cost(
    model: InputOutput,
    expenditures: Mapping[str, float],
    branch_mix_by_coicop: Mapping[str, Mapping[str, float]],
    shocks: list[PriceShock],
) -> dict:
    """Donne la fourchette en euros annuels, à quantités et prix d'importation constants."""
    indices = {code: i for i, code in enumerate(model.branches)}
    low_total = high_total = 0.0
    for shock in shocks:
        impact = np.zeros(len(model.branches))
        for branch, value in shock.cost_by_branch.items():
            impact[indices[branch]] = value
        cost = np.linalg.solve(np.eye(len(indices)) - model.domestic_coefficients.T, impact)
        cost_ttc_full = 0.0
        for coicop, expenditure in expenditures.items():
            if not np.isfinite(expenditure) or expenditure < 0:
                raise ValueError(f"Dépense invalide pour {coicop}")
            mix = branch_mix_by_coicop.get(coicop, {})
            if shock.cost_by_branch and not mix:
                raise ValueError(f"Correspondance TES manquante pour {coicop}")
            if any(not np.isfinite(weight) or weight < 0 for weight in mix.values()) or sum(mix.values()) > 1 + 1e-10:
                raise ValueError(f"Parts de production domestique invalides pour {coicop}")
            indirect = sum(cost[indices[branch]] * weight for branch, weight in mix.items())
            direct = shock.direct_by_coicop.get(coicop, 0.0)
            cost_ttc_full += expenditure * (indirect + direct)
        endpoints = (cost_ttc_full * shock.transmission_low, cost_ttc_full * shock.transmission_high)
        low_total += min(endpoints)
        high_total += max(endpoints)
    return {
        "cout_annuel_bas_eur": low_total,
        "cout_annuel_haut_eur": high_total,
        "calc_certainty": "yellow",
        "source_ref": [TES_SOURCE, *dict.fromkeys(shock.source_ref for shock in shocks)],
    }
