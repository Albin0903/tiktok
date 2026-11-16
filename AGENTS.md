# AGENTS.md — Règles Impératives d'Ingénierie & Audit (VeriteFiscale-2027)

Ce fichier s'applique à **Antigravity**, à **Codex CLI** (`codex review`) et à tout agent local (`llama-server` / MoE) intervenant sur le monorepo `verite-fiscale-2027`.

---

## 1. Contraintes Système Windows 11 ARM64 Natif (`win_arm64`)

1. **Zéro WSL2 / zéro Docker Linux par défaut** : tout le code du workspace (`engine/`, `parser/`, `api/`, `web/`, `video/`) doit s'exécuter nativement sous **Windows 11 on ARM (`aarch64-pc-windows-msvc`)** via PowerShell, `uv` (Python ARM64) et Node.js ARM64.
2. **Version Python épinglée (`win_arm64`)** : utiliser exclusivement `cpython-3.13-windows-aarch64-none` (ou `3.12` ARM64) géré par `uv` via `.python-version`. Ne jamais invoquer un Python `x86_64` émulé (ex: `C:\Python315\python.exe`).
3. **Interdiction de PyTorch / TensorFlow / vLLM dans `engine/` et `api/`** :
   - Les environnements `engine/`, `api/` et `parser/` restent légers et strictement découplés des runtimes GPU lourds.
   - Toute inférence IA locale passe par des appels HTTP standards compatibles OpenAI (`httpx` / client SDK léger) vers `llama-server.exe` (`llama.cpp` Windows ARM64 CUDA) :
     - **LLM local (MoE rapide / Vision)** : `http://127.0.0.1:8081/v1` (ou routeur local sur `9931`)
     - **Embeddings (`EmbeddingGemma 2` en `Q8_0` ou `BF16`, JAMAIS `FP16`)** : `http://127.0.0.1:8082/v1`
4. **Règle sur les paquets binaires C/C++/Rust (`win_arm64`)** :
   - Toujours vérifier l'existence d'un wheel `win_arm64` ou pur Python (`uv pip compile --only-binary :all:`) avant d'ajouter une dépendance.
   - **Interdiction d'ajouter `pyarrow`** : aucun wheel `win_arm64` n'existe sur PyPI. Utiliser **`polars`** (backend Rust natif) et **`duckdb`** (backend C++ natif) pour lire/écrire les fichiers `.parquet`.
   - **Interdiction d'installer `openfisca-france-indirect-taxation` depuis PyPI** : l'archive `0.4.dev0` est taguée `py2` et incompatible avec Python 3.13 et `openfisca-france>=170`. Implémenter la fiscalité indirecte (TVA par décile/COICOP, TICPE) en Python déterministe dans `engine/second_round/`.
   - Si une lib indispensable d'OCR/GPU n'existe pas sur `win_arm64` (ex: `marker-pdf`, `mineru`), l'isoler dans un notebook `scripts/colab/` dédié à Google Colab Pro.

---

## 2. Règles Techniques Impératives pour `OpenFisca-France` sous Windows

