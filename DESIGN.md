# DESIGN.md — Bible de Direction Artistique (« Comptable Punk / Ticket de Caisse 2027 »)

Ce document définit l'identité visuelle unifiée partagée entre les vidéos 9:16 (`video/` sous Remotion) et l'application citoyenne (`web/` sous Next.js + Tailwind + Visx).

---

## 1. Concept Éditorial : « Comptable Punk / Ticket de Caisse 2027 »

L'esthétique croise la **rigueur clinique d'un logiciel comptable / terminal Bloomberg** et la **lisibilité brute d'un ticket de caisse ou d'une fiche de paie annotée au marqueur fluo**.
- Pas d'avatars IA génériques, pas de dégradés "startup SaaS" violets, pas de graphiques 3D décoratifs.
- Chaque pixel porte une donnée vérifiable : **un montant en euros/an**, **un différentiel mensuel**, **une ligne de cotisation ou d'impôt** et **un tampon de certitude sourcé**.

---

## 2. Palette Chromatique Officielle

| Rôle | Nom | Code Hex | Usage strict |
| :--- | :--- | :--- | :--- |
| **Fond Clair (Éditorial / Ticket)** | Papier Millimétré | `#F4F2EC` | Fond principal des fiches de paie, tickets de caisse comparatifs et pages de simulateur clair. |
| **Fond Sombre (Data / Nuage)** | Terminal Nuit | `#0F1115` | Fond des scènes de distribution 10 000 ménages, mode sombre webapp et bandeaux techniques. |
| **Surface Secondaire Sombre** | Encre Carbone | `#1A1D24` | Cartes d'analyse, encadrés de formules OpenFisca et tooltips de déciles. |
| **Lignes & Quadrillage** | Grille Technique | `#D8D4C8` | Filets millimétrés `1px`, séparateurs de lignes comptables et bordures de tableaux sur fond `#F4F2EC`. |
| **Gain Net (Pouvoir d'achat +)** | Vert Gain | `#00C853` | Uniquement pour une hausse nette de revenu disponible (`+X €/mois`, `+Y €/an`) ou tampon `🟢`. |
| **Perte Nette (Pouvoir d'achat -)** | Rouge Perte | `#FF3D00` | Uniquement pour une baisse nette de revenu disponible ou hausse de prélèvement (`-X €/mois`). |
| **Alerte / Angle Mort / Second Tour** | Jaune Angle Mort | `#FFE600` | Surligneur marqueur sur le texte clé, avertissements de bouclage macroéconomique et effets de seuil. |

> **Règle d'accessibilité & contraste :** sur `#FFE600`, le texte est toujours en `#0F1115`. Sur `#00C853` et `#FF3D00`, utiliser `#0F1115` (ou `#FFFFFF` uniquement pour les corps >= 18px en gras). Ne jamais mélanger Vert Gain et Rouge Perte pour de la décoration pure.

---

## 3. Typographies & Hiérarchie

1. **Titres, Hooks & Verdict Choc : `Space Grotesk`** (graisses `600`, `700`)
   - Tracking serré (`-0.03em`) sur les titres 9:16 et bandeaux "VERDICT".
   - Majuscules réservées aux tampons courts (`IMPÔT SUR LE REVENU`, `SIMULATION EX-ANTE`).
2. **Chiffres, Tableaux, Formules & Sources : `JetBrains Mono`** (graisses `400`, `500`, `700`)
   - **Obligatoire sur tous les montants** : `font-variant-numeric: tabular-nums` afin que les colonnes de chiffres et compteurs animés à 60 fps ne tremblent jamais horizontalement.
   - Utilisée également pour les tampons de source (`SOURCE: OPENFISCA v177 / DGFIP 2025`) et les codes de variables (`abatpen.max`).

---

## 4. Grille & Safe Zones Vidéo 9:16 (`1080 x 1920`, 60 fps)

Les plateformes TikTok, Instagram Reels et YouTube Shorts masquent les bords avec leurs interfaces (profil, icônes like/commentaire à droite, description/barre de lecture en bas, recherche/onglets en haut).

```text
+--------------------------------------------------+  y = 0
|   MARGE HAUTE INTERDITE (Search / Tabs) : 160px  |
+----+--------------------------------------+------+  y = 160
|    |                                      |      |
| M  |                                      |  M   |
| A  |                                      |  A   |
| R  |         ZONE UTILE CENTRALE          |  R   |
| G  |           880 px × 1380 px           |  G   |
| E  |                                      |  E   |
|    |    (Titres, Ticket, Nuage, Tampons)  |      |
| G  |                                      |  D   |
| 60 |                                      | 140  |
| px |                                      |  px  |
+----+--------------------------------------+------+  y = 1540
|                                                  |
|   MARGE BASSE INTERDITE (Caption / Audio) : 380px|
|                                                  |
+--------------------------------------------------+  y = 1920
x=0  x=60                                 x=940   x=1080
```

- **Canvas total** : `1080 × 1920 px` (`60 fps`).
- **Marge haute** : `160 px` minimum (aucun texte critique ni KPI dans `y < 160`).
- **Marge basse** : `380 px` minimum (aucun texte critique dans `y > 1540` ; seul le filigrane discret ou fond millimétré s'y prolonge).
- **Marge droite** : `140 px` (zone des boutons cœur / commentaire / partage TikTok & Reels).
- **Marge gauche** : `60 px`.
- **Zone de sécurité active** : `880 × 1380 px` (`x ∈ [60, 940]`, `y ∈ [160, 1540]`).

---

## 5. Composants Partagés (`web/` & `video/`)

Les composants visuels sont pensés pour être réutilisés entre l'app Next.js (`web/`) et les compositions Remotion (`video/`), à partir des mêmes schémas JSON/Parquet générés par `engine/`.

### A. Le « Ticket de Caisse Comparatif » (Avant / Après)
- Aspect papier millimétré `#F4F2EC` avec bordure dentelée haute/basse ou filet pointillé `--` en `JetBrains Mono`.
- Colonnes strictes : `POSTE FISCAL`, `ACTUEL`, `RÉFORME`, `DELTA/AN`.
- Ligne finale en double filet avec badge `#00C853` (gain) ou `#FF3D00` (perte) et équivalent mensuel (`ex: -36 €/mois`).
- Tampon incliné à `-4°` en bas du ticket indiquant le profil exact (ex: `RETRAITÉ ISOLÉ • 4 500 € BRUT/MOIS`).

### B. Le « Nuage des 10 000 Ménages » (`<canvas>` 2D)
- **Rendu Canvas2D pur** (jamais 10 000 nœuds SVG dans le DOM, afin de garantir 60 fps en rendu Remotion headless Chromium et fluidité mobile sur `web/`).
- Chaque point représente un ménage pondéré de `france_synthetique.parquet` :
  - Axe X : niveau de vie par décile (`D1` à `D10`).
  - Axe Y : variation nette annuelle de revenu disponible (`€/an` ou `%`).
  - Couleur : `#00C853` (gagnant > +50 €/an), `#D8D4C8` / `#6E7681` (neutre ±50 €/an), `#FF3D00` (perdant < -50 €/an).
- Ligne médiane et ligne zéro surlignées ; interpolation lissée (cubic-bezier) lors des transitions d'une mesure à une autre.

### C. Tampons d'Échelle de Certitude (`🟢 / 🟡 / 🔴`)
Tout écran de résultat (vidéo ou simulateur web) affiche obligatoirement un badge de certitude :

| Badge | Couleur | Libellé officiel | Critère d'attribution |
| :--- | :--- | :--- | :--- |
| `🟢` | `#00C853` | **CERTITUDE LÉGISLATIVE / CALCUL DIRECT** | Mesure paramétrique exacte dans `OpenFisca-France`, barème ou texte de loi chiffré sans ambiguïté. |
| `🟡` | `#FFE600` | **HYPOTHÈSE DE CHIFFRAGE / PARAMÈTRE INCOMPLET** | Mesure issue d'un programme politique dont un seuil ou décret d'application nécessite une hypothèse documentée. |
| `🔴` | `#FF3D00` | **EFFET DE SECOND TOUR / BOUCLAGE MACRO** | Estimation à 24–36 mois via matrice TES INSEE + fourchettes d'élasticités OFCE/IPP (présentée en intervalle min–max, jamais en point unique). |
