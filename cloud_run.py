"""Une passe complète pour GitHub Actions : collecte -> compaction -> export du site.

Écrit `changed=true|false` dans $GITHUB_OUTPUT pour ne republier le site que s'il y a du nouveau.
"""
import os
import sys
import time

from bz.api import BlizzardAPI, ROOT
from bz.db import compact, connect
from collect import Source, collect_once, log
import export


def snapshot_count(con):
    return con.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    src = Source()
    api = BlizzardAPI()
    con = connect()

    before = snapshot_count(con)
    collect_once(api, con, src)
    changed = snapshot_count(con) > before or "--force-export" in sys.argv

    if changed:
        removed = compact(con, keep_hourly_days=int(os.environ.get("BZ_KEEP_HOURLY_DAYS", "14")))
        if removed:
            log(f"Compaction : {removed} points horaires anciens regroupés par jour")
            con.execute("VACUUM")
        con.close()
        t0 = time.time()
        export.export(ROOT / "site")
        log(f"Site exporté ({time.time() - t0:.1f}s)")
    else:
        con.close()
        log("Rien de nouveau, pas de republication.")

    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"changed={'true' if changed else 'false'}\n")


if __name__ == "__main__":
    main()
