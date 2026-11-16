"""Simulation déterministe PLF 2027 : Abattement de 10 % sur les pensions de retraite.

Compare sur ``OpenFisca-France`` (année de référence 2025, ``max_spiral_loops=3``) :
  1. **PLF 2027 n° 3210, art. 3** (``PlafonnementAbattementRetraites3000``) :
     instaure un sous-plafond spécifique de **3 000 € par foyer fiscal** limité aux
     **seules pensions de retraite** ; les pensions alimentaires et d'invalidité conservent
     le plafond général de droit commun (``4 439 €`` sur revenus 2025, CGI art. 158, 5-a).
  2. **Scénario alternatif ciblé** (``SuppressionAbattementRetraites10Pct``) :
     suppression de l'abattement de 10 % à périmètre constant (**retraites seules** par
     défaut, ou global CGI art. 158, 5-a via ``scope="global_158_5_a"``).

Horizons temporels (``horizon``) :
  - ``"annee_1"`` : réforme appliquée uniquement à l'année courante 2025 (RFR N-2 de 2023
    inchangé → pas de bascule CSG immédiate).
  - ``"regime_permanent"`` : réforme appliquée sur toute la fenêtre 2021..2025 pour
    observer la boucle rétroactive ``RFR(N-2) -> taux CSG(N)``.

Règle exacte et implémentation du lissage CSG / CASA (CSS art. L. 136-8, III) :
  Conformément à l'article L. 136-8, III du Code de la sécurité sociale et à l'Instruction
  interministérielle DSS/2B/2024/184 du 04/12/2024 (Annexe 1, §2 « Mesure de lissage », p. 4-5) :
  - Le lissage sur 2 ans protège **le passage d'un taux <= 3,8 % (exonération ou taux réduit)
    vers un taux supérieur (6,6 % ou 8,3 % et CASA 0,3 %)**, ce qui exige de dépasser le
    plafond du taux réduit (``16 755 €`` pour 1 part en 2025) pendant **deux années consécutives
    (N-3 et N-2)**.
  - **Il n'y a PAS de lissage sur 2 ans entre 6,6 % et 8,3 %** : un pensionné déjà au taux
    médian (6,6 %) dont le ``RFR(N-2)`` est **>= 26 004 €** (1 part) bascule immédiatement au
    taux plein (8,3 %) dès l'année N.
  - Correctifs appliqués dans ce module sur ``csg_deductible_retraite``,
    ``csg_imposable_retraite``, ``crds_retraite`` et ``casa`` (vs ``openfisca-france 177.0.0``
    natif) :
      1. Borne exacte du taux plein : ``rfr >= seuil_rfr3`` (``26 004 €`` -> 8,3 %, au lieu de
         ``rfr > 26 004 €`` dans OpenFisca natif).
      2. Lissage ``N-3 / N-2`` (pour ``N >= 2024``) : maintien au taux réduit (3,8 %) et
         exonération de CASA lors du premier dépassement du seuil réduit si ``RFR(N-3) <= seuil_rfr2(N-1)``.

SOURCE: PLF 2027 AN n° 3210, art. 3 (déposé le 01/10/2026), https://www.assemblee-nationale.fr/dyn/docs/PRJLANR5L17B3210.raw (Article 3 modifiant CGI art. 158, 5-a ; rejeté à l'AN le 04/11/2026, examen Sénat à partir du 20/11/2026).
SOURCE: DGFiP Notice 2041-NOTFC 2026 (revenus 2025), https://www.impots.gouv.fr/sites/default/files/formulaires/2041-notfc/2026/2041-notfc_5516.pdf (Rubrique Pensions, retraites et rentes : abattement 10 %, min 454 € par pensionné, plafond 4 439 € par foyer fiscal).
SOURCE: Instruction interministérielle DSS/2B/2024/184 du 04/12/2024, https://legislation.lassuranceretraite.fr/Pdf/instruction_ministerielle_04122024.pdf (Annexe 1 §2 « Mesure de lissage » p. 4-5 & Annexe 2 « Barème 2025 métropole » p. 7 : seuils RFR 2023 pour 1 part = 12 817 € / 16 755 € / 26 004 €).
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any, Literal
import unicodedata

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from openfisca_core.model_api import ADD, MONTH, YEAR, Variable, max_, min_, not_, round_, where
from openfisca_core.reforms import Reform
from openfisca_core.simulations import SimulationBuilder
from openfisca_core.taxbenefitsystems import TaxBenefitSystem
from openfisca_france.entities import FoyerFiscal, Individu
from openfisca_france.model.prelevements_obligatoires.prelevements_sociaux.contributions_sociales.base import (
    montant_csg_crds,
)
from pydantic import BaseModel

from engine.reforms import get_tax_benefit_system

HorizonMode = Literal["annee_1", "regime_permanent"]
SuppressionScope = Literal["retraites_seules", "global_158_5_a"]
CalcCertainty = Literal["green", "yellow", "red"]
LegalStatus = Literal["en_vigueur", "projet_de_loi_en_navette", "proposition_programme"]

# SOURCE: DGFiP Notice 2041-NOTFC 2026 (revenus 2025), https://www.impots.gouv.fr/sites/default/files/formulaires/2041-notfc/2026/2041-notfc_5516.pdf (Année d'imposition de référence 2025 et fenêtre N-4..N pour RFR N-2 / N-3)
REFERENCE_YEAR = "2025"
# SOURCE: Instruction interministérielle DSS/2B/2024/184 du 04/12/2024, https://legislation.lassuranceretraite.fr/Pdf/instruction_ministerielle_04122024.pdf (Annexe 1 §2 p. 4-5 : historique N-4..N requis pour RFR N-2 et N-3)
HISTORY_YEARS = ("2021", "2022", "2023", "2024", "2025")
# SOURCE: OpenFisca-France v177.0.0 — boucle récursive csg_deductible_retraite(N) <-> rfr(N-2) <-> retraite_imposable(N-2)
DEFAULT_MAX_SPIRAL_LOOPS = 3

# SOURCE: DGFiP Notice 2041-NOTFC 2026 (revenus 2025), https://www.impots.gouv.fr/sites/default/files/formulaires/2041-notfc/2026/2041-notfc_5516.pdf (Rubrique Pensions, retraites et rentes : taux 10 %)
ABATPEN_TAUX_2025 = 0.10
# SOURCE: DGFiP Notice 2041-NOTFC 2026 (revenus 2025), https://www.impots.gouv.fr/sites/default/files/formulaires/2041-notfc/2026/2041-notfc_5516.pdf (Rubrique Pensions, retraites et rentes : minimum 454 € par pensionné)
ABATPEN_MIN_2025 = 454.0
# SOURCE: DGFiP Notice 2041-NOTFC 2026 (revenus 2025), https://www.impots.gouv.fr/sites/default/files/formulaires/2041-notfc/2026/2041-notfc_5516.pdf (Rubrique Pensions, retraites et rentes : plafond 4 439 € par foyer fiscal)
ABATPEN_MAX_2025 = 4439.0
# SOURCE: PLF 2027 AN n° 3210, art. 3 (déposé le 01/10/2026), https://www.assemblee-nationale.fr/dyn/docs/PRJLANR5L17B3210.raw (Article 3 modifiant CGI art. 158, 5-a : sous-plafond 3 000 € pensions de retraite)
PLAFOND_ABATPEN_RETRAITE_3000 = 3000.0

# SOURCE: Instruction interministérielle DSS/2B/2024/184 du 04/12/2024, https://legislation.lassuranceretraite.fr/Pdf/instruction_ministerielle_04122024.pdf (Annexe 2 « Barème 2025 métropole » p. 7 : seuil d'exonération RFR 2023 pour 1 part = 12 817 €)
CSG_SEUIL_EXO_1_PART_2025 = 12817.0
# SOURCE: Instruction interministérielle DSS/2B/2024/184 du 04/12/2024, https://legislation.lassuranceretraite.fr/Pdf/instruction_ministerielle_04122024.pdf (Annexe 2 « Barème 2025 métropole » p. 7 : seuil taux réduit 3,8 % -> médian 6,6 % RFR 2023 pour 1 part = 16 755 €)
CSG_SEUIL_MEDIAN_1_PART_2025 = 16755.0
# SOURCE: Instruction interministérielle DSS/2B/2024/184 du 04/12/2024, https://legislation.lassuranceretraite.fr/Pdf/instruction_ministerielle_04122024.pdf (Annexe 2 « Barème 2025 métropole » p. 7 : seuil taux médian 6,6 % -> plein 8,3 % RFR 2023 pour 1 part = 26 004 €)
CSG_SEUIL_PLEIN_1_PART_2025 = 26004.0

# SOURCE: Code du travail art. L3231-2 & Décret n° 2024-951 du 23/10/2024, https://www.legifrance.gouv.fr/loda/id/JORFTEXT000050385094 (SMIC mensuel brut 1 801,80 € x 12)
SMIC_ANNUEL_BRUT_2025 = 21621.60


def horizon_to_start_date(horizon: HorizonMode) -> str:
    """Convertit l'horizon analytique en date d'entrée en vigueur dans OpenFisca."""
    if horizon == "annee_1":
        return f"{REFERENCE_YEAR}-01-01"
    if horizon == "regime_permanent":
        return f"{HISTORY_YEARS[0]}-01-01"
    raise ValueError(f"Horizon inconnu : {horizon!r}")


def _compute_csg_retraite_masks(individu: Any, period: Any, parameters: Any) -> tuple[Any, Any, Any, Any]:
    """Calcule les 4 masques de taux CSG retraites conformes à CSS art. L. 136-8, III.

    Corrige deux écarts d'OpenFisca-France 177.0.0 natif :
      1. Borne exacte du taux plein : ``rfr >= seuil_rfr3`` (26 004 € pour 1 part -> 8,3 %).
      2. Lissage sur 2 ans (pour N >= 2024 où N-3 >= 2021 est renseigné) : un foyer dont
         ``RFR(N-3) <= seuil_rfr2(N-1)`` reste au taux réduit (3,8 %) et exonéré de CASA
         lors du premier dépassement de ``seuil_rfr2(N)``.
    """
    rfr_n_2 = individu.foyer_fiscal("rfr", period=period.n_2)
    nbptr_n_2 = individu.foyer_fiscal("nbptr", period=period.n_2)
    params_n = parameters(period)
    seuils = params_n.prelevements_sociaux.contributions_sociales.csg.remplacement.seuils

    seuil_exo = seuils.seuil_rfr1.seuil_rfr1 + (nbptr_n_2 - 1) * 2 * seuils.seuil_rfr1.demi_part_suppl_rfr1
    seuil_red = seuils.seuil_rfr2.seuil_rfr2 + (nbptr_n_2 - 1) * 2 * seuils.seuil_rfr2.demi_part_suppl_rfr2
    seuil_plein = seuils.seuil_rfr3.seuil_rfr3 + (nbptr_n_2 - 1) * 2 * seuils.seuil_rfr3.demi_part_suppl_rfr3

    est_exo = rfr_n_2 <= seuil_exo
    est_red = (rfr_n_2 > seuil_exo) & (rfr_n_2 <= seuil_red)
    est_med = (rfr_n_2 > seuil_red) & (rfr_n_2 < seuil_plein)
    est_plein = rfr_n_2 >= seuil_plein

    if period.start.year >= 2024:
        period_n_1 = period.offset(-1, "year")
        period_n_3 = period_n_1.n_2
        rfr_n_3 = individu.foyer_fiscal("rfr", period=period_n_3)
        nbptr_n_3 = individu.foyer_fiscal("nbptr", period=period_n_3)
        seuils_prev = parameters(period_n_1).prelevements_sociaux.contributions_sociales.csg.remplacement.seuils
        seuil_red_prev = (
            seuils_prev.seuil_rfr2.seuil_rfr2 + (nbptr_n_3 - 1) * 2 * seuils_prev.seuil_rfr2.demi_part_suppl_rfr2
        )
        # CSS art. L. 136-8, III : maintien à 3,8 % (et hors CASA) si taux <= 3,8 % en N-1
        lissage_actif = (rfr_n_3 <= seuil_red_prev) & (est_med | est_plein)
        est_red = est_red | lissage_actif
        est_med = est_med & not_(lissage_actif)
        est_plein = est_plein & not_(lissage_actif)

    return est_exo, est_red, est_med, est_plein


class _BaseRetraitesReform(Reform):
    """Socle commun appliquant le lissage CSG/CASA (N-3/N-2) et la borne exacte >= 26 004 €."""

    def apply(self) -> None:
        class csg_deductible_retraite(Variable):
            value_type = float
            entity = Individu
            label = "CSG déductible sur les pensions de retraite (lissage N-3 et borne exacte)"
            definition_period = MONTH

            def formula_2019(individu, period, parameters):
                retraite_brute = individu("retraite_brute", period)
                _, est_red, est_med, est_plein = _compute_csg_retraite_masks(individu, period, parameters)
                params_n = parameters(period)
                return montant_csg_crds(
                    base_sans_abattement=retraite_brute,
                    indicatrice_taux_plein=est_plein,
                    indicatrice_taux_reduit=est_red,
                    indicatrice_taux_intermediaire=est_med,
                    law_node=params_n.prelevements_sociaux.contributions_sociales.csg.remplacement.pensions_retraite_invalidite.deductible,
                    plafond_securite_sociale=params_n.prelevements_sociaux.pss.plafond_securite_sociale_mensuel,
                )

        class csg_imposable_retraite(Variable):
            value_type = float
            entity = Individu
            label = "CSG imposable sur les pensions de retraite (lissage N-3 et borne exacte)"
            definition_period = MONTH

            def formula_2019(individu, period, parameters):
                retraite_brute = individu("retraite_brute", period)
                _, est_red, est_med, est_plein = _compute_csg_retraite_masks(individu, period, parameters)
                params_n = parameters(period)
                return montant_csg_crds(
                    base_sans_abattement=retraite_brute,
                    indicatrice_taux_plein=est_plein,
                    indicatrice_taux_reduit=est_red,
                    indicatrice_taux_intermediaire=est_med,
                    law_node=params_n.prelevements_sociaux.contributions_sociales.csg.remplacement.pensions_retraite_invalidite.imposable,
                    plafond_securite_sociale=params_n.prelevements_sociaux.pss.plafond_securite_sociale_mensuel,
                )

        class crds_retraite(Variable):
            value_type = float
            entity = Individu
            label = "CRDS sur les pensions de retraite (borne et lissage exacts)"
            definition_period = MONTH

            def formula_2019(individu, period, parameters):
                retraite_brute = individu("retraite_brute", period)
                est_exo, _, _, _ = _compute_csg_retraite_masks(individu, period, parameters)
                params_n = parameters(period)
                return montant_csg_crds(
                    base_sans_abattement=retraite_brute,
                    law_node=params_n.prelevements_sociaux.contributions_sociales.crds,
                    plafond_securite_sociale=params_n.prelevements_sociaux.pss.plafond_securite_sociale_mensuel,
                ) * not_(est_exo)

        class casa(Variable):
            value_type = float
            entity = Individu
            label = "Contribution additionnelle de solidarité et d'autonomie (lissage N-3 et borne exacte)"
            definition_period = MONTH

            def formula_2019_01_01(individu, period, parameters):
                retraite_brute = individu("retraite_brute", period)
                _, _, est_med, est_plein = _compute_csg_retraite_masks(individu, period, parameters)
                bareme = parameters(period).prelevements_sociaux.cotisations_securite_sociale_regime_general.casa
                montant = (est_plein | est_med) * bareme.pensions_retraite_preretraite_invalidite.calc(retraite_brute)
                return -montant

        self.update_variable(csg_deductible_retraite)
        self.update_variable(csg_imposable_retraite)
        self.update_variable(crds_retraite)
        self.update_variable(casa)


class LoiEnVigueurBaseline(_BaseRetraitesReform):
    """Enveloppe de la loi en vigueur portant les métadonnées d'audit et le lissage CSG/CASA exact."""

    name = "Loi en vigueur 2025 (CGI art. 158, 5-a — référence OpenFisca-France)"
    calc_certainty: CalcCertainty = "green"
    legal_status: LegalStatus = "en_vigueur"
    source_ref: str = (
        "DGFiP Notice 2041-NOTFC 2026 (revenus 2025), "
        "https://www.impots.gouv.fr/sites/default/files/formulaires/2041-notfc/2026/2041-notfc_5516.pdf"
    )

    def __init__(self, baseline: TaxBenefitSystem, horizon: HorizonMode) -> None:
        self.horizon: HorizonMode = horizon
        super().__init__(baseline)

    def apply(self) -> None:
        super().apply()


