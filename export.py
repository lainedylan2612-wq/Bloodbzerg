"""Exporte la base en site statique (GitHub Pages) + Data.lua pour l'addon.

  python export.py            # écrit dans ./site
  python export.py --out dossier
"""
import argparse
import json
import shutil
import sys
import time
from collections import defaultdict
from pathlib import Path

from bz.api import ROOT
from bz.db import connect

BUCKETS = 100  # les historiques d'objets sont regroupés en 100 fichiers (id % 100)
SITE_HISTORY_DAYS = 90


def dump(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def export(out: Path, db=None):
    import server  # réutilise exactement les requêtes du serveur local
    server.DB_PATH = db
    con = connect(db)

    if out.exists():
        shutil.rmtree(out)
    (out / "api").mkdir(parents=True)

    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    html = html.replace("<head>", "<head>\n<script>window.BZ_STATIC = true;</script>", 1)
    (out / "index.html").write_text(html, encoding="utf-8")
    (out / ".nojekyll").write_text("")

    meta = server.api_meta({})
    meta["generated"] = int(time.time())
    dump(out / "api" / "meta.json", meta)

    lua_houses = []
    for h in meta["houses"]:
        ah = h["key"]
        board = server.api_board({"ah": ah})
        dump(out / "api" / "board" / f"{ah}.json", board)
        if not board["ts"]:
            continue

        # historiques + carnets d'ordres, regroupés par paquet d'objets
        since = board["ts"] - SITE_HISTORY_DAYS * 86400
        buckets = defaultdict(dict)
        info = {r["id"]: r for r in con.execute("SELECT id, name, quality, icon FROM items")}
        for r in con.execute("""SELECT item_id, ts, min_unit, median_unit, qty, n_auctions, sold_qty_est
                                FROM item_stats WHERE ah_key=? AND ts>=? ORDER BY item_id, ts""", (ah, since)):
            e = buckets[r[0] % BUCKETS].setdefault(r[0], {"h": [], "b": []})
            e["h"].append(list(r[1:]))
        for r in con.execute("""SELECT item_id, unit_price, SUM(quantity), COUNT(*) FROM live_auctions
                                WHERE ah_key=? AND unit_price>0 GROUP BY item_id, unit_price
                                ORDER BY item_id, unit_price""", (ah,)):
            e = buckets[r[0] % BUCKETS].setdefault(r[0], {"h": [], "b": []})
            if len(e["b"]) < 60:
                e["b"].append(list(r[1:]))
        for b, items in buckets.items():
            for iid, e in items.items():
                i = info.get(iid)
                e["i"] = [i["name"], i["quality"], i["icon"]] if i else [None, None, None]
            dump(out / "api" / "items" / ah / f"{b}.json", items)

        lua_houses.append((h, board))

    write_lua(out / "Data.lua", lua_houses)
    con.close()
    return meta


def lua_str(s):
    return '"' + str(s or "").replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


def write_lua(path: Path, houses):
    """Données compactes pour l'addon : par objet {min, médiane, moy. médiane 7j, ventes 24h, min il y a 24h}."""
    lines = ["-- Généré automatiquement par BZ Terminal, ne pas modifier.", "BZT_DATA = {",
             f"  generated = {int(time.time())},", "  houses = {"]
    for h, board in houses:
        lines.append(f"    [{lua_str(h['key'])}] = {{ name = {lua_str(h['name'])}, ts = {board['ts']}, items = {{")
        for r in board["rows"]:
            vals = [r["min"], r["med"], round(r["med7"]) if r["med7"] else None, r["sold24"], r["min_prev"]]
            lines.append(f"      [{r['id']}]={{{','.join('nil' if v is None else str(int(v)) for v in vals)}}},")
        lines.append("    } },")
    lines += ["  },", "}", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "site"))
    ap.add_argument("--db")
    args = ap.parse_args()
    t0 = time.time()
    meta = export(Path(args.out), args.db)
    print(f"Site exporté dans {args.out} ({len(meta['houses'])} HV, {time.time() - t0:.1f}s)")


if __name__ == "__main__":
    main()
