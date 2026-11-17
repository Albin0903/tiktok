# 02 — Sources de Données Officielles & Dépôts de Référence

Chaque chiffre affiché par **VeriteFiscale-2027** doit être traçable jusqu'à une source publique primaire ou un modèle économique institutionnel audité.

---

## 1. APIs et Jeux de Données Statistiques & Fiscaux (France)

| Source / Jeu de données | Producteur | Accès / URL | Granularité & Usage exact dans le projet |
| :--- | :--- | :--- | :--- |
| **API Melodi** | INSEE | `https://api.insee.fr/melodi` | Téléchargement automatisé des séries démographiques, structures de ménages, salaires et revenus par décile pour le calage IPF. |
| **Filosofi (Revenus localisés)** | INSEE / DGFiP | `https://www.insee.fr/fr/statistiques/collection/116579` | Distribution des niveaux de vie (déciles D1–D10), taux de pauvreté et structure des revenus disponibles par territoire et âge. |
| **DGFiP 2042 / IRCOM & POTE** | DGFiP (Ministère des Finances) | `https://www.impots.gouv.fr/statistiques` / `data.economie.gouv.fr` | Statistiques agrégées de l'impôt sur le revenu (RFR, tranches, nombre de parts, abattements, niches fiscales) par commune et tranche de RFR. |
| **Enquête Budget de Famille (BDF)** | INSEE | `https://www.insee.fr/fr/metadonnees/source/serie/s1194` | Structure de consommation des ménages par poste **COICOP** et par décile de niveau de vie -> indispensable pour calculer la TVA effective et l'impact carburant/énergie sans `openfisca-france-indirect-taxation` py2. |
| **Tableau des Entrées-Sorties (TES niveau 38 / A38)** | INSEE (Comptes Nationaux) | `https://www.insee.fr/fr/statistiques/collection/13028` | Matrice des consommations intermédiaires entre 38 branches économiques -> calcul des chocs de coûts et de répercussion prix à 24–36 mois (`engine/second_round/`). |
| **Barèmes IPP** | Institut des Politiques Publiques (IPP) | `https://baremes.ipp.eu` (`github.com/openfisca/openfisca-france`) | Barèmes historiques et actuels (IR, CSG, cotisations sociales, prestations familiales, aides au logement) avec références Légifrance/BOFiP. |
| **Open Data Assemblée nationale (17e législature)** | Assemblée nationale | `https://data.assemblee-nationale.fr` | Dossiers législatifs PLF/PLFSS 2027, textes adoptés, amendements déposés et scrutins publics en XML/JSON structurés. |

---

### Cache France Synthétique

Depuis la racine, `uv run python -m engine.synthetic.fetch_official_data` télécharge les ressources ci-dessous et écrit le manifeste local `data/raw/manifest.json` avec l'URL, le statut, la taille et le SHA-256 des fichiers disponibles. `--refresh` retente les téléchargements. Si le serveur échoue, le script conserve une copie locale valide et signale son utilisation. Une ressource absente donne un code de sortie non nul.

