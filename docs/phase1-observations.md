# Phase 1: Read-only observations

Recorded from the Pi (`pi5home`) over SSH with key authentication. No changes were made to the Pi.

## ngrok

- Version: `3.39.10` (the local dev machine reports `3.39.13`).
- Config: `~/.config/ngrok/ngrok.yml` is valid according to `ngrok config check`. The authtoken was not printed.

## SSH

- `sshd` listens on `0.0.0.0:22` and `[::]:22`.
- `sshd -T` needs root and is unavailable without a password (`sudo -n` fails).
- `/etc/ssh/sshd_config` sets only `KbdInteractiveAuthentication no`.
- `PasswordAuthentication` and `PermitRootLogin` are not set in any config file read. Debian's default for `PasswordAuthentication` is `yes`, so password logins are likely enabled.
- **Open item:** confirm the effective value (`sudo sshd -T | grep -i passwordauthentication`) before exposing SSH through a public endpoint.

## Network

Routes match `DEVELOPMENT_PLAN.md`:

```text
default dev happ-xray metric 1
default via 192.168.0.1 dev eth0 proto dhcp src 192.168.0.118 metric 100
172.19.0.0/30 dev happ-xray proto kernel scope link src 172.19.0.1
192.168.0.0/24 dev eth0 proto kernel scope link src 192.168.0.118 metric 100
```

NetworkManager devices: `eth0` connected, `happ-xray` connected (externally managed), `wlan0` disconnected.

## Services

| Unit | State |
|---|---|
| `happd.service` | active |
| `vpn-gateway-watch.service` | active |
| `vpn-gateway-forward.service` | active |
| `ssh.service` | active |
| `NetworkManager-dispatcher.service` | inactive (expected) |

## Development machine

The repo lives on a different machine (`dell`, Wi-Fi `wlp8s0`, no `happ-xray`). Do not treat its network state as the Pi's.

## Step 7: TCP endpoint entitlement (2026-11-15)

- A temporary `ngrok tcp 22` on the Pi was assigned a TCP endpoint on `tcp://2.tcp.eu.ngrok.io` with a random port. The free account can create TCP endpoints.
- The endpoint address is random per start. Port and host must be treated as changeable.
- The agent stopped cleanly after the test. Nothing is left running.

## Endpoint change across restarts

- Two separate temporary starts gave the same port (`20038`) in step 8, and a different host and port (`7.tcp.eu.ngrok.io:17862`) in step 11.
- The endpoint is therefore not stable across agent restarts. Discovery and notification are required.

## Telegram reachability (step 14)

- A test message sent from the Pi through the notifier succeeded with the Happ VPN on. The route to `api.telegram.org` went via `happ-xray`.
- VPN-off reachability is not yet tested. It needs the VPN stopped, which needs your go-ahead.

## Step 19: agent restart experiment (2026-11-15)

Five consecutive temporary agent starts on the Pi, with the Happ VPN on:

| Run | Endpoint |
|---|---|
| 1 | `2.tcp.eu.ngrok.io:24281` |
| 2 | `2.tcp.eu.ngrok.io:24281` (same as run 1) |
| 3 | `7.tcp.eu.ngrok.io:17862` (changed) |
| 4 | `2.tcp.eu.ngrok.io:20038` (changed) |
| 5 | `2.tcp.eu.ngrok.io:20038` (same as run 4) |

- Restarts sometimes keep the endpoint and sometimes change it.
- Endpoints previously seen (`17862`, `20038`) reappeared, so the pool is small and reuse is possible.
- Conclusion: the notifier must handle both cases. Do not assume the address is stable.
- Not yet measured: Happ VPN start/stop and Ethernet reconnect (both disrupt connectivity and need explicit go-ahead).
