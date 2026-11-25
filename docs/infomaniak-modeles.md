# Modèles Infomaniak : embeddings et reranking

Relevé du 23.11.2026. Sources : [modèles](https://www.infomaniak.com/fr/hebergement/ai-services/open-source-models),
[prix](https://www.infomaniak.com/fr/hebergement/ai-services/tarifs),
[API embeddings](https://developer.infomaniak.com/docs/api/post/2/ai/%7Bproduct_id%7D/openai/v1/embeddings),
[API rerank](https://developer.infomaniak.com/docs/api/post/2/ai/%7Bproduct_id%7D/cohere/v2/rerank),
fiches Hugging Face. Noms, dimensions, limites et facturation vérifiés par des appels réels le 23.11.2026.

| Modèle (nom affiché) | Nom côté API | CHF / M tokens | Dim. | Entrée max (Infomaniak) | Publié (Hugging Face) |
|---|---|---|---|---|---|
| Qwen/Qwen3-Embedding-8B | idem | 0,07 | 4096 | 8 192 (fiche : 32k) | 03.06.2025 |
| Bge Multilingual Gemma2 | `bge_multilingual_gemma2` | 0,065 | 3584 | 8 000 (fiche : 8 192) | 25.07.2024 |
| All MiniLM L12 v2 | `mini_lm_l12_v2` | gratuit | 384 | 128 | dépôt du 02.03.2022 |
| BAAI/bge-reranker-v2-m3 | idem | 0,01 | | 8 192 | 15.03.2024 |
| Qwen/Qwen3-Reranker-0.6B | idem | 0,009 | | 32 768 | 29.05.2025 |

## Hypothèses de départ

- Prix : les cinq sont confirmés (0,07 ; 0,065 ; gratuit ; 0,01 ; 0,009).
- Dates : 2024 et mi-2025 confirmées par la création des dépôts (Qwen3-Reranker : 29.05.2025).
  MiniLM « 2021 » non confirmé : le dépôt Hugging Face date de mars 2022, ce qui peut être une
  migration. La date de publication n'est pas la date de coupure des données d'entraînement.

## Ce que les appels ont montré

- **Rerank : la requête est facturée à chaque document.** Même longue requête, 1 puis 10
  copies d'un document : bge 399 → 3 990 tokens, Qwen3 428 → 4 280. Coût = N × (CV + offre).
- **Gabarit de Qwen3-Reranker** : 90 tokens pour une paire minuscule, contre 20 pour bge. Les
  ~70 tokens d'écart sont compatibles avec son gabarit de conversation appliqué côté serveur.
- **Troncature** : `max_tokens_per_doc=512` donne 522 tokens (bge) et 589 (Qwen3) sur l'offre la
  plus longue, contre 4 751 et 5 097. Défaut de l'API : 4 096 par document.
- **MiniLM refuse** (HTTP 413) tout texte de plus de 128 tokens au lieu de le tronquer :
  `embeddings.Model.max_chars` coupe avant l'envoi. Offre et CV n'y sont vus que par leur début.
- **MiniLM multilingue ?** Doute sérieux, malgré l'affichage : FR/EN 0,13, sous une paire sans
  rapport (0,24). FR/DE fait 0,50, mais les deux textes partagent « Detail/détail ». Une paire
  par cas : indice cohérent avec un modèle anglais, pas une preuve.
- **Requête** : les fiches de Qwen3-Embedding et de Gemma2 demandent une instruction côté requête,
  rien côté document (gabarits dans `embeddings.EMBEDDERS`).

## Longueur des offres (étape 1)

Tokens facturés, lots de 32 triés par longueur (moyenne par lot : le maximum est sous-estimé).

| Modèle | Offres | n | Moyenne | Médiane | p95 |
|---|---|---|---|---|---|
| Qwen3 | toutes | 5 216 | 426 | 26 | 1 259 |
| Qwen3 | titre seul | 2 647 | 14 | 13 | 23 |
| Qwen3 | avec description | 2 569 | 852 | 788 | 1 527 |
| Gemma2 | toutes | 5 216 | 381 | 24 | 1 196 |
| Gemma2 | avec description | 2 569 | 760 | 682 | 1 459 |

L'hypothèse « 1 000 tokens par offre » était 2,3 fois trop haute en moyenne (852 pour les
seules offres décrites). 5 216 offres ne font que 3 256 textes distincts : indexer tout le
corpus coûte **0,155 CHF** (Qwen3) ou **0,129 CHF** (Gemma2), une seule fois.

Coût mensuel estimé (Qwen3, ~150 offres nouvelles par jour : 184 et 82 vues les 16 et 17.11,
échantillon trop petit pour en faire une moyenne) : 4 500 offres × 426 tokens ≈ 1,9 M tokens
≈ **0,13 CHF** (0,32 avec 1 000 tokens par offre). Une recommandation coûte de 0,00005 CHF
(vecteurs) à ~0,0015 CHF (60 candidats reclassés) : 1 000 recommandations ≈ 0,05 à 1,5 CHF.

## Date de coupure (étape 4)

`experiments/date_de_coupure.py`, [graphique](img/m4-date-de-coupure.png).

| Paire | Qwen3 | Gemma2 | MiniLM |
|---|---|---|---|
| MCP / Model Context Protocol | 0,715 | 0,643 | 0,266 |
| vibe coding / dév. assisté par IA | 0,679 | 0,593 | 0,193 |
| témoin FR/FR | 0,802 | 0,871 | 0,400 |
| témoin FR/EN | 0,897 | 0,732 | 0,126 |
| témoin FR/DE | 0,929 | 0,688 | 0,499 |
| sens opposé | 0,658 | 0,675 | 0,579 |
| sans rapport | 0,600 | 0,561 | 0,242 |
| piège lexical (codage) | 0,609 | 0,597 | 0,145 |

Lecture : les valeurs absolues ne se comparent pas d'un modèle à l'autre. Pour chaque modèle, la
paire récente se situe-t-elle plus près des témoins ou des paires sans rapport ? Qwen3 : 0,715 et
0,679, nettement sous les témoins (0,80 à 0,93) et 0,07 à 0,12 au-dessus des paires sans
rapport. Gemma2 (2024) : la paire « vibe coding » (0,593) est au niveau du piège lexical (0,597),
rien n'indique qu'elle soit reconnue ; « MCP » (0,643) l'est un peu plus. Les deux modèles rapprochent autant
des phrases de sens OPPOSÉ (0,66 à 0,68) que les paires récentes : un embedding voit le sujet,
pas la polarité. Une seule paire par cas : un indice, pas une preuve.
