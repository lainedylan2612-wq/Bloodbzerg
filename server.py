"""Serveur local du terminal : API JSON + interface.

  python server.py                    # http://localhost:8765
  python server.py --db data/demo.db  # sur les données de démo
"""
import argparse
import json
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from bz.api import ROOT
from bz.db import connect

STATIC = ROOT / "static"
DB_PATH = None


def q(sql, params=()):
    con = connect(DB_PATH)
    try:
        return [dict(r) for r in con.execute(sql, params)]
    finally:
        con.close()


def latest_ts(ah):
    r = q("SELECT MAX(ts) AS t FROM snapshots WHERE ah_key=?", (ah,))
    return r[0]["t"] if r else None


def api_meta(_):
    houses = q("""SELECT h.key, h.name, h.realm_name,
                         (SELECT MAX(ts) FROM snapshots s WHERE s.ah_key=h.key) AS last_ts,
                         (SELECT COUNT(*) FROM snapshots s WHERE s.ah_key=h.key) AS n_snapshots,
                         (SELECT n_auctions FROM snapshots s WHERE s.ah_key=h.key ORDER BY ts DESC LIMIT 1) AS n_auctions
                  FROM auction_houses h ORDER BY h.ah_id""")
    return {"houses": houses}


def api_board(p):
    ah = p["ah"]
    L = latest_ts(ah)
    if L is None:
        return {"ts": None, "rows": []}
    prev = q("SELECT MAX(ts) AS t FROM snapshots WHERE ah_key=? AND ts<=?", (ah, L - 86400))[0]["t"]
    if prev is None:  # moins de 24h d'historique : on compare au plus vieux snapshot
        prev = q("SELECT MIN(ts) AS t FROM snapshots WHERE ah_key=?", (ah,))[0]["t"]
    rows = q("""
        WITH d1 AS (SELECT item_id, SUM(sold_qty_est) AS sold24 FROM item_stats
                    WHERE ah_key=:ah AND ts>:t24 GROUP BY item_id),
             d7 AS (SELECT item_id, AVG(median_unit) AS med7, COUNT(*) AS n7 FROM item_stats
                    WHERE ah_key=:ah AND ts>:t7 AND median_unit IS NOT NULL GROUP BY item_id)
        SELECT s.item_id AS id, i.name, i.quality, i.icon,
               s.min_unit AS min, s.median_unit AS med, s.qty, s.n_auctions AS n,
               p.min_unit AS min_prev, d1.sold24, d7.med7, d7.n7
        FROM item_stats s
        LEFT JOIN item_stats p ON p.ah_key=s.ah_key AND p.item_id=s.item_id AND p.ts=:prev
        LEFT JOIN d1 ON d1.item_id=s.item_id
        LEFT JOIN d7 ON d7.item_id=s.item_id
        LEFT JOIN items i ON i.id=s.item_id
        WHERE s.ah_key=:ah AND s.ts=:L AND s.qty>0
    """, {"ah": ah, "L": L, "prev": prev, "t24": L - 86400, "t7": L - 7 * 86400})
    return {"ts": L, "prev_ts": prev, "rows": rows}


def api_item(p):
    ah, item = p["ah"], int(p["id"])
    info = q("SELECT * FROM items WHERE id=?", (item,))
    hist = q("""SELECT ts, min_unit AS min, median_unit AS med, qty, n_auctions AS n, sold_qty_est AS sold
                FROM item_stats WHERE ah_key=? AND item_id=? ORDER BY ts""", (ah, item))
    book = q("""SELECT unit_price AS price, SUM(quantity) AS qty, COUNT(*) AS n
                FROM live_auctions WHERE ah_key=? AND item_id=? AND unit_price>0
                GROUP BY unit_price ORDER BY unit_price LIMIT 60""", (ah, item))
    return {"item": info[0] if info else {"id": item}, "history": hist, "book": book}


ROUTES = {"/api/meta": api_meta, "/api/board": api_board, "/api/item": api_item}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        if url.path in ROUTES:
            params = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
            try:
                data = ROUTES[url.path](params)
                self._send(200, json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8")
            except Exception as e:
                self._send(500, json.dumps({"error": repr(e)}).encode(), "application/json")
            return
        if url.path in ("/", "/index.html"):
            self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            return
        self._send(404, b"not found", "text/plain")

    def log_message(self, *a):
        pass


def main():
    global DB_PATH
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--db")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    DB_PATH = args.db
    connect(DB_PATH).close()
    print(f"Terminal disponible sur http://localhost:{args.port}  (Ctrl+C pour arrêter)")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
