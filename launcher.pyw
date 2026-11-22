"""BZ Terminal — lanceur graphique (double-clic). Démarre/arrête la collecte, ouvre le terminal."""
import os
import queue
import sqlite3
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from bz.api import ENV_FILE, load_env, update_env  # noqa: E402

PORT = 8765
URL = f"http://localhost:{PORT}"
DB = ROOT / "data" / "auctions.db"
STARTUP_LNK = Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup\BZ Terminal.lnk"
DESKTOP_LNK = Path.home() / "Desktop" / "BZ Terminal.lnk"

BG, PANEL, AMBER, TXT, MUTE, GREEN, RED = "#0b0b0b", "#151515", "#ffa028", "#e0e0e0", "#808080", "#3ddc84", "#ff5c5c"
FONT = ("Consolas", 10)


def python_exe():
    """python.exe (pas pythonw) pour pouvoir lire la sortie du collecteur."""
    p = Path(sys.executable)
    cand = p.with_name("python.exe")
    return str(cand if cand.exists() else p)


def make_shortcut(lnk: Path, extra_args=""):
    pyw = Path(sys.executable).with_name("pythonw.exe")
    target = pyw if pyw.exists() else Path(sys.executable)
    ps = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:BZ_LNK);"
        "$s.TargetPath=$env:BZ_TARGET;$s.Arguments=$env:BZ_ARGS;"
        "$s.WorkingDirectory=$env:BZ_DIR;$s.Description='BZ Terminal';$s.Save()"
    )
    env = dict(os.environ, BZ_LNK=str(lnk), BZ_TARGET=str(target),
               BZ_ARGS=f'"{ROOT / "launcher.pyw"}" {extra_args}'.strip(), BZ_DIR=str(ROOT))
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], env=env, check=True,
                   creationflags=subprocess.CREATE_NO_WINDOW)


