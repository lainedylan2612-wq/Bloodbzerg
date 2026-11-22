"""BZ Terminal — lanceur (double-clic).

La collecte tourne sur GitHub. Ce lanceur :
  - installe / met à jour l'addon BZTerminal dans WoW Forever,
  - télécharge les dernières données (Data.lua) toutes les 15 min,
  - ouvre le terminal en ligne.
"""
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.request
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "launcher.json"
ADDON_SRC = ROOT / "addon" / "BZTerminal"
SITE_URL = "https://lainedylan2612-wq.github.io/Bloodbzerg/"
SYNC_EVERY = 15 * 60
STARTUP_LNK = Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup\BZ Terminal.lnk"
DESKTOP_LNK = Path.home() / "Desktop" / "BZ Terminal.lnk"
WOW_CANDIDATES = [
    Path(r"C:\Program Files (x86)\World of Warcraft\_forever_"),
    Path(r"C:\Program Files\World of Warcraft\_forever_"),
] + [Path(f"{d}:\\") / sub / "_forever_" for d in "CDEFG"
     for sub in ("World of Warcraft", r"Games\World of Warcraft", r"Program Files (x86)\World of Warcraft")]

BG, PANEL, AMBER, TXT, MUTE, GREEN, RED = "#0b0b0b", "#151515", "#ffa028", "#e0e0e0", "#808080", "#3ddc84", "#ff5c5c"
FONT = ("Consolas", 10)


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


def fetch(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "BZ-Terminal-Launcher", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def make_shortcut(lnk: Path, extra_args=""):
    pyw = Path(sys.executable).with_name("pythonw.exe")
    target = pyw if pyw.exists() else Path(sys.executable)
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:BZ_LNK);"
          "$s.TargetPath=$env:BZ_TARGET;$s.Arguments=$env:BZ_ARGS;"
          "$s.WorkingDirectory=$env:BZ_DIR;$s.Description='BZ Terminal';$s.Save()")
    env = dict(os.environ, BZ_LNK=str(lnk), BZ_TARGET=str(target),
               BZ_ARGS=f'"{ROOT / "launcher.pyw"}" {extra_args}'.strip(), BZ_DIR=str(ROOT))
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], env=env, check=True,
                   creationflags=subprocess.CREATE_NO_WINDOW)


