# 05 — Ligne Éditoriale, Transparence AI Act & Mentions Légales 2027

## 1. Structure Narrative d'une Vidéo 9:16 (45–60 secondes)

Chaque vidéo générée dans `video/` (1080×1920, 60 fps) suit une grammaire constante en 5 temps, calée sur les zones de sécurité définies dans [`DESIGN.md`](../DESIGN.md) :

1. **0–3 s — Le Hook Factuel Brut** :
   - Chiffre choc sourcé à l'écran + question directe au spectateur *(ex: « Suppression de l'abattement de 10 % des retraités : voici ton vrai ticket d'impôt »)*.
   - Pas de musique dramatique anxiogène ni de titre putaclic non chiffré.
2. **3–15 s — Le Ticket de Caisse Comparatif (Cas-Type Concret)** :
   - Animation ligne par ligne du ticket papier millimétré `#F4F2EC` : Pension brute, CSG/CRDS, Abattement, Impôt sur le Revenu avant/après, Delta mensuel (`€/mois`) et annuel (`€/an`).
   - Affichage immédiat du tampon de certitude **`🟢 CALCUL DIRECT OPENFISCA`**.
3. **15–35 s — Le Nuage des 10 000 Ménages (`<canvas>` sur fond `#0F1115`)** :
   - Passage du cas particulier à la France réelle (`france_synthetique.parquet`) : qui gagne (`#00C853`), qui est neutre (`#D8D4C8`), qui perd (`#FF3D00`) selon les déciles D1–D10 et le statut.
4. **35–50 s — L'Angle Mort / Effet de Second Tour (`#FFE600` & `🔴`)** :
   - Mise en lumière systématique de ce que la promesse politique oublie (effet retardé $N+2$ sur le RFR et les seuils CSG, ou répercussion prix via matrice TES présentée en intervalle min–max).
5. **50–60 s — Call-to-Action & Vérification Ouverte** :
   - Renvoi vers le simulateur web (`web/`) pour tester sa propre situation en 30 secondes + mention du dépôt open-source et des sources publiques.

---

## 2. Échelle de Certitude Obligatoire (`🟢 / 🟡 / 🔴`)

Aucun visuel (vidéo, carte OG, tableau web) ne peut être publié sans l'un des 3 tampons normalisés :

| Niveau | Code | Signification exacte |
| :--- | :--- | :--- |
| **`🟢` Certitude Législative / Calcul Direct** | `#00C853` | Mesure codée sans ambiguïté sur des paramètres et formules audités d'`OpenFisca-France` (ex: barème IR, plafond `abatpen.max`, seuils RFR CSG). |
| **`🟡` Hypothèse de Chiffrage / Paramètre Incomplet** | `#FFE600` | Proposition politique dont le texte laisse un paramètre flou (ex: date d'entrée en vigueur, seuil exact non précisé). Les hypothèses retenues sont affichées explicitement. |
| **`🔴` Effet de Second Tour / Bouclage Macro** | `#FF3D00` | Simulation indirecte à 24–36 mois (matrice TES INSEE + élasticités OFCE/IPP/ThreeME). Toujours affichée sous forme de **fourchette `[min, max]`**. |

---

## 3. Conformité Règlement Européen sur l'IA (AI Act — Article 50)

Conformément aux obligations de transparence de l'**Article 50 de l'AI Act** (applicables en 2026–2027 aux contenus générés ou manipulés par IA) :
1. **Voix off / Synthèse vocale (TTS)** : si une voix de synthèse (ex: Magpie / TTS local) est utilisée pour la narration vidéo, la description de la vidéo ET le générique de fin portent la mention explicite : `Narration audio générée par synthèse vocale (IA) — Chiffrage 100 % déterministe sans IA (OpenFisca-France)`.
2. **Métadonnées C2PA / Description plateforme** : activation systématique du marqueur "Contenu généré/assisté par IA" sur TikTok/Reels/Shorts lorsque du TTS ou des éléments graphiques assistés sont présents, tout en précisant que **les calculs fiscaux ne sont pas générés par IA**.
3. **Interdiction de clonage vocal ou deepfake** : interdiction absolue d'imiter la voix ou le visage d'une personnalité politique ou d'un journaliste.

---

## 4. Obligations Open-Source (AGPL-3.0) & Mentions Légales 2027

1. **Licence `AGPL-3.0` d'`OpenFisca-France`** :
   - Le moteur `OpenFisca-France` étant sous licence GNU AGPL-3.0, tout code dérivé ou exposé via l'API réseau (`engine/` et `api/`) doit rester publiquement accessible sous licence compatible AGPL-3.0 avec lien permanent vers le dépôt source depuis l'interface web (`web/`).
2. **Disclaimer Éditorial & Non-Affiliation** :
   - *« VeriteFiscale-2027 est un outil citoyen et open-source de micro-simulation ex-ante indépendant. Il n'est affilié ni à la DGFiP, ni à l'INSEE, ni à aucun parti politique ou candidat. Les résultats sont fournis à titre indicatif sur la base des barèmes législatifs publiés et des hypothèses documentées ; seul le simulateur officiel d'impots.gouv.fr fait foi pour votre déclaration. »*
3. **Neutralité Électorale & Équité des Comparaisons** :
   - Chaque programme ou projet de loi est simulé avec la **même version figée d'`OpenFisca-France`**, la **même population `france_synthetique.parquet`** et les **mêmes fourchettes d'élasticités TES**.