class App:
    def __init__(self, root, autostart=False):
        self.root = root
        self.proc = None
        self.logq = queue.Queue()
        self.server_ok = False
        root.title("BZ Terminal")
        root.configure(bg=BG)
        root.geometry("720x520")
        root.minsize(600, 420)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        top = tk.Frame(root, bg=AMBER)
        top.pack(fill="x")
        tk.Label(top, text=" BZ TERMINAL · WoW Forever", bg=AMBER, fg="#000",
                 font=("Consolas", 13, "bold"), pady=6).pack(side="left")

        # --- statut
        st = tk.Frame(root, bg=PANEL, padx=14, pady=10)
        st.pack(fill="x", padx=12, pady=(12, 6))
        self.lbl_state = tk.Label(st, text="", bg=PANEL, fg=TXT, font=("Consolas", 12, "bold"), anchor="w")
        self.lbl_state.pack(fill="x")
        self.lbl_info = tk.Label(st, text="", bg=PANEL, fg=MUTE, font=FONT, anchor="w", justify="left")
        self.lbl_info.pack(fill="x", pady=(4, 0))

        # --- boutons
        bt = tk.Frame(root, bg=BG)
        bt.pack(fill="x", padx=12, pady=6)
        self.btn_start = self.button(bt, "▶  Démarrer la collecte", self.start, primary=True)
        self.btn_stop = self.button(bt, "■  Arrêter", self.stop)
        self.button(bt, "Ouvrir le terminal  ↗", self.open_terminal)

        opt = tk.Frame(root, bg=BG)
        opt.pack(fill="x", padx=12)
        self.var_boot = tk.BooleanVar(value=STARTUP_LNK.exists())
        tk.Checkbutton(opt, text="Lancer automatiquement au démarrage de Windows (collecte comprise)",
                       variable=self.var_boot, command=self.toggle_boot, bg=BG, fg=TXT, selectcolor=PANEL,
                       activebackground=BG, activeforeground=AMBER, font=FONT).pack(side="left")
        tk.Button(opt, text="Raccourci Bureau", command=self.desktop_shortcut, bg=PANEL, fg=MUTE, bd=0,
                  font=FONT, activebackground="#222", activeforeground=AMBER, padx=8).pack(side="right")

        # --- journal
        tk.Label(root, text="Journal", bg=BG, fg=MUTE, font=FONT, anchor="w").pack(fill="x", padx=12, pady=(10, 0))
        self.log = tk.Text(root, bg="#000", fg="#bdbdbd", font=("Consolas", 9), bd=0, height=12,
                           insertbackground=AMBER, wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True, padx=12, pady=(2, 12))

        self.start_server()
        if not self.ensure_credentials():
            self.write("Identifiants Blizzard manquants : renseigne-les pour démarrer la collecte.")
        elif autostart:
            self.start()
        self.refresh()
        self.pump_log()

    def button(self, parent, text, cmd, primary=False):
        b = tk.Button(parent, text=text, command=cmd, font=("Consolas", 11, "bold"), bd=0, padx=14, pady=8,
                      bg=AMBER if primary else PANEL, fg="#000" if primary else TXT,
                      activebackground="#ffb84d" if primary else "#262626", activeforeground="#000" if primary else AMBER,
                      disabledforeground="#555", cursor="hand2")
        b.pack(side="left", padx=(0, 8))
        return b

    # --- journal ---------------------------------------------------------------
    def write(self, line):
        self.logq.put(line)

    def pump_log(self):
        lines = []
        while not self.logq.empty():
            lines.append(self.logq.get())
        if lines:
            self.log.configure(state="normal")
            self.log.insert("end", "\n".join(lines) + "\n")
            if int(self.log.index("end-1c").split(".")[0]) > 600:
                self.log.delete("1.0", "200.0")
            self.log.see("end")
            self.log.configure(state="disabled")
        self.root.after(300, self.pump_log)

    # --- identifiants -------------------------------------------------------------
    def ensure_credentials(self):
        load_env()
        if os.environ.get("BLIZZARD_CLIENT_ID") and os.environ.get("BLIZZARD_CLIENT_SECRET"):
            if not os.environ.get("BZ_RULESET"):
                update_env({"BZ_NAMESPACE": "dynamic-forever-eu", "BZ_RULESET": 1,
                            "BZ_AUCTION_HOUSES": 113, "BZ_REALM_NAME": "Forever PvP"})
            return True
        return self.ask_credentials()

    def ask_credentials(self):
        win = tk.Toplevel(self.root, bg=BG, padx=16, pady=14)
        win.title("Identifiants Blizzard")
        win.transient(self.root)
        win.grab_set()
        tk.Label(win, text="Colle les identifiants de ton client\n(develop.battle.net → API Access)",
                 bg=BG, fg=TXT, font=FONT, justify="left").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        entries = {}
        for i, (key, label) in enumerate([("BLIZZARD_CLIENT_ID", "Client ID"), ("BLIZZARD_CLIENT_SECRET", "Client Secret")]):
            tk.Label(win, text=label, bg=BG, fg=MUTE, font=FONT).grid(row=i + 1, column=0, sticky="w")
            e = tk.Entry(win, width=42, bg="#000", fg=AMBER, insertbackground=AMBER, font=FONT,
                         show="•" if "SECRET" in key else "")
            e.grid(row=i + 1, column=1, pady=3)
            entries[key] = e
        ok = {"v": False}

        def save():
            vals = {k: e.get().strip() for k, e in entries.items()}
            if not all(vals.values()):
                return
            vals.update({"BZ_REGION": "eu", "BZ_LOCALE": "fr_FR", "BZ_NAMESPACE": "dynamic-forever-eu",
                         "BZ_RULESET": 1, "BZ_AUCTION_HOUSES": 113, "BZ_REALM_NAME": "Forever PvP"})
            update_env(vals)
            ok["v"] = True
            win.destroy()

        tk.Button(win, text="Enregistrer", command=save, bg=AMBER, fg="#000", bd=0, font=("Consolas", 10, "bold"),
                  padx=12, pady=4).grid(row=3, column=1, sticky="e", pady=(10, 0))
        self.root.wait_window(win)
        return ok["v"]

    # --- serveur web (dans ce processus) -------------------------------------------
    def start_server(self):
        def run():
            try:
                import server
                from http.server import ThreadingHTTPServer
                httpd = ThreadingHTTPServer(("127.0.0.1", PORT), server.Handler)
                self.server_ok = True
                httpd.serve_forever()
            except OSError:
                # port déjà pris : probablement un serveur déjà lancé, le terminal reste accessible
                self.server_ok = True
                self.write(f"Le port {PORT} est déjà utilisé (terminal déjà lancé ailleurs ?).")
            except Exception as e:
                self.write(f"Erreur serveur : {e!r}")
        threading.Thread(target=run, daemon=True).start()

    def open_terminal(self):
        webbrowser.open(URL)

    # --- collecteur (sous-processus) ------------------------------------------------
    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self):
        if self.running() or not self.ensure_credentials():
            return
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        self.proc = subprocess.Popen(
            [python_exe(), "collect.py", "--loop"], cwd=ROOT, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW)
        self.write(time.strftime("[%H:%M:%S] ") + "Collecte démarrée (vérification toutes les 10 min).")
        threading.Thread(target=self.read_proc, args=(self.proc,), daemon=True).start()
        self.refresh(once=True)

    def read_proc(self, proc):
        for line in proc.stdout:
            self.write(line.rstrip())
        code = proc.wait()
        if code not in (0, None) and proc is self.proc:
            self.write(time.strftime("[%H:%M:%S] ") + f"La collecte s'est arrêtée (code {code}).")

    def stop(self):
        if self.running():
            self.proc.terminate()
            self.write(time.strftime("[%H:%M:%S] ") + "Collecte arrêtée.")
        self.refresh(once=True)

    # --- options -----------------------------------------------------------------
    def toggle_boot(self):
        try:
            if self.var_boot.get():
                make_shortcut(STARTUP_LNK, "--autostart --minimized")
                self.write("Lancement automatique au démarrage de Windows : activé.")
            else:
                STARTUP_LNK.unlink(missing_ok=True)
                self.write("Lancement automatique au démarrage de Windows : désactivé.")
        except Exception as e:
            messagebox.showerror("BZ Terminal", f"Impossible de modifier le démarrage automatique :\n{e}")
            self.var_boot.set(STARTUP_LNK.exists())

    def desktop_shortcut(self):
        try:
            make_shortcut(DESKTOP_LNK)
            self.write(f"Raccourci créé sur le Bureau : {DESKTOP_LNK.name}")
        except Exception as e:
            messagebox.showerror("BZ Terminal", f"Impossible de créer le raccourci :\n{e}")

    # --- statut ------------------------------------------------------------------
    def db_status(self):
        if not DB.exists():
            return None
        try:
            con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=2)
            r = con.execute("SELECT MAX(ts), COUNT(*) FROM snapshots").fetchone()
            last = con.execute("SELECT n_auctions FROM snapshots ORDER BY ts DESC LIMIT 1").fetchone()
            items = con.execute("SELECT COUNT(*) FROM items").fetchone()[0]
            con.close()
            return {"ts": r[0], "n": r[1], "auctions": last[0] if last else 0, "items": items}
        except sqlite3.Error:
            return None

    def refresh(self, once=False):
        run = self.running()
        self.lbl_state.configure(text="●  Collecte en cours" if run else "●  Collecte arrêtée",
                                 fg=GREEN if run else RED)
        self.btn_start.configure(state="disabled" if run else "normal")
        self.btn_stop.configure(state="normal" if run else "disabled")
        s = self.db_status()
        if s and s["ts"]:
            mins = int((time.time() - s["ts"]) / 60)
            age = f"{mins} min" if mins < 60 else f"{mins // 60} h {mins % 60:02d}"
            info = (f"Dernières données HV : {time.strftime('%d/%m %H:%M', time.localtime(s['ts']))} (il y a {age})\n"
                    f"{s['auctions']:,} annonces · {s['items']:,} objets connus · {s['n']} snapshots enregistrés"
                    ).replace(",", " ")
        else:
            info = "Aucune donnée pour l'instant : clique sur « Démarrer la collecte »."
        srv = f"\nTerminal : {URL}" if self.server_ok else "\nTerminal : démarrage…"
        self.lbl_info.configure(text=info + srv)
        if not once:
            self.root.after(5000, self.refresh)

    def on_close(self):
        if self.running():
            if not messagebox.askyesno("BZ Terminal", "Fermer arrête la collecte.\n"
                                       "(Astuce : réduis la fenêtre pour la laisser tourner.)\n\nFermer quand même ?"):
                return
            self.proc.terminate()
        self.root.destroy()


def main():
    root = tk.Tk()
    App(root, autostart="--autostart" in sys.argv)
    if "--minimized" in sys.argv:
        root.iconify()
    root.mainloop()


if __name__ == "__main__":
    main()