class App:
    def __init__(self, root):
        self.root = root
        self.cfg = load_config()
        self.logq = queue.Queue()
        self.busy = False
        self.meta = None
        self.last_sync = None

        root.title("BZ Terminal")
        root.configure(bg=BG)
        root.geometry("720x500")
        root.minsize(600, 420)

        top = tk.Frame(root, bg=AMBER)
        top.pack(fill="x")
        tk.Label(top, text=" BZ TERMINAL · WoW Forever", bg=AMBER, fg="#000",
                 font=("Consolas", 13, "bold"), pady=6).pack(side="left")

        st = tk.Frame(root, bg=PANEL, padx=14, pady=10)
        st.pack(fill="x", padx=12, pady=(12, 6))
        self.lbl_state = tk.Label(st, text="", bg=PANEL, fg=TXT, font=("Consolas", 12, "bold"), anchor="w")
        self.lbl_state.pack(fill="x")
        self.lbl_info = tk.Label(st, text="", bg=PANEL, fg=MUTE, font=FONT, anchor="w", justify="left")
        self.lbl_info.pack(fill="x", pady=(4, 0))

        bt = tk.Frame(root, bg=BG)
        bt.pack(fill="x", padx=12, pady=6)
        self.btn_sync = self.button(bt, "⟳  Mettre à jour maintenant", self.sync_async, primary=True)
        self.button(bt, "Ouvrir le terminal  ↗", lambda: webbrowser.open(SITE_URL))
        self.button(bt, "Dossier WoW…", self.choose_wow)

        opt = tk.Frame(root, bg=BG)
        opt.pack(fill="x", padx=12)
        self.var_boot = tk.BooleanVar(value=STARTUP_LNK.exists())
        tk.Checkbutton(opt, text="Lancer au démarrage de Windows (mise à jour auto toutes les 15 min)",
                       variable=self.var_boot, command=self.toggle_boot, bg=BG, fg=TXT, selectcolor=PANEL,
                       activebackground=BG, activeforeground=AMBER, font=FONT).pack(side="left")
        tk.Button(opt, text="Raccourci Bureau", command=self.desktop_shortcut, bg=PANEL, fg=MUTE, bd=0,
                  font=FONT, activebackground="#222", activeforeground=AMBER, padx=8).pack(side="right")

        tk.Label(root, text="Journal", bg=BG, fg=MUTE, font=FONT, anchor="w").pack(fill="x", padx=12, pady=(10, 0))
        self.log = tk.Text(root, bg="#000", fg="#bdbdbd", font=("Consolas", 9), bd=0, height=10,
                           wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True, padx=12, pady=(2, 12))

        if not self.wow_path():
            found = find_wow()
            if found:
                self.cfg["wow_path"] = str(found)
                save_config(self.cfg)
        self.pump_log()
        self.refresh()
        self.sync_async()
        self.schedule()

    def button(self, parent, text, cmd, primary=False):
        b = tk.Button(parent, text=text, command=cmd, font=("Consolas", 11, "bold"), bd=0, padx=14, pady=8,
                      bg=AMBER if primary else PANEL, fg="#000" if primary else TXT,
                      activebackground="#ffb84d" if primary else "#262626",
                      activeforeground="#000" if primary else AMBER, disabledforeground="#555", cursor="hand2")
        b.pack(side="left", padx=(0, 8))
        return b

    # --- journal --------------------------------------------------------------
    def write(self, msg):
        self.logq.put(time.strftime("[%H:%M:%S] ") + msg)

    def pump_log(self):
        lines = []
        while not self.logq.empty():
            lines.append(self.logq.get())
        if lines:
            self.log.configure(state="normal")
            self.log.insert("end", "\n".join(lines) + "\n")
            if int(self.log.index("end-1c").split(".")[0]) > 400:
                self.log.delete("1.0", "150.0")
            self.log.see("end")
            self.log.configure(state="disabled")
            self.refresh()
        self.root.after(300, self.pump_log)

    # --- dossier WoW -------------------------------------------------------------
    def wow_path(self):
        p = self.cfg.get("wow_path")
        return Path(p) if p and Path(p).is_dir() else None

    def addon_dir(self):
        w = self.wow_path()
        return w / "Interface" / "AddOns" / "BZTerminal" if w else None

    def choose_wow(self):
        d = filedialog.askdirectory(title="Choisis le dossier _forever_ de World of Warcraft",
                                    initialdir=str(self.wow_path() or r"C:\Program Files (x86)\World of Warcraft"))
        if d:
            self.cfg["wow_path"] = d
            save_config(self.cfg)
            self.write(f"Dossier WoW : {d}")
            self.sync_async()

    # --- synchronisation ----------------------------------------------------------
    def schedule(self):
        self.root.after(SYNC_EVERY * 1000, lambda: (self.sync_async(), self.schedule()))

    def sync_async(self):
        if not self.busy:
            self.busy = True
            self.btn_sync.configure(state="disabled")
            threading.Thread(target=self.sync, daemon=True).start()

    def sync(self):
        try:
            dest = self.addon_dir()
            if not dest:
                self.write("Dossier WoW Forever introuvable : clique sur « Dossier WoW… » et choisis le dossier _forever_.")
                return
            # 1. installer / mettre à jour le code de l'addon
            dest.mkdir(parents=True, exist_ok=True)
            fresh_install = not (dest / "BZTerminal.toc").exists()
            for f in ADDON_SRC.iterdir():
                if f.name != "Data.lua":
                    shutil.copy2(f, dest / f.name)
            if fresh_install:
                self.write(f"Addon installé dans {dest}")
            # 2. données
            self.meta = json.loads(fetch(SITE_URL + "api/meta.json"))
            data = fetch(SITE_URL + "Data.lua", timeout=120)
            tmp = dest / "Data.lua.tmp"
            tmp.write_bytes(data)
            os.replace(tmp, dest / "Data.lua")
            self.last_sync = time.time()
            h = (self.meta.get("houses") or [{}])[0]
            ts = h.get("last_ts")
            when = time.strftime("%d/%m %H:%M", time.localtime(ts)) if ts else "?"
            self.write(f"Données à jour (HV du {when}, {len(data) // 1024} Ko)."
                       + ("  Lance le jeu : l'addon est prêt." if fresh_install else "  En jeu : /reload"))
        except Exception as e:
            self.write(f"Échec de la mise à jour : {e}")
        finally:
            self.busy = False
            self.root.after(0, lambda: self.btn_sync.configure(state="normal"))

    # --- statut -----------------------------------------------------------------
    def refresh(self):
        dest = self.addon_dir()
        ok = bool(dest and (dest / "BZTerminal.toc").exists() and self.last_sync)
        self.lbl_state.configure(text="●  Addon à jour" if ok else "●  Addon pas encore à jour",
                                 fg=GREEN if ok else RED)
        lines = []
        h = (self.meta or {}).get("houses") or []
        if h:
            ts = h[0].get("last_ts")
            if ts:
                mins = int((time.time() - ts) / 60)
                age = f"{mins} min" if mins < 60 else f"{mins // 60} h {mins % 60:02d}"
                lines.append(f"Dernières données HV (GitHub) : {time.strftime('%d/%m %H:%M', time.localtime(ts))}"
                             f" (il y a {age}) · {h[0].get('n_snapshots', 0)} snapshots")
        lines.append(f"Dossier WoW : {self.wow_path() or 'introuvable'}")
        if self.last_sync:
            lines.append(f"Dernière mise à jour de l'addon : {time.strftime('%H:%M', time.localtime(self.last_sync))}"
                         f" · prochaine dans ~15 min")
        self.lbl_info.configure(text="\n".join(lines))

    # --- options ------------------------------------------------------------------
    def toggle_boot(self):
        try:
            if self.var_boot.get():
                make_shortcut(STARTUP_LNK, "--minimized")
                self.write("Démarrage automatique avec Windows : activé.")
            else:
                STARTUP_LNK.unlink(missing_ok=True)
                self.write("Démarrage automatique avec Windows : désactivé.")
        except Exception as e:
            messagebox.showerror("BZ Terminal", f"Impossible de modifier le démarrage automatique :\n{e}")
            self.var_boot.set(STARTUP_LNK.exists())

    def desktop_shortcut(self):
        try:
            make_shortcut(DESKTOP_LNK)
            self.write(f"Raccourci créé sur le Bureau : {DESKTOP_LNK.name}")
        except Exception as e:
            messagebox.showerror("BZ Terminal", f"Impossible de créer le raccourci :\n{e}")


def main():
    root = tk.Tk()
    App(root)
    if "--minimized" in sys.argv:
        root.iconify()
    root.mainloop()


if __name__ == "__main__":
    main()
