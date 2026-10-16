#!/usr/bin/env python3
"""Viessmann Monatsstichtag-Snapshot – für GitHub Actions.

Wird am 1. jedes Monats ausgeführt und speichert alle kumulativen
API-Werte als monatsdaten/YYYY-MM-DD.json im Repo.

monat_update in viessmann_abruf.py kann diese Dateien einlesen
und damit den vorherigen Monat automatisch vorausfüllen.

Umgebungsvariablen:
  VIESSMANN_REFRESH_TOKEN  (required)
  VIESSMANN_CLIENT_ID      (optional)
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib import error, parse, request

CLIENT_ID  = os.environ.get("VIESSMANN_CLIENT_ID", "e186f3828415aa2355000ad0609e2a63")
INST_ID    = "2877437"
GATEWAY    = "7736172086735224"
DEVICE_WP  = "0"
DEVICE_EMS = "7377953317397203"

IAM        = "https://iam.viessmann-climatesolutions.com/idp/v3"
API        = "https://api.viessmann-climatesolutions.com"
OUT_DIR    = Path(__file__).parent / "monatsdaten"


def token_from_refresh(refresh_token: str) -> str:
    req = request.Request(
        f"{IAM}/token",
        data=parse.urlencode({
            "grant_type":    "refresh_token",
            "client_id":     CLIENT_ID,
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


def features_of(access_token: str, device_id: str) -> dict:
    path = (
        f"/iot/v2/features/installations/{INST_ID}"
        f"/gateways/{GATEWAY}/devices/{device_id}/features"
    )
    raw = api_get(access_token, path)
    return {f["feature"]: f.get("properties", {}) for f in raw.get("data", [])}


def v(feats: dict, feature: str, prop: str = "value") -> object:
    return feats.get(feature, {}).get(prop, {}).get("value")


def to1(wh) -> float | None:
    return round(wh / 1000, 1) if wh is not None else None


def main():
    refresh_token = os.environ.get("VIESSMANN_REFRESH_TOKEN", "").strip()
    if not refresh_token:
        sys.exit("VIESSMANN_REFRESH_TOKEN nicht gesetzt.")

    try:
        access = token_from_refresh(refresh_token)
    except Exception as e:
        sys.exit(f"Token-Fehler: {e}")

    now = datetime.now(timezone.utc)
    datum = now.strftime("%Y-%m-%d")
    ts    = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    print(f"Lade WP-Features (Device 0) ...")
    try:
        wp = features_of(access, DEVICE_WP)
    except error.HTTPError as e:
        sys.exit(f"API-Fehler WP: {e.code} {e.read().decode()}")

    print(f"Lade EMS-Features (Device {DEVICE_EMS}) ...")
    try:
        ems = features_of(access, DEVICE_EMS)
    except error.HTTPError as e:
        sys.exit(f"API-Fehler EMS: {e.code} {e.read().decode()}")

    # Monatswerte WP (letzter vollständiger Monat = Index 1)
    total_arr   = v(wp, "heating.power.consumption.total",   "month") or []
    heating_arr = v(wp, "heating.power.consumption.heating", "month") or []
    dhw_arr     = v(wp, "heating.power.consumption.dhw",     "month") or []
    read_at     = v(wp, "heating.power.consumption.total",   "monthValueReadAt")

    wp_letzter = None
    if total_arr and read_at:
        read_dt = datetime.fromisoformat(read_at.replace("Z", "+00:00"))
        m = read_dt.month - 1 or 12
        y = read_dt.year if read_dt.month > 1 else read_dt.year - 1
        wp_letzter = {
            "monat":      f"{y}-{m:02d}",
            "wp_total":   round(total_arr[1], 1)   if len(total_arr)   > 1 else None,
            "wp_heizung": round(heating_arr[1], 1) if len(heating_arr) > 1 else None,
            "wp_ww":      round(dhw_arr[1], 1)     if len(dhw_arr)     > 1 else None,
        }

    def lc(feat, key):
        return (ems.get(feat) or {}).get(key, {}).get("value")

    snapshot = {
        "datum":                 datum,
        "ts_utc":                ts,
        # Kumulative EMS-Werte (für Monatsdiff)
        "pv_vitocharge_lc_kWh":  to1(lc("photovoltaic.production.cumulated", "lifeCycle")),
        "batt_laden_lc_kWh":     to1(lc("ess.transfer.charge.cumulated",      "lifeCycle")),
        "batt_entlad_lc_kWh":    to1(lc("ess.transfer.discharge.cumulated",   "lifeCycle")),
        "nb_lc_kWh":             to1(v(ems, "pcc.transfer.consumption.total")),
        "einsp_lc_kWh":          to1(v(ems, "pcc.transfer.feedIn.total")),
        # Kompressor-Zähler
        "kompressor_starts_ges": v(wp, "heating.compressors.0.statistics", "starts"),
        "kompressor_stunden_ges":v(wp, "heating.compressors.0.statistics", "hours"),
        # Letzter vollständiger WP-Monat (direkt aus API)
        "wp_letzter_monat":      wp_letzter,
    }

    OUT_DIR.mkdir(exist_ok=True)
    out = OUT_DIR / f"{datum}.json"
    out.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Snapshot gespeichert: {out}")
    for k, val in snapshot.items():
        if k != "wp_letzter_monat":
            print(f"  {k}: {val}")
    if wp_letzter:
        print(f"  wp_letzter_monat: {wp_letzter}")


if __name__ == "__main__":
    main()