| Ressource | Champ et millésime |
| --- | --- |
| [Recensement, dossier complet](https://www.insee.fr/fr/statistiques/2011101?geo=METRO-1) | Population, familles, activité et logement en France métropolitaine, 2023. |
| [ERFS, revenu des ménages par décile](https://www.insee.fr/fr/statistiques/fichier/8731692/irsocerfs2023_dd1_bis_excel.zip) | Revenus et niveau de vie en logement ordinaire, métropole, 2023. |
| [IRCOM 2024](https://static.data.gouv.fr/resources/limpot-sur-le-revenu-par-collectivite-territoriale-ircom/20250919-135242/ircom-2024-revenus-2023.zip) | Revenus 2023, foyers fiscaux et impôt net, avec ventilation territoriale. |
| [IRCOM 2025](https://static.data.gouv.fr/resources/limpot-sur-le-revenu-par-collectivite-territoriale-ircom/20260526-131537/ircom-2025-revenus-2024.zip) | Revenus 2024, mêmes agrégats. |
| [Déclarations nationales 2042](https://data.economie.gouv.fr/explore/dataset/ir-declarations-2042-nat/) | Effectifs et montants nationaux par case, pour 2023 et 2024. |
| [Budget de famille TF106](https://www.insee.fr/fr/statistiques/fichier/4648335/TF106.csv) et [TF206](https://www.insee.fr/fr/statistiques/fichier/4648335/TF206.csv) | Dépenses et coefficients budgétaires par décile, France, enquête 2017. |
| [TES symétrique A38](https://www.insee.fr/fr/statistiques/fichier/8068640/TES_symetrique_A38_2022SD.xlsx) | Comptes nationaux, base 2020, tableau 9.400, millésime 2022. |

`uv run python -m engine.synthetic.build_synthetic_france` génère les 10 000 lignes. Les poids sont calés sur les marges de structure et de logement du recensement, des groupes d'âge et d'activité approchés, et les tranches ERFS DIS01MO par type de ménage. Le rang associé à chaque ligne est relatif à son type de ménage. Il sert de proxy pour sélectionner les postes Budget de famille 2017, en euros de l’enquête. Les marges publiées ne donnent pas directement la distribution croisée des âges, des revenus individuels et du rattachement fiscal dans chacun des ménages.

`uv run python -m engine.synthetic.audit_macro` calcule l'IR OpenFisca sous la législation 2023 puis compare les estimations aux 13 régions IRCOM et à la population vivant en ménage du recensement. Les 66,17 millions d'habitants de la population municipale incluent aussi des personnes hors ménages ordinaires. L'IR d'IRCOM est l'impôt net émis sur les revenus 2023. Les 94,9 Md€ indiqués par la DGFiP pour l'exercice 2023 sont des recettes recouvrées au cours de l'année. [Recettes fiscales budgétaires collectées en 2023, DGFiP](https://www.impots.gouv.fr/sites/default/files/media/9_statistiques/0_etudes_et_stats/0_publications/dgfip_statistiques/2024/num26_07/dgfip_stat26_budget_2023.pdf)

La phase 2B distingue les foyers en union libre et les cohabitants majeurs imposés séparément. Les tranches IRCOM, les statuts familiaux du 2042 et des déciles de RFR par part sont utilisés pour caler les poids, avec une imputation de charges et d’avantages fiscaux dans les variables OpenFisca. La distribution conjointe n’est pas publiée. Les dépenses par case sont ventilées par rang de RFR et critères d’éligibilité, puis simulées, ce qui laisse des écarts de composition. Le [rapport de validation](06-validation-phase-2.md) donne les chiffres et les hypothèses à chaque millésime.

## 2. Dépôts Open-Source & Modèles Institutionnels Fédérés

Ces dépôts servent de **références d'étalonnage et de validation croisée** (et non de dépendances blindées copiées sans vérification) :

| Dépôt / Projet | Institution / Mainteneur | Rôle exact dans VeriteFiscale-2027 |
| :--- | :--- | :--- |
| [`openfisca/openfisca-france`](https://github.com/openfisca/openfisca-france) | Communauté OpenFisca / DINUM / IPP | **Cœur de calcul principal** installé dans `engine/` (v177.0.0+, > 3 180 variables législatives). |
| `openfisca/openfisca-france-indirect-taxation` | OpenFisca (archive historique) | Référence conceptuelle pour les variables de fiscalité indirecte (TVA, TICPE). *Note ARM64/Py3.13 : le paquet PyPI `0.4.dev0` est tagué `py2` et inutilisable directement ; les formules sont réécrites en Python 3.13 propre dans `engine/second_round/`.* |
| [`leximpact/simulateur-socio-fiscal`](https://git.leximpact.dev/leximpact/simulateur-socio-fiscal) & `leximpact-socio-fiscal-openfisca-json` | Assemblée nationale (Cellule LexImpact) | Cas-types officiels en JSON et références d'audit parlementaire pour croiser nos résultats d'IR, CSG et aides sociales. |
| [`drees_code_public` (Modèle **Ines**)](https://git.drees.fr/drees_code_public) | INSEE / DREES (en R) | Benchmark de référence pour les règles sociales complexes (aides au logement, minima sociaux, non-recours) et la représentativité des ménages. |
| [`ThreeME-org/ThreeME_V3-open`](https://github.com/ThreeME-org/ThreeME_V3-open) | ADEME / OFCE | Référence pour les élasticités macroéconomiques sectorielles (énergie, TVA, cotisations, boucle prix-salaires) utilisées dans `engine/second_round/`. |
| [`etalab/calculette-impots-m-source-code`](https://github.com/etalab/calculette-impots-m-source-code) | DGFiP / Etalab | Code source officiel de la calculette d'impôt sur le revenu (langage M) pour audit exact des cas limites d'IR (décote, CEHR, plafonnement QF). |
| [`theosorus/QuelImpact`](https://github.com/theosorus/QuelImpact) | Prototype Hackathon AN 2026 | Référence d'architecture MCP / connecteurs autour d'OpenFisca et des données parlementaires. |

---

## 3. Règle de Citation dans le Code (`# SOURCE:`)

Aucune constante fiscale ou macroéconomique ne peut apparaître dans `engine/` sans son bloc de traçabilité :
```python
# SOURCE: INSEE / Comptes Nationaux 2025 — TES Niveau A38, Tableau entrées-sorties symétrique
# SOURCE: DGFiP / BOFiP — CGI art. 158-5-a (plafond abattement pensions 2025 = 4 439 €)
# SOURCE: OFCE / ThreeME V3 — Élasticité de répercussion TVA sur prix à la consommation (0.65 à 0.90)
```
