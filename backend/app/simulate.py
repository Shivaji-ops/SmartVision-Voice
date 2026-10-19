"""Pretend to be the glasses, so the backend and dashboard can be demoed with no hardware.

Examples (run from the backend folder, with the server running):

    python -m app.simulate --key sv_... heartbeat --battery 80
    python -m app.simulate --key sv_... heartbeat --battery 80 --every 30
    python -m app.simulate --key sv_... fall
    python -m app.simulate --key sv_... fall --unworn
    python -m app.simulate --key sv_... sos
    python -m app.simulate --key sv_... took --schedule 1
    python -m app.simulate --key sv_... location --lat 17.385 --lon 78.4867
    python -m app.simulate --key sv_... prompts --since 0
"""
import argparse
import json
import sys
import time

import httpx


def main() -> int:
    parser = argparse.ArgumentParser(description="Smart Vision device simulator")
    parser.add_argument("--key", required=True, help="Device key from the dashboard or the seed script")
    parser.add_argument("--url", default="http://localhost:8000", help="Backend address")
    sub = parser.add_subparsers(dest="command", required=True)

    hb = sub.add_parser("heartbeat", help="Report battery and wear state")
    hb.add_argument("--battery", type=int, default=80)
    hb.add_argument("--unworn", action="store_true", help="Report the frame as not being worn")
    hb.add_argument("--every", type=int, default=0, help="Repeat every N seconds until stopped")

    fall = sub.add_parser("fall", help="Send a fall")
    fall.add_argument("--unworn", action="store_true", help="Frame was off the face, so the alarm is suppressed")

    sub.add_parser("sos", help="Press the SOS button")

    took = sub.add_parser("took", help="Report a dose as taken")
    took.add_argument("--schedule", type=int, required=True, help="Schedule id")

    loc = sub.add_parser("location", help="Report a position")
    loc.add_argument("--lat", type=float, required=True)
    loc.add_argument("--lon", type=float, required=True)

    pr = sub.add_parser("prompts", help="Fetch voice prompts changed since a version")
    pr.add_argument("--since", type=int, default=0)

    args = parser.parse_args()
    client = httpx.Client(base_url=args.url, headers={"X-Device-Key": args.key}, timeout=10)

    def show(response: httpx.Response) -> None:
        if response.status_code == 204 or not response.content:
            print(response.status_code)
            return
        print(response.status_code, json.dumps(response.json(), indent=2))

    try:
        if args.command == "heartbeat":
            while True:
                show(client.post("/api/device/heartbeat", json={"battery_pct": args.battery, "worn": not args.unworn}))
                if not args.every:
                    break
                time.sleep(args.every)
        elif args.command == "fall":
            kind = "fall_suppressed" if args.unworn else "fall_confirmed"
            show(client.post("/api/device/events", json={"type": kind, "payload": {"worn": not args.unworn}}))
        elif args.command == "sos":
            show(client.post("/api/device/events", json={"type": "sos", "payload": {"worn": True}}))
        elif args.command == "took":
            show(client.post("/api/device/events", json={"type": "med_taken", "schedule_id": args.schedule}))
        elif args.command == "location":
            show(client.post("/api/device/events", json={"type": "location", "payload": {"lat": args.lat, "lon": args.lon}}))
        elif args.command == "prompts":
            show(client.get("/api/device/prompts", params={"since_version": args.since}))
    except httpx.ConnectError:
        print(f"Could not reach {args.url}. Is the server running?", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
