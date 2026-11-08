# AgriSense Lab API

Base URL: `https://<your host>`. All bodies are JSON. Times are UTC ISO-8601 (`2026-11-08T14:05:00Z`).

## Devices (`X-Device-Key` header)

### POST /api/v1/ingest
The **gateway** posts node readings:
```json
{"firmware": "gateway-1.0.0", "rssi": -61,
 "readings": [{"node": "ND-1B33", "moisture": 24.1, "temp": 19.2, "ec": 410, "ph": 6.5, "n": 37, "p": 12, "k": 94, "rssi": -81, "supply_v": 3.31},
              {"node": "ND-1B34", "fault": true}]}
```
- Below 10 % moisture, EC, N, P and K are not stored, and a **too dry** alert is raised.
- `fault: true` raises a **sensor fault** alert.

A **node or build deck** can post one reading directly, using the same fields without `node`.

The **pump node** (usually relayed by the gateway) posts:
```json
{"event": "no_flow" | "blocked" | "tank_low" | "done", "tank": "OK"}
```

A **Trainer Board** posts:
```json
{"feeds": {"moisture": 22.4, "air-temp": 23.1, "pressure": 46.0, "tank": "OK", "pump": "OFF", "fan": "ON", "vent": 90}, "event": "no_flow"}
```

The response always includes queued commands, and each command is delivered once:
```json
{"ok": true, "stored": 7, "server_time": "...", "commands": ["RUN,40,B"]}
```

### GET /api/v1/commands
Poll between posts (about every 1 s on the Trainer). It returns `{"commands": [...], "config": {"components": [...]}}`.

Commands:

| Command | Meaning |
|---|---|
| `RUN,<seconds>,<tray letter>` | Bench pump. One tray at a time, at most 300 s. |
| `STOP` | Stop every output now. |
| `SET,pump,ON,<s>` | Trainer pump, at most 30 s. |
| `SET,pump,OFF` | Trainer pump off. |
| `SET,fan,ON[,<s>]` | Trainer fan. |
| `SET,buzzer,ON,<s>` | Buzzer. |
| `SET,vent,<0-180>` | Vent servo angle. |
| `SET,ledbar,<0-10>` | LED bar level. |
| `SET,motor,<-100..100>` | Motor speed. |
| `RESTART` | Restart the device. |

## Team code (`X-Team-Key` header)

A team makes its key in Field Studio → API & keys. Feed keys look like `agri03-team-1.fan`. The team prefix is optional.

| Call | What it does |
|---|---|
| `GET /api/v1/feeds` | Lists the team's feeds. |
| `GET /api/v1/feeds/<key>/data?limit=100` | Returns history. |
| `GET /api/v1/feeds/<key>/data/last` | Returns the latest value. |
| `POST /api/v1/feeds/<key>/data` with `{"value": 12.5}` | Adds a value to a manual feed, or switches an output. Outputs follow the same rules as the dashboard: controls must be unlocked, the pump runs at most 30 s with a 60 s rest, and the tank must be OK. If a rule blocks the switch, the response is `409` with a reason. |

## Pages (session cookie + `X-CSRF` header)

| Call | Returns |
|---|---|
| `GET /api/class/<id>/live` | Current tray readings (simulated when the class is in simulation). |
| `GET /api/tray/<id>/series?class=<id>&metric=moisture&hours=48` | One tray's history. |
| `GET /api/studio/<team>/state?feed=...` | Dashboard values. |
| `GET /api/studio/<team>/series?feed=...&hours=1` | One feed's history. |
| `POST /api/studio/<team>/set` with `{"feed": "...", "value": "ON"}` | Switches an output. |
