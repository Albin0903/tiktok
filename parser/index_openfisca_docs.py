"""Indexeur RAG des variables et paramètres d'OpenFisca-France via EmbeddingGemma 2 (localhost:8082).

Usage depuis ``engine/`` (environnement uv Windows 11 ARM64) :
  - Mode dry-run (export catalogue Parquet/DuckDB sans appeler le serveur d'embeddings) :
      uv run python ../parser/index_openfisca_docs.py --dry-run --limit 50
  - Mode complet avec serveur EmbeddingGemma 2 (Q8_0/BF16) actif sur http://127.0.0.1:8082/v1 :
      uv run python ../parser/index_openfisca_docs.py

Rappel : ne jamais exécuter EmbeddingGemma 2 en FP16 (risque de NaN).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import duckdb
import httpx
import polars as pl
from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parent.parent
ENGINE_DIR = REPO_ROOT / "engine"
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from reforms import get_tax_benefit_system  # noqa: E402


class OpenFiscaDocEntry(BaseModel):
    """Entrée documentaire normalisée pour l'indexation vectorielle RAG."""

    doc_id: str
    kind: str = Field(description="'variable' ou 'parameter'")
    name: str
    entity: str = ""
    definition_period: str = ""
    label: str = ""
    reference: str = ""
    document_text: str


def extract_openfisca_catalog(limit: int | None = None, include_parameters: bool = True) -> list[OpenFiscaDocEntry]:
    """Extrait les variables (et paramètres clés) depuis OpenFisca-France installé localement."""
    tbs = get_tax_benefit_system()
    entries: list[OpenFiscaDocEntry] = []

    for var_name in sorted(tbs.variables.keys()):
        var = tbs.variables[var_name]
        entity_key = getattr(getattr(var, "entity", None), "key", "")
        period = str(getattr(var, "definition_period", ""))
        label = str(getattr(var, "label", "") or "")
        ref_raw = getattr(var, "reference", "") or ""
        reference = ", ".join(ref_raw) if isinstance(ref_raw, (list, tuple)) else str(ref_raw)

        doc_text = (
            f"[VARIABLE OpenFisca-France] nom={var_name} | entite={entity_key} | "
            f"periode={period} | libelle={label} | source={reference}"
        )
        entries.append(
            OpenFiscaDocEntry(
                doc_id=f"var:{var_name}",
                kind="variable",
                name=var_name,
                entity=entity_key,
                definition_period=period,
                label=label,
                reference=reference,
                document_text=doc_text,
            )
        )
        if limit is not None and len(entries) >= limit:
            return entries

    if include_parameters:
        for param_path, param_node in _walk_parameter_leaves(tbs.parameters):
            desc = str(getattr(param_node, "description", "") or "")
            doc_text = f"[PARAMETRE OpenFisca-France] chemin={param_path} | description={desc}"
            entries.append(
                OpenFiscaDocEntry(
                    doc_id=f"param:{param_path}",
                    kind="parameter",
                    name=param_path,
                    label=desc,
                    document_text=doc_text,
                )
            )
            if limit is not None and len(entries) >= limit:
                return entries

    return entries


def _walk_parameter_leaves(node: Any, prefix: str = "") -> list[tuple[str, Any]]:
    """Parcourt récursivement l'arbre des paramètres OpenFisca sans dépendances externes."""
    results: list[tuple[str, Any]] = []
    children = getattr(node, "children", None)
    if not children:
        if prefix:
            results.append((prefix, node))
        return results
    for key, child in sorted(children.items()):
        next_prefix = f"{prefix}.{key}" if prefix else key
        results.extend(_walk_parameter_leaves(child, next_prefix))
    return results


def fetch_embeddings(
    texts: list[str],
    base_url: str,
    model: str,
    batch_size: int = 32,
    timeout: float = 60.0,
) -> list[list[float]]:
    """Appelle l'endpoint OpenAI-compatible /v1/embeddings (EmbeddingGemma 2 Q8_0/BF16)."""
    url = base_url.rstrip("/") + "/embeddings"
    vectors: list[list[float]] = []

    with httpx.Client(timeout=timeout) as client:
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            resp = client.post(url, json={"model": model, "input": batch})
            resp.raise_for_status()
            payload = resp.json()
            data_sorted = sorted(payload["data"], key=lambda item: item["index"])
            for item in data_sorted:
                vec = item["embedding"]
                if any(v != v for v in vec):  # Vérifie NaN (protection FP16)
                    raise ValueError("Vecteur d'embedding contenant NaN détecté (vérifier que EmbeddingGemma 2 tourne en Q8_0/BF16 et non FP16).")
                vectors.append(vec)
    return vectors


def save_catalog_and_index(
    entries: list[OpenFiscaDocEntry],
    embeddings: list[list[float]] | None,
    output_dir: Path,
) -> dict[str, Path]:
    """Sauvegarde le catalogue en Parquet (via Polars natif ARM64) et en base DuckDB."""
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = [entry.model_dump() for entry in entries]
    if embeddings is not None:
        for row, vec in zip(rows, embeddings, strict=True):
            row["embedding"] = vec

    df = pl.DataFrame(rows)
    parquet_path = output_dir / "openfisca_docs_catalog.parquet"
    df.write_parquet(parquet_path)

    duckdb_path = output_dir / "openfisca_rag.duckdb"
    con = duckdb.connect(str(duckdb_path))
    try:
        con.execute("CREATE OR REPLACE TABLE openfisca_docs AS SELECT * FROM read_parquet(?)", [str(parquet_path)])
    finally:
        con.close()

    manifest_path = output_dir / "openfisca_docs_manifest.json"
    manifest = {
        "total_entries": len(entries),
        "has_embeddings": embeddings is not None,
        "embedding_dim": len(embeddings[0]) if embeddings else 0,
        "parquet_file": str(parquet_path),
        "duckdb_file": str(duckdb_path),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"parquet": parquet_path, "duckdb": duckdb_path, "manifest": manifest_path}


def main() -> int:
    parser = argparse.ArgumentParser(description="Indexation RAG des variables OpenFisca-France via EmbeddingGemma 2.")
    parser.add_argument(
        "--base-url",
        default=os.getenv("LOCAL_EMBEDDING_BASE_URL", "http://127.0.0.1:8082/v1"),
        help="URL OpenAI-compatible du serveur d'embeddings local.",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("LOCAL_EMBEDDING_MODEL", "embeddinggemma-2"),
        help="Nom du modèle exposé par llama-server.",
    )
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--limit", type=int, default=None, help="Limiter le nombre d'entrées extraites (test rapide).")
    parser.add_argument("--no-parameters", action="store_true", help="N'indexer que les variables OpenFisca.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Extrait et écrit le catalogue Parquet/DuckDB sans contacter l'endpoint :8082.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "data" / "processed",
    )
    args = parser.parse_args()

    entries = extract_openfisca_catalog(limit=args.limit, include_parameters=not args.no_parameters)
    print(f"Catalogue OpenFisca-France extrait : {len(entries)} entrées.")

    embeddings: list[list[float]] | None = None
    if not args.dry_run:
        print(f"Calcul des embeddings via {args.base_url} (modèle={args.model})...")
        embeddings = fetch_embeddings(
            [e.document_text for e in entries],
            base_url=args.base_url,
            model=args.model,
            batch_size=args.batch_size,
        )
        print(f"Embeddings calculés : {len(embeddings)} vecteurs de dimension {len(embeddings[0])}.")

    artifacts = save_catalog_and_index(entries, embeddings, args.output_dir)
    for kind, path in artifacts.items():
        print(f"Sortie [{kind}] : {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