class PlafonnementAbattementRetraites3000(_BaseRetraitesReform):
    """PLF 2027 art. 3 : sous-plafond de 3 000 € par foyer sur les seules pensions de retraite.

    Les pensions alimentaires et pensions d'invalidité conservent le plafond de droit
    commun CGI art. 158, 5-a (4 439 € sur les revenus 2025).
    """

    name = "PLF 2027 art. 3 — Sous-plafond 3 000 € (pensions de retraite seules)"
    calc_certainty: CalcCertainty = "green"
    legal_status: LegalStatus = "projet_de_loi_en_navette"
    source_ref: str = (
        "PLF 2027 AN n° 3210, art. 3 (déposé le 01/10/2026), "
        "https://www.assemblee-nationale.fr/dyn/docs/PRJLANR5L17B3210.raw"
    )

    def __init__(self, baseline: TaxBenefitSystem, horizon: HorizonMode = "annee_1") -> None:
        self.horizon: HorizonMode = horizon
        self._start_year = int(horizon_to_start_date(horizon)[:4])
        super().__init__(baseline)

    def apply(self) -> None:
        super().apply()
        start_year = self._start_year

        class indu_plaf_abat_pen(Variable):
            value_type = float
            entity = FoyerFiscal
            label = "Plafonnement abattement 10 % pensions (sous-plafond 3 000 € retraites seules)"
            definition_period = YEAR

            def formula(foyer_fiscal, period, parameters):
                # SOURCE: DGFiP Notice 2041-NOTFC 2026 (revenus 2025), https://www.impots.gouv.fr/sites/default/files/formulaires/2041-notfc/2026/2041-notfc_5516.pdf (min 454 € par pensionné, plafond 4 439 € par foyer fiscal)
                abatpen = parameters(period).impot_revenu.calcul_revenus_imposables.deductions.abatpen
                rev_pen_i = foyer_fiscal.members("revenu_assimile_pension", period)
                pen_net_i = foyer_fiscal.members("revenu_assimile_pension_apres_abattements", period)
                abat_i = rev_pen_i - pen_net_i
                abat_foyer = foyer_fiscal.sum(abat_i)

                if period.start.year < start_year:
                    return max_(0.0, abat_foyer - min_(abat_foyer, abatpen.max))

                retraite_i = foyer_fiscal.members("retraite_imposable", period, options=[ADD])
                pa_i = foyer_fiscal.members("pensions_alimentaires_percues", period, options=[ADD])
                pa_decl_i = foyer_fiscal.members("pensions_alimentaires_percues_decl", period, options=[ADD])
                inv_i = foyer_fiscal.members("pensions_invalidite", period, options=[ADD])
                autres_i = pa_i * pa_decl_i + inv_i

                # Part d'abattement attribuable aux pensions alimentaires / d'invalidité hors retraite
                abat_autres_i = where(
                    autres_i > 0,
                    min_(autres_i, round_(max_(abatpen.taux * autres_i, abatpen.min * (retraite_i == 0)))),
                    0.0,
                )
                abat_retraite_i = max_(0.0, abat_i - abat_autres_i)

                abat_retraite_foyer = foyer_fiscal.sum(abat_retraite_i)
                abat_autres_foyer = foyer_fiscal.sum(abat_autres_i)

                # SOURCE: PLF 2027 AN n° 3210, art. 3 (déposé le 01/10/2026), https://www.assemblee-nationale.fr/dyn/docs/PRJLANR5L17B3210.raw (sous-plafond 3 000 € pensions de retraite)
                abat_retraite_plafonne = min_(abat_retraite_foyer, PLAFOND_ABATPEN_RETRAITE_3000)
                abat_autorise = min_(abatpen.max, abat_retraite_plafonne + abat_autres_foyer)
                return max_(0.0, abat_foyer - abat_autorise)

        self.update_variable(indu_plaf_abat_pen)


