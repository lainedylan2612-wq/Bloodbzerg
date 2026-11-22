"""Installe l'addon et télécharge les dernières données (Data.lua) depuis GitHub Pages."""
import json
import os
import shutil
import time
import urllib.request
from pathlib import Path

from .api import ROOT

CONFIG = ROOT / "launcher.json"
ADDON_SRC = ROOT / "addon" / "BZTerminal"
SITE_URL = "https://lainedylan2612-wq.github.io/Bloodbzerg/"
WOW_CANDIDATES = [
    Path(r"C:\Program Files (x86)\World of Warcraft\_forever_"),
    Path(r"C:\Program Files\World of Warcraft\_forever_"),
] + [Path(f"{d}:\\") / sub / "_forever_" for d in "CDEFG"
     for sub in ("World of Warcraft", r"Games\World of Warcraft", r"Program Files (x86)\World of Warcraft")]


def load_config():
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    CONFIG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def find_wow():
    for p in WOW_CANDIDATES:
        if (p / "Interface").is_dir() or (p / "Wow.exe").exists():
            return p
    return None


def wow_path():
    """Dossier _forever_ : celui de launcher.json, sinon détection automatique (mémorisée)."""
    cfg = load_config()
    p = cfg.get("wow_path")
    if p and Path(p).is_dir():
        return Path(p)
    found = find_wow()
    if found:
        cfg["wow_path"] = str(found)
        save_config(cfg)
    return found


def fetch(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "BZ-Terminal-Sync", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def run(log=print, wow=None):
    """Met à jour l'addon. Retourne meta.json du site (ou lève une exception)."""
    wow = wow or wow_path()
    if not wow:
        raise RuntimeError("dossier WoW Forever introuvable (choisis-le dans le lanceur)")
    dest = wow / "Interface" / "AddOns" / "BZTerminal"
    dest.mkdir(parents=True, exist_ok=True)
    fresh = not (dest / "BZTerminal.toc").exists()
    for f in ADDON_SRC.iterdir():
        if f.name != "Data.lua":
            shutil.copy2(f, dest / f.name)
    if fresh:
        log(f"Addon installé dans {dest}")

    meta = json.loads(fetch(SITE_URL + "api/meta.json"))
    data = fetch(SITE_URL + "Data.lua", timeout=120)
    tmp = dest / "Data.lua.tmp"
    tmp.write_bytes(data)
    os.replace(tmp, dest / "Data.lua")

    h = (meta.get("houses") or [{}])[0]
    ts = h.get("last_ts")
    when = time.strftime("%d/%m %H:%M", time.localtime(ts)) if ts else "?"
    log(f"Données à jour (HV du {when}, {len(data) // 1024} Ko)."
        + ("  Lance le jeu : l'addon est prêt." if fresh else "  En jeu : /reload"))
    return meta
