"""Calage des ménages, des déclarations fiscales et des marges du rôle IRCOM."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl

from engine.reforms import get_tax_benefit_system
from engine.synthetic.official_margins import read_2042, read_ircom, read_ircom_bands, read_ircom_tail


# SOURCE: DGFiP, déclarations 2042 / 2042-RICI 2023–2024,
# https://data.economie.gouv.fr/explore/dataset/ir-declarations-2042-nat/
FAMILY_CASES = {
    "celibataire": "0AC", "divorce": "0AD", "marie": "0AM", "pacse": "0AO", "veuf": "0AV",
}
EXPENSES = {
    "f7db": "7DB", "f7dr": "7DR", "f7uf": "7UF", "f7ud": "7UD", "f7ga": "7GA", "f7gb": "7GB", "f7gc": "7GC",
    "f7ea": "7EA", "f7ec": "7EC",
    "f6gu": "6GU", "f6ns": "6NS", "f6ns_partenaire": "6NT", "f6rs": "6RS", "f6rs_partenaire": "6RT",
}
QUOTIENT_BOXES = {"caseL": "0AL", "caseP": "0AP", "caseF": "0AF"}
CAPITAL_AND_PROFITS = {
    "f2dc": "2DC", "f2tr": "2TR", "f2zz": "2ZZ", "f3vg": "3VG", "f4ba": "4BA", "f4bb": "4BB",
    "abnc_impo": "5QC", "abnc_impo_partenaire": "5RC", "abic_impn": "5KC", "abic_impn_partenaire": "5LC",
}
UPPER_RICI = {
    "f7rb": "7RB", "f7ji": "7JI", "f7jj": "7JJ", "f7jf": "7JF", "f7ov": "7OV", "f7ns": "7NS",
    "f7fm": "7FM", "f7fq": "7FQ", "f7gq": "7GQ", "f7ci": "7CI", "f8tk": "8TK",
}


def calibrate_moments(initial: np.ndarray, features: np.ndarray, sums: np.ndarray, penalties=None, *, bounds=None) -> np.ndarray:
    """Calage entropique positif sur des marges et des effectifs multicatégories."""
    scales = np.maximum(1.0, np.maximum(np.abs(features).max(axis=0), np.abs(sums / initial.sum())))
    matrix = features / scales
    target = sums / scales / initial.sum()
    prior = initial / initial.sum()
    coefficients = np.zeros(matrix.shape[1])
    penalties = np.zeros_like(coefficients) if penalties is None else penalties
    regularization = np.diag(penalties)
    if bounds is None:
        def dual(eta):
            weights = prior * np.exp(np.clip(eta, -55, 55))
            return weights.sum(), weights, weights
    else:
        # SOURCE: Deville & Särndal (1992), calibration logit, https://doi.org/10.1080/01621459.1992.10475217
        lower, upper = np.asarray(bounds) / len(prior)
        clipped = np.clip(prior, lower + 1e-3 / len(prior), upper - 1e-3 / len(prior))
        offset = np.log((clipped - lower) / (upper - clipped))

        def dual(eta):
            logit = eta + offset
            sigmoid = np.exp(-np.logaddexp(0, -logit))
            potential = (lower * eta + (upper - lower) * np.logaddexp(0, logit)).sum()
            return potential, lower + (upper - lower) * sigmoid, (upper - lower) * sigmoid * (1 - sigmoid)

    for _ in range(65):
        potential, weights, derivative = dual(matrix @ coefficients)
        gradient = matrix.T @ weights - target + penalties * coefficients
        # Les résidus portent sur des masses normalisées. Au-delà de cette
        # précision, la recherche linéaire peut buter sur l'arrondi du dual.
        if np.max(np.abs(gradient)) < 1e-7:
            return weights * initial.sum()
        curvature = matrix.T @ (matrix * derivative[:, None]) + regularization
        direction = np.linalg.lstsq(curvature, gradient, rcond=1e-11)[0]
        objective = potential - target @ coefficients + (penalties * coefficients) @ coefficients / 2
        factor = 1.0
        while factor > 1e-8:
            candidate = coefficients - factor * direction
            candidate_potential, _, _ = dual(matrix @ candidate)
            if candidate_potential - target @ candidate + (penalties * candidate) @ candidate / 2 < objective:
                coefficients = candidate
                break
            factor /= 2
        else:
            break
    indexes = np.argsort(np.abs(gradient))[-3:][::-1]
    details = ", ".join(f"marge {i}: {gradient[i]:+.3g}" for i in indexes)
    raise ValueError(f"Marges fiscales incompatibles avec le support simulé : {details}")


def _tax_features(records, tax, bands, status_targets, target_population, ircom):
    initial = records["poids"].to_numpy()
    features = [np.ones(records.height), (records["adultes"] + records["enfants"]).to_numpy()]
    targets = [initial.sum(), target_population]
    # Les marges d'âge et d'activité de la personne de référence sont des
    # approximations au stade IPF. Le calage fiscal préserve les marges
    # observées de structure et de logement.
    for column in ("structure", "logement"):
        values = records[column].to_numpy()
        for category in sorted(set(values))[:-1]:
            feature = (values == category).astype(float)
            features.append(feature)
            targets.append(initial @ feature)
    households = _household_positions(records, tax)
    status_column = tax["statut_marital"].to_numpy()
    for status, target in status_targets.items():
        if status == "celibataire":
            continue  # Cette marge est déterminée par les autres et le total fiscal.
        features.append(np.bincount(households[status_column == status], minlength=records.height))
        targets.append(target)
    rfr_groups = np.searchsorted(bands["rfr_max"].drop_nulls().to_list(), tax["rfr_eur"].to_numpy(), side="left")
    for index, target in enumerate(bands["foyers_fiscaux"]):
        feature = np.bincount(households[rfr_groups == index], minlength=records.height)
        features.append(feature)
        targets.append(target)
    # SOURCE: DGFiP IRCOM, colonnes « traitements et salaires » et « retraites et pensions ».
    for measure in ("salaires_declares_eur", "pensions_declarees_eur"):
        features.append(np.bincount(households, weights=tax[measure].to_numpy(), minlength=records.height))
        targets.append(ircom[measure])
    return np.column_stack(features), np.asarray(targets)


def _household_positions(records, tax):
    positions = {identifier: index for index, identifier in enumerate(records["menage_id"])}
    if len(positions) != records.height:
        raise ValueError("Les identifiants de ménage doivent être uniques")
    return np.fromiter((positions[identifier] for identifier in tax["menage_id"]), dtype=np.intp, count=tax.height)


def _ircom_features(records, tax, bands):
    positions = _household_positions(records, tax)
    rfr = tax["rfr_eur"].to_numpy()
    rfr_groups = np.searchsorted(bands["rfr_max"].drop_nulls(), rfr, side="left")
    features, targets = [], []

    def add(selected, values, target):
        features.append(np.bincount(positions[selected], weights=values[selected], minlength=records.height))
        targets.append(target)

    measures = {
        "rfr_eur": rfr, "foyers_imposes": tax["impose"].to_numpy(), "impot_net_eur": tax["impot_net_eur"].to_numpy(),
        "salaires_declares_eur": tax["salaires_declares_eur"].to_numpy(),
        "pensions_declarees_eur": tax["pensions_declarees_eur"].to_numpy(),
    }
    for index, band in enumerate(bands.iter_rows(named=True)):
        for key, values in measures.items():
            add(rfr_groups == index, values, band[key])
    return np.column_stack(features), np.asarray(targets)


def _capital_tail_multiplier(tail, national_foyers, ranks):
    # SOURCE: DGFiP IRCOM, tranches nationales supérieures à 100 000 €.
    # Ajuste une loi de Pareto sur la survie observée aux bornes des tranches.
    frequencies = tail["foyers_fiscaux"].to_numpy()
    survival = np.cumsum(frequencies[::-1])[::-1]
    thresholds = np.r_[100_000, tail["rfr_max"].drop_nulls().to_numpy()]
    log_thresholds = np.log(thresholds / thresholds[0])
    log_survival = np.log(survival / survival[0])
    pareto_shape = -float(log_thresholds @ log_survival / (log_thresholds @ log_thresholds))
    rank_survival = np.maximum(1 - ranks, 1 / national_foyers)
    tail_rank = np.maximum(survival[0] / national_foyers / rank_survival, 1)
    return tail_rank ** (1 / pareto_shape)


def _enrich_tail(records, tax, tail, national_foyers, rate, generator):
    # Plan d'échantillonnage synthétique: 200 profils extrêmes sur 10 000.
    # On réserve le support parmi les déclarants principaux déjà aisés.
    count = 200
    heads = tax.filter(pl.col("foyer_fiscal_id").str.ends_with("_f0")).with_columns(
        (pl.col("rfr_eur") / pl.col("parts_fiscales")).alias("rfr_par_part")
    ).sort("rfr_par_part", descending=True).head(count * 6)
    positions = _household_positions(records, heads)
    sampled = generator.choice(heads.height, count, replace=False)
    # SOURCE: IRCOM national, seuil de début de queue 100 000 €, appliqué ici
    # par part pour sur-échantillonner les foyers extrêmes.
    survival = tail["foyers_fiscaux"].sum() / national_foyers
    ranks = 1 - survival * ((np.arange(count) + 0.5) / count)
    rfr_targets = 100_000 * _capital_tail_multiplier(tail, national_foyers, ranks)
    cases = records["cases_fiscales"].to_list()
    reserved = np.zeros(records.height, dtype=bool)
    for i, target in zip(sampled, rfr_targets):
        position = positions[i]
        case = cases[position][0]
        # Les RICI de ce profil restent celles imputées à partir du 2042.
        case["f2dc"] = max(0, round(target * heads["parts_fiscales"][int(i)] - heads["rfr_eur"][int(i)]
                                    - sum(case[key] for key in ("f2tr", "f2zz", "f4ba", "f3vg"))))
        case["f2op"] = 0
        case["f2ck"] = round(rate * (case["f2dc"] + case["f2tr"] + case["f2zz"]))
        reserved[position] = True
    return records.with_columns(pl.Series("cases_fiscales", cases), pl.Series("support_pareto", reserved))


def _impute_expenses(records, tax, declarations, national_foyers, target_foyers, generator, *, pfu_rate=None):
    rows = records.to_dicts()
    mapping = {**EXPENSES, **QUOTIENT_BOXES, **CAPITAL_AND_PROFITS, **UPPER_RICI}
    if pfu_rate is not None:
        mapping["f2op"] = "2OP"
        mapping["f2ck"] = "2CK"
    identifiers = tax["foyer_fiscal_id"].to_list()
    head_indexes = [int(identifier.rsplit("_f", 1)[1]) for identifier in identifiers]
    positions = _household_positions(records, tax)
    common_statuses = tax["imposition_commune"].to_list()
    selected_by_foyer = [dict.fromkeys(mapping, 0) for _ in identifiers]
    rank = tax["rfr_eur"].rank(method="average").to_numpy() / tax.height
    weights = records["poids"].to_numpy()[positions]
    rfr = tax["rfr_eur"].to_numpy()
    scale = target_foyers / national_foyers
    income_order = np.argsort(rfr, kind="stable")
    weighted_rank = np.zeros(tax.height)
    weighted_rank[income_order] = (weights[income_order].cumsum() - weights[income_order] / 2) / weights.sum()
    for variable, case in mapping.items():
        if case not in declarations:
            continue
        source = declarations[case]
        if variable == "f2ck":
            for cases in selected_by_foyer:
                cases[variable] = round(pfu_rate * (cases["f2dc"] + cases["f2tr"] + cases["f2zz"]))
            continue
        eligible = np.ones(tax.height, dtype=bool)
        for i, (position, index, common) in enumerate(zip(positions, head_indexes, common_statuses)):
            row = rows[position]
            head = index == 0
            children = row["enfants"] - row["cohabitants_fiscaux"]
            if variable in {"f7ga", "f7gb", "f7gc"}:
                eligible[i] = head and children >= "abc".index(variable[-1]) + 1 and row["age_enfant_impute"] < 6
            if variable in {"f7ea", "f7ec"}:
                school_ages = range(11, 15) if variable == "f7ea" else range(15, 18)
                eligible[i] = head and children > 0 and row["age_enfant_impute"] in school_ages
            if variable == "caseL":
                eligible[i] = not common and head and children == 0 and row["age_reference"] >= 50
            if variable == "caseF":
                eligible[i] = common
            if variable.endswith("_partenaire"):
                eligible[i] = common
            if variable.startswith(("f6ns", "f6rs")):
                eligible[i] &= row["age_reference"] < 65 and rfr[i] > 0
            if variable == "f7dr":
                eligible[i] = selected_by_foyer[i]["f7db"] > 0
            if variable == "f4bb":
                eligible[i] = selected_by_foyer[i]["f4ba"] == 0
            if variable in CAPITAL_AND_PROFITS or variable in UPPER_RICI:
                eligible[i] &= index < (1 if common else row.get("adultes", 1))
            if variable == "f8tk":
                eligible[i] &= row.get("activite") in {"salarie_cadre", "salarie_non_cadre", "chomeur", "retraite"} and rfr[i] > 0
            if variable == "f2op":
                cases = selected_by_foyer[i]
                eligible[i] = tax["tmi"][i] <= pfu_rate and any(cases[name] > 0 for name in ("f2dc", "f2tr", "f2zz", "f3vg"))
        available = np.flatnonzero(eligible)
        if not len(available) or source["nombre"] <= 0:
            continue
        # Imputation synthétique : stratification probabiliste par rang de RFR.
        # Le 2042 national publie une marge par case, sans croisement par tranche.
        rank_weight = 1 + rank[available]
        if variable in CAPITAL_AND_PROFITS or variable in UPPER_RICI:
            # Hypothèse d'imputation de concentration, distincte de la règle fiscale.
            rank_weight = (0.05 + weighted_rank[available]) ** 4
        priority = -np.log(generator.uniform(np.finfo(float).tiny, 1, size=len(available))) / rank_weight
        ordered = available[np.argsort(priority)]
        cumulative = weights[ordered].cumsum()
        limit = min(len(ordered), np.searchsorted(cumulative, source["nombre"] * scale) + 1)
        chosen = ordered[:limit]
        if variable in QUOTIENT_BOXES or variable == "f2op":
            amounts = np.ones(len(chosen), dtype=int)
        else:
            amounts = np.full(len(chosen), round(source["montant"] * scale / weights[chosen].sum()), dtype=int)
        for index, amount in zip(chosen, amounts):
            cases = selected_by_foyer[index]
            if variable == "f7dr":
                amount = min(amount, cases["f7db"])
            if variable == "f8tk":
                amount = min(amount, tax["salaires_declares_eur"][int(index)] + tax["pensions_declarees_eur"][int(index)])
            cases[variable] = int(amount)
    by_household = [[] for _ in rows]
    for position, index, cases in zip(positions, head_indexes, selected_by_foyer):
        by_household[position].append((index, cases))
    cases_by_household = []
    for group in by_household:
        ordered = sorted(group, key=lambda item: item[0])
        if [index for index, _ in ordered] != list(range(len(ordered))):
            raise ValueError("Les indices de foyers fiscaux doivent être contigus dans chaque ménage")
        cases_by_household.append([cases for _, cases in ordered])
    return records.with_columns(pl.Series("cases_fiscales", cases_by_household))


def calibrate_fiscal_population(records: pl.DataFrame, raw_dir: Path, census: dict, year: int, generator) -> pl.DataFrame:
    from engine.synthetic.audit_macro import calculate_tax

    declarations = read_2042(raw_dir, year)
    ircom = read_ircom(raw_dir, year)
    bands = read_ircom_bands(raw_dir, year)
    target_foyers = ircom["foyers_fiscaux"]
    national_foyers = sum(declarations[key]["nombre"] for key in FAMILY_CASES.values())
    status_targets = {status: declarations[key]["nombre"] * target_foyers / national_foyers for status, key in FAMILY_CASES.items()}
    initial = records["poids"].to_numpy()
    people = records["adultes"].to_numpy()
    children = records["enfants"].to_numpy()
    current_foyers = initial @ (people - records["imposition_commune"].to_numpy())
    household_gap = max(0.0, target_foyers - current_foyers)
    # Le résidu de rapprochement des unités est affecté aux cohabitants adultes
    # des ménages à enfants. Il n'est pas une observation statistique d'âge.
    child_population = initial @ children
    share = min(1.0, household_gap / child_population) if child_population else 0.0
    autonomous = generator.binomial(children, share)
    statuses = []
    for position, row in enumerate(records.iter_rows(named=True)):
        if row["imposition_commune"]:
            pacs_share = status_targets["pacse"] / (status_targets["marie"] + status_targets["pacse"])
            head_status = ["pacse" if generator.random() < pacs_share else "marie"]
        elif row["structure"] in {"couple", "couple_enfants", "colocation"}:
            head_status = ["celibataire"] * row["adultes"]
        else:
            # Hypothèse de support : le veuvage est imputé aux adultes mûrs
            # vivant sans conjoint. Les effectifs viennent du 2042 national.
            choices = ["celibataire", "divorce"]
            if row["age_reference"] >= 50:
                choices.append("veuf")
            counts = np.array([status_targets[key] for key in choices])
            head_status = [str(generator.choice(choices, p=counts / counts.sum()))]
        statuses.append(head_status + ["celibataire"] * autonomous[position])
    # SOURCE: IRCOM, tranche la plus basse ; revenu moyen du premier groupe,
    # utilisé comme proxy de rattachement en l'absence de croisement public.
    young_income = bands["rfr_eur"][0] / bands["foyers_fiscaux"][0]
    household_income = records["revenu_declare_moyen"].to_numpy()
    estimated = np.minimum(young_income, household_income / (people + autonomous))
    records = records.with_columns(
        pl.Series("cohabitants_fiscaux", autonomous),
        pl.Series("revenu_cohabitant_eur", estimated),
        pl.Series("age_enfant_impute", generator.integers(0, 18, size=records.height)),
        pl.Series("situations_fiscales", statuses),
        pl.lit(year).alias("annee_calage"),
    )
    system = get_tax_benefit_system()
    tax, _ = calculate_tax(records, system, str(year))
    features, targets = _tax_features(records, tax, bands, status_targets, census["population_des_menages"], ircom)
    # Ratio maximal de 9. Pour des poids dans [a,b], Kish >= n*4ab/(a+b)^2.
    bounds = (0.22, 1.98)
    penalties = np.full(features.shape[1], 0.002)
    penalties[0] = 0
    records = records.with_columns(pl.Series("poids", calibrate_moments(initial, features, targets, penalties, bounds=bounds)))
    tail = read_ircom_tail(raw_dir, year)
    pfu = system.parameters(str(year)).taxation_capital.prelevement_forfaitaire.partir_2018
    rate = pfu.taux_prelevement_forfaitaire_rev_capital_eligibles_pfu_interets_dividendes_etc
    records = _impute_expenses(records, tax, declarations, national_foyers, target_foyers, generator, pfu_rate=rate)
    records = _enrich_tail(records, tax, tail, national_foyers, rate, generator)
    tax_after, _ = calculate_tax(records, system, str(year))
    # Les charges déductibles peuvent déplacer des foyers de tranche de RFR.
    # Le calage final conserve les marges démographiques et utilise le RFR recalculé.
    features, targets = _tax_features(records, tax_after, bands, status_targets, census["population_des_menages"], ircom)
    detail, detail_targets = _ircom_features(records, tax_after, bands)
    positions = _household_positions(records, tax_after)
    outcome_names = ("foyers_fiscaux", "rfr_eur", "foyers_imposes", "impot_net_eur")
    outcomes = np.column_stack([
        np.bincount(positions, weights=values, minlength=records.height)
        for values in (None, tax_after["rfr_eur"].to_numpy(), tax_after["impose"].to_numpy(), tax_after["impot_net_eur"].to_numpy())
    ])
    outcome_targets = np.array([ircom[name] for name in outcome_names])
    shared = np.column_stack((features, detail, outcomes[:, :-1]))
    shared_targets = np.r_[targets, detail_targets, outcome_targets[:-1]]
    shared_penalties = np.r_[penalties, np.full(detail.shape[1], 0.001), 0, 0.0001, 0.001]
    before = calibrate_moments(initial, shared, shared_targets, shared_penalties, bounds=bounds)
    # L'IR reste libre dans un intervalle de ±2,5 %. Sinon, on vise la borne
    # atteignable la plus proche de l'estimation sans contrainte nationale d'IR.
    observed_ir = before @ outcomes[:, -1]
    ir_target = np.clip(observed_ir, 0.975 * outcome_targets[-1], 1.025 * outcome_targets[-1])
    final = before if observed_ir == ir_target else calibrate_moments(
        initial, np.column_stack((shared, outcomes[:, -1])), np.r_[shared_targets, ir_target],
        np.r_[shared_penalties, 0], bounds=bounds,
    )
    return records.with_columns(
        pl.Series("poids_avant_calage_resultats", before),
        pl.Series("poids", final),
    )
