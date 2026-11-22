"""Liste les rulesets et hôtels des ventes WoW Forever, et enregistre la config.

WoW Forever n'a pas de royaumes mais des « rulesets » : 1 = PvP, 2 = Normal, 3 = RP, 15 = RP PvP.

  python discover.py                               # liste rulesets + HV
  python discover.py --save --ruleset 1 --ah 113   # enregistre dans .env (113 = Horde PvP EU)
  python discover.py --save --ah 110,113,116       # Alliance + Horde + Flots noirs
"""
import argparse
import sys

from bz.api import BlizzardAPI, update_env

RULESET_NAMES = {1: "PvP", 2: "Normal", 3: "Roleplay", 15: "Roleplay PvP"}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--ruleset", type=int, default=1, help="id du ruleset (1 = PvP)")
    ap.add_argument("--ah", default="113", help="ids d'HV à suivre, ex: 113 ou 110,113,116")
    ap.add_argument("--save", action="store_true", help="enregistrer dans .env")
    args = ap.parse_args()

    api = BlizzardAPI()
    ns = f"dynamic-forever-{api.region}"
    j, _ = api.get("/data/wow/ruleset/index", ns)
    ids = sorted(r["id"] for r in j.get("rulesets", []))
    print(f"Namespace : {ns}")
    print("Rulesets  : " + ", ".join(f"{i} ({RULESET_NAMES.get(i, '?')})" for i in ids))

    j, _ = api.get(f"/data/wow/ruleset/{args.ruleset}/auctions/", ns)
    print(f"\nHV du ruleset {args.ruleset} :")
    for h in j.get("auctions", []):
        print(f"  id {h['id']:>4}  {h.get('name')}")
    print("\nHV EU PvP (selon la communauté et Blackwater Exchange) : "
          "110 = Alliance, 113 = Horde, 116 = Flots noirs.")

    if args.save:
        update_env({
            "BZ_NAMESPACE": ns,
            "BZ_RULESET": args.ruleset,
            "BZ_AUCTION_HOUSES": args.ah,
            "BZ_REALM_NAME": f"Forever {RULESET_NAMES.get(args.ruleset, args.ruleset)}",
        })
        print(f"\nConfig enregistrée dans .env (ruleset {args.ruleset}, HV {args.ah}). Lance : python collect.py")


if __name__ == "__main__":
    main()
