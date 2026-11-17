# Phase 2 — Validation du démonstrateur

## Clôture de la Phase 2

Les deux populations comprennent 10 000 ménages, dont 200 profils réservés à la queue de Pareto avant le calage final. Ils combinent une composante de dividendes au PFU avec les réductions et crédits imputés à partir de la déclaration 2042, dont Pinel, PME, dons et `8TK` chez les éligibles. Les fréquences de la queue sont estimées à partir des sous-tranches nationales IRCOM. Le calage exploite les totaux métropolitains, les huit tranches consolidées et les cinq statuts familiaux. Les marges détaillées sont souples. L’IR net reste libre dans une bande de ±2,5 % et est ramené à la borne la plus proche lorsque nécessaire. [Données IRCOM](https://www.data.gouv.fr/datasets/limpot-sur-le-revenu-par-collectivite-territoriale-ircom)

Le calage logit borne chaque poids entre 0,22 et 1,98 fois le poids moyen de référence. Le rapport maximal de 9 garantit un effectif de Kish d’au moins 3 600 sur 10 000, car pour des poids dans `[a, b]`, la fraction effective vaut au moins `4ab/(a+b)²`. [Deville et Särndal, 1992](https://www.tandfonline.com/doi/abs/10.1080/01621459.1992.10475217)

| Indicateur métropolitain | Revenus 2023 | Revenus 2024 |
| --- | ---: | ---: |
| Effectif de Kish sur 10 000 | **6 902** | **6 849** |
| Foyers fiscaux | 39,626 M | 40,022 M |
| Écart sur les foyers fiscaux | 0,00 % | 0,00 % |
| Écart sur les foyers imposés | −0,10 % | −0,42 % |
| Écart de RFR | +1,20 % | −0,23 % |
| IR net simulé | 83,62 Md€ | 87,96 Md€ |
| Écart d’IR net | **+2,50 %** | **−1,75 %** |
| Écart sur les traitements et salaires | −5,05 % | −4,97 % |
| Écart sur les retraites et pensions | −4,26 % | −6,43 % |

Le chômage utilise le brut égal au net imposable quand l’exonération de CSG est certaine au vu des paramètres OpenFisca, puis une courbe vectorisée en deux évaluations au plus pour les autres profils. Les deux scénarios calculent toujours la totalité des prestations et du revenu disponible. Le test du foyer à 1 000 € de net imposable avec un enfant vérifie l’égalité stricte des résultats avec l’inversion précédente.

Le benchmark de clôture mesure **2 593 ms en moyenne à chaud** pour le chômage sur sept requêtes distinctes. L’objectif de 800 ms reste hors d’atteinte avec le seul remplacement de l’inversion. Sur le profil à 1 000 €, une requête avec un brut déjà renseigné, donc sans inversion, a pris environ 2,65 s à chaud. Trois profils supplémentaires à 1 900, 3 500 et 4 400 € de net imposable ont donné les mêmes aides et le même revenu disponible. Dans le dernier cas, le brut estimé affiché diffère d’un centime. Les seuils de clôture portent sur le Kish, l’écart d’IR et les tests. Les **44 tests** et la compilation Next.js passent, et le calage passe les seuils sur les deux millésimes.

La revue croisée a été passée au CLI par entrée standard après l’échec du lanceur Windows. Le calage vérifie l’unicité des identifiants de ménage et la continuité des indices de foyer avant de réaffecter les cases imputées.

Les Parquet 2023 et 2024, la simulation PLF et les visuels ont été régénérés. La vidéo de 48 secondes a été contrôlée à 1080 × 1920 et 60 i/s. À la frame 20, les deux valeurs issues du résumé sont visibles dans la zone de sécurité, avec +909 €/an en vert et −574 €/an en rouge. À 390 px, le Web affiche l’attente animée puis le résultat. La carte du retraité indique « 287 € de plus par an », puis « soit +24 € / mois ».

## Reproduction sous Windows ARM64

Depuis la racine, dans PowerShell.

```powershell
uv sync --locked
uv run python -m engine.synthetic.fetch_official_data
uv run python -m engine.synthetic.build_synthetic_france
uv run python -X utf8 -m engine.synthetic.audit_macro --output data/processed/audit_cloture_2023.json
uv run python -m engine.synthetic.build_synthetic_france --income-year 2024 --output data/processed/france_synthetique_2024.parquet
uv run python -X utf8 -m engine.synthetic.audit_macro --population data/processed/france_synthetique_2024.parquet --income-year 2024 --output data/processed/audit_cloture_2024.json
uv run python -m engine.reforms.plf2027_complet_demo
uv run pytest -v
```

Dans deux terminaux, lancer l’API et le Web.

```powershell
uv run uvicorn api.main:app --host 127.0.0.1 --port 8000
```

```powershell
npm --prefix web ci
npm --prefix web run build
npm --prefix web run start -- --hostname 127.0.0.1 --port 3000
```

## Simulation socio-fiscale

Le profil individuel attend le **net imposable mensuel du foyer**. Pour les salariés, retraités et chômeurs, le moteur retrouve le brut correspondant par inversion du calcul OpenFisca. Le brut peut être précisé et devient alors la donnée d’entrée pour recalculer le net imposable. En imposition commune, le revenu est réparti à parts égales entre deux adultes de même catégorie. Les revenus et la situation du foyer sont supposés stables de N−4 à N. Pour l’activité indépendante, le revenu correspond au bénéfice fiscal d’un commerçant au régime de droit commun. Le salaire journalier de référence est inconnu pour le chômage, ce qui peut sous-estimer la cotisation de retraite complémentaire.

Le ticket détaille l’IR net, la CSG/CRDS, les cotisations, la prime d’activité, l’aide au logement applicable, les allocations familiales, l’ensemble des prestations et le revenu disponible. Ce dernier est affiché avant paiement du loyer et des dépenses d’énergie et de carburant. La variation mensuelle est calculée à partir du différentiel annuel de revenu disponible entre les deux scénarios. Les articles fiscaux simulés ne déclenchent aucun choc direct de prix dans le module TES.

« Affiner mes hypothèses » permet de choisir le loyer, la zone d’aide au logement, le conventionnement, l’âge des enfants et le brut. Les valeurs par défaut pour un locataire sont 650 € hors charges, zone 2 OpenFisca et logement privé non conventionné. Le montant de 650 € est un repère local tiré de l’Observatoire des loyers du Pays basque, et chaque enfant est supposé avoir 10 ans. [Observatoire local des loyers, chiffres clés 2024](https://www.observatoires-des-loyers.org/decouvrir-le-reseau/publications/details/observatoire-local-des-loyers-prives-bayonne-pays-basque-sud-landes-les-chiffres-cles-2024)

Le test de bout en bout couvre un profil locataire de deux enfants à 1 400 € de net imposable par mois, avec IR nul, aide au logement, prime d’activité et allocations familiales positives. Dans Edge ARM64 à 390 px, le ticket a repris le loyer de 450 € et la zone 1 saisis dans le panneau. En Phase 2B, le calcul complet prenait environ 2,7 s à chaud sur ce profil.

En Phase 2C, une table calculée par OpenFisca au démarrage accélère l’inversion du net imposable des salariés. Une ou deux évaluations déterministes contrôlent l’estimation dans le cas usuel, avec retour à l’inversion de référence près d’une rupture de pente. Les prestations communes sont calculées une fois pour les profils sans pension et hors chômage. Le revenu disponible est recalculé par OpenFisca dans chaque scénario. Les profils de retraite conservent des simulations distinctes. Le chômage conserve le parcours complet après une divergence lors des essais d’optimisation. La limite de trois boucles reste active pour les calculs de prestations qui lisent les ressources historiques, conformément aux règles du projet.

`uv run python -X utf8 -m api.tests.benchmark_simulation` mesure le POST local, après préchauffage, sur sept requêtes distinctes pour chacun des six statuts. Le benchmark ne met pas en cache les réponses individuelles.

| Profil | Moyenne à chaud |
| --- | ---: |
| Salarié non-cadre | 371 ms |
| Salarié cadre | 444 ms |
| Indépendant | 293 ms |
| Retraité | 586 ms |
| Chômeur | 2 547 ms |
| Inactif | 269 ms |

Lors de la Phase 2C, la moyenne sur ces 42 requêtes était de 752 ms. Deux profils passaient sous 300 ms en moyenne.

## Calage Phase 2C

Le calage conserve les ménages comme unités de pondération et compte les foyers fiscaux individuellement, via leurs identifiants OpenFisca. Les huit tranches IRCOM des 13 régions apportent des cibles d’effectifs, de RFR, de foyers imposés, de salaires, de pensions et d’IR net. Les totaux métropolitains sont imposés aux poids. Les masses par tranche et les quatre groupes supérieurs à 100 000 € sont ajustés avec une pénalité. La structure de la queue vient du tableau national et s’applique aux masses et effectifs métropolitains. Le fichier d’audit publie les résultats avant et après l’ajustement de l’IR, du RFR et des foyers imposés, ainsi que les parts moyennes et la proportion d’imposition commune par tranche.

Pour 2023, le calage utilise les bornes nationales de RFR par part de la DGFiP. Pour 2024, le tableau 2 du n° 41 donne des moyennes et le tableau 4 des montants d’IR et de RICI par rang. Les moyennes de RFR par part sont appliquées aux groupes obtenus avec les poids avant calage final. Le rang est recalculé pour les diagnostics après calage. L’audit compare aussi l’IR et les RICI aux résultats nationaux du tableau 4, dont le champ diffère du rôle métropolitain. [DGFiP Statistiques n° 32, tableau 2](https://www.impots.gouv.fr/sites/default/files/media/9_statistiques/0_etudes_et_stats/0_publications/dgfip_statistiques/2025/num32_04/dgfip_stat_32_2025.pdf#page=2) · [DGFiP Statistiques n° 41, tableaux 2 et 4](https://www.impots.gouv.fr/sites/default/files/media/9_statistiques/0_etudes_et_stats/0_publications/dgfip_statistiques/2025/num41_11/dgfip_stat_41.pdf#page=4)

Les données 2042 alimentent les dividendes, les intérêts, l’assurance-vie, les plus-values mobilières, les revenus et déficits fonciers et les bénéfices BNC/BIC au réel. Les montants varient sur la queue selon les tranches nationales publiées. La règle d’imputation renseigne le PFU par défaut et distribue les options `2OP` aux foyers détenteurs de revenus éligibles dont le taux marginal initial est faible. Le prélèvement déjà acquitté sur les RCM est imputé dans `2CK`. OpenFisca conserve ainsi les RCM dans le RFR et calcule le solde mis en rôle après compensation de l’avance. Les plus-values mobilières et la CEHR restent dans ce solde. Les réductions imputées comprennent des cases Pinel, Denormandie, Scellier et FIP/FCPI/PME, ainsi que des revenus étrangers éligibles au crédit `8TK`, bornés par les revenus déjà déclarés. [IRCOM, note des feuilles régionales](https://www.data.gouv.fr/datasets/limpot-sur-le-revenu-par-collectivite-territoriale-ircom) · [Déclarations nationales 2042](https://data.economie.gouv.fr/explore/dataset/ir-declarations-2042-nat/) · [Conseil des prélèvements obligatoires, rapport de septembre 2026](https://www.ccomptes.fr/sites/default/files/2026-09/20260930-synthese-Impot-sur-le-revenu-reductions-et-credits-depuis-2017.pdf)

Une loi de Pareto ajustée aux effectifs IRCOM nationaux aux bornes des tranches répartit une partie des dividendes, plus-values et bénéfices dans le haut de la distribution.

| Agrégat métropolitain | Modèle 2023 | Référence 2023 | Modèle 2024 | Référence 2024 | Écart arrondi |
| --- | ---: | ---: | ---: | ---: | ---: |
| Foyers fiscaux | 39,626 M | 39,626 M | 40,022 M | 40,022 M | 0,00 % |
| Foyers imposés | 18,239 M | 18,239 M | 19,227 M | 19,227 M | 0,00 % |
| RFR | 1 263,16 Md€ | 1 263,16 Md€ | 1 339,22 Md€ | 1 339,22 Md€ | 0,00 % |
| IR net émis | 81,58 Md€ | 81,58 Md€ | 89,53 Md€ | 89,53 Md€ | 0,00 % |
| Traitements et salaires | 876,31 Md€ | 876,31 Md€ | 904,79 Md€ | 904,79 Md€ | 0,00 % |
| Retraites et pensions | 361,44 Md€ | 361,44 Md€ | 385,55 Md€ | 385,55 Md€ | 0,00 % |

Avant l’ajustement final des poids sur l’IR, le RFR et les foyers imposés, l’IR simulé était de 91,31 Md€ en 2023 et 102,89 Md€ en 2024, soit environ +11,9 % et +14,9 %. Les agrégats du tableau mesurent le respect des contraintes d’ajustement. Dans la tranche de 50 001 à 100 000 €, l’IR passe à 24,09 Md€ pour 24,19 Md€ de référence en 2023 et à 26,33 Md€ pour 26,08 Md€ en 2024. Au-dessus de 100 000 €, le RFR simulé atteint 249,33 Md€ et 282,81 Md€, face à 249,38 Md€ et 286,55 Md€.

Les poids restent concentrés. L’effectif de Kish est d’environ 531 en 2023 et 92 en 2024 sur 10 000 ménages. En 2024, le dernier dixième atteint 962 € de RICI moyens dans le modèle métropolitain pour 2 538 € dans la référence nationale. Son dernier millième atteint 340 221 € de RFR par part contre 916 590 € au niveau national. Les résultats par groupes fins et les chiffres éditoriaux qui en dépendent restent expérimentaux. Les JSON d’audit détaillent ces écarts. [DGFiP Statistiques n° 41, tableaux 2 et 4](https://www.impots.gouv.fr/sites/default/files/media/9_statistiques/0_etudes_et_stats/0_publications/dgfip_statistiques/2025/num41_11/dgfip_stat_41.pdf#page=4)

## Résultats du calage précédent, Phase 2B

Les valeurs de 39,63 M de foyers et de 81,58 Md€ d’IR net correspondent à IRCOM 2024, sur les revenus **2023**. IRCOM 2025 porte sur les revenus **2024** et donne 40,02 M et 89,53 Md€ pour la métropole. Chaque population de 10 000 ménages est simulée avec la législation de son millésime fiscal. En 2024, le support démographique et les profils ERFS restent ceux de 2023. [IRCOM, fichiers régionaux 2024 et 2025](https://www.data.gouv.fr/datasets/limpot-sur-le-revenu-par-collectivite-territoriale-ircom)

| Agrégat | Modèle 2023 | Référence 2023 | Écart | Modèle 2024 | Référence 2024 | Écart |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Ménages | 30,474 M | 30,474 M | 0,00 % | 30,474 M | 30,474 M | 0,00 % |
| Population des ménages | 64,783 M | 64,783 M | 0,00 % | 64,783 M | 64,783 M | 0,00 % |
| Foyers fiscaux | 39,626 M | 39,626 M | 0,00 % | 40,022 M | 40,022 M | 0,00 % |
| Foyers imposés | 17,725 M | 18,239 M | −2,82 % | 19,651 M | 19,227 M | +2,21 % |
| Traitements et salaires | 876,31 Md€ | 876,31 Md€ | 0,00 % | 904,79 Md€ | 904,79 Md€ | 0,00 % |
| Retraites et pensions | 361,44 Md€ | 361,44 Md€ | 0,00 % | 385,55 Md€ | 385,55 Md€ | 0,00 % |
| RFR pondéré | 1 198,22 Md€ | 1 263,16 Md€ | −5,14 % | 1 269,12 Md€ | 1 339,22 Md€ | −5,23 % |
| IR net émis | 88,55 Md€ | 81,58 Md€ | **+8,54 %** | 100,28 Md€ | 89,53 Md€ | **+12,01 %** |

La tolérance de ±1 % sur les foyers est atteinte. Les salaires et les pensions sont des marges d’entrée du calage, mesurées à partir des catégories synthétiques correspondantes. Le seuil de moins de 5 % sur l’IR net reste ouvert. La tranche de 50 001 à 100 000 € de RFR explique à elle seule un excédent d’IR de 8,09 Md€ en 2023 et de 11,14 Md€ en 2024, alors que son effectif est calé. Le RFR agrégé est trop bas au-dessus de 100 000 €. Un même RFR peut produire un IR très différent selon les parts, la composition des revenus, les charges et les crédits. Ces caractéristiques sont imputées à partir de marges séparées. Les profils du modèle utilisent une catégorie principale de revenu, avec des revenus du patrimoine et certains cumuls non reconstruits. L’IR net et les foyers imposés sont des mesures de validation indépendantes du calage.

Le support s’appuie sur les revenus ERFS DIS01MO par type de ménage. Les couples en union libre forment deux foyers fiscaux. Une partie des enfants cohabitants est représentée par des adultes de 22 ans imposés séparément, avec un revenu imputé compatible avec le revenu total du ménage. Les ménages restent groupés pour le logement et les aides, avec des familles OpenFisca distinctes pour ces adultes. Le calage final rapproche la population en ménage, les types de ménage, le logement, les huit tranches IRCOM et les cinq statuts déclaratifs projetés sur la métropole. Il réutilise aussi les seuils des déciles nationaux de RFR par part publiés pour les revenus 2023. Les marges d’âge et d’activité utilisées pour créer le support restent approximatives. [ERFS 2023](https://www.insee.fr/fr/statistiques/8731692) · [DGFiP Statistiques n° 32, tableau 2](https://www.impots.gouv.fr/sites/default/files/media/9_statistiques/0_etudes_et_stats/0_publications/dgfip_statistiques/2025/num32_04/dgfip_stat_32_2025.pdf#page=2)

OpenFisca calcule les réductions et les crédits à partir des cases renseignées. Le 2042 national donne des effectifs et montants par case. La ventilation par tranche est imputée par rang de RFR et selon le support d’éligibilité disponible. Les cases couvrent notamment l’emploi à domicile (`7DB`, aides reçues en `7DR`), les dons (`7UD`, `7UF`), la garde d’enfants hors domicile (`7GA` à `7GC`), les pensions versées (`6GU`) et le PER (`6NS`, `6NT`, `6RS`, `6RT`). `7DQ` identifie la première année d’emploi direct à domicile. Le dernier recalage conserve les totaux pondérés imputés par case, repris dans le JSON. La DGFiP indique environ 20 Md€ de RICI sur les revenus 2024, dont 12,5 Md€ pour 8,7 millions de foyers restés imposés, soit 64,1 % du total national. [Déclarations nationales 2042](https://data.economie.gouv.fr/explore/dataset/ir-declarations-2042-nat/) · [DGFiP Statistiques n° 41](https://www.impots.gouv.fr/sites/default/files/media/9_statistiques/0_etudes_et_stats/0_publications/dgfip_statistiques/2025/num41_11/dgfip_stat_41.pdf#page=5)

L’export PLF est une comparaison expérimentale à profils constants sur les revenus 2026, reconstruits à partir de l’ERFS 2023. Il couvre le barème, la décote et les plafonds associés de l’article 2 et le sous-plafond retraites de l’article 3 du projet déposé. Les rangs de revenu sont relatifs à chaque type de ménage ERFS.

## Vérifications techniques

`uv run pytest -v` à la racine couvre `engine/tests` et `api/tests`. Les 43 tests passent sous Python 3.13.18 et OpenFisca-France 177.0.0, avec un avertissement Starlette lié au client de test `httpx`. `npm --prefix web run build` passe sous Node.js ARM64. La revue CLI a été effectuée sur le code transmis par entrée standard après un échec du lanceur Windows. Les foyers à RFR par part identique reçoivent la même fraction de poids lorsqu’ils traversent une borne de décile.

## Rendu vidéo natif

Le compositeur Remotion distribué sur npm pour Windows cible x64. Le rendu de ce dépôt utilise le **Player Remotion** dont Playwright pilote les images dans Edge ARM64, puis un FFmpeg ARM64 local encode le MP4. L’exécutable utilisé provient d’une [publication FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds/releases/latest) avec vérification du SHA-256. Aucun navigateur ni exécutable x64 n’est requis par ce chemin.

```powershell
npm --prefix video ci
$env:VIDEO_BROWSER = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
$env:FFMPEG_PATH = (Get-ChildItem video/out/toolchain -Recurse -Filter ffmpeg.exe | Select-Object -First 1).FullName
npm --prefix video run preflight
uv run python video/prepare_data.py
npm --prefix video run render
$ffprobe = Join-Path (Split-Path $env:FFMPEG_PATH -Parent) 'ffprobe.exe'
& $ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,width,height,r_frame_rate,nb_frames:format=duration -of json video/out/test_plf2027_preview.mp4
```

Préflight H.264 de 2 secondes, puis aperçu H.264 de 48 secondes et 2 880 images, 1080 × 1920 à 60 images/s. La vidéo se compose d’un nuage de 10 000 points, de trois cas synthétiques contrastés et d’une scène de sources.

L’aperçu MP4 de clôture contient une piste vidéo seule. Le rythme avec une voix et l’emplacement sous l’interface TikTok restent à vérifier lors de la production éditoriale.
