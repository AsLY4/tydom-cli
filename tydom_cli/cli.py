"""Command-line interface for Delta Dore Tydom gateways.

A terminal client that drives a gateway through the pytydom transport —
useful on its own for diagnostics, and a full end-to-end exercise of the
library against real hardware.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys

from pytydom import (
    Frame,
    TydomAuthenticationError,
    TydomCommunicationError,
    TydomConnectionError,
    protocol,
)

from . import endpoints
from .client import TydomClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tydom",
        description="Terminal client for Delta Dore Tydom gateways.",
    )
    # Secrets and identity default from the environment so they need not be
    # typed on the command line (kept out of shell history / the process list).
    parser.add_argument(
        "--mac",
        default=os.environ.get("TYDOM_MAC"),
        help="Gateway MAC, 12 hex chars [env: TYDOM_MAC]",
    )
    conn = parser.add_argument_group("connection")
    conn.add_argument(
        "--host",
        default=os.environ.get("TYDOM_HOST"),
        help="Gateway IP/hostname (local mode) [env: TYDOM_HOST]",
    )
    conn.add_argument(
        "--remote",
        action="store_true",
        help=f"Connect through the mediation service ({endpoints.MEDIATION_HOST})",
    )
    conn.add_argument(
        "--port", type=int, default=endpoints.GATEWAY_PORT, help="Gateway port"
    )
    conn.add_argument(
        "--timeout",
        type=float,
        default=endpoints.REQUEST_TIMEOUT,
        help="Request timeout",
    )
    auth = parser.add_argument_group("authentication (choose one)")
    auth.add_argument(
        "--password",
        default=os.environ.get("TYDOM_PASSWORD"),
        help="Gateway password, manual mode [env: TYDOM_PASSWORD]",
    )
    auth.add_argument(
        "--email",
        default=os.environ.get("TYDOM_EMAIL"),
        help="Delta Dore account email, account mode [env: TYDOM_EMAIL]",
    )
    auth.add_argument(
        "--account-password",
        default=os.environ.get("TYDOM_ACCOUNT_PASSWORD"),
        help="Delta Dore account password, account mode [env: TYDOM_ACCOUNT_PASSWORD]",
    )
    parser.add_argument("--json", action="store_true", help="Raw JSON output")
    parser.add_argument("-v", "--debug", action="store_true", help="Debug logging")

    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("ping", help="Ping the gateway")
    sub.add_parser("info", help="Show /info (firmware, clock, weather, geoloc)")
    sub.add_parser("list", help="List devices with their live state")
    sub.add_parser("scenarios", help="List stored scenarios")
    sub.add_parser(
        "password",
        help="Print the gateway password fetched from the account (account mode; "
        "no gateway connection, so it works even while HA holds the session)",
    )
    p_get = sub.add_parser("get", help="Show one device's full state")
    p_get.add_argument("device", help="Device key (endpoint_device) or device id")
    p_set = sub.add_parser(
        "set",
        help="Write a command to a device endpoint",
        description=(
            'Send [{"name": NAME, "value": VALUE}] to a device endpoint. NAME is '
            "the writable Tydom attribute/command (e.g. position 0-100, positionCmd "
            "UP/DOWN/STOP, level, levelCmd ON/OFF, setpoint). Run `get <device_id>` "
            "to see each device's attributes with their permission and allowed values."
        ),
    )
    p_set.add_argument("device_id", type=int, help="Device id (from `list`)")
    p_set.add_argument("endpoint_id", type=int, help="Endpoint id (from `list`)")
    p_set.add_argument(
        "name", help="Writable attribute/command name (see `get <device_id>`)"
    )
    p_set.add_argument("value", help="Value to write (e.g. 50, UP, ON, 19.5)")
    p_set.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Confirm the write to the REAL gateway without prompting",
    )
    p_raw = sub.add_parser("raw", help="Send an arbitrary request")
    p_raw.add_argument("method")
    p_raw.add_argument("path")
    p_raw.add_argument("body", nargs="?", default="")
    p_raw.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Confirm a write (non-GET) to the REAL gateway without prompting",
    )
    p_watch = sub.add_parser("watch", help="Stream unsolicited pushes")
    p_watch.add_argument(
        "--seconds",
        type=float,
        default=None,
        help="Stop after N seconds (default: forever)",
    )
    return parser


async def _confirm(prompt: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    # Run the blocking prompt off the event loop so the reader/heartbeat
    # keep running while the user decides.
    loop = asyncio.get_running_loop()
    try:
        answer = await loop.run_in_executor(None, input, f"{prompt} [y/N] ")
    except EOFError:
        return False
    return answer.strip().lower() in ("y", "yes", "o", "oui")


def _frame_json(frame: Frame):
    """The frame's JSON body, or None when the body is absent or not JSON —
    a diagnostic tool must never crash on an odd response."""
    try:
        return frame.json
    except ValueError:
        return None


def _dump(value, as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, indent=2, ensure_ascii=False, default=str))
    else:
        print(value)


def _print_frame(frame: Frame, as_json: bool) -> None:
    body = _frame_json(frame)
    if as_json:
        payload = body if body is not None else (frame.body or None)
        _dump({"status": frame.status, "path": frame.path, "body": payload}, True)
        return
    print(f"HTTP {frame.status} {frame.path}")
    if body is not None:
        print(json.dumps(body, indent=2, ensure_ascii=False))
    elif frame.body.strip():
        print(frame.body)


async def _inventory(client: TydomClient) -> list[dict]:
    configs = protocol.parse_configs(
        _frame_json(await client.request("GET", "/configs/file"))
    )
    meta = protocol.parse_meta(
        _frame_json(await client.request("GET", "/devices/meta"))
    )
    cmeta = protocol.parse_cmeta(
        _frame_json(await client.request("GET", "/devices/cmeta"))
    )
    data = protocol.parse_devices_data(
        _frame_json(await client.request("GET", "/devices/data"))
    )
    devices = []
    for key, entry in sorted(configs.items()):
        advertised = cmeta.get(key, {})
        devices.append(
            {
                "key": key,
                "device_id": entry["device_id"],
                "endpoint_id": entry["endpoint_id"],
                "name": entry["name"],
                "usage": entry["usage"],
                # Full attribute schema (name -> permission/type/enum/bounds) so
                # `get` shows what is writable and the allowed `set` values.
                "metadata": meta.get(key, {}),
                "energy_dests": advertised.get("dests", []),
                "data": data.get(key, {}),
            }
        )
    return devices


def _summarize_state(data: dict) -> str:
    if not data:
        return "-"
    return ", ".join(f"{k}={v}" for k, v in sorted(data.items()))


async def _cmd_ping(client: TydomClient, args) -> int:
    frame = await client.request("GET", "/ping")
    ok = frame.status is not None and 200 <= frame.status < 300
    if args.json:
        _dump({"status": frame.status, "ok": ok}, True)
    else:
        print(
            f"pong (HTTP {frame.status})"
            if ok
            else f"ping failed (HTTP {frame.status})"
        )
    return 0 if ok else 1


async def _cmd_info(client: TydomClient, args) -> int:
    _print_frame(await client.request("GET", "/info"), args.json)
    return 0


async def _cmd_list(client: TydomClient, args) -> int:
    devices = await _inventory(client)
    if args.json:
        _dump(devices, True)
        return 0
    if not devices:
        print("No devices reported.")
        return 0
    print(f"{len(devices)} device(s):")
    for d in devices:
        print(
            f"  dev={d['device_id']} ep={d['endpoint_id']}"
            f"  {d['usage']:<12}  {d['name']}"
        )
        print(f"      state: {_summarize_state(d['data'])}")
    print("\nUse `get <device_id>` for writable attributes, then `set …`.")
    return 0


async def _cmd_scenarios(client: TydomClient, args) -> int:
    payload = _frame_json(await client.request("GET", "/configs/file"))
    scenarios = protocol.parse_scenarios(payload)
    if args.json:
        _dump(scenarios, True)
    else:
        for s in scenarios:
            print(f"  {s['id']:>12}  {s['name']}")
    return 0


async def _cmd_get(client: TydomClient, args) -> int:
    devices = await _inventory(client)
    match = [
        d
        for d in devices
        if d["key"] == args.device or str(d["device_id"]) == args.device
    ]
    if not match:
        print(f"No device matching {args.device!r}.", file=sys.stderr)
        return 1
    _dump(match[0] if len(match) == 1 else match, True)
    return 0


async def _cmd_set(client: TydomClient, args) -> int:
    path = f"/devices/{args.device_id}/endpoints/{args.endpoint_id}/data"
    body = json.dumps([{"name": args.name, "value": args.value}])
    if not await _confirm(
        f"Send {args.name}={args.value} to {path} on the REAL gateway?", args.yes
    ):
        print("Aborted.")
        return 1
    _print_frame(await client.request("PUT", path, body), args.json)
    return 0


async def _cmd_raw(client: TydomClient, args) -> int:
    if args.method.upper() != "GET" and not await _confirm(
        f"Send {args.method} {args.path} to the REAL gateway?", args.yes
    ):
        print("Aborted.")
        return 1
    _print_frame(
        await client.request(args.method.upper(), args.path, args.body), args.json
    )
    return 0


async def _cmd_watch(client: TydomClient, args) -> int:
    def _on_push(frame: Frame) -> None:
        body = _frame_json(frame)
        if args.json:
            _dump({"path": frame.path, "method": frame.method, "body": body}, True)
        else:
            print(f"<- {frame.method or ''} {frame.path}")
            if body is not None:
                print(json.dumps(body, indent=2, ensure_ascii=False))

    client.on_push(_on_push)
    # Solicit a full state broadcast so there is something to watch.
    await client.request("POST", "/refresh/all")
    print("Watching pushes (Ctrl-C to stop)…", file=sys.stderr)
    try:
        if args.seconds is not None:
            await asyncio.sleep(args.seconds)
        else:
            await asyncio.Event().wait()
    except asyncio.CancelledError:
        pass
    return 0


_COMMANDS = {
    "ping": _cmd_ping,
    "info": _cmd_info,
    "list": _cmd_list,
    "scenarios": _cmd_scenarios,
    "get": _cmd_get,
    "set": _cmd_set,
    "raw": _cmd_raw,
    "watch": _cmd_watch,
}


def _make_client(args) -> TydomClient:
    if args.remote:
        host, verify_tls, remote = endpoints.MEDIATION_HOST, True, True
    else:
        if not args.host:
            raise SystemExit("--host is required (or use --remote)")
        host, verify_tls, remote = args.host, False, False
    return TydomClient(
        host,
        args.mac,
        port=args.port,
        timeout=args.timeout,
        heartbeat=endpoints.KEEPALIVE_INTERVAL,
        verify_tls=verify_tls,
        remote=remote,
    )


async def _resolve_password(client: TydomClient, args) -> str:
    if args.password:
        return args.password
    if args.email and args.account_password:
        return await client.fetch_gateway_password(
            args.email,
            args.account_password,
            discovery_url=endpoints.CLOUD_DISCOVERY_URL,
            sites_url=endpoints.CLOUD_SITES_URL,
            client_id=endpoints.CLOUD_CLIENT_ID,
            scope=endpoints.CLOUD_SCOPE,
        )
    raise SystemExit(
        "Provide --password (manual) or --email/--account-password (account)"
    )


async def _cmd_password(args) -> int:
    """Fetch and print the gateway password from the account.

    Cloud-only — it never opens a gateway session, so it works even while
    Home Assistant holds the gateway's single session.
    """
    if not (args.email and args.account_password):
        raise SystemExit(
            "`password` needs account mode: --email and --account-password"
        )
    client = TydomClient(
        args.host or "",
        args.mac,
        port=args.port,
        timeout=args.timeout,
        heartbeat=endpoints.KEEPALIVE_INTERVAL,
    )
    try:
        password = await client.fetch_gateway_password(
            args.email,
            args.account_password,
            discovery_url=endpoints.CLOUD_DISCOVERY_URL,
            sites_url=endpoints.CLOUD_SITES_URL,
            client_id=endpoints.CLOUD_CLIENT_ID,
            scope=endpoints.CLOUD_SCOPE,
        )
    finally:
        await client.close()
    if args.json:
        _dump({"gateway_password": password}, True)
    else:
        print(password)
    return 0


async def _run(args) -> int:
    # `password` is a cloud-only lookup: no gateway connection required.
    if args.command == "password":
        return await _cmd_password(args)
    client = _make_client(args)
    try:
        password = await _resolve_password(client, args)
        await client.connect(password)
        return await _COMMANDS[args.command](client, args)
    finally:
        await client.close()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.mac:
        parser.error("--mac is required (or set TYDOM_MAC)")
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        return asyncio.run(_run(args))
    except TydomAuthenticationError as err:
        print(f"Authentication failed: {err}", file=sys.stderr)
        return 2
    except TydomCommunicationError as err:
        print(f"Cloud unreachable: {err}", file=sys.stderr)
        return 3
    except TydomConnectionError as err:
        print(f"Gateway unreachable: {err}", file=sys.stderr)
        return 4
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
