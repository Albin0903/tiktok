# VeriteFiscale-2027

**Plateforme open-source et média data-driven français de micro-simulation socio-fiscale et budgétaire (PLF/PLFSS 2027 & Présidentielle 2027).**

> **Principe fondateur (Règle Zéro Hallucination) :** Aucun LLM ne calcule d'impôts, de cotisations, de prestations ou d'effets macroéconomiques. Tout chiffrage repose exclusivement sur le moteur déterministe [`OpenFisca-France`](https://github.com/openfisca/openfisca-france), une population synthétique calée sur les données publiques INSEE/DGFiP (`france_synthetique.parquet`) et un module matriciel transparent de second tour basé sur le TES INSEE.

---

## Architecture du Monorepo

```text
verite-fiscale-2027/
├── README.md                  # Présentation, philosophie open-source et guide Windows 11 ARM64
├── AGENTS.md                  # Règles strictes pour Antigravity, Codex CLI (/review) et agents locaux
├── DESIGN.md                  # Direction Artistique ("Comptable Punk / Ticket de Caisse 2027")
├── docs/                      # Documentation technique, sources publiques, méthodologie & roadmap
├── scripts/
│   ├── windows/               # Lancement llama-server (8081/8082) & revue croisée Codex
│   └── colab/                 # Notebooks Colab Pro (OCR lourd Marker v2 / MinerU 4.0)
├── data/
│   ├── raw/                   # Données brutes INSEE / DGFiP / OpenData AN (ignorées par git)
│   ├── processed/             # france_synthetique.parquet, index OpenFisca EmbeddingGemma 2
│   └── programs/              # Programmes politiques, annexes PLF/PLFSS et mesures extraites JSON
├── engine/                    # Cœur déterministe Python (uv) : réformes OpenFisca, IPF, TES & pytest
├── parser/                    # Extraction sourcée Docling + LLM local MoE + RAG OpenFisca
├── api/                       # Backend FastAPI (< 50 ms / ménage) [Phase 2/3]
├── web/                       # Simulateur citoyen Next.js + Tailwind + Visx [Phase 2/3]
└── video/                     # Générateur vidéo 9:16 Remotion + Canvas2D 60fps [Phase 2/3]
```

---

## Prérequis & Environnement Windows 11 ARM64 (Natif)

Ce dépôt est conçu pour fonctionner **nativement sur Windows 11 on ARM (`ARM64` / `win_arm64`)** sur station NVIDIA RTX Spark (128 Go RAM unifiée), **sans WSL2 ni Docker Linux par défaut**.

| Outil | Rôle | Version / Binaire vérifié |
| :--- | :--- | :--- |
| **`uv`** | Gestionnaire Python & environnements virtuels | `uv >= 0.13` (`aarch64-pc-windows-msvc`) |
| **Python ARM64** | Exécution moteur `engine/` & `parser/` | `cpython-3.13-windows-aarch64-none` (`.python-version`) |
| **Node.js ARM64** | Frontend `web/` et rendu `video/` Remotion | `v26.x` natif ARM64 |
| **`llama-server.exe`** | Inférence locale MoE + Embeddings (`8081` / `8082`) | `C:\llama.cpp\llama-server.exe` |
| **`ffmpeg.exe`** | Encodage vidéo 1080x1920 60fps | Build natif `winarm64` |
| **Codex CLI** | Double audit indépendant des réformes (`codex review`) | `codex` dans le terminal Windows |

### Spécificités techniques Windows ARM64 (à connaître)
1. **Pas de `pyarrow` sur `win_arm64`** : Apache Arrow ne publie pas de wheel binaire `win_arm64`. Toutes les lectures/écritures `.parquet` utilisent nativement **`polars`** (Rust) et **`duckdb`** (C++).
2. **Pas de `openfisca-france-indirect-taxation` depuis PyPI** : le paquet PyPI (`0.4.dev0`) est une archive Python 2 obsolète. La fiscalité indirecte (TVA par poste COICOP, accises carburant/énergie) est implémentée dans `engine/second_round/`.
3. **Chemins longs Windows (`MAX_PATH` 260 car.)** : certains fichiers YAML d'OpenFisca-France (allocations logement) dépassent 260 caractères dans le cache `uv`/`.venv`. Le helper `engine.reforms.get_tax_benefit_system()` préfixe automatiquement `COUNTRY_DIR` avec `\\?\`.
4. **Récursion CSG / RFR $N-2$** : toute simulation OpenFisca calcule `rfr(N-2)` avec `sim.max_spiral_loops = 3` pour éviter que `csg_deductible_retraite` ne retombe à zéro lors d'un appel direct sur `impot_revenu_restant_a_payer`.

---

## Démarrage Rapide (Phase 1)

### 1. Installer et tester le moteur déterministe `engine/`
```powershell
cd engine
uv sync --python cpython-3.13-windows-aarch64-none
uv run pytest -v
uv run python reforms/demo_plf2027_retraites.py
```

### 2. Vérifier l'IA locale (`llama-server.exe` + modèles MoE)
```powershell
.\scripts\windows\start_local_ai.ps1 -Mode Check
```
Pour lancer le serveur LLM (`8081`) ou Embeddings (`8082`, `EmbeddingGemma 2` en `Q8_0`/`BF16`) :
```powershell
.\scripts\windows\start_local_ai.ps1 -Mode StartLLM -LlmAlias nemotron
# Dans un second terminal (si serveur d'embeddings GGUF configuré) :
.\scripts\windows\start_local_ai.ps1 -Mode StartEmbedding
```

### 3. Indexer les variables `OpenFisca-France` (RAG)
```powershell
cd engine
uv run python ..\parser\index_openfisca_docs.py --dry-run --limit 50
# Avec le serveur d'embeddings actif sur 127.0.0.1:8082 :
uv run python ..\parser\index_openfisca_docs.py
```

### 4. Double audit croisé avec Codex CLI
```powershell
.\scripts\windows\run_codex_review.ps1 -TargetFile engine/reforms/demo_plf2027_retraites.py
```

---

## Licence & Transparence

- Le moteur `OpenFisca-France` est distribué sous licence **AGPL-3.0** ; toutes les réformes et formules dérivées publiées dans `engine/` respectent les obligations de partage de la licence AGPL-3.0.
- Chaque constante économique, barème ou élasticité est accompagné d'un commentaire `# SOURCE: <Organisme, Année, URL/Page>`.
- Les simulations constituent des évaluations *ex-ante* indépendantes à visée d'information citoyenne et ne se substituent pas au simulateur officiel de la DGFiP (`impots.gouv.fr`).
