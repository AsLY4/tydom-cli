# tydom-cli

A terminal client for **Delta Dore Tydom** gateways, built entirely on the
[`pytydom`](https://github.com/AsLY4/pytydom) transport library. It is useful on its own
for diagnostics, and it exercises the whole library end to end against real
hardware — the digest handshake and websocket session, the cloud
gateway-password lookup, HTTP-over-websocket request/response correlation,
and the unsolicited push stream.

> **The gateway accepts only ONE session at a time.** If Home Assistant (or
> the Tydom app) is connected, the CLI's connection times out with
> `Gateway unreachable`. Disable the `deltadore` integration in Home
> Assistant (or stop HA) before running the CLI, then re-enable it after.

## Install

```bash
pip install .          # installs tydom-cli and its pytydom dependency (from PyPI)
# or run without installing, from the repo root (pytydom must be installed):
pip install pytydom
PYTHONPATH=. python -m tydom_cli --help
```

## Authentication (choose one)

- **Manual** — you provide the gateway password directly:
  `--host 192.168.1.10 --mac 001A25XXXXXX --password <gateway-password>`
- **Account** — the CLI fetches the gateway password from your Delta Dore
  account via the cloud:
  `--host 192.168.1.10 --mac 001A25XXXXXX --email you@example.com --account-password <account-password>`
- `--remote` connects through the mediation service instead of a local IP.

### Environment variables

The identity and secrets can be set via the environment instead of flags
(so they stay out of your shell history and the process list). A flag, when
given, overrides its variable.

| Flag | Variable |
| --- | --- |
| `--host` | `TYDOM_HOST` |
| `--mac` | `TYDOM_MAC` |
| `--password` | `TYDOM_PASSWORD` |
| `--email` | `TYDOM_EMAIL` |
| `--account-password` | `TYDOM_ACCOUNT_PASSWORD` |

```bash
export TYDOM_HOST=192.168.1.10 TYDOM_MAC=001A25XXXXXX
export TYDOM_EMAIL=you@example.com TYDOM_ACCOUNT_PASSWORD=…
tydom list          # no secrets on the command line
```

## Commands

```bash
tydom --host <ip> --mac <mac> --password <pw> ping           # ping the gateway
tydom ... info                                               # /info (firmware, clock, geoloc)
tydom ... list                                               # devices + live state
tydom ... get <device-key|device-id>                         # one device's full state
tydom ... scenarios                                          # stored scenarios
tydom ... watch [--seconds N]                                # stream unsolicited pushes
tydom --mac <mac> --email <e> --account-password <pw> password  # print the gateway password (account mode)
tydom ... raw GET /info                                      # arbitrary request
tydom ... set <device_id> <endpoint_id> <name> <value>       # send a command (writes!)
```

Global flags: `--json` (machine-readable output), `-v/--debug`
(protocol-level logging), `--port`, `--timeout`.

Write commands (`set`, and non-GET `raw`) act on the **real** gateway and
prompt for confirmation unless `-y`/`--yes` is passed on the command, e.g.
`tydom set 5 1 position 50 --yes`.

### Sending a command with `set`

`set <device_id> <endpoint_id> <name> <value>` sends
`[{"name": <name>, "value": <value>}]` to `/devices/<device_id>/endpoints/<endpoint_id>/data`.

- `device_id` / `endpoint_id` — shown by `list` (`dev=… ep=…`).
- `name` — the writable Tydom attribute or command for that device. It is a
  protocol key, so **discover it with `get <device_id>`**, which lists each
  attribute with its `permission` (`w`/`rw` = writable) and its allowed
  values (`enum_values`, or `min`/`max`).
- `value` — the value to write.

Common examples: shutters `position 50` (0-100) or `positionCmd UP|DOWN|STOP`;
lights `level 80` or `levelCmd ON|OFF`; thermostats `setpoint 19.5`.

```bash
tydom get 5                 # e.g. shows positionCmd (w, [UP,DOWN,STOP]), position (rw, 0-100)
tydom set 5 1 position 50   # close a shutter to 50 %
```
