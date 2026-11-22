"""Stockage SQLite + ingestion d'un snapshot d'HV (calcul des stats et des ventes estimées)."""
import os
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from .api import ROOT

DEFAULT_DB = ROOT / "data" / "auctions.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS auction_houses (
    key TEXT PRIMARY KEY,            -- "<connected_realm>-<ah_id>"
    connected_realm INTEGER,
    ah_id INTEGER,
    name TEXT,
    realm_name TEXT
);
CREATE TABLE IF NOT EXISTS snapshots (
    ah_key TEXT, ts INTEGER, last_modified TEXT, n_auctions INTEGER,
    PRIMARY KEY (ah_key, ts)
);
-- État courant de l'HV (sert au carnet d'ordres et à détecter les ventes)
CREATE TABLE IF NOT EXISTS live_auctions (
    ah_key TEXT, auction_id INTEGER, item_id INTEGER, quantity INTEGER,
    unit_price INTEGER, bid INTEGER, time_left TEXT, first_seen INTEGER,
    PRIMARY KEY (ah_key, auction_id)
);
CREATE INDEX IF NOT EXISTS ix_live_item ON live_auctions(ah_key, item_id, unit_price);
-- Série temporelle agrégée par objet et par snapshot (prix en cuivre, par unité)
CREATE TABLE IF NOT EXISTS item_stats (
    ah_key TEXT, ts INTEGER, item_id INTEGER,
    min_unit INTEGER, median_unit INTEGER, qty INTEGER, n_auctions INTEGER,
    sold_qty_est INTEGER,
    PRIMARY KEY (ah_key, item_id, ts)
);
CREATE INDEX IF NOT EXISTS ix_stats_ts ON item_stats(ah_key, ts);
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY, name TEXT, quality TEXT, icon TEXT, fetched_at INTEGER
);
"""

# Une annonce qui disparaît alors qu'il lui restait beaucoup de temps a très
# probablement été achetée (ou annulée — indiscernable via l'API).
SOLD_TIME_LEFT = {"LONG", "VERY_LONG"}


def connect(path=None):
    path = Path(path or os.environ.get("BZ_DB") or DEFAULT_DB)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    return con


def weighted_median(prices):
    """prices: liste triée de (prix_unitaire, quantité)."""
    total = sum(q for _, q in prices)
    half = total / 2
    cum = 0
    for p, q in prices:
        cum += q
        if cum >= half:
            return p
    return prices[-1][0]


def ingest(con, ah_key, ts, auctions, last_modified=None):
    """Intègre un snapshot complet d'une HV. Retourne un petit résumé."""
    prev = {
        r["auction_id"]: r
        for r in con.execute(
            "SELECT auction_id, item_id, quantity, time_left, first_seen FROM live_auctions WHERE ah_key=?",
            (ah_key,),
        )
    }

    cur = {}
    prices = defaultdict(list)
    count = Counter()
    qty = Counter()
    for a in auctions:
        item = (a.get("item") or {}).get("id")
        if not item:
            continue
        q = a.get("quantity") or 1
        buyout = a.get("buyout") or 0
        unit = a.get("unit_price") or (buyout // q if buyout else 0)
        count[item] += 1
        qty[item] += q
        if unit > 0:
            prices[item].append((unit, q))
        cur[a["id"]] = (item, q, unit, a.get("bid") or 0, a.get("time_left"))

    sold = Counter()
    if prev:  # pas d'estimation au tout premier snapshot
        for aid, r in prev.items():
            if aid not in cur and r["time_left"] in SOLD_TIME_LEFT:
                sold[r["item_id"]] += r["quantity"]

    rows = []
    for item in set(count) | set(sold):
        p = sorted(prices.get(item, []))
        mn = p[0][0] if p else None
        med = weighted_median(p) if p else None
        rows.append((ah_key, ts, item, mn, med, qty[item], count[item], sold[item]))

    with con:
        con.execute("DELETE FROM live_auctions WHERE ah_key=?", (ah_key,))
        con.executemany(
            "INSERT INTO live_auctions VALUES (?,?,?,?,?,?,?,?)",
            [
                (ah_key, aid, it, q, unit, bid, tl, prev[aid]["first_seen"] if aid in prev else ts)
                for aid, (it, q, unit, bid, tl) in cur.items()
            ],
        )
        con.executemany("INSERT OR REPLACE INTO item_stats VALUES (?,?,?,?,?,?,?,?)", rows)
        con.execute(
            "INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?)", (ah_key, ts, last_modified, len(cur))
        )
    return {"auctions": len(cur), "items": len(count), "sold_est": sum(sold.values())}


def compact(con, keep_hourly_days=14):
    """Au-delà de `keep_hourly_days`, ne garde qu'un point par objet et par jour
    (le dernier de la journée, avec les ventes estimées de la journée cumulées)."""
    cur = con.execute("SELECT MAX(ts) FROM item_stats").fetchone()[0]
    if not cur:
        return 0
    cut = cur - keep_hourly_days * 86400
    with con:
        con.execute("DROP TABLE IF EXISTS temp.k")
        con.execute("""CREATE TEMP TABLE k AS
            SELECT ah_key, item_id, ts/86400 AS d, MAX(ts) AS keep, SUM(sold_qty_est) AS s
            FROM item_stats WHERE ts < ? GROUP BY ah_key, item_id, d HAVING COUNT(*) > 1""", (cut,))
        con.execute("""UPDATE item_stats SET sold_qty_est = k.s FROM k
            WHERE item_stats.ah_key=k.ah_key AND item_stats.item_id=k.item_id AND item_stats.ts=k.keep""")
        n = con.execute("""DELETE FROM item_stats WHERE ts < ? AND EXISTS (
            SELECT 1 FROM k WHERE k.ah_key=item_stats.ah_key AND k.item_id=item_stats.item_id
              AND k.d=item_stats.ts/86400 AND k.keep<>item_stats.ts)""", (cut,)).rowcount
        con.execute("DROP TABLE temp.k")
    return n
