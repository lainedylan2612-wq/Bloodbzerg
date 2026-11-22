"""BZ Terminal — lanceur (double-clic).

La collecte tourne sur GitHub. Ce lanceur sert à :
  - installer l'addon BZTerminal dans WoW Forever et le mettre à jour à la demande,
  - activer la mise à jour automatique (tâche planifiée Windows invisible, toutes les 15 min),
  - ouvrir le terminal en ligne.
"""
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from bz import sync  # noqa: E402

TASK_NAME = "BZ Terminal - MAJ addon"
DESKTOP_LNK = Path.home() / "Desktop" / "BZ Terminal.lnk"
SYNC_LOG = ROOT / "data" / "sync.log"

BG, PANEL, AMBER, TXT, MUTE, GREEN, RED = "#0b0b0b", "#151515", "#ffa028", "#e0e0e0", "#808080", "#3ddc84", "#ff5c5c"
FONT = ("Consolas", 10)
NO_WINDOW = subprocess.CREATE_NO_WINDOW


def pythonw():
    p = Path(sys.executable).with_name("pythonw.exe")
    return str(p if p.exists() else sys.executable)


def powershell(script, **env):
    return subprocess.run(["powershell", "-NoProfile", "-Command", script], env=dict(os.environ, **env),
                          capture_output=True, text=True, creationflags=NO_WINDOW)


def task_exists():
    return subprocess.run(["schtasks", "/Query", "/TN", TASK_NAME], capture_output=True,
                          creationflags=NO_WINDOW).returncode == 0


def create_task():
    script = (
        "$a = New-ScheduledTaskAction -Execute $env:BZ_EXE -Argument ('\"' + $env:BZ_SCRIPT + '\"') "
        "-WorkingDirectory $env:BZ_DIR;"
        "$t = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) "
        "-RepetitionInterval (New-TimeSpan -Minutes 15);"
        "$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries "
        "-DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 5);"
        "Register-ScheduledTask -TaskName $env:BZ_TASK -Action $a -Trigger $t -Settings $s "
        "-Description 'Télécharge les données BZ Terminal dans l addon WoW' -Force | Out-Null"
    )
    r = powershell(script, BZ_EXE=pythonw(), BZ_SCRIPT=str(ROOT / "sync.py"), BZ_DIR=str(ROOT), BZ_TASK=TASK_NAME)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or r.stdout.strip())


def delete_task():
    subprocess.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"], capture_output=True, creationflags=NO_WINDOW)


