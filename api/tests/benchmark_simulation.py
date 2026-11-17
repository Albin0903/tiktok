"""Mesure locale du POST sur des profils distincts avec OpenFisca préchauffé."""

import json
from statistics import mean, median
from time import perf_counter

from fastapi.testclient import TestClient

from api.main import create_app


def main() -> None:
    profiles = (
        ("salarie_non_cadre", 35, 1400, 2), ("salarie_cadre", 48, 4700, 2),
        ("independant", 40, 1850, 1), ("retraite", 70, 1650, 0),
        ("chomeur", 37, 1000, 1), ("inactif", 24, 0, 0),
    )
    results = {}
    with TestClient(create_app()) as client:
        for status, age, income, children in profiles:
            profile = dict(statut=status, age=age, revenu_net_imposable_mensuel=income, enfants=children)
            client.post("/api/simulate", json=profile).raise_for_status()
            timings = []
            for offset in range(1, 8):
                sample = {**profile, "age": age + offset, "revenu_net_imposable_mensuel": income + offset if income else 0}
                start = perf_counter()
                client.post("/api/simulate", json=sample).raise_for_status()
                timings.append(1000 * (perf_counter() - start))
            results[status] = {"moyenne_ms": round(mean(timings), 1), "mediane_ms": round(median(timings), 1),
                               "max_ms": round(max(timings), 1), "requetes": len(timings)}
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