class SuppressionAbattementRetraites10Pct(_BaseRetraitesReform):
    """Suppression de l'abattement forfaitaire de 10 % sur les pensions.

    Par défaut (``scope="retraites_seules"``), la suppression est ciblée sur les seules
    pensions de retraite afin de comparer à périmètre constant avec PLF 2027 art. 3.
    L'option ``scope="global_158_5_a"`` supprime l'ensemble de l'abattement CGI art. 158, 5-a.
    """

    calc_certainty: CalcCertainty = "green"
    legal_status: LegalStatus = "proposition_programme"
    source_ref: str = (
        "Scénario analytique de suppression CGI art. 158, 5-a (comparaison à périmètre constant PLF 2027 art. 3), "
        "https://www.impots.gouv.fr/sites/default/files/formulaires/2041-notfc/2026/2041-notfc_5516.pdf"
    )

    def __init__(
        self,
        baseline: TaxBenefitSystem,
        horizon: HorizonMode = "annee_1",
        scope: SuppressionScope = "retraites_seules",
    ) -> None:
        self.horizon: HorizonMode = horizon
        self.scope: SuppressionScope = scope
        self._start_date = horizon_to_start_date(horizon)
        self._start_year = int(self._start_date[:4])
        scope_label = "retraites seules" if scope == "retraites_seules" else "global CGI art. 158, 5-a"
        self.name = f"Suppression abattement 10 % ({scope_label})"
        super().__init__(baseline)

    def apply(self) -> None:
        super().apply()
        if self.scope == "global_158_5_a":
            start_date = self._start_date

            def modify_params(parameters: Any) -> Any:
                # SOURCE: DGFiP Notice 2041-NOTFC 2026 (revenus 2025), https://www.impots.gouv.fr/sites/default/files/formulaires/2041-notfc/2026/2041-notfc_5516.pdf (suppression globale taux/min/max)
                abatpen = parameters.impot_revenu.calcul_revenus_imposables.deductions.abatpen
                abatpen.taux.update(start=start_date, value=0.0)
                abatpen.min.update(start=start_date, value=0.0)
                abatpen.max.update(start=start_date, value=0.0)
                return parameters

            self.modify_parameters(modifier_function=modify_params)
            return

        start_year = self._start_year

        class revenu_assimile_pension_apres_abattements(Variable):
            value_type = float
            entity = Individu
            label = "Pensions après abattements (suppression ciblée retraites seules)"
            definition_period = YEAR

            def formula(individu, period, parameters):
                # SOURCE: DGFiP Notice 2041-NOTFC 2026 (revenus 2025), https://www.impots.gouv.fr/sites/default/files/formulaires/2041-notfc/2026/2041-notfc_5516.pdf
                abatpen = parameters(period).impot_revenu.calcul_revenus_imposables.deductions.abatpen
                rev_pen = individu("revenu_assimile_pension", period)

                if period.start.year < start_year:
                    return max_(0.0, rev_pen - round_(max_(abatpen.taux * rev_pen, abatpen.min)))

                retraite_imposable = individu("retraite_imposable", period, options=[ADD])
                pa = individu("pensions_alimentaires_percues", period, options=[ADD])
                pa_decl = individu("pensions_alimentaires_percues_decl", period, options=[ADD])
                pensions_invalidite = individu("pensions_invalidite", period, options=[ADD])
                autres_pensions = pa * pa_decl + pensions_invalidite

                abat_autres = where(
                    autres_pensions > 0,
                    min_(autres_pensions, round_(max_(abatpen.taux * autres_pensions, abatpen.min))),
                    0.0,
                )
                return max_(0.0, retraite_imposable + max_(0.0, autres_pensions - abat_autres))

        self.update_variable(revenu_assimile_pension_apres_abattements)


