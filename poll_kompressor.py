#!/usr/bin/env python3
"""Viessmann Kompressor Polling – für GitHub Actions.

Hängt eine Zeile an kompressor_log.csv an.
Wird alle 10 Minuten per GitHub Actions Cron ausgeführt.

Umgebungsvariablen:
  VIESSMANN_REFRESH_TOKEN  (required – aus GitHub Secret)
  VIESSMANN_CLIENT_ID      (optional – default: e186f3828415aa2355000ad0609e2a63)
"""
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib import error, parse, request

CLIENT_ID = os.environ.get("VIESSMANN_CLIENT_ID", "e186f3828415aa2355000ad0609e2a63")
INST_ID   = "2877437"
GATEWAY   = "7736172086735224"
DEVICE    = "0"

IAM      = "https://iam.viessmann-climatesolutions.com/idp/v3"
API      = "https://api.viessmann-climatesolutions.com"
LOG_FILE = Path(__file__).parent / "kompressor_log.csv"

COLS = [
    "ts_utc", "aktiv", "phase", "starts_ges", "stunden_ges",
    "drehzahl_pct", "t_ansaug_c", "t_hk1_vorlauf_c", "t_hk1_soll_c",
    "t_motorraum_c", "hk1_neigung", "hk1_niveau",
]


def token_from_refresh(refresh_token: str) -> str:
    req = request.Request(
        f"{IAM}/token",
        data=parse.urlencode({
            "grant_type":  "refresh_token",
            "client_id":   CLIENT_ID,
            "refresh_token": refresh_token,
        }).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with request.urlopen(req, timeout=30) as resp:
        return json.load(resp)["access_token"]


def api_get(access_token: str, path: str) -> dict:
    req = request.Request(
        API + path,
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
    )
    with request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def v(feats: dict, feature: str, prop: str = "value") -> object:
    return feats.get(feature, {}).get(prop, {}).get("value")


def main():
    refresh_token = os.environ.get("VIESSMANN_REFRESH_TOKEN", "").strip()
    if not refresh_token:
        sys.exit("VIESSMANN_REFRESH_TOKEN nicht gesetzt.")

    try:
        access = token_from_refresh(refresh_token)
    except Exception as e:
        sys.exit(f"Token-Fehler: {e}")

    path = (
        f"/iot/v2/features/installations/{INST_ID}"
        f"/gateways/{GATEWAY}/devices/{DEVICE}/features"
    )
    try:
        raw = api_get(access, path)
    except error.HTTPError as e:
        sys.exit(f"API-Fehler {e.code}: {e.read().decode(errors='replace')}")

    feats = {f["feature"]: f.get("properties", {}) for f in raw.get("data", [])}

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    row = {
        "ts_utc":           ts,
        "aktiv":            1 if v(feats, "heating.compressors.0", "active") else 0,
        "phase":            v(feats, "heating.compressors.0", "phase") or "",
        "starts_ges":       v(feats, "heating.compressors.0.statistics", "starts") or "",
        "stunden_ges":      v(feats, "heating.compressors.0.statistics", "hours") or "",
        "drehzahl_pct":     v(feats, "heating.compressors.0.speed.current") or "",
        "t_ansaug_c":       v(feats, "heating.compressors.0.sensors.temperature.inlet") or "",
        "t_hk1_vorlauf_c":  v(feats, "heating.circuits.1.sensors.temperature.supply") or "",
        "t_hk1_soll_c":     v(feats, "heating.circuits.1.temperature") or "",
        "t_motorraum_c":    v(feats, "heating.compressors.0.sensors.temperature.motorChamber") or "",
        "hk1_neigung":      v(feats, "heating.circuits.1.heating.curve", "slope") or "",
        "hk1_niveau":       v(feats, "heating.circuits.1.heating.curve", "shift") or "",
    }

    new_file = not LOG_FILE.exists()
    with LOG_FILE.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS, delimiter=";")
        if new_file:
            w.writeheader()
        w.writerow(row)

    print(
        f"{ts}  aktiv={row['aktiv']}  phase={row['phase']}"
        f"  t_ansaug={row['t_ansaug_c']}°C"
        f"  t_vorlauf={row['t_hk1_vorlauf_c']}°C (soll {row['t_hk1_soll_c']}°C)"
        f"  drehzahl={row['drehzahl_pct']}%"
        f"  kurve: Neigung={row['hk1_neigung']} Niveau={row['hk1_niveau']}"
    )


if __name__ == "__main__":
    main()
