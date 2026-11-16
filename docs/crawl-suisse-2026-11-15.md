# Collecte suisse : comparaison locale du 15–16 novembre 2026

**5 046 offres actives, contre 1 692 : +3 354 (+198,2 %), presque trois fois plus.**
La collecte complète a tourné le 15 novembre ; EY, seule source en erreur, a été reprise
avec succès le 16 novembre après correction du pré-filtre SuccessFactors. Ces chiffres
concernent la base locale, pas le VPS. Le point de départ date du 5 novembre : la variation
inclut à la fois l'ouverture géographique et dix jours de publications/retraits.

## Avant / après

| Indicateur | Avant · 05.11 | Après · 15–16.11 |
| --- | --- | --- |
| Offres actives | 1 692 | 5 046 |
| Cantons représentés | 7 | 26 |
| Sources avec des offres actives | 59 | 64 |
| Offres sans canton dans la vue API | 0 | 103 |

Le catalogue compte 128 sources configurées : 66 ont été traitées, 62 restent ignorées
(absence de connecteur/board ou exclusion explicite). Après la reprise d'EY, aucune erreur
résiduelle et aucune offre active conservée sans rafraîchissement. Une alerte d'expiration
reste à examiner : l'OIM, 8 offres anciennes retirées et 2 nouvelles, soit 8 → 2 actives.

## D'où viennent les offres supplémentaires ?

| Source | Avant | Après | Écart |
| --- | --- | --- | --- |
| Coop | 394 | 2 651 | +2 257 |
| Hirslanden | 58 | 350 | +292 |
| Lonza | 0 | 193 | +193 |
| Helvetia Baloise | 36 | 170 | +134 |
| EY | 38 | 123 | +85 |
| PwC | 9 | 80 | +71 |
| Julius Baer | 2 | 66 | +64 |
| Zurich Assurances | 7 | 45 | +38 |
| La Mobilière | 17 | 46 | +29 |
| État de Fribourg | 74 | 98 | +24 |

Coop représente **52,5 %** du corpus final (2 651 / 5 046). C'est une forte concentration :
plus d'offres ne signifie pas automatiquement de meilleures recommandations. Ses descriptions
sont souvent très courtes, comme dans le corpus précédent.

En réappliquant le filtre géographique d'avant la modification aux lieux du corpus final :

- **1 685** offres correspondent encore à l'ancien filtre romand ;
- **3 226** ne passaient pas cet ancien filtre et ont désormais un canton suisse reconnu ;
- **135** ont un lieu insuffisamment précis pour cette comparaison. La vue API rattache 32
  d'entre elles au canton de l'employeur (repli JSON-LD déjà existant), d'où 103 sans canton.

Cette comparaison sur les mêmes offres montre que l'ouverture géographique explique
l'essentiel de la hausse. Elle ne simule pas exactement tous les anciens connecteurs : certains
acceptaient déjà les adresses JSON-LD sans ville. Les offres multi-sites gardent un seul canton.

Au niveau des URL : **1 357** anciennes offres actives sont encore actives, **335** ne le sont
plus, **3 507** nouvelles URL ont été ajoutées et **182** anciennes URL ont été réactivées.
Contrôle : 1 692 − 335 + 3 507 + 182 = **5 046**.

## Répartition par canton

| Canton | Avant | Après |
| --- | --- | --- |
| ZH | 0 | 994 |
| GE | 681 | 710 |
| BE | 83 | 623 |
| VD | 511 | 484 |
| AG | 0 | 313 |
| FR | 214 | 258 |
| VS | 72 | 255 |
| LU | 0 | 173 |
| GR | 0 | 171 |
| BS | 0 | 161 |
| TG | 0 | 123 |
| SO | 0 | 119 |
| NE | 106 | 111 |
| unknown | 0 | 103 |
| SZ | 0 | 85 |
| ZG | 0 | 67 |
| SG | 0 | 57 |
| TI | 0 | 50 |
| SH | 0 | 42 |
| BL | 0 | 40 |
| JU | 25 | 26 |
| GL | 0 | 24 |
| OW | 0 | 20 |
| NW | 0 | 14 |
| UR | 0 | 13 |
| AR | 0 | 6 |
| AI | 0 | 4 |

## Durée et correctif découvert pendant la collecte