class HouseholdResult(BaseModel):
    """Résultat socio-fiscal annuel (année 2025) pour un foyer type donné.

    Convention d'affichage comptable :
      - ``ir_paye`` >= 0 : impôt sur le revenu payé (opposé de ``impot_revenu_restant_a_payer``).
      - ``csg_retraite`` >= 0 : CSG totale sur pensions (déductible + imposable).
      - ``prelevements_sociaux_retraite`` >= 0 : CSG + CRDS + CASA sur pensions.
      - ``rfr_n_2`` : RFR de 2023 utilisé par OpenFisca pour le taux CSG retraites 2025.
      - ``rfr`` : RFR de 2025.
      - ``revenu_disponible`` : variable OpenFisca ``revenu_disponible`` (Menage, YEAR).
    """

    household_id: str
    label: str
    scenario: str
    horizon: HorizonMode
    calc_certainty: CalcCertainty
    legal_status: LegalStatus
    source_ref: str
    pension_brute_annuelle: float
    pension_hors_retraite_annuelle: float
    salaire_brut_annuel: float
    rfr_n_2: float
    rfr: float
    ir_paye: float
    csg_retraite: float
    prelevements_sociaux_retraite: float
    revenu_disponible: float


@dataclass(frozen=True)
class HouseholdSpec:
    """Descripteur explicite d'un foyer type avec clés d'entités déterministes."""

    household_id: str
    label: str
    foyer_fiscal_id: str
    famille_id: str
    menage_id: str
    member_ids: tuple[str, ...]


def _const_years(value: Any) -> dict[str, Any]:
    return {year: value for year in HISTORY_YEARS}


def _spec(household_id: str, label: str, member_ids: tuple[str, ...]) -> HouseholdSpec:
    return HouseholdSpec(
        household_id=household_id,
        label=label,
        foyer_fiscal_id=f"ff_{household_id}",
        famille_id=f"fam_{household_id}",
        menage_id=f"men_{household_id}",
        member_ids=member_ids,
    )


