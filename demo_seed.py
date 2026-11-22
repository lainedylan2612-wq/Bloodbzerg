"""Génère une base de démo (7 jours de snapshots horaires synthétiques) dans data/demo.db.
Utilise la même fonction d'ingestion que le vrai collecteur.

  python demo_seed.py && python server.py --db data/demo.db
"""
import math
import random
import sys
import time

from bz.api import ROOT
from bz.db import connect, ingest

ITEMS = [  # id, nom, qualité, prix de base (cuivre), offre moyenne (nb annonces)
    (12359, "Thorium Bar", "COMMON", 9000, 40), (12360, "Arcanite Bar", "UNCOMMON", 450000, 6),
    (13463, "Dreamfoil", "COMMON", 12000, 35), (13464, "Golden Sansam", "COMMON", 15000, 30),
    (13465, "Mountain Silversage", "COMMON", 22000, 25), (13467, "Icecap", "COMMON", 18000, 15),
    (13468, "Black Lotus", "UNCOMMON", 1200000, 3), (8846, "Gromsblood", "COMMON", 14000, 20),
    (8831, "Purple Lotus", "COMMON", 6000, 25), (14047, "Runecloth", "COMMON", 3500, 80),
    (7076, "Essence of Earth", "UNCOMMON", 30000, 12), (7078, "Essence of Fire", "UNCOMMON", 85000, 8),
    (12811, "Righteous Orb", "UNCOMMON", 160000, 5), (20725, "Nexus Crystal", "EPIC", 950000, 4),
    (16204, "Illusion Dust", "COMMON", 35000, 30), (16203, "Greater Eternal Essence", "UNCOMMON", 120000, 15),
    (13444, "Major Mana Potion", "COMMON", 55000, 20), (13446, "Major Healing Potion", "COMMON", 28000, 25),
    (12808, "Essence of Undeath", "UNCOMMON", 70000, 10), (7910, "Star Ruby", "UNCOMMON", 40000, 10),
    (12364, "Huge Emerald", "RARE", 600000, 3), (12799, "Large Opal", "RARE", 250000, 4),
    (8170, "Rugged Leather", "COMMON", 5000, 60), (15417, "Devilsaur Leather", "UNCOMMON", 180000, 6),
    (12804, "Powerful Mojo", "UNCOMMON", 45000, 10), (11382, "Blood of the Mountain", "UNCOMMON", 300000, 3),
    (13926, "Golden Pearl", "RARE", 400000, 3), (19774, "Souldarite", "UNCOMMON", 150000, 2),
]
TIME_LEFT = ["SHORT", "MEDIUM", "LONG", "LONG", "VERY_LONG", "VERY_LONG"]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    path = ROOT / "data" / "demo.db"
    for suffix in ("", "-wal", "-shm"):
        p = path.with_name(path.name + suffix)
        if p.exists():
            p.unlink()
    con = connect(path)
    rnd = random.Random(42)
    with con:
        con.executemany("INSERT INTO auction_houses VALUES (?,?,?,?,?)", [
            ("9999-2", 9999, 2, "Alliance", "Démo"), ("9999-6", 9999, 6, "Horde", "Démo")])
        con.executemany("INSERT INTO items VALUES (?,?,?,?,?)",
                        [(i, n, q, None, 0) for i, n, q, _, _ in ITEMS])

    now = int(time.time()) // 3600 * 3600
    hours = 24 * 7
    next_id = 1
    for ah_key, bias in (("9999-2", 1.05), ("9999-6", 1.0)):
        level = {i: 0.0 for i, *_ in ITEMS}
        pool = {}  # auction_id -> dict
        for h in range(hours, -1, -1):
            ts = now - h * 3600
            # disparitions : la plupart des annonces "chères" restent, les moins chères partent (ventes)
            for aid in list(pool):
                a = pool[aid]
                ref = ITEMS_BY_ID[a["item"]["id"]][3] * bias * math.exp(level[a["item"]["id"]])
                p_sell = 0.35 if a["buyout"] / a["quantity"] < ref else 0.08
                if rnd.random() < p_sell:
                    del pool[aid]
                elif rnd.random() < 0.25:  # le temps passe
                    a["time_left"] = TIME_LEFT[max(0, TIME_LEFT.index(a["time_left"]) - 1)]
            for item_id, _, _, base, supply in ITEMS:
                level[item_id] = 0.92 * level[item_id] + rnd.gauss(0, 0.06)
                if h == 30 and item_id == 13468:  # un petit choc pour la démo
                    level[item_id] += 0.5
                if h == 5 and item_id == 12359:
                    level[item_id] -= 0.4
                ref = base * bias * math.exp(level[item_id])
                for _ in range(rnd.randint(0, max(1, supply // 4))):
                    qty = rnd.choice([1, 1, 5, 10, 20]) if base < 60000 else 1
                    unit = int(ref * rnd.uniform(0.85, 1.4))
                    pool[next_id] = {"id": next_id, "item": {"id": item_id}, "quantity": qty,
                                     "buyout": unit * qty, "bid": int(unit * qty * 0.8),
                                     "time_left": rnd.choice(TIME_LEFT[2:])}
                    next_id += 1
            ingest(con, ah_key, ts, list(pool.values()), None)
        print(f"{ah_key}: {hours + 1} snapshots, {len(pool)} annonces en cours")
    print(f"Base de démo : {path}\nLance : python server.py --db data/demo.db")


ITEMS_BY_ID = {i[0]: i for i in ITEMS}

if __name__ == "__main__":
    main()