1. **Contournement Windows `MAX_PATH` (260 caractères)** :
   - Certains fichiers YAML de paramètres d'`openfisca-france` (notamment `prestations_sociales/aides_logement/.../saint_pierre_et_miquelon/taux_pac_supp.yaml` et `.../tf_taille_famille/metropole/personnes_isolees.yaml`) dépassent 260 caractères dans le cache `uv` ou `.venv` Windows, provoquant un `ParameterNotFoundError` au calcul de `revenu_disponible`.
   - **Obligatoire** : toujours instancier le système socio-fiscal via `engine.reforms.get_tax_benefit_system()`, qui préfixe `COUNTRY_DIR` avec `\\?\` sous Windows (`os.name == "nt"`).
2. **Boucle récursive `CSG ↔ RFR (N-2)` (`max_spiral_loops`)** :
   - `csg_deductible_retraite(N)` dépend de `rfr(N-2)`, qui dépend lui-même de `retraite_imposable(N-2)` donc de `csg_deductible_retraite(N-2)`.
   - **Obligatoire** : renseigner les revenus des profils sur la fenêtre historique `N-4 .. N` (ex: `2021..2025`) et configurer `simulation.max_spiral_loops = 3` sur chaque `Simulation`. Ne jamais laisser `max_spiral_loops = 0` sur une simulation impliquant des pensions ou allocations sous condition de ressources `N-2`.

---

## 3. Règle Zéro Hallucination & Traçabilité Scientifique

1. **Séparation stricte IA / Calcul** :
   - **INTERDICTION** de demander à un LLM (cloud ou local) de calculer un impôt, une cotisation sociale, une prestation, un taux marginal ou un effet macroéconomique.
   - Les LLM servent uniquement à :
     1. Extraire mot pour mot les propositions politiques ou amendements depuis les PDF avec numéro de page exact (`parser/`).
     2. Proposer un pré-mapping candidat vers les variables/paramètres `openfisca_france` via recherche vectorielle (`EmbeddingGemma 2`).
2. **Traçabilité obligatoire des constantes (`# SOURCE:`)** :
   - Toute constante numérique, barème législatif, seuil ou élasticité codé en dur dans `engine/` DOIT porter immédiatement au-dessus ou en bout de ligne un commentaire normalisé :
     `# SOURCE: <Organisme, Année, URL/Page>`
   - Exemple :
     `# SOURCE: DGFiP / OpenFisca-France parameters 2025 (CGI art. 158-5-a), https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000048801686`

---

## 4. Protocole Obligatoire pour Toute Nouvelle Réforme Fiscale

Avant qu'une réforme dans `engine/reforms/` soit considérée valide, l'agent doit suivre ces **4 étapes dans l'ordre** :

1. **Étape A — Inspection préalable dans `openfisca_france`** :
   - Inspecter le code source réel et la hiérarchie des paramètres dans le package installé (`CountryTaxBenefitSystem().variables[...]` et `tbs.parameters(...)`) ou via l'index RAG généré par `parser/index_openfisca_docs.py`.
   - Vérifier l'entité (`Individu`, `FoyerFiscal`, `Famille`, `Menage`), la période (`MONTH` vs `YEAR`) et la convention de signe (en OpenFisca-France, l'IRPP, la CSG et la CRDS calculés sont **négatifs** ; les prestations sont **positives**).
2. **Étape B — Implémentation déterministe dans `engine/reforms/`** :
   - Créer un module dédié (ex: `engine/reforms/plf2027_<mesure>.py`) héritant d'`openfisca_core.reforms.Reform`.
   - Documenter chaque paramètre modifié avec `# SOURCE: ...` et l'échelle de certitude (`green` / `yellow` / `red`).
3. **Étape C — Suite de tests `pytest` sur les foyers types canoniques** :
   - Créer `engine/tests/test_<mesure>.py` couvrant obligatoirement les **5 foyers types de référence** du socle :
     1. **SMICard isolé** (actif salarié au SMIC, sans pension)
     2. **Couple avec 2 enfants** (actifs salariés, QF 3 parts)
     3. **Cadre propriétaire** (actif salarié cadre supérieur)
     4. **Retraité modeste** (isolé, exonéré/taux réduit CSG, non imposable IR)
     5. **Retraité aisé** (isolé ou couple, CSG taux plein, TMI 30 %)
   - Plus les cas-types ciblés spécifiques à la réforme si celle-ci touche une tranche ou un statut particulier (ex: retraité médian, retraité intermédiaire, couple de retraités).
   - Vérifier la conservation des invariants (ex: un ménage non concerné par une mesure retraites doit avoir `ΔIR == 0`, `ΔCSG == 0`, `ΔRevenu_Disponible == 0`) et comparer la cohérence avec `impots.gouv.fr` / `LexImpact`.
   - Lancer `uv run pytest -v` dans `engine/` et exiger 100 % de réussite.
4. **Étape D — Double audit croisé via `Codex CLI` (`codex review`)** :
   - Dès qu'une réforme ou modification critique de `engine/` est terminée et verte sous `pytest`, préparer/lancer la revue croisée indépendante via :
     ```powershell
     .\scripts\windows\run_codex_review.ps1 -TargetFile engine/reforms/<fichier>.py
     ```
   - Consigner et corriger tout écart de bord (effets de seuil RFR, décote, plafonnement du quotient familial, convention de signe, arrondis fiscaux à l'euro).
