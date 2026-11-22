"""Mise à jour silencieuse de l'addon (lancée toutes les 15 min par la tâche planifiée Windows).
Journal : data/sync.log
"""
import time

from bz.api import ROOT
from bz import sync

LOG = ROOT / "data" / "sync.log"


def log(msg):
    LOG.parent.mkdir(exist_ok=True)
    lines = LOG.read_text(encoding="utf-8").splitlines()[-300:] if LOG.exists() else []
    lines.append(time.strftime("[%d/%m %H:%M:%S] ") + msg)
    LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    try:
        sync.run(log)
    except Exception as e:
        log(f"Échec : {e}")