def build_retiree_households_payload() -> tuple[dict[str, Any], list[HouseholdSpec]]:
    """Construit 6 foyers types de retraités (incluant 63 ans <65 vs 68 ans >=65)."""
    specs = [
        _spec("modeste", "1. Retraité isolé modeste, 67 ans (1 200 €/mois brut)", ("ind_modeste_1",)),
        _spec("median_63ans", "2a. Retraité isolé médian, 63 ans <65 (2 400 €/mois brut)", ("ind_median_63_1",)),
        _spec("median_68ans", "2b. Retraité isolé médian, 68 ans >=65 (2 400 €/mois brut)", ("ind_median_68_1",)),
        _spec("intermediaire", "3. Retraité isolé intermédiaire, 67 ans (3 200 €/mois brut)", ("ind_inter_1",)),
        _spec("aise", "4. Retraité isolé aisé, 67 ans (4 500 €/mois brut)", ("ind_aise_1",)),
        _spec(
            "couple_aise",
            "5. Couple retraités aisés, 67 & 66 ans (3 000 + 2 500 €/mois brut)",
            ("ind_couple_aise_1", "ind_couple_aise_2"),
        ),
    ]
    payload: dict[str, Any] = {
        "individus": {
            "ind_modeste_1": {
                "date_naissance": {"ETERNITY": "1958-01-01"},
                # HYPOTHÈSE DE SIMULATION : cas-type pédagogique calibré (non issu de données individuelles ERFS)
                "retraite_brute": _const_years(14400.0),
            },
            "ind_median_63_1": {
                "date_naissance": {"ETERNITY": "1962-01-01"},
                # HYPOTHÈSE DE SIMULATION : cas-type pédagogique calibré (non issu de données individuelles ERFS)
                "retraite_brute": _const_years(28800.0),
            },
            "ind_median_68_1": {
                "date_naissance": {"ETERNITY": "1957-01-01"},
                # HYPOTHÈSE DE SIMULATION : cas-type pédagogique calibré (non issu de données individuelles ERFS)
                "retraite_brute": _const_years(28800.0),
            },
            "ind_inter_1": {
                "date_naissance": {"ETERNITY": "1958-01-01"},
                # HYPOTHÈSE DE SIMULATION : cas-type pédagogique calibré (non issu de données individuelles ERFS)
                "retraite_brute": _const_years(38400.0),
            },
            "ind_aise_1": {
                "date_naissance": {"ETERNITY": "1958-01-01"},
                # HYPOTHÈSE DE SIMULATION : cas-type pédagogique calibré (non issu de données individuelles ERFS)
                "retraite_brute": _const_years(54000.0),
            },
            "ind_couple_aise_1": {
                "date_naissance": {"ETERNITY": "1958-01-01"},
                "statut_marital": _const_years("marie"),
                # HYPOTHÈSE DE SIMULATION : cas-type pédagogique calibré (non issu de données individuelles ERFS)
                "retraite_brute": _const_years(36000.0),
            },
            "ind_couple_aise_2": {
                "date_naissance": {"ETERNITY": "1959-01-01"},
                "statut_marital": _const_years("marie"),
                # HYPOTHÈSE DE SIMULATION : cas-type pédagogique calibré (non issu de données individuelles ERFS)
                "retraite_brute": _const_years(30000.0),
            },
        },
        "foyers_fiscaux": {
            "ff_modeste": {"declarants": ["ind_modeste_1"]},
            "ff_median_63ans": {"declarants": ["ind_median_63_1"]},
            "ff_median_68ans": {"declarants": ["ind_median_68_1"]},
            "ff_intermediaire": {"declarants": ["ind_inter_1"]},
            "ff_aise": {"declarants": ["ind_aise_1"]},
            "ff_couple_aise": {"declarants": ["ind_couple_aise_1", "ind_couple_aise_2"]},
        },
        "familles": {
            "fam_modeste": {"parents": ["ind_modeste_1"]},
            "fam_median_63ans": {"parents": ["ind_median_63_1"]},
            "fam_median_68ans": {"parents": ["ind_median_68_1"]},
            "fam_intermediaire": {"parents": ["ind_inter_1"]},
            "fam_aise": {"parents": ["ind_aise_1"]},
            "fam_couple_aise": {"parents": ["ind_couple_aise_1", "ind_couple_aise_2"]},
        },
        "menages": {
            "men_modeste": {"personne_de_reference": ["ind_modeste_1"]},
            "men_median_63ans": {"personne_de_reference": ["ind_median_63_1"]},
            "men_median_68ans": {"personne_de_reference": ["ind_median_68_1"]},
            "men_intermediaire": {"personne_de_reference": ["ind_inter_1"]},
            "men_aise": {"personne_de_reference": ["ind_aise_1"]},
            "men_couple_aise": {"personne_de_reference": ["ind_couple_aise_1"], "conjoint": ["ind_couple_aise_2"]},
        },
    }
    return payload, specs


