"""Prépare le JSON local du lecteur à partir des exports du moteur."""

import json
from pathlib import Path

import polars as pl


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"
TARGET = ROOT / "video" / "out" / "video-data.json"


def main():
    summary = json.loads((DATA / "sim_plf2027_summary.json").read_text(encoding="utf-8"))
    details = pl.read_parquet(DATA / "sim_plf2027_10k.parquet")
    points = details.select("decile", "gain_ir_eur").rows()
    profiles = [
        ("Salarié seul", "seul", "salarie_non_cadre", False),
        ("Couple avec enfants", "couple_enfants", "salarie_cadre", False),
        ("Retraité seul", "seul", "retraite", True),
    ]
    cases = []
    for label, family, job, loses in profiles:
        candidates = details.filter(
            (pl.col("structure") == family)
            & (pl.col("activite") == job)
            & (pl.col("gain_ir_eur") < 0 if loses else pl.col("gain_ir_eur") > 0)
        ).sort("gain_ir_eur")
        if candidates.is_empty():
            raise ValueError(f"Aucun cas expérimental disponible pour {label}")
        row = candidates.row(candidates.height // 2, named=True)
        cases.append({
            "label": label,
            "gel": row["ir_gel_eur"],
            "plf": row["ir_plf_eur"],
            "gain": row["gain_ir_eur"],
            "revenu": row["revenu_declare_moyen"],
        })
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(json.dumps({"summary": summary, "points": points, "cases": cases}, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
