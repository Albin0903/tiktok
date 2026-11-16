# 04 — Stack IA Locale RTX Spark (Windows 11 ARM64) & Répartition des Abonnements

## 1. Contrainte Matérielle RTX Spark (128 Go LPDDR5X Unifiée)

Sur une station NVIDIA RTX Spark, la bande passante de la mémoire unifiée LPDDR5X est le facteur limitant de la vitesse de génération :
- **Modèles Denses à éviter (`Qwen 3.8 27B` dense)** : activent l'ensemble des 27B paramètres à chaque token (~13,4 tok/s mesurés sur RTX Spark). Trop lents pour itérer rapidement sur des extractions JSON/PDF.
- **Modèles MoE (*Mixture of Experts*) à privilégier** : n'activent qu'une fraction des paramètres par token (~3B à 9B actifs), multipliant par 3× à 4× le débit en tokens/s tout en conservant la qualité d'un grand modèle.
- **Réglage BIOS / Panneau NVIDIA recommandé** : allouer **64 Go ou 96 Go** de mémoire GPU dédiée, en conservant **32 à 64 Go** pour Windows 11 ARM64, Antigravity, Chromium (Remotion headless) et les calculs Polars/DuckDB.

---

## 2. Inventaire des Modèles & Binaires sur la Station

Les éléments suivants ont été vérifiés sur la station lors de l'initialisation Phase 1 :

| Rôle | Modèle / Binaire | Statut local | Chemin / Endpoint |
| :--- | :--- | :--- | :--- |
| **Serveur d'inférence natif ARM64** | `llama-server.exe` (`llama.cpp` v0.8.0-dev build 12079, Clang 20.1.8 Win-ARM64) | Présent | `C:\llama.cpp\llama-server.exe` |
| **Moteur rapide JSON / Tool-calling** | `unsloth/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-GGUF` (`UD-Q4_K_XL`, 3B actifs) | Présent en cache HF | `http://127.0.0.1:8081/v1` |
| **Moteur Vision / PDF complexes (VLM MoE)** | `unsloth/Qwen3.8-Flash-Next-GGUF` (`UD-IQ4_XS` + `mmproj-BF16.gguf`) — *alternative optionnelle : `NVIDIA-Nemotron-3.5-Bolt-74B-A9B` GGUF corrigé `tekken`* | `Qwen3.8-Flash-Next` présent en cache HF | `http://127.0.0.1:8081/v1` (ou `vllm-for-rtx-spark` si 96 Go GPU) |
| **Moteur RAG & Mapping OpenFisca** | `EmbeddingGemma 2` (270M texte+code, Matryoshka 768d→256d, ctx 8K) | Poids safetensors présents (`C:\AI\jarvis\models\embeddinggemma-2`) ; poids **GGUF Q8_0 / BF16** (`ggml-org/embeddinggemma-2-GGUF`) à placer si lancement via `llama-server` sur `:8082` | `http://127.0.0.1:8082/v1` |
| **Encodage vidéo ARM64** | `ffmpeg.exe` (n8.1 `winarm64-gpl-shared`) | Présent | `C:\AI\jarvis\ffmpeg\ffmpeg-n8.1-latest-winarm64-gpl-shared-8.1\bin\ffmpeg.exe` |

> **RÈGLE CRITIQUE SUR `EmbeddingGemma 2` :** ne **JAMAIS** lancer `EmbeddingGemma 2` avec `--cache-type-k f16` / `--cache-type-v f16` ou un quant `FP16` sous `llama-server` (risque de valeurs `NaN` dans les vecteurs). Utiliser exclusivement **`Q8_0`** ou **`BF16`**. Le script `scripts/windows/start_local_ai.ps1` bloque explicitement `FP16` pour l'endpoint d'embeddings.

---

## 3. Commandes PowerShell d'Exploitation (`llama-server.exe`)

### Vérifier l'environnement et les modèles détectés
```powershell
.\scripts\windows\start_local_ai.ps1 -Mode Check
```

### Lancer le serveur LLM sur le port `8081` (`Nemotron-3.5-Lightning-30B-A3B`)
```powershell
.\scripts\windows\start_local_ai.ps1 -Mode StartLLM -LlmAlias nemotron -LlmPort 8081
```
*(Ou `-LlmAlias flash-next` pour basculer sur `Qwen3.8-Flash-Next` avec projecteur multimodal `mmproj-BF16.gguf`.)*

### Lancer le serveur Embeddings sur le port `8082` (`EmbeddingGemma 2` GGUF Q8_0/BF16)
```powershell
.\scripts\windows\start_local_ai.ps1 -Mode StartEmbedding -EmbeddingModelPath "C:\AI\models\embeddinggemma-2-Q8_0.gguf" -EmbeddingPort 8082
```
La commande exécutée en interne par le script pour `8082` active `--embeddings`, `--pooling mean` (ou config modèle), `-ngl 999`, `--ctx-size 8192` et `--cache-type-k q8_0 --cache-type-v q8_0`.

> **Note sur le routeur existant (`C:\llama.cpp\rtx-spark-models.ini`) :** un routeur sur le port `9931` peut déjà exister sur le poste (`start_models_router.ps1`). Le script `start_local_ai.ps1` du projet cible les ports dédiés `8081` (LLM) et `8082` (Embeddings) pour éviter tout conflit avec Jarvis/MCP.

---

## 4. Répartition Zéro-Chevauchement des 3 Abonnements

| Abonnement | Outil / Modèle | Rôle strict dans le projet |
| :--- | :--- | :--- |
| **Google AI Pro** | **Antigravity (`Orchestrator Argon` + `Hydrogen`)** | Architecte et développeur principal du monorepo (`engine/`, `parser/`, `api/`, `web/`, `video/`), installation `uv`/`win_arm64` et validation `pytest`. |
| **ChatGPT / Codex Plus** | **Codex CLI (`codex review`)** | Auditeur indépendant (« Commissaire aux comptes ») lancé après chaque réforme OpenFisca pour croiser deux familles de modèles et détecter les bugs fiscaux silencieux. |
| **Google Colab Pro** | **Notebooks GPU A100/L4 (`scripts/colab/`)** | Usine lourde ponctuelle : OCR massif (`Marker v2` / `MinerU 4.0`) sur annexes budgétaires de 1 000+ pages, indexation massive ou rendus batch. *Jamais utilisé pour OpenFisca.* |