def build_active_control_households_payload() -> tuple[dict[str, Any], list[HouseholdSpec]]:
    """Construit les 3 foyers d'actifs du protocole AGENTS.md + foyers témoins hors retraite."""
    specs = [
        _spec("smicard_isole", "Actif A. SMICard isolé, 30 ans (21 622 €/an brut)", ("ind_smic_1",)),
        _spec(
            "couple_2_enfants",
            "Actif B. Couple salarié, 39 & 37 ans, 2 enfants (54 000 €/an brut)",
            ("ind_c2e_1", "ind_c2e_2", "ind_c2e_enf1", "ind_c2e_enf2"),
        ),
        _spec("cadre_proprietaire", "Actif C. Cadre propriétaire isolé, 41 ans (60 000 €/an brut)", ("ind_cadre_1",)),
        _spec(
            "pension_alimentaire_seule",
            "Témoin D. Pension alimentaire seule, 45 ans (38 400 €/an)",
            ("ind_pa_1",),
        ),
        _spec(
            "pension_invalidite_seule",
            "Témoin E. Pension d'invalidité seule, 52 ans (38 400 €/an)",
            ("ind_inv_1",),
        ),
        _spec(
            "mixte_retraite_pension_alim",
            "Témoin F. Mixte retraite + pension alimentaire, 67 ans (36 000 + 10 000 €/an)",
            ("ind_mixte_1",),
        ),
    ]
    payload: dict[str, Any] = {
        "individus": {
            "ind_smic_1": {
                "date_naissance": {"ETERNITY": "1995-01-01"},
                # HYPOTHÈSE DE SIMULATION : cas-type pédagogique calibré (SMIC 2025, non issu de données individuelles ERFS)
                "salaire_de_base": _const_years(SMIC_ANNUEL_BRUT_2025),
            },
            "ind_c2e_1": {
                "date_naissance": {"ETERNITY": "1986-01-01"},
                "statut_marital": _const_years("marie"),
                # HYPOTHÈSE DE SIMULATION : cas-type pédagogique calibré (non issu de données individuelles ERFS)
                "salaire_de_base": _const_years(30000.0),
            },
            "ind_c2e_2": {
                "date_naissance": {"ETERNITY": "1988-01-01"},
                "statut_marital": _const_years("marie"),
                # HYPOTHÈSE DE SIMULATION : cas-type pédagogique calibré (non issu de données individuelles ERFS)
                "salaire_de_base": _const_years(24000.0),
            },
            "ind_c2e_enf1": {"date_naissance": {"ETERNITY": "2015-05-01"}},
            "ind_c2e_enf2": {"date_naissance": {"ETERNITY": "2018-09-01"}},
            "ind_cadre_1": {
                "date_naissance": {"ETERNITY": "1984-01-01"},
                "categorie_salarie": _const_years("prive_cadre"),
                # HYPOTHÈSE DE SIMULATION : cas-type pédagogique calibré (non issu de données individuelles ERFS)
                "salaire_de_base": _const_years(60000.0),
            },
            "ind_pa_1": {
                "date_naissance": {"ETERNITY": "1980-01-01"},
                # HYPOTHÈSE DE SIMULATION : cas-type pédagogique calibré (non issu de données individuelles ERFS)
                "pensions_alimentaires_percues": _const_years(38400.0),
            },
            "ind_inv_1": {
                "date_naissance": {"ETERNITY": "1973-01-01"},
                # HYPOTHÈSE DE SIMULATION : cas-type pédagogique calibré (non issu de données individuelles ERFS)
                "pensions_invalidite": _const_years(38400.0),
            },
            "ind_mixte_1": {
                "date_naissance": {"ETERNITY": "1958-01-01"},
                # HYPOTHÈSE DE SIMULATION : cas-type pédagogique calibré (non issu de données individuelles ERFS)
                "retraite_brute": _const_years(36000.0),
                # HYPOTHÈSE DE SIMULATION : cas-type pédagogique calibré (non issu de données individuelles ERFS)
                "pensions_alimentaires_percues": _const_years(10000.0),
            },
        },
        "foyers_fiscaux": {
            "ff_smicard_isole": {"declarants": ["ind_smic_1"]},
            "ff_couple_2_enfants": {
                "declarants": ["ind_c2e_1", "ind_c2e_2"],
                "personnes_a_charge": ["ind_c2e_enf1", "ind_c2e_enf2"],
            },
            "ff_cadre_proprietaire": {"declarants": ["ind_cadre_1"]},
            "ff_pension_alimentaire_seule": {"declarants": ["ind_pa_1"]},
            "ff_pension_invalidite_seule": {"declarants": ["ind_inv_1"]},
            "ff_mixte_retraite_pension_alim": {"declarants": ["ind_mixte_1"]},
        },
        "familles": {
            "fam_smicard_isole": {"parents": ["ind_smic_1"]},
            "fam_couple_2_enfants": {
                "parents": ["ind_c2e_1", "ind_c2e_2"],
                "enfants": ["ind_c2e_enf1", "ind_c2e_enf2"],
            },
            "fam_cadre_proprietaire": {"parents": ["ind_cadre_1"]},
            "fam_pension_alimentaire_seule": {"parents": ["ind_pa_1"]},
            "fam_pension_invalidite_seule": {"parents": ["ind_inv_1"]},
            "fam_mixte_retraite_pension_alim": {"parents": ["ind_mixte_1"]},
        },
        "menages": {
            "men_smicard_isole": {"personne_de_reference": ["ind_smic_1"]},
            "men_couple_2_enfants": {
                "personne_de_reference": ["ind_c2e_1"],
                "conjoint": ["ind_c2e_2"],
                "enfants": ["ind_c2e_enf1", "ind_c2e_enf2"],
            },
            "men_cadre_proprietaire": {
                "personne_de_reference": ["ind_cadre_1"],
                "statut_occupation_logement": _const_years("proprietaire"),
            },
            "men_pension_alimentaire_seule": {"personne_de_reference": ["ind_pa_1"]},
            "men_pension_invalidite_seule": {"personne_de_reference": ["ind_inv_1"]},
            "men_mixte_retraite_pension_alim": {"personne_de_reference": ["ind_mixte_1"]},
        },
    }
    return payload, specs


def _resolve_and_validate_metadata(
    tax_benefit_system: TaxBenefitSystem,
    horizon: HorizonMode | None,
    calc_certainty: CalcCertainty | None,
    legal_status: LegalStatus | None,
    source_ref: str | None,
) -> tuple[HorizonMode, CalcCertainty, LegalStatus, str]:
    """Déduit et verrouille les métadonnées depuis le TaxBenefitSystem ; lève ValueError si incohérent."""
    sys_horizon = getattr(tax_benefit_system, "horizon", None)
    sys_certainty = getattr(tax_benefit_system, "calc_certainty", None)
    sys_legal = getattr(tax_benefit_system, "legal_status", None)
    sys_source = getattr(tax_benefit_system, "source_ref", None)

    if sys_horizon is not None and horizon is not None and sys_horizon != horizon:
        raise ValueError(
            f"Incohérence horizon : le système {type(tax_benefit_system).__name__} porte horizon={sys_horizon!r} "
            f"mais evaluate_households() a reçu horizon={horizon!r}."
        )
    if sys_certainty is not None and calc_certainty is not None and sys_certainty != calc_certainty:
        raise ValueError(
            f"Incohérence calc_certainty : {type(tax_benefit_system).__name__} porte {sys_certainty!r}, "
            f"reçu {calc_certainty!r}."
        )
    if sys_legal is not None and legal_status is not None and sys_legal != legal_status:
        raise ValueError(
            f"Incohérence legal_status : {type(tax_benefit_system).__name__} porte {sys_legal!r}, "
            f"reçu {legal_status!r}."
        )

    resolved_horizon = horizon if horizon is not None else sys_horizon
    resolved_certainty = calc_certainty if calc_certainty is not None else sys_certainty
    resolved_legal = legal_status if legal_status is not None else sys_legal
    resolved_source = source_ref if source_ref is not None else sys_source

    if resolved_horizon is None or resolved_certainty is None or resolved_legal is None:
        raise ValueError(
            f"Métadonnées manquantes pour {type(tax_benefit_system).__name__} : "
            "horizon, calc_certainty et legal_status doivent être portés par le système (Reform/LoiEnVigueurBaseline) "
            "ou passés explicitement sans valeur par défaut silencieuse."
        )
    if not resolved_source:
        resolved_source = getattr(tax_benefit_system, "name", type(tax_benefit_system).__name__)

    return resolved_horizon, resolved_certainty, resolved_legal, resolved_source


