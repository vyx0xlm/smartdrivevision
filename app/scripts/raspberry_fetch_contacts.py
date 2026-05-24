#!/usr/bin/env python3
"""
Fetch emergency numbers from SmartDrive (when WiFi works) and save locally.
Your drowsiness / GSM script on the Pi should READ this file when sending SMS
so alerts still work if the Flask server is unreachable (no WiFi to app).

Example (cron every 30 min while home WiFi exists):
    */30 * * * * cd /home/pi/smartdrive && ./venv/bin/python scripts/raspberry_fetch_contacts.py --url http://192.168.1.50:5000 --id RP4_CAR01

Then in your detector code:
    contacts = json.load(open("/home/pi/smartdrive/emergency_phones.json"))["phones"]
"""
from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync emergency phones to local JSON on Raspberry Pi.")
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:5000",
        help="Base URL where Flask SmartDrive runs (same LAN as Pi)",
    )
    parser.add_argument(
        "--id",
        required=True,
        help='Driver database id OR device_id string (matches "IoT Device ID" in web app)',
    )
    parser.add_argument(
        "--output",
        default="emergency_phones.json",
        help="Where to save numbers (readable by GSM alert code offline)",
    )
    args = parser.parse_args()

    base = args.url.rstrip("/")
    path = f"/api/driver/{args.id}/emergency-phones"
    full = base + path

    req = urllib.request.Request(full, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print("Error: driver not found. Check --id and device registration.")
        else:
            print(f"HTTP error: {e.code}")
        raise SystemExit(1)
    except urllib.error.URLError as e:
        print(f"Cannot reach server ({full}): {e.reason}")
        print("Keep existing emergency_phones.json if any; GSM can still use last sync.")
        raise SystemExit(1)

    phones = data.get("phones") or []
    out = {
        "phones": phones,
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_url": full,
    }
    tmp = args.output + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    import os

    os.replace(tmp, args.output)
    print(f"Saved {len(phones)} number(s) to {args.output}")


if __name__ == "__main__":
    main()