Le premier passage a duré **3 h 14**. Coop a pris environ **47 minutes** ; EY a échoué après
**87 minutes** (`RemoteProtocolError`, connexion coupée par le serveur). Ses 38 anciennes
annonces avaient été conservées, conformément à la règle de non-expiration sur panne.

La lecture du sitemap EY a révélé 1 565 URL candidates sur 9 168, dont de nombreuses annonces
étrangères : un suffixe postal à quatre chiffres était pris pour un NPA possible, par exemple
Brisbane 4000 ou Debrecen 4021. Le pré-filtre n'accepte désormais un NPA seul que pour un board
déjà limité à la Suisse (la branche `/Hirslanden` de Mediclinic). Sur les boards mondiaux,
un lieu suisse reconnu est nécessaire ; le détail de l'annonce reste le filtre final.

**Reprise d'EY après correction : 123 offres, 2 min 17, zéro erreur.** Le cycle complet n'a
pas été relancé avec ce correctif : ne pas présenter une durée nationale optimisée comme
mesurée. Le plafond VPS de 3 h reste à surveiller au premier déploiement ; la mémoire VPS
avec ce corpus n'a pas été mesurée ici.

Validation du code final : `uv run ruff check .` et `uv run pytest -q` — **453 tests réussis**.
Aucun fichier de `checkpoints/` modifié.

## Correctif géographique (16.11) : répertoire officiel et homonymes étrangers

La relecture de la branche a trouvé deux faiblesses de `geo.py` une fois le périmètre
élargi :

- **Homonymes étrangers non bloqués.** Le veto avait été écrit pour les noms romands.
  Emmen (Pays-Bas), Cham (Bavière), Baden (Autriche), Lucerne (Californie), Saint-Louis
  (Bâle) étaient classés suisses. En base : 2 offres EY à « Freiburg i. Br., 79098 BW »
  (classées FR) et 1 à « Palma de Mallorca, 07010 Bale » (classée BS).
- **Géographie écrite à la main.** Environ 150 communes sur 2 100, et une table NPA
  partielle (CH-8032 reconnu, pas CH-8001 ni CH-4051).

Correctif : la table NPA/localités vient du **répertoire officiel des localités** de
swisstopo (open data ; `localities.py` génère `ch_localities.csv` : 3 147 NPA, 4 362 noms).
Un nom du répertoire ne compte que s'il forme seul un morceau du lieu (« CH - Ittigen »),
car « Rue », « Sur » ou « Ins » sont des localités. Les noms ambigus sont écartés
(« Stein » : AG, AR, SG), ainsi que les NPA partagés sans canton dominant (1290). Le veto
nomme maintenant les pays, régions, États américains et villes frontalières.

Le répertoire a aussi corrigé une erreur de la liste manuelle : **Moutier est jurassienne
depuis le 01.01.2026**. Une règle « code postal à cinq chiffres = étranger » a été essayée
puis retirée : l'État de Genève colle le numéro de rue au NPA (« Rue David-Dufour
51205 Genève »), ce qui écartait 14 offres genevoises.

Effet mesuré sur les 5 046 offres actives (lieux recalculés, base non modifiée) :

| | avant | après |
|---|---:|---:|
| offres sans canton | 135 | **70** |
| offres classées suisses à tort (sortent du périmètre) | — | 3 |
| offres dont le canton change | — | 4 (Moutier → JU ; Kemptthal → ZH) |

Les 70 restantes : État de Genève sans lieu ou avec une adresse en texte libre (27, canton
venu de l'employeur dans la vue API), Lonza « CH - Stein » (24, ambigu sans contexte), lieux
réduits au pays. Validation : ruff valide, **487 tests réussis**, checkpoints M1/M2 15/15.

## Reproductibilité

- Sauvegarde avant collecte : `data/raw/switzerland-comparison-2026-11-15/before.duckdb`.
- Mesures : `before.json`, `after.json` (premier passage), `after-ey.json` (reprise),
  `comparison.json`, journaux et scripts dans ce même dossier local, ignoré par Git.
- Base actualisée : `data/jobs.duckdb` ; réponses des ATS dans `data/raw/2026-11-15/`
  et `data/raw/2026-11-16/`.
- PR : https://github.com/mieleif/job-rec-ai/pull/22. Aucune mise à jour du VPS effectuée ici.
