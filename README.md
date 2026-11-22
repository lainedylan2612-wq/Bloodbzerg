# BZ Terminal — HV WoW Forever façon Bloomberg

Prototype sans dépendance (Python 3.10+ standard + une page HTML).

## Le plus simple

Double-clique sur **`Lancer BZ Terminal.bat`**. Une fenêtre s'ouvre avec trois boutons : démarrer la collecte, l'arrêter, ouvrir le terminal. Elle propose aussi le lancement automatique au démarrage de Windows et un raccourci sur le Bureau.

## Démarrage en ligne de commande

1. Identifiants : client sur https://develop.battle.net/access/clients, à copier dans `.env` (voir `.env.example`).
2. Config (déjà faite pour l'HV Horde PvP EU) :
   ```
   python discover.py                               # liste rulesets + HV
   python discover.py --save --ruleset 1 --ah 113   # Horde PvP
   python discover.py --save --ah 110,113,116       # Alliance + Horde + Flots noirs
   ```
3. Collecte et terminal (deux terminaux) :
   ```
   python collect.py --loop
   python server.py
   ```
   Puis ouvre http://localhost:8765

Démo hors ligne : `python demo_seed.py` puis `python server.py --db data/demo.db`.

## Comment WoW Forever est exposé dans l'API (non documenté par Blizzard)

- Namespace `dynamic-forever-eu` pour les HV, `static-forever-eu` pour les objets.
- Il n'y a pas de royaumes mais des **rulesets** : 1 = PvP, 2 = Normal, 3 = RP, 15 = RP PvP.
- `/data/wow/ruleset/{r}/auctions/` (le slash final est obligatoire) donne la liste des HV, avec les ids 110 à 125.
- `/data/wow/ruleset/{r}/auctions/{hv}` donne les objets, et `/data/wow/ruleset/{r}/auctions/{hv}/commodities` les composants et consommables. Le collecteur fusionne les deux.
- **HV EU PvP** (d'après la communauté et Blackwater Exchange) : 110 = Alliance, 113 = Horde, 116 = Flots noirs.
- Tous les rulesets renvoient actuellement les mêmes HV : ne pas additionner.
- Environ 40 % des objets n'ont pas de fiche `static-forever`. Le nom est alors pris dans le catalogue retail (`static-eu`).

## Fichiers

| Fichier | Rôle |
|---|---|
| `bz/api.py` | OAuth, requêtes, limitation de débit (30 req/s) |
| `bz/db.py` | Schéma SQLite, ingestion d'un snapshot, stats et ventes estimées |
| `discover.py` | Liste les rulesets et HV, enregistre la config |
| `collect.py` | Collecte les snapshots et les fiches objets |
| `server.py` | API JSON + interface |
| `static/index.html` | Interface (tableau, graphiques, carnet d'ordres) |
| `demo_seed.py` | Données synthétiques pour tester |

## Limites

- **Ventes estimées** : une annonce qui disparaît alors qu'il lui restait LONG ou VERY_LONG est comptée comme vendue. Les annulations sont comptées à tort.
- Les variantes d'un objet (bonus, suffixes) sont regroupées par id d'objet.
- L'historique commence au premier lancement du collecteur.
- La première collecte récupère environ 7 000 fiches objets, ce qui prend 5 à 10 minutes une seule fois.
