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
