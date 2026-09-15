#!/usr/bin/env python3
"""Diagnostic tool: dumps raw Froeling Connect API responses for a facility.

Run this yourself in an interactive terminal (it uses getpass, so your
password is never echoed or stored anywhere). It writes the FULL raw
responses to diagnostics/<timestamp>/ (gitignored) for your own reference,
and prints a REDACTED summary to stdout (facility/user IDs, owner name,
address and equipment number stripped) that is safe to share.

Usage:
    python3 tools/diagnose_froeling.py
"""

from __future__ import annotations

import getpass
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API_BASE = "https://connect-api.froeling.com"
LOGIN_URL = f"{API_BASE}/connect/v1.0/resources/login"


def request(method: str, url: str, token: str | None = None, body: dict | None = None) -> tuple[dict, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept-Language", "de")
    if token:
        req.add_header("Authorization", token)
    try:
        with urllib.request.urlopen(req) as res:
            headers = dict(res.headers)
            payload = json.loads(res.read().decode("utf-8"))
            return headers, payload
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code} for {method} {url}: {e.read().decode('utf-8', 'ignore')}", file=sys.stderr)
        raise


def redact(obj):
    """Strip personally identifying fields, keep everything structurally useful."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in ("owner", "address", "equipmentNumber", "email", "firstname", "surname", "street", "zip", "city"):
                out[k] = "<redacted>"
            elif k in ("facilityId", "userId"):
                out[k] = "<redacted>"
            elif k == "pictureUrl":
                out[k] = "<redacted-url>"
            else:
                out[k] = redact(v)
        return out
    if isinstance(obj, list):
        return [redact(i) for i in obj]
    return obj


def main() -> None:
    print("Froeling Connect Diagnose-Tool")
    print("Dein Passwort wird NICHT angezeigt, NICHT gespeichert und NICHT an mich (Claude) gesendet.\n")

    username = input("Froeling Connect E-Mail: ").strip()
    password = getpass.getpass("Froeling Connect Passwort: ")

    print("\nLogin...")
    login_headers, login_body = request("POST", LOGIN_URL, body={
        "osType": "web",
        "username": username,
        "password": password,
    })
    token = login_headers.get("Authorization")
    if not token:
        print("Kein Authorization-Header in der Antwort erhalten - Abbruch.", file=sys.stderr)
        sys.exit(1)
    user_id = login_body["userData"]["userId"]
    print("Login erfolgreich.")

    out_dir = Path(__file__).resolve().parent.parent / "diagnostics" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir.mkdir(parents=True, exist_ok=True)

    _, facilities = request("GET", f"{API_BASE}/connect/v1.0/resources/service/user/{user_id}/facility", token=token)
    (out_dir / "facilities_raw.json").write_text(json.dumps(facilities, indent=2, ensure_ascii=False))

    print(f"\n{len(facilities)} Anlage(n) gefunden:")
    summary = []
    for facility in facilities:
        fid = facility["facilityId"]
        gen = facility.get("facilityGeneration")
        product = (facility.get("protocol3200Info") or {}).get("productType")
        print(f"  - facilityGeneration={gen}  productType={product}")

        _, components = request(
            "GET",
            f"{API_BASE}/fcs/v1.0/resources/user/{user_id}/facility/{fid}/componentList",
            token=token,
        )
        (out_dir / f"facility_{fid}_componentList.json").write_text(json.dumps(components, indent=2, ensure_ascii=False))

        facility_summary = {"facilityGeneration": gen, "productType": product, "components": []}
        for comp in components:
            cid = comp["componentId"]
            print(f"      component {cid}: {comp.get('displayName')} ({comp.get('type')}/{comp.get('subType')})")
            _, detail = request(
                "GET",
                f"{API_BASE}/fcs/v1.0/resources/user/{user_id}/facility/{fid}/component/{cid}",
                token=token,
            )
            safe_cid = re.sub(r"[^A-Za-z0-9_-]", "_", cid)
            (out_dir / f"facility_{fid}_component_{safe_cid}.json").write_text(
                json.dumps(detail, indent=2, ensure_ascii=False)
            )
            top_keys = list((detail.get("topView") or {}).keys())
            other_keys = [k for k in detail.keys() if k not in ("topView", "componentId")]
            print(f"          topView keys: {top_keys}")
            print(f"          top-level keys: {other_keys}")
            facility_summary["components"].append({
                "componentId": cid,
                "type": comp.get("type"),
                "subType": comp.get("subType"),
                "topViewKeys": top_keys,
                "topLevelKeys": other_keys,
            })
        summary.append(facility_summary)

    (out_dir / "SUMMARY_redacted.json").write_text(json.dumps(redact(summary), indent=2, ensure_ascii=False))

    print(f"\nFertig. Volle Rohdaten liegen (unredigiert, nur lokal) in: {out_dir}")
    print(f"Redigierte Zusammenfassung: {out_dir / 'SUMMARY_redacted.json'}")
    print("\nBitte teile mir NUR die *_component_*.json Dateien der Komponenten, die keine")
    print("Werte anzeigen (z.B. Kessel), sowie SUMMARY_redacted.json. Diese enthalten keine")
    print("privaten Daten (Adresse/Name/Zaehlernummer wurden in der Summary redigiert; die")
    print("component-JSONs enthalten nur Messwerte, keine persoenlichen Daten).")


if __name__ == "__main__":
    main()