class App:
    def __init__(self, root):
        self.root = root
        self.logq = queue.Queue()
        self.busy = False
        self.meta = None

        root.title("BZ Terminal")
        root.configure(bg=BG)
        root.geometry("720x480")
        root.minsize(600, 400)

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
        self.button(bt, "Ouvrir le terminal  ↗", lambda: webbrowser.open(sync.SITE_URL))
        self.button(bt, "Dossier WoW…", self.choose_wow)

        opt = tk.Frame(root, bg=BG)
        opt.pack(fill="x", padx=12)
        self.var_auto = tk.BooleanVar(value=task_exists())
        tk.Checkbutton(opt, text="Mise à jour automatique (invisible, toutes les 15 min, même sans ce lanceur)",
                       variable=self.var_auto, command=self.toggle_auto, bg=BG, fg=TXT, selectcolor=PANEL,
                       activebackground=BG, activeforeground=AMBER, font=FONT).pack(side="left")
        tk.Button(opt, text="Raccourci Bureau", command=self.desktop_shortcut, bg=PANEL, fg=MUTE, bd=0,
                  font=FONT, activebackground="#222", activeforeground=AMBER, padx=8).pack(side="right")

        tk.Label(root, text="Journal", bg=BG, fg=MUTE, font=FONT, anchor="w").pack(fill="x", padx=12, pady=(10, 0))
        self.log = tk.Text(root, bg="#000", fg="#bdbdbd", font=("Consolas", 9), bd=0, height=10,
                           wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True, padx=12, pady=(2, 12))

        if SYNC_LOG.exists():  # dernières lignes de la tâche automatique
            for line in SYNC_LOG.read_text(encoding="utf-8").splitlines()[-3:]:
                self.logq.put(line)
        self.pump_log()
        self.sync_async()

    def button(self, parent, text, cmd, primary=False):
        b = tk.Button(parent, text=text, command=cmd, font=("Consolas", 11, "bold"), bd=0, padx=14, pady=8,
                      bg=AMBER if primary else PANEL, fg="#000" if primary else TXT,
                      activebackground="#ffb84d" if primary else "#262626",
                      activeforeground="#000" if primary else AMBER, disabledforeground="#555", cursor="hand2")
        b.pack(side="left", padx=(0, 8))
        return b

    def write(self, msg):
        self.logq.put(time.strftime("[%H:%M:%S] ") + msg)

    def pump_log(self):
        lines = []
        while not self.logq.empty():
            lines.append(self.logq.get())
        if lines:
            self.log.configure(state="normal")
            self.log.insert("end", "\n".join(lines) + "\n")
            self.log.see("end")
            self.log.configure(state="disabled")
            self.refresh()
        self.root.after(300, self.pump_log)

    def choose_wow(self):
        d = filedialog.askdirectory(title="Choisis le dossier _forever_ de World of Warcraft",
                                    initialdir=str(sync.wow_path() or r"C:\Program Files (x86)\World of Warcraft"))
        if d:
            cfg = sync.load_config()
            cfg["wow_path"] = d
            sync.save_config(cfg)
            self.write(f"Dossier WoW : {d}")
            self.sync_async()

    def sync_async(self):
        if self.busy:
            return
        self.busy = True
        self.btn_sync.configure(state="disabled")

        def work():
            try:
                self.meta = sync.run(self.write)
            except Exception as e:
                self.write(f"Échec de la mise à jour : {e}")
            finally:
                self.busy = False
                self.root.after(0, lambda: self.btn_sync.configure(state="normal"))
        threading.Thread(target=work, daemon=True).start()

    def refresh(self):
        wow = sync.wow_path()
        installed = bool(wow and (wow / "Interface" / "AddOns" / "BZTerminal" / "BZTerminal.toc").exists())
        auto = self.var_auto.get()
        if installed and auto:
            self.lbl_state.configure(text="●  Addon installé · mise à jour automatique active", fg=GREEN)
        elif installed:
            self.lbl_state.configure(text="●  Addon installé · mise à jour automatique désactivée", fg=AMBER)
        else:
            self.lbl_state.configure(text="●  Addon pas encore installé", fg=RED)
        lines = []
        h = (self.meta or {}).get("houses") or []
        if h and h[0].get("last_ts"):
            ts = h[0]["last_ts"]
            mins = int((time.time() - ts) / 60)
            age = f"{mins} min" if mins < 60 else f"{mins // 60} h {mins % 60:02d}"
            lines.append(f"Dernières données HV (GitHub) : {time.strftime('%d/%m %H:%M', time.localtime(ts))}"
                         f" (il y a {age}) · {h[0].get('n_snapshots', 0)} snapshots")
        lines.append(f"Dossier WoW : {wow or 'introuvable — clique sur « Dossier WoW… »'}")
        lines.append("En jeu : /reload pour charger les dernières données · /bz · /bz affaires")
        self.lbl_info.configure(text="\n".join(lines))

    def toggle_auto(self):
        try:
            if self.var_auto.get():
                create_task()
                self.write("Mise à jour automatique activée (tâche Windows « " + TASK_NAME + " »).")
            else:
                delete_task()
                self.write("Mise à jour automatique désactivée.")
        except Exception as e:
            messagebox.showerror("BZ Terminal", f"Impossible de modifier la tâche planifiée :\n{e}")
        self.var_auto.set(task_exists())
        self.refresh()

    def desktop_shortcut(self):
        script = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:BZ_LNK);"
                  "$s.TargetPath=$env:BZ_EXE;$s.Arguments=('\"' + $env:BZ_SCRIPT + '\"');"
                  "$s.WorkingDirectory=$env:BZ_DIR;$s.Save()")
        r = powershell(script, BZ_LNK=str(DESKTOP_LNK), BZ_EXE=pythonw(),
                       BZ_SCRIPT=str(ROOT / "launcher.pyw"), BZ_DIR=str(ROOT))
        self.write("Raccourci créé sur le Bureau." if r.returncode == 0 else f"Échec du raccourci : {r.stderr.strip()}")


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
