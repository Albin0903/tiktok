# 03 — Méthodologie Économique (Micro-simulation + France Synthétique + Second Tour)

La crédibilité de **VeriteFiscale-2027** repose sur la séparation nette de **trois horizons analytiques**, chacun accompagné de son niveau de certitude (`🟢` / `🟡` / `🔴`).

---

## 1. Étage 1 : Micro-simulation « Jour J / Année 1 » (`OpenFisca-France`) — Certitude `🟢`

Cet étage calcule l'impact direct, mécanique et déterministe d'une mesure sur le budget d'un individu, d'un foyer fiscal, d'une famille et d'un ménage avant changement de comportement.

### A. Mécanique de simulation
- Chaque mesure est traduite en une classe `Reform` d'`openfisca_core` modifiant soit des **paramètres législatifs** (`modify_parameters`), soit des **formules de variables** (`update_variable` / `add_variable`).
- L'indicateur pivot de comparaison est le **`revenu_disponible`** du ménage (`Menage`, année `N`), décomposé en :
  - Revenus nets du travail (`revenus_nets_du_travail`)
  - Pensions nettes (`pensions_nettes`, incluant la CSG déductible, la CSG imposable, la CRDS et la CASA)
  - Revenus nets du capital (`revenus_nets_du_capital`)
  - Impôts directs (`impots_directs` : IRPP économique, IFI, CDHR)
  - Prestations sociales (`prestations_sociales` : allocations familiales, APL/AL, prime d'activité, RSA, AAH)

### B. Gestion des effets de décalage temporel ($N-2$)
En France, le **Revenu Fiscal de Référence (RFR) de l'année $N-2$** détermine :
- Le taux de **CSG applicable aux pensions de retraite** en année $N$ (`0 %`, `3,8 %`, `6,6 %` médian ou `8,3 %` taux plein) ainsi que la **CASA** (`0,3 %`).
- Les bases de ressources historiques de certaines prestations.

**Règle d'implémentation :** toute simulation évalue les années $N-4 \dots N$ (ex: `2021..2025`) avec `simulation.max_spiral_loops = 3`. Cela permet de distinguer explicitement deux horizons (`horizon: "annee_1" | "regime_permanent"`) :
1. **L'effet immédiat Année 1 (`annee_1`)** : la réforme s'applique uniquement sur l'année courante $N$ (`2025-01-01`). Le `rfr(N-2)` (`2023`) reste inchangé : aucune bascule immédiate de tranche CSG n'intervient.
2. **L'effet en régime permanent (`regime_permanent`)** : la réforme s'applique sur toute la fenêtre historique $N-4 \dots N$ (`2021-01-01`), mettant en évidence lorsqu'une hausse d'assiette imposable fait basculer un retraité au-dessus d'un seuil de RFR pour la CSG (effet de falaise CSG, ex. `16 755 €` pour `3,8 % -> 6,6 %` et `26 004 €` pour `6,6 % -> 8,3 %` pour 1 part en 2025).

> **Règle juridique exacte et implémentation du lissage CSG / CASA :**
> Conformément à l'**article L. 136-8, III du Code de la sécurité sociale** et à l'**Instruction interministérielle DSS/2B/2024/184 du 04/12/2024 (Annexe 1, §2 « Mesure de lissage », p. 4-5 & Annexe 2/3)** :
> - Le dispositif de lissage sur 2 ans **protège le passage d'un taux `<= 3,8 %` (exonération `0 %` ou taux réduit `3,8 %`) vers un taux supérieur (`6,6 %` ou `8,3 %` et CASA `0,3 %`)**, en exigeant que le RFR dépasse le plafond du taux réduit (`16 755 €` pour 1 part en 2025) pendant **deux années consécutives (`N-3` et `N-2`)**.
> - **Il n'existe PAS de lissage sur 2 ans entre le taux médian (`6,6 %`) et le taux normal (`8,3 %`)** : un pensionné déjà assujetti au taux médian `6,6 %` dont le `RFR(N-2)` est **`>= 26 004 €`** (1 part) bascule immédiatement à `8,3 %` dès l'année $N$.
> - **Correctifs embarqués dans `engine/reforms/demo_plf2027_retraites.py`** : nos réformes surchargent `csg_deductible_retraite`, `csg_imposable_retraite`, `crds_retraite` et `casa` pour appliquer à la fois la borne exacte `rfr >= 26 004 €` (au lieu de `rfr > 26 004 €` dans OpenFisca natif) et le lissage `N-3 / N-2` (pour `N >= 2024`).

### C. Procédure de contre-vérification externe (`impots.gouv.fr` & `LexImpact`)
Conformément à l'étape C de `AGENTS.md`, chaque réforme sur les foyers types baseline doit être vérifiée indépendamment du moteur OpenFisca par deux contrôles :
1. **Contre-calcul analytique dans `pytest`** : recalcul direct en Python des tranches du barème IR (CGI art. 197), de l'abattement 10 %, de l'abattement +65 ans (`abat_spe`), de la décote (`seuil_celib - 0,4525 * droits_simples`) et des arrondis fiscaux à l'euro le plus proche (reproduit dans `engine/tests/test_demo_plf2027_retraites.py`).
2. **Vérification manuelle sur les simulateurs institutionnels** :
   - **DGFiP (`https://simulateur-ir-ifi.impots.gouv.fr`)** : sélectionner l'année d'imposition 2025, renseigner l'année de naissance du déclarant (`1962` pour `< 65 ans` ou `1957` pour `>= 65 ans`) et reporter en case **`1AS`** la *retraite imposable* (`retraite_brute + csg_deductible_retraite`, ex. `27 590 €` pour `28 800 €` brut ou `50 814 €` pour `54 000 €` brut) afin de comparer l'impôt dû et le RFR.
   - **Assemblée nationale — LexImpact (`https://leximpact.an.fr`)** : saisir le cas-type équivalent dans le calculateur socio-fiscal et vérifier la convergence à l'euro sur `irpp`, `csg_deductible_retraite`, `csg_imposable_retraite` et `revenu_disponible`.

---

## 2. Étage 2 : Population Synthétique `france_synthetique.parquet` (Calage IPF) — Certitude `🟢 / 🟡`

Afin de dépasser les simples "5 cas-types" et d'afficher la distribution réelle sur les ménages français (le nuage de 10 000 points), le moteur génère en Phase 2 un fichier `data/processed/france_synthetique.parquet` (10 000 à 50 000 ménages synthétiques pondérés représentant ~30 millions de ménages).

### Méthode de construction : Iterative Proportional Fitting (IPF / Raking)
1. **Tirage initial (Prior)** : construction d'une grille réaliste de ménages combinant âge, statut d'activité (salarié privé, fonctionnaire, indépendant, chômeur, retraité, inactif), configuration familiale (isolé, monoparental, couple 0..3+ enfants), statut d'occupation (locataire HLM, locataire privé, propriétaire) et décile de revenu.
2. **Calage sur marges conjointes officielles** via **IPF** jusqu'à convergence ($L_1 < 10^{-5}$) sur :
   - Distribution des niveaux de vie et déciles D1–D10 (**INSEE Filosofi / Melodi**).
   - Pyramide des âges et types de ménages (**INSEE Recensement / Melodi**).
   - Tranches de RFR, masse de salaires, masse de pensions et rendement total de l'IR (**DGFiP IRCOM / POTE 2042**).
   - Propension à consommer par poste COICOP et décile (**INSEE Budget de Famille**).
3. **Contrôle de bouclage macro** : la somme pondérée $\sum_i w_i \cdot \text{IRPP}_i$ et $\sum_i w_i \cdot \text{Pensions}_i$ doit rester cohérente avec les agrégats DGFiP/DSS publiés (écart documenté dans le rapport d'étalonnage).

---

## 3. Étage 3 : Fiscalité Indirecte & Effets de Second Tour (`TES / OFCE / IPP`) — Certitude `🔴`

Les programmes politiques promettent souvent des chocs de TVA, de cotisations employeurs, de SMIC ou de taxes sur l'énergie dont l'effet ne se lit pas uniquement sur la fiche de paie au Jour J.

### A. Fiscalité indirecte au Jour J (sans LLM, sans `openfisca-france-indirect-taxation` py2)
En croisant la propension à consommer et les parts budgétaires **COICOP** (alimentation, énergie/carburants, logement, transport, services) issues de l'enquête **INSEE Budget de Famille**, `engine/second_round/indirect_taxation.py` calcule la variation de pouvoir d'achat réel due à :
- Une variation des taux de TVA (`20 %`, `10 %`, `5,5 %`, `2,1 %`).
- Une hausse ou baisse d'accises sur les carburants / l'électricité / le gaz.

### B. Choc de coûts et répercussion prix à 24–36 mois (Matrice TES de Leontief)
Lorsqu'une mesure modifie les **coûts de production par branche** $\Delta \mathbf{c}$ (ex: hausse du SMIC, baisse/hausse des allègements de cotisations employeurs, taxe carbone, hausse de la fiscalité énergétique), le vecteur de variation des prix à la production $\Delta \mathbf{p}$ se propage à travers les consommations intermédiaires selon le modèle classique de Leontief :

$$
\Delta \mathbf{p}^\top = \Delta \mathbf{c}^\top \, (I - A)^{-1}
$$

où $A$ est la matrice des coefficients techniques tirée du **TES INSEE niveau A38**.

### C. Règle absolue de présentation en intervalle
Parce que les élasticités de répercussion (*pass-through* prix, élasticité-prix de la demande, substitution travail/capital) varient selon la conjoncture, **tout résultat de second tour est obligatoirement borné par une fourchette `[Hypothèse Basse, Hypothèse Haute]`** sourcée sur la littérature économique (`ThreeME`, `OFCE`, `IPP`), et affiché avec le tampon **`🔴 EFFET DE SECOND TOUR / BOUCLAGE MACRO`**.
