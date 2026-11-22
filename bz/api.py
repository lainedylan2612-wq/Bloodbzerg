"""Client minimal pour la Game Data API de Blizzard (stdlib uniquement)."""
import base64
import gzip
import http.client
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"


def load_env():
    """Charge le fichier .env (clé=valeur) dans os.environ sans écraser l'existant."""
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def update_env(values: dict):
    """Met à jour/ajoute des clés dans .env en conservant le reste du fichier."""
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    seen = set()
    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if key in values:
            out.append(f"{key}={values[key]}")
            seen.add(key)
        else:
            out.append(line)
    for k, v in values.items():
        if k not in seen:
            out.append(f"{k}={v}")
    ENV_FILE.write_text("\n".join(out) + "\n", encoding="utf-8")
    for k, v in values.items():
        os.environ[k] = str(v)


class BlizzardAPI:
    def __init__(self, region=None, locale=None):
        load_env()
        self.client_id = os.environ.get("BLIZZARD_CLIENT_ID")
        self.client_secret = os.environ.get("BLIZZARD_CLIENT_SECRET")
        if not self.client_id or not self.client_secret:
            raise SystemExit(
                "Identifiants manquants : renseigne BLIZZARD_CLIENT_ID et BLIZZARD_CLIENT_SECRET "
                "dans le fichier .env (voir .env.example)."
            )
        self.region = region or os.environ.get("BZ_REGION", "eu")
        self.locale = locale or os.environ.get("BZ_LOCALE", "fr_FR")
        self.base = f"https://{self.region}.api.blizzard.com"
        self._token = None
        self._token_exp = 0.0
        # Blizzard limite à 100 req/s et 36 000 req/h : on reste sous ~30 req/s
        self._min_gap = 1 / float(os.environ.get("BZ_MAX_RPS", "30"))
        self._next_slot = 0.0
        self._lock = threading.Lock()

    def _throttle(self):
        with self._lock:
            now = time.monotonic()
            wait = self._next_slot - now
            self._next_slot = max(now, self._next_slot) + self._min_gap
        if wait > 0:
            time.sleep(wait)

    # --- OAuth client_credentials -------------------------------------------------
    def token(self):
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        data = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
        req = urllib.request.Request("https://oauth.battle.net/token", data=data)
        auth = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        req.add_header("Authorization", "Basic " + auth)
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                j = json.load(r)
        except urllib.error.HTTPError as e:
            raise SystemExit(f"Échec d'authentification OAuth ({e.code}) : vérifie client id / secret.")
        self._token = j["access_token"]
        self._token_exp = time.time() + int(j.get("expires_in", 3600))
        return self._token

    # --- GET générique --------------------------------------------------------------
    def get(self, path, namespace, params=None, if_modified_since=None, retries=4):
        """Retourne (json | None si 304, headers). `path` peut être un href complet de l'API."""
        if path.startswith("http"):
            parsed = urllib.parse.urlsplit(path)
            url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        else:
            url = self.base + path
        q = {"namespace": namespace, "locale": self.locale}
        q.update(params or {})
        url += "?" + urllib.parse.urlencode(q)

        for attempt in range(retries + 1):
            self._throttle()
            req = urllib.request.Request(url)
            req.add_header("Authorization", "Bearer " + self.token())
            req.add_header("Accept-Encoding", "gzip")
            if if_modified_since:
                req.add_header("If-Modified-Since", if_modified_since)
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    raw = r.read()
                    if r.headers.get("Content-Encoding") == "gzip":
                        raw = gzip.decompress(raw)
                    return json.loads(raw), r.headers
            except urllib.error.HTTPError as e:
                if e.code == 304:
                    return None, e.headers
                if e.code == 401 and attempt < retries:
                    self._token = None
                    continue
                if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                    time.sleep(2 ** attempt)
                    continue
                raise
            except (urllib.error.URLError, http.client.HTTPException, OSError):
                # coupure réseau, réponse tronquée (IncompleteRead), timeout…
                if attempt < retries:
                    time.sleep(2 ** attempt)
                    continue
                raise


def static_namespace(dynamic_ns: str) -> str:
    """dynamic-forever-eu -> static-forever-eu (namespace des objets)."""
    return dynamic_ns.replace("dynamic-", "static-", 1)


def retail_static_namespace(dynamic_ns: str) -> str:
    """Catalogue retail de la même région (repli quand l'objet manque côté Forever)."""
    return "static-" + dynamic_ns.rsplit("-", 1)[-1]
