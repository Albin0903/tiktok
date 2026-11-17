"""API locale du démonstrateur PLF 2027."""

from __future__ import annotations

from contextlib import asynccontextmanager
import json
from pathlib import Path
from typing import Annotated, Literal

import duckdb
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from engine.household_social import DEFAULT_ZONE, RENT_SOURCE, HouseholdInputs, cache_social_parameters, simulate_social
from engine.reforms import get_tax_benefit_system
from engine.reforms.plf2027_complet_demo import (
    DETAIL_NAME,
    INCOME_YEAR,
    PLF_SOURCE,
    REFORM_ID,
    SCOPE,
    SUMMARY_NAME,
    GelBaremeRevenus2026,
    PLF2027BaremeEtRetraites,
)


PROCESSED_DIR = Path(__file__).resolve().parents[1] / "data" / "processed"
ORIGINS = ("http://127.0.0.1:3000", "http://localhost:3000")


class HouseholdProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revenu_net_imposable_mensuel: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    age: Annotated[int, Field(ge=18, le=120)]
    statut: Literal["salarie_non_cadre", "salarie_cadre", "independant", "retraite", "chomeur", "inactif"]
    couple: bool = False
    enfants: Annotated[int, Field(ge=0, le=10)] = 0
    logement: Literal["locataire", "proprietaire", "loge_gratuitement"] = "locataire"
    carburant_mensuel: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 0
    energie_mensuelle: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 0
    loyer_mensuel: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None
    zone_apl: Literal[1, 2, 3] = DEFAULT_ZONE
    age_enfant: Annotated[int, Field(ge=0, le=17)] = 10
    revenu_brut_mensuel: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None
    logement_conventionne: bool = False


def simulate_profile(profile: HouseholdProfile, baseline, reform) -> dict:
    inputs = HouseholdInputs(
        net_taxable_monthly=profile.revenu_net_imposable_mensuel, age=profile.age, status=profile.statut,
        couple=profile.couple, children=profile.enfants, housing=profile.logement, rent=profile.loyer_mensuel,
        zone=profile.zone_apl, child_age=profile.age_enfant, gross_monthly=profile.revenu_brut_mensuel,
        subsidized_housing=profile.logement_conventionne,
    )
    before, after, assumptions = simulate_social(inputs, baseline, reform)
    return {
        "reform_id": REFORM_ID,
        "calc_certainty": "yellow",
        "legal_status": reform.legal_status,
        "horizon": reform.horizon,
        "source_ref": PLF_SOURCE,
        "perimetre": SCOPE,
        "annee_revenus": INCOME_YEAR,
        "variation_revenu_disponible_mensuelle_eur": round((after["revenu_disponible"] - before["revenu_disponible"]) / 12, 2),
        "lignes": [
            {"poste": name, "gel_eur": round(value, 2), "plf_eur": round(after[name], 2), "delta_eur": round(after[name] - value, 2)}
            for name, value in before.items()
        ],
        "second_tour": {
            "cout_annuel_bas_eur": 0,
            "cout_annuel_haut_eur": 0,
            "calc_certainty": "yellow",
            "source_ref": PLF_SOURCE,
            "hypothese": "Aucun choc direct de TVA, d'énergie ou de cotisations dans le périmètre IR simulé.",
        },
        "hypotheses": [
            "En couple, imposition commune et revenus de même catégorie répartis à parts égales.",
            "Revenus annuels et situation du foyer supposés stables sur les cinq années de simulation.",
            "Le profil simplifié ne renseigne ni invalidité, ni droits à l’ASS, ni patrimoine imposable à l’IFI.",
            "Le brut fourni remplace le net imposable dans les calculs. Le brut estimé est obtenu en inversant le net imposable OpenFisca.",
            "Pour les indépendants, le net imposable est traité comme le bénéfice fiscal d’un commerçant au régime de droit commun. Un chiffre d’affaires brut ne peut pas en être déduit.",
            "Pour le chômage, le salaire journalier de référence n’est pas connu. La cotisation de retraite complémentaire peut être sous-estimée.",
            "Le revenu disponible est affiché avant paiement du loyer et des dépenses de carburant et d’énergie.",
        ],
        "hypotheses_appliquees": assumptions,
        "source_loyer": RENT_SOURCE,
    }


def create_app(processed_dir: Path = PROCESSED_DIR) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        reference = get_tax_benefit_system()
        app.state.baseline = GelBaremeRevenus2026(reference, "annee_1")
        app.state.reform = PLF2027BaremeEtRetraites(reference)
        cache_social_parameters(app.state.baseline, prepare_payroll=True)
        cache_social_parameters(app.state.reform)
        yield

    app = FastAPI(title="Vérité Fiscale 2027", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=ORIGINS, allow_methods=["GET", "POST"], allow_headers=["Content-Type"])

    @app.get("/api/reforms")
    def reforms(request: Request):
        reform = request.app.state.reform
        return [{
            "id": REFORM_ID, "label": reform.name, "calc_certainty": "yellow",
            "legal_status": reform.legal_status, "horizon": reform.horizon, "source_ref": PLF_SOURCE,
            "perimetre": SCOPE,
        }]

    @app.get("/api/distribution/{reform_id}")
    def distribution(reform_id: str, limit: Annotated[int, Query(ge=1, le=10_000)] = 500):
        if reform_id != REFORM_ID:
            raise HTTPException(404, "Réforme inconnue")
        summary = processed_dir / SUMMARY_NAME
        detail = processed_dir / DETAIL_NAME
        if not summary.is_file() or not detail.is_file():
            raise HTTPException(503, "Distribution locale indisponible. Générer les exports OpenFisca.")
        with duckdb.connect() as connection:
            points = connection.execute(
                """select menage_id, decile, gain_ir_eur, poids
                from read_parquet(?) order by hash(menage_id) limit ?""",
                [str(detail), limit],
            ).fetchall()
        return {
            **json.loads(summary.read_text(encoding="utf-8")),
            "points": [dict(zip(("menage_id", "decile", "gain_ir_eur", "poids"), point)) for point in points],
        }

    @app.post("/api/simulate")
    def simulate(profile: HouseholdProfile, request: Request):
        try:
            return simulate_profile(profile, request.app.state.baseline, request.app.state.reform)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    return app


app = create_app()
