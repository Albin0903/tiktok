"""Télécharge les fichiers officiels utilisés par France Synthétique."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import file_digest
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from zipfile import is_zipfile

import httpx


RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"


@dataclass(frozen=True)
class Source:
    filename: str
    producer: str
    dataset: str
    reference: str
    url: str


SOURCES = (
    Source(
        "rp2023_metropole.html", "INSEE", "Recensement 2023 – dossier France métropolitaine",
        "https://www.insee.fr/fr/statistiques/2011101?geo=METRO-1",
        "https://www.insee.fr/fr/statistiques/2011101?geo=METRO-1",
    ),
    Source(
        "erfs2023_deciles.zip", "INSEE / DGFiP", "ERFS 2023 – revenus des ménages par décile",
        "https://www.insee.fr/fr/statistiques/8731692",
        "https://www.insee.fr/fr/statistiques/fichier/8731692/irsocerfs2023_dd1_bis_excel.zip",
    ),
    Source(
        "ircom2024_revenus2023.zip", "DGFiP", "IRCOM 2024 – revenus 2023",
        "https://www.data.gouv.fr/datasets/limpot-sur-le-revenu-par-collectivite-territoriale-ircom",
        "https://static.data.gouv.fr/resources/limpot-sur-le-revenu-par-collectivite-territoriale-ircom/20250919-135242/ircom-2024-revenus-2023.zip",
    ),
    Source(
        "ircom2025_revenus2024.zip", "DGFiP", "IRCOM 2025 – revenus 2024",
        "https://www.data.gouv.fr/datasets/limpot-sur-le-revenu-par-collectivite-territoriale-ircom",
        "https://static.data.gouv.fr/resources/limpot-sur-le-revenu-par-collectivite-territoriale-ircom/20260526-131537/ircom-2025-revenus-2024.zip",
    ),
    Source(
        "2042_nat_2023_2024.csv", "DGFiP", "Déclarations nationales 2042 – revenus 2023 et 2024",
        "https://data.economie.gouv.fr/explore/dataset/ir-declarations-2042-nat/",
        "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/ir-declarations-2042-nat/exports/csv?where=year%28annee%29%3D2023%20or%20year%28annee%29%3D2024",
    ),
    Source(
        "bdf2017_tf106.csv", "INSEE", "Budget de famille 2017 – dépenses par décile (TF106)",
        "https://www.insee.fr/fr/statistiques/4648335",
        "https://www.insee.fr/fr/statistiques/fichier/4648335/TF106.csv",
    ),
    Source(
        "bdf2017_tf206.csv", "INSEE", "Budget de famille 2017 – structure des dépenses par décile (TF206)",
        "https://www.insee.fr/fr/statistiques/4648335",
        "https://www.insee.fr/fr/statistiques/fichier/4648335/TF206.csv",
    ),
    Source(
        "tes_symetrique_a38_2022.xlsx", "INSEE", "TES symétrique A38 2022, base 2020",
        "https://www.insee.fr/fr/statistiques/8068640?sommaire=8068749",
        "https://www.insee.fr/fr/statistiques/fichier/8068640/TES_symetrique_A38_2022SD.xlsx",
    ),
)


def _validate(path: Path, source: Source) -> None:
    suffix = Path(source.filename).suffix
    if suffix in {".zip", ".xlsx"}:
        if not is_zipfile(path):
            raise ValueError("contenu ZIP/XLSX illisible")
        return

    if suffix == ".html":
        body = path.read_text(encoding="utf-8")
        if "France métropolitaine" in body and 'id="produit-tableau-POP_T1"' in body:
            return
        raise ValueError("le dossier INSEE ne contient pas les tableaux métropolitains attendus")
    with path.open("rb") as stream:
        header = stream.read(16384)
    if source.filename == "2042_nat_2023_2024.csv" and b"annee;libelle;nom;nombre;montant" in header:
        return
    if suffix == ".csv" and b"NOMENCLATURE" in header and b"DECUC" in header:
        return
    raise ValueError("en-tête inattendu pour cette source")


def _download(client: httpx.Client, source: Source, target: Path) -> None:
    with NamedTemporaryFile(dir=target.parent, delete=False) as stream:
        temporary = Path(stream.name)
    try:
        with client.stream("GET", source.url) as response:
            response.raise_for_status()
            with temporary.open("wb") as stream:
                for chunk in response.iter_bytes():
                    stream.write(chunk)
        _validate(temporary, source)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def fetch_official_data(raw_dir: Path = RAW_DIR, *, refresh: bool = False) -> list[dict]:
    """Actualise le manifeste et conserve les fichiers valides en cas d'échec réseau."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    with httpx.Client(follow_redirects=True, timeout=60) as client:
        for source in SOURCES:
            target = raw_dir / source.filename
            entry = asdict(source)
            try:
                _validate(target, source)
            except (OSError, ValueError):
                status = "missing"
            else:
                status = "cached"

            if refresh or status == "missing":
                try:
                    _download(client, source, target)
                except (httpx.HTTPError, OSError, ValueError) as error:
                    entry["error"] = str(error)
                    if status == "cached":
                        status = "cached_after_error"
                else:
                    status = "downloaded"

            entry["status"] = status
            if status != "missing":
                with target.open("rb") as stream:
                    entry["sha256"] = file_digest(stream, "sha256").hexdigest()
                entry["bytes"] = target.stat().st_size
            manifest.append(entry)

    report = {"checked_at_utc": datetime.now(timezone.utc).isoformat(), "sources": manifest}
    path = raw_dir / "manifest.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    manifest = fetch_official_data(args.raw_dir, refresh=args.refresh)
    for entry in manifest:
        print(f"{entry['filename']}: {entry['status']}")
        if "error" in entry:
            print(f"  {entry['error']}")
    return int(any(entry["status"] == "missing" for entry in manifest))


if __name__ == "__main__":
    raise SystemExit(main())