def _validate_specs_against_payload(payload: dict[str, Any], specs: list[HouseholdSpec]) -> None:
    """Vérifie avant simulation l'existence et la cohérence exacte des membres (FoyerFiscal, Famille, Menage)."""
    individus = payload.get("individus", {})
    foyers = payload.get("foyers_fiscaux", {})
    familles = payload.get("familles", {})
    menages = payload.get("menages", {})

    for spec in specs:
        if spec.foyer_fiscal_id not in foyers:
            raise ValueError(f"Foyer fiscal absent : {spec.foyer_fiscal_id}")
        if spec.famille_id not in familles:
            raise ValueError(f"Famille absente : {spec.famille_id}")
        if spec.menage_id not in menages:
            raise ValueError(f"Ménage absent : {spec.menage_id}")
        for pid in spec.member_ids:
            if pid not in individus:
                raise ValueError(f"Individu absent : {pid}")

        expected_members = set(spec.member_ids)
        ff_data = foyers[spec.foyer_fiscal_id]
        expected_ff = set(ff_data.get("declarants", [])) | set(ff_data.get("personnes_a_charge", []))
        if expected_ff != expected_members:
            raise ValueError(f"Incohérence membres FoyerFiscal pour {spec.household_id}")

        fam_data = familles[spec.famille_id]
        expected_fam = set(fam_data.get("parents", [])) | set(fam_data.get("enfants", []))
        if expected_fam != expected_members:
            raise ValueError(f"Incohérence membres Famille pour {spec.household_id}")

        men_data = menages[spec.menage_id]
        expected_men = (
            set(men_data.get("personne_de_reference", []))
            | set(men_data.get("conjoint", []))
            | set(men_data.get("enfants", []))
            | set(men_data.get("autres", []))
        )
        if expected_men != expected_members:
            raise ValueError(f"Incohérence membres Menage pour {spec.household_id}")


def evaluate_households(
    tax_benefit_system: TaxBenefitSystem,
    payload: dict[str, Any],
    specs: list[HouseholdSpec],
    scenario_name: str,
    horizon: HorizonMode | None = None,
    calc_certainty: CalcCertainty | None = None,
    legal_status: LegalStatus | None = None,
    source_ref: str | None = None,
    period: str = REFERENCE_YEAR,
) -> dict[str, HouseholdResult]:
    """Exécute une simulation OpenFisca et indexe strictement les résultats par ID d'entité."""
    resolved_horizon, resolved_certainty, resolved_legal, resolved_source = _resolve_and_validate_metadata(
        tax_benefit_system=tax_benefit_system,
        horizon=horizon,
        calc_certainty=calc_certainty,
        legal_status=legal_status,
        source_ref=source_ref,
    )
    _validate_specs_against_payload(payload, specs)

    sim = SimulationBuilder().build_from_entities(tax_benefit_system, payload)
    sim.max_spiral_loops = DEFAULT_MAX_SPIRAL_LOOPS

    n_2_period = str(int(period) - 2)
    ir_arr = sim.calculate("impot_revenu_restant_a_payer", period)
    rfr_arr = sim.calculate("rfr", period)
    rfr_n_2_arr = sim.calculate("rfr", n_2_period)
    rev_disp_arr = sim.calculate("revenu_disponible", period)

    csg_ded = sim.calculate_add("csg_deductible_retraite", period)
    csg_imp = sim.calculate_add("csg_imposable_retraite", period)
    crds_ret = sim.calculate_add("crds_retraite", period)
    casa_ret = sim.calculate_add("casa", period)
    retraite_brute = sim.calculate_add("retraite_brute", period)
    pa_percues = sim.calculate_add("pensions_alimentaires_percues", period)
    pensions_inv = sim.calculate_add("pensions_invalidite", period)
    salaire_brut = sim.calculate_add("salaire_de_base", period)

    person_index = {pid: idx for idx, pid in enumerate(sim.individu.ids)}
    ff_index = {fid: idx for idx, fid in enumerate(sim.foyer_fiscal.ids)}
    men_index = {mid: idx for idx, mid in enumerate(sim.menage.ids)}

    results: dict[str, HouseholdResult] = {}
    for spec in specs:
        ff_idx = ff_index[spec.foyer_fiscal_id]
        men_idx = men_index[spec.menage_id]
        member_indices = [person_index[pid] for pid in spec.member_ids]

        # En OpenFisca-France, l'IR et les prélèvements sociaux calculés sont négatifs.
        # L'addition `+ 0.0` normalise IEEE-754 `-0.0` en `0.0`.
        ir_paye = round(float(-ir_arr[ff_idx]), 2) + 0.0
        rfr_val = round(float(rfr_arr[ff_idx]), 2) + 0.0
        rfr_n_2_val = round(float(rfr_n_2_arr[ff_idx]), 2) + 0.0
        csg_tot = round(float(-sum(csg_ded[i] + csg_imp[i] for i in member_indices)), 2) + 0.0
        ps_tot = round(
            float(-sum(csg_ded[i] + csg_imp[i] + crds_ret[i] + casa_ret[i] for i in member_indices)),
            2,
        ) + 0.0
        rev_disp = round(float(rev_disp_arr[men_idx]), 2) + 0.0
        pens_brute = round(float(sum(retraite_brute[i] for i in member_indices)), 2) + 0.0
        pens_autres = round(float(sum(pa_percues[i] + pensions_inv[i] for i in member_indices)), 2) + 0.0
        sal_brut = round(float(sum(salaire_brut[i] for i in member_indices)), 2) + 0.0

        results[spec.household_id] = HouseholdResult(
            household_id=spec.household_id,
            label=spec.label,
            scenario=scenario_name,
            horizon=resolved_horizon,
            calc_certainty=resolved_certainty,
            legal_status=resolved_legal,
            source_ref=resolved_source,
            pension_brute_annuelle=pens_brute,
            pension_hors_retraite_annuelle=pens_autres,
            salaire_brut_annuel=sal_brut,
            rfr_n_2=rfr_n_2_val,
            rfr=rfr_val,
            ir_paye=ir_paye,
            csg_retraite=csg_tot,
            prelevements_sociaux_retraite=ps_tot,
            revenu_disponible=rev_disp,
        )
    return results


