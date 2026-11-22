"""Collecte les snapshots des HV WoW Forever et les stocke dans SQLite.

  python collect.py          # une passe
  python collect.py --loop   # vérifie toutes les 10 min, n'enregistre que les nouveaux snapshots

Endpoints : /data/wow/ruleset/{r}/auctions/{hv} + /commodities  (namespace dynamic-forever-eu)
"""
import argparse
import os
import sys
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime

from bz.api import BlizzardAPI, load_env, retail_static_namespace, static_namespace
from bz.db import connect, ingest


def log(msg):
    print(time.strftime("[%H:%M:%S] ") + msg, flush=True)


class Source:
    def __init__(self):
        load_env()
        self.ns = os.environ.get("BZ_NAMESPACE")
        self.ruleset = os.environ.get("BZ_RULESET")
        self.houses = [int(x) for x in os.environ.get("BZ_AUCTION_HOUSES", "").split(",") if x.strip()]
        self.label = os.environ.get("BZ_REALM_NAME", "")
        if not self.ns or not self.ruleset or not self.houses:
            raise SystemExit("Config incomplète dans .env. Lance d'abord : python discover.py --save")
        self.base = f"/data/wow/ruleset/{self.ruleset}/auctions/"  # slash final obligatoire

    def key(self, ah):
        return f"r{self.ruleset}-{ah}"


def fetch_items(api, con, ns):
    """Récupère nom / qualité / icône des objets encore inconnus (repli sur le catalogue retail)."""
    missing = [r[0] for r in con.execute(
        "SELECT DISTINCT item_id FROM live_auctions WHERE item_id NOT IN (SELECT id FROM items)")]
    if not missing:
        return
    log(f"Récupération de {len(missing)} fiches objets (une seule fois, quelques minutes)…")
    namespaces = [static_namespace(ns), retail_static_namespace(ns)]

    def one(item_id):
        try:
            return lookup(item_id)
        except Exception as e:  # erreur réseau persistante : on réessaiera au prochain passage
            log(f"  objet {item_id} : {e!r}")
            return None

    def lookup(item_id):
        for sns in namespaces:
            try:
                j, _ = api.get(f"/data/wow/item/{item_id}", sns)
            except urllib.error.HTTPError:
                continue
            icon = None
            try:
                m, _ = api.get(f"/data/wow/media/item/{item_id}", sns)
                icon = next((a["value"] for a in m.get("assets", []) if a.get("key") == "icon"), None)
            except urllib.error.HTTPError:
                pass
            return (item_id, j.get("name"), (j.get("quality") or {}).get("type"), icon, int(time.time()))
        return (item_id, f"Objet #{item_id}", None, None, int(time.time()))

    done = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        batch = []
        for row in pool.map(one, missing):
            done += 1
            if row is None:
                continue
            batch.append(row)
            if len(batch) >= 250:
                with con:
                    con.executemany("INSERT OR REPLACE INTO items VALUES (?,?,?,?,?)", batch)
                batch = []
                log(f"  {done}/{len(missing)} objets")
        if batch:
            with con:
                con.executemany("INSERT OR REPLACE INTO items VALUES (?,?,?,?,?)", batch)
    log("Fiches objets à jour.")


def collect_once(api, con, src):
    names = {}
    try:
        j, _ = api.get(src.base, src.ns)
        names = {h["id"]: h.get("name") for h in j.get("auctions", [])}
    except urllib.error.HTTPError as e:
        log(f"Index des HV : HTTP {e.code}")

    for ah in src.houses:
        key = src.key(ah)
        with con:
            con.execute("INSERT OR REPLACE INTO auction_houses VALUES (?,?,?,?,?)",
                        (key, int(src.ruleset), ah, names.get(ah, f"HV {ah}"), src.label))
        row = con.execute("SELECT last_modified FROM snapshots WHERE ah_key=? ORDER BY ts DESC LIMIT 1",
                          (key,)).fetchone()
        last = row[0] if row else None
        try:
            data, headers = api.get(f"{src.base}{ah}", src.ns, if_modified_since=last)
        except urllib.error.HTTPError as e:
            log(f"{key}: HTTP {e.code}")
            continue
        lm = headers.get("Last-Modified")
        if data is None or (lm and lm == last):
            log(f"{key}: pas de nouveau snapshot")
            continue
        auctions = list(data.get("auctions") or [])
        if "commodities" in data:  # les commodités (composants, conso…) sont servies à part
            try:
                c, _ = api.get(f"{src.base}{ah}/commodities", src.ns)
                auctions += c.get("auctions") or []
            except urllib.error.HTTPError as e:
                log(f"{key}: commodités HTTP {e.code}")
        ts = int(parsedate_to_datetime(lm).timestamp()) if lm else int(time.time())
        t0 = time.time()
        res = ingest(con, key, ts, auctions, lm)
        log(f"{key} ({names.get(ah, '')}): {res['auctions']} annonces, {res['items']} objets, "
            f"~{res['sold_est']} unités vendues depuis le dernier snapshot ({time.time() - t0:.1f}s)")
    fetch_items(api, con, src.ns)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--interval", type=int, default=600, help="secondes entre deux vérifications")
    args = ap.parse_args()

    src = Source()
    api = BlizzardAPI()
    con = connect()
    while True:
        try:
            collect_once(api, con, src)
        except Exception as e:  # on ne veut pas que la boucle meure pour une erreur réseau
            if not args.loop:
                raise
            log(f"Erreur : {e!r}")
        if not args.loop:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
