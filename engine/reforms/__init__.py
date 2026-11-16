"""Helpers et réformes déterministes OpenFisca-France."""

from __future__ import annotations

import os
import sys
from functools import lru_cache

import openfisca_france


def _apply_windows_long_path_fix() -> None:
    """Préfixe COUNTRY_DIR avec \\\\?\\ sous Windows pour contourner MAX_PATH (260 car.).

    Certains fichiers YAML de paramètres d'openfisca-france (notamment aides_logement)
    dépassent 260 caractères dans le cache uv ou un .venv Windows, ce qui les rend
    invisibles à os.walk() sans le préfixe étendu \\\\?\\.
    """
    if os.name != "nt":
        return
    mod = sys.modules.get(openfisca_france.CountryTaxBenefitSystem.__module__)
    if mod is not None and hasattr(mod, "COUNTRY_DIR"):
        country_dir = mod.COUNTRY_DIR
        if not country_dir.startswith("\\\\?\\"):
            mod.COUNTRY_DIR = "\\\\?\\" + os.path.abspath(country_dir)


@lru_cache(maxsize=1)
def get_tax_benefit_system() -> openfisca_france.CountryTaxBenefitSystem:
    """Retourne l'instance de référence CountryTaxBenefitSystem prête sous Windows ARM64."""
    _apply_windows_long_path_fix()
    return openfisca_france.CountryTaxBenefitSystem()