def run_comparison_suite(
    horizon: HorizonMode = "annee_1",
    suppression_scope: SuppressionScope = "retraites_seules",
) -> dict[str, dict[str, dict[str, HouseholdResult]]]:
    """Lance la comparaison complète pour un horizon donné (Base vs Art. 3 PLF 2027 vs Suppression 10 %)."""
    baseline_raw = get_tax_benefit_system()
    systems: dict[str, TaxBenefitSystem] = {
        "base": LoiEnVigueurBaseline(baseline_raw, horizon=horizon),
        "plafond_3000": PlafonnementAbattementRetraites3000(baseline_raw, horizon=horizon),
        "suppression_10pct": SuppressionAbattementRetraites10Pct(
            baseline_raw,
            horizon=horizon,
            scope=suppression_scope,
        ),
    }

    retiree_payload, retiree_specs = build_retiree_households_payload()
    active_payload, active_specs = build_active_control_households_payload()

    retirees: dict[str, dict[str, HouseholdResult]] = {}
    actives: dict[str, dict[str, HouseholdResult]] = {}
    for scenario_name, tbs in systems.items():
        retirees[scenario_name] = evaluate_households(
            tbs,
            retiree_payload,
            retiree_specs,
            scenario_name=scenario_name,
        )
        actives[scenario_name] = evaluate_households(
            tbs,
            active_payload,
            active_specs,
            scenario_name=scenario_name,
        )

    return {"retirees": retirees, "actives": actives}


def to_ascii_safe(text: str) -> str:
    """Convertit les symboles et accents en ASCII pur pour consoles CP1252/CP850 strictes."""
    replaced = text.replace("€", "EUR").replace("Δ", "Delta").replace("→", "->").replace("«", '"').replace("»", '"')
    normalized = unicodedata.normalize("NFKD", replaced)
    return normalized.encode("ascii", errors="ignore").decode("ascii")


def _configure_console_utf8() -> bool:
    """Tente de reconfigurer stdout/stderr en UTF-8 ; retourne True si UTF-8 est actif."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    encoding = (getattr(sys.stdout, "encoding", None) or "").lower()
    return "utf" in encoding


def format_comparison_table(
    retirees_by_scenario: dict[str, dict[str, HouseholdResult]],
    horizon: HorizonMode,
    ascii_safe: bool = False,
) -> str:
    """Formate un tableau Markdown comparant RFR (N-2/N), IR, CSG (Δ) et Revenu Disponible (Δ)."""
    base_map = retirees_by_scenario["base"]
    plaf_map = retirees_by_scenario["plafond_3000"]
    supp_map = retirees_by_scenario["suppression_10pct"]

    rfr_col_title = "RFR 2025" if horizon == "annee_1" else "RFR 23 (N-2)"

    header = (
        f"| Foyer type (2025, €/an) | Brut/an | Base {rfr_col_title} | Base IR | Base CSG | Base RevDisp | "
        f"Art.3 3000€ {rfr_col_title} | Art.3 IR (Δ) | Art.3 CSG (Δ) | Art.3 RevDisp (Δ) | "
        f"Suppr.10% {rfr_col_title} | Suppr.10% IR (Δ) | Suppr.10% CSG (Δ) | Suppr.10% RevDisp (Δ) |"
    )
    sep = "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
    lines = [header, sep]

    def _fmt_rfr(res: HouseholdResult) -> str:
        return f"{res.rfr:,.0f} €" if horizon == "annee_1" else f"{res.rfr_n_2:,.0f} €"

    for hid, b in base_map.items():
        p = plaf_map[hid]
        s = supp_map[hid]
        lines.append(
            f"| {b.label} | {b.pension_brute_annuelle:,.0f} € | "
            f"{_fmt_rfr(b)} | {b.ir_paye:,.0f} € | {b.csg_retraite:,.1f} € | {b.revenu_disponible:,.2f} € | "
            f"{_fmt_rfr(p)} | {p.ir_paye:,.0f} € ({p.ir_paye - b.ir_paye:+,.0f} €) | "
            f"{p.csg_retraite:,.1f} € ({p.csg_retraite - b.csg_retraite:+,.1f} €) | "
            f"{p.revenu_disponible:,.2f} € ({p.revenu_disponible - b.revenu_disponible:+,.2f} €) | "
            f"{_fmt_rfr(s)} | {s.ir_paye:,.0f} € ({s.ir_paye - b.ir_paye:+,.0f} €) | "
            f"{s.csg_retraite:,.1f} € ({s.csg_retraite - b.csg_retraite:+,.1f} €) | "
            f"{s.revenu_disponible:,.2f} € ({s.revenu_disponible - b.revenu_disponible:+,.2f} €) |"
        )
    rendered = "\n".join(lines)
    return to_ascii_safe(rendered) if ascii_safe else rendered


def main() -> int:
    utf8_ok = _configure_console_utf8()

    parser = argparse.ArgumentParser(description="Simulation PLF 2027 art. 3 vs Suppression 10 % retraites.")
    parser.add_argument(
        "--horizon",
        choices=["annee_1", "regime_permanent", "both"],
        default="both",
        help="Horizon temporel de simulation (défaut : both).",
    )
    parser.add_argument(
        "--ascii",
        action="store_true",
        help="Force un rendu ASCII pur (Delta / EUR) compatible CP1252/CP850.",
    )
    args = parser.parse_args()
    use_ascii = bool(args.ascii or not utf8_ok)

    def _emit(line: str) -> None:
        print(to_ascii_safe(line) if use_ascii else line)

    horizons: list[HorizonMode] = ["annee_1", "regime_permanent"] if args.horizon == "both" else [args.horizon]
    for horizon in horizons:
        suite = run_comparison_suite(horizon=horizon)
        titre_h = (
            "EFFET ANNÉE 1 (2025 seul, RFR N-2 figé)"
            if horizon == "annee_1"
            else "RÉGIME PERMANENT (2021..2025, rétroaction RFR N-2 -> CSG)"
        )
        _emit(f"\n=== VERITE FISCALE 2027 :: DEMO PLF RETRAITES [{titre_h}] ===\n")
        _emit(format_comparison_table(suite["retirees"], horizon=horizon, ascii_safe=use_ascii))
        _emit("\n--- Contrôle périmètre Actifs & Pensions hors retraite (AGENTS.md) ---")
        for hid, b in suite["actives"]["base"].items():
            p = suite["actives"]["plafond_3000"][hid]
            s = suite["actives"]["suppression_10pct"][hid]
            _emit(
                f"- {b.label}: Base IR={b.ir_paye:,.0f} € | Base RevDisp={b.revenu_disponible:,.2f} € | "
                f"Δ Art.3 3000€={p.revenu_disponible - b.revenu_disponible:+.2f} € | "
                f"Δ Suppr.10% (retraites seules)={s.revenu_disponible - b.revenu_disponible:+.2f} €"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
