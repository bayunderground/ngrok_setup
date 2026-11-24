# DEVELOPMENT_PLAN.md

## 1. Objective

Expose SSH on the Raspberry Pi `pi5home` through an ngrok TCP tunnel, and keep it working across boot, Ethernet/Wi-Fi changes, Happ VPN transitions, and ngrok crashes. The Pi writes the current public address, as a ready-to-use `ssh` line, to `/root/pi5home_ngrok_endpoint.txt` on `root@vdsn2` whenever it changes. Telegram is an optional second channel.

The project is reproducible on a fresh supported system (Debian 13 / Raspberry Pi OS, arm64) through an idempotent setup script.

## 2. Status (2026-11-15)

The project is implemented, installed on `pi5home`, and running. Phase status is summarised below; section 5 has the details and section 6 the test matrix.

| Phase | Status |
|---|---|
| 0. Prerequisites and design verification | Done, except Ethernet and VPN-off measurements (deferred) |
| 1. Skeleton and documentation | Done |
| 2. Runtime service and endpoint reporting | Done and tested on the Pi |
| 3. Network and VPN recovery | Hook, recovery, watchdog implemented; VPN/Ethernet transitions not fully tested |
| 4. Setup script | `check`, `status`, `install`, `uninstall` implemented; real install done on `pi5home`; real uninstall and fresh-system install not tested |
| 5. Testing and hardening | Partly done; see section 6 |

Development and the runtime host are both `pi5home`. The repository is cloned at `~/ngrok_setup` on the Pi. Commits are pushed from the Pi with a repository deploy key (write access). The development machine (`dell`) is not the target and does not run the tunnel.

## 3. Confirmed environment

Observed on `pi5home`, 2026-11-15:

| Component | Observed state |
|---|---|
| Hardware | Raspberry Pi 5 |
| Hostname | `pi5home` |
| OS | Debian GNU/Linux 13 (Trixie), Raspberry Pi OS |
| Kernel | `6.18.29+rpt-rpi-2712` |
| Architecture | `arm64` |
| systemd | `257.13-1~deb13u1` |
| Network manager | NetworkManager |
| Ethernet | `eth0`, `192.168.0.118/24` |
| Wi-Fi | `wlan0`, disconnected |
| VPN | Happ / Xray; `happd.service` starts at boot |
| VPN interface | `happ-xray`, `172.19.0.1/30` |
| SSH | `ssh.service`, TCP/22; `PasswordAuthentication no` (verified with `sshd -T`) |
| ngrok | `/usr/local/bin/ngrok`, v3.39.10 |
| ngrok config | `/home/bliss/.config/ngrok/ngrok.yml` (valid; authtoken accepted by the service) |
| Plan | ngrok free plan; TCP endpoints work (verified by starting endpoints) |
| Sudo | Passwordless sudo is not available for `bliss` in general; a cached `sudo -v` is used for installs |

Routes observed at install time:

```text
default dev happ-xray metric 1
default via 192.168.0.1 dev eth0 proto dhcp src 192.168.0.118 metric 100
172.19.0.0/30 dev happ-xray proto kernel scope link src 172.19.0.1
192.168.0.0/24 dev eth0 proto kernel scope link src 192.168.0.118 metric 100
```

With Happ stopped, the default route moved to `eth0` (observed, 2026-11-15). Telegram was reachable with the VPN on, routed via `happ-xray`.

Existing components that the project must not modify: `happd.service`, `vpn-gateway-watch.service`, `vpn-gateway-forward.service`, `/usr/local/lib/vpn-gateway/`, `android-vpn-share.service`, `android-vpn-share.timer`, `/etc/NetworkManager/dispatcher.d/90-android-vpn-share`.

Existing dispatcher caveat: `90-android-vpn-share` matches `wlp8s0` and `tun0`, not the interfaces on this Pi. That is out of scope and is not copied by this project.

### ngrok account facts

- Free plan. TCP endpoints work: a temporary `ngrok tcp 22` was assigned a random `tcp://<region>.tcp.ngrok.io:<port>` address (step 7).
- Reserved TCP addresses are not available on the free plan. The project does not use one.
- Measured on restart: the address sometimes stays the same and sometimes changes, and previously seen addresses come back (table in `docs/phase1-observations.md`).
- Measured on reboot: the address changed; the notifier announced it after boot.
- Measured on crash (`SIGKILL`): systemd restarted the agent after about 10 seconds; the address stayed the same.
- Limits (free plan, from ngrok docs): 1 GB/month data out, 5,000 TCP connections/month, 100 connections/minute.

## 4. Desired behaviour

1. SSH is exposed only by a TCP ngrok endpoint forwarding to `127.0.0.1:22`.
2. The tunnel starts after boot.
3. The tunnel comes back when a usable path appears (Ethernet, Wi-Fi, or VPN).
4. A crashed agent is restarted by systemd.
5. A missed network event is caught by the watchdog within about two minutes.
6. The current endpoint is available on the Pi (`status`) and is written to `root@vdsn2:/root/pi5home_ngrok_endpoint.txt` when it changes. When the tunnel is down, the file says so. Telegram is sent too when configured.
7. Stopping the tunnel is explicit (`systemctl disable --now`); the recovery code does not override it.
8. Existing VPN gateway and Android-sharing components are untouched.
9. The same project installs on a fresh supported system with `setup.sh install`.

## 5. Architecture and implementation

### 5.1 Components

| Component | Path | Role |
|---|---|---|
| Agent unit | `systemd/ngrok-ssh.service` | Runs `ngrok start ssh` as `bliss`; `Restart=on-failure`, `RestartSec=10`, rate-limited |
| Agent config | `config/ngrok-ssh.yml` | Endpoint `ssh` → `127.0.0.1:22`, layered on the user's ngrok config |
| Endpoint helper | `scripts/ngrok-endpoint.py` | Reads `127.0.0.1:4040/api/tunnels`; prints `host:port`, or `--status` with `state=up/down` |
| Dispatcher hook | `dispatcher/50-ngrok-ssh` | NetworkManager events (`up`, `down`, `vpn-up`, `vpn-down`, `connectivity-change`, `dhcp4-change`): sets a request flag; never restarts |
| Recovery | `scripts/ngrok_recover.py`, `systemd/ngrok-ssh-recover.{service,timer}` | Debounce (5 s), lock, restart only when a route exists and no endpoint is up; does nothing when the service is disabled |
| Watchdog | same script, `--watchdog` | Every 60 s: sets the request flag if a route exists but no endpoint is up |
| Notifier | `scripts/ngrok_notify_check.py`, `ngrok_notify_remote.py`, `ngrok_notify_state.py`, `ngrok_notify_telegram.py`, `systemd/ngrok-ssh-notify.{service,timer}` | Publishes the endpoint, or `ngrok tunnel is down`, to the remote file when the value changes; Telegram too when configured. Each channel has its own state |
| Setup | `setup.sh` | `check`, `status`, `install`, `uninstall`; `--dry-run`, `--user`; test hooks via `NGROK_SSH_ROOT` |
| Tests | `tests/` | 58 unit tests (unittest), run on the Pi |

### 5.2 Installed layout

- `/usr/local/lib/ngrok-ssh/scripts/*`, `/usr/local/lib/ngrok-ssh/config/ngrok-ssh.yml`
- `/etc/systemd/system/ngrok-ssh*.{service,timer}`
- `/etc/NetworkManager/dispatcher.d/50-ngrok-ssh`
- `/home/bliss/.config/ngrok-ssh/telegram.env` (optional; mode 600, created from the `TELEGRAM_*` keys in `.env`; kept on reinstall)
- `/home/bliss/.local/state/ngrok-ssh/last_remote` and `last_endpoint` (mode 600, per-channel notifier state)
- `root@vdsn2:/root/pi5home_ngrok_endpoint.txt` (remote, mode 600, one line; written over SSH, not removed by uninstall)
- `/run/ngrok-ssh/` (recovery flag and lock; tmpfs)

### 5.3 Decisions made during implementation

- Recovery restarts the agent only when no endpoint is up. A healthy endpoint is left alone, to avoid restart storms.
- The watchdog creates the request flag only when none exists, so the debounce can elapse. (Bug found in the watchdog test: rewriting the flag every minute kept it under 5 seconds old forever. Fixed in `e4939a7`.)
- A disabled `ngrok-ssh.service` is respected by recovery. `systemctl disable --now ngrok-ssh.service` is the way to stop the tunnel for real. A plain `systemctl stop` is undone by the watchdog within about two minutes. (`c08ff8a`.)
- The notifier publishes only on change and writes each channel's state only after a successful publish. A failed publish is retried on the next run. Channels are independent.
- Endpoint file on vdsn2 (2026-11-24, replaces the Telegram-only design as the primary channel): fixed remote command with the content on stdin, so no value is in argv; atomic `mv`; `umask 077`. Uses the existing key and host key for `root@vdsn2`, reachable with the Happ VPN on or off. Overwrite, never append: one line only.
- Telegram is an optional second channel, enabled when `telegram.env` exists. Its credentials are copied from `.env` into `~/.config/ngrok-ssh/telegram.env` at install time. `.env` is gitignored and stays on the Pi only.
- Installed units point at `/usr/local/lib/ngrok-ssh`, not at the repository checkout.
- The ngrok binary is not installed by `setup.sh`. `check` fails without it. Automating an official, verifiable install is open (section 8).

## 6. Phases and test status

Status legend: **Pass** = executed, result recorded. **Fail** = executed, did not pass. **Deferred** = not run, by user decision. **Not run** = still to do.

### Phase 0 — Prerequisites and design verification

| Item | Status |
|---|---|
| ngrok account supports TCP endpoints (real endpoint started) | Pass |
| Authtoken in the existing config is accepted | Pass (agent starts and gets an endpoint) |
| Public address changes on agent restart (5 runs) | Pass: changes in some runs, not others; old addresses reappear |
| Public address after reboot | Pass: changed; notifier announced it |
| Public address after crash (`SIGKILL`) | Pass: unchanged in one test |
| Telegram reachable with VPN on | Pass (test message delivered) |
| Telegram reachable with VPN off | Deferred (user: not needed) |
| VPN stop/start effect on the tunnel | Partly observed (~2 minutes VPN off; endpoint API stayed up; external reachability not checked). Deferred |
| Ethernet disconnect/reconnect | Not run |
| Wi-Fi disconnect/reconnect | Not run |
| Happ dispatcher events observed in NetworkManager logs | Not run |
| Password authentication disabled on the Pi | Pass (`sshd -T`: `passwordauthentication no`, verified by the user) |

### Phase 1 — Skeleton and documentation

| Item | Status |
|---|---|
| `README.md` (install, configuration, operation, recovery, troubleshooting, update, uninstall, stop/start) | Pass (written; command accuracy checked against the implementation) |
| `README_RU.md` (user guide in Russian) | Pass (written) |
| `CLAUDE.md` and `DEVELOPMENT_PLAN.md` at the project root | Pass |
| Project-owned paths and file ownership defined | Pass (section 5.2) |
| Supported OS defined; other systems fail `check` | Pass (`check` tests) |

### Phase 2 — Runtime service and endpoint reporting

| Item | Status |
|---|---|
| Ngrok unit starts and forwards to `127.0.0.1:22` | Pass (manual and after reboot) |
| Boot startup | Pass (reboot test) |
| Exactly one agent instance | Pass (no duplicate observed in crash or reboot tests) |
| Restart policy and rate limit | Pass (crash test restarted after 10 s) |
| Endpoint helper (`host:port`, `--status`) | Pass (unit tests and live, up and down) |
| Telegram sender (0600 credential check, bounded retries, no token in args) | Pass (unit tests; live send delivered) |
| Notifier: first announcement, unchanged, changed | Pass (live: announced, unchanged; after recovery change: announced) |
| Secrets not in argv, logs, or status output | Pass (reviewed; `status` prints no credentials) |

### Phase 3 — Network and VPN recovery

| Item | Status |
|---|---|
| Dispatcher hook (unique filename, no interface names, fast) | Implemented and unit-tested; not yet triggered by real NetworkManager events on the Pi |
| Recovery: debounce, lock, route check, restart only when no endpoint | Pass (unit tests; live recovery after `systemctl stop`) |
| Watchdog as backstop | Pass (live: after the `e4939a7` fix, recovered within one tick) |
| Disabled service stays disabled | Pass (live: 150 s, `disabled` logged, agent stayed down) |
| Happ start/stop | Partly observed (see Phase 0) |
| Ethernet and Wi-Fi transitions | Not run |
| No restart storm or duplicate agent during transitions | Not run |

### Phase 4 — Setup script

| Item | Status |
|---|---|
| `check`: OS, arch, systemd, NetworkManager, user, ngrok, project files | Pass (on the Pi; wrong OS/arch fail clearly) |
| `status` | Pass |
| `install`: runs `check`, verifies units, atomic file placement, creates credentials, enables units | Pass (real install on the Pi; fake-root tests) |
| Second install is idempotent and keeps credentials | Pass (fake-root test) |
| `--dry-run` writes nothing | Pass (fake-root test) |
| `uninstall`: removes only project files; keeps credentials and state; keeps edited dispatcher | Pass (fake-root tests) |
| Real uninstall and reinstall on the Pi | Not run |
| Clean install on a fresh Debian 13 arm64 image | Not run |
| Automated ngrok binary install (official, verified) | Not implemented; ngrok must be installed beforehand |

### Phase 5 — Testing and hardening

| Test | Status |
|---|---|
| Clean install on fresh supported image | Not run |
| Repeated setup | Pass (fake root) |
| Existing ngrok binary and config | Not separately tested (install never writes ngrok files; the real install left the binary and config unchanged) |
| Missing credentials (no `.env` and no `telegram.env`) | Not run (code path exists; no test covers it) |
| Invalid credentials | Not run |
| Missing payment method / no TCP entitlement | Not run (account has entitlement) |
| Address change after each recovery path | Partly: restart, crash, reboot recorded |
| Boot with Ethernet only / Wi-Fi only | Not run |
| Boot with VPN already active | Pass (current boot state) |
| VPN starts after boot | Not run as a separate case |
| VPN stops while Ethernet remains | Deferred (user) |
| VPN restarts | Not run |
| Ethernet disconnect/reconnect | Not run |
| Wi-Fi disconnect/reconnect | Not run |
| Default-route replacement | Partly (VPN off changed the route to `eth0`; deferred for full test) |
| ngrok process crash | Pass |
| External connectivity interruption | Not run |
| SSH daemon unavailable initially, started later | Not run |
| Endpoint discovery after every recovery | Pass for restart, crash, reboot |
| Uninstall and reinstall on the Pi | Not run |
| Happ, VPN gateway, Android-sharing units unchanged | Pass (no changes made to them; checked by reading unit state) |

Security checks:
- Key-based SSH only (password authentication off): Pass.
- Tunnel forwards to `127.0.0.1:22` only: Pass (`status` shows `addr=//127.0.0.1:22`).
- No secrets in logs, arguments, or generated docs: Pass (reviewed; the authtoken and bot token were never printed).

## 7. Operational notes

- Stop the tunnel for real: `sudo systemctl disable --now ngrok-ssh.service`. Re-enable with `sudo systemctl enable --now ngrok-ssh.service` (re-running `setup.sh install` does the same).
- Sudo: `bliss` has passwordless sudo only for some Happ diagnostic commands. Installs need a cached sudo session (`sudo -v`), which lasts about 15 minutes.
- Endpoint changes are written to the vdsn2 file within about two minutes (the notify timer runs every 60 s). Telegram is sent at the same time when configured.
- Free plan limits apply: 1 GB/month data out, 5,000 TCP connections/month.

## 8. Open items and risks

| Item | Impact | Next step |
|---|---|---|
| Ethernet and Wi-Fi transitions untested | Recovery through physical link changes is unverified | Test with the user's go-ahead, including a rescue plan if SSH drops |
| VPN stop/start (full) | Recovery through VPN transitions is only partly observed | Deferred by user |
| Watchdog overrides a plain `systemctl stop` within about 2 minutes | Stopping without `disable` does not hold | Documented; use `disable --now` |
| Crash outage about 10–15 s | Brief unavailability on each crash | Accepted |
| Fresh-system install not tested | Reproducibility is unproven | Build a clean Debian 13 arm64 image or VM and run `check`, `install`, `uninstall` |
| ngrok binary not installed by `setup.sh` | Fresh install stops at `check` until ngrok is installed | Decide on an official, verified install method |
| Dispatcher hook not yet fired by real NM events | Event path is unverified on the Pi | Trigger a real event with the user's go-ahead (ties to Ethernet/VPN tests) |
| Random endpoint address on the free plan | Clients read the vdsn2 file (or the optional Telegram message) after each change | Accepted by decision; reserved address would need a paid plan |
| vdsn2 unreachable | Endpoint file goes stale until the next successful write | Retried every minute; the failure is in `journalctl -u ngrok-ssh-notify.service` |
| The Pi has no GitHub password or token; pushes use a deploy key | Pushes fail if the key is removed | Keep the key scoped to this repository (write access) |

## 9. Scope exclusions

This project will not:
- install or configure Happ VPN, or modify its service or Xray configuration;
- repair or modify the Android VPN-sharing setup or the VPN gateway watcher/forwarder;
- change global routing, policy routing, firewall, NAT, or IP forwarding;
- change SSH authentication policy or authorized keys;
- create an ngrok account or reserve a TCP endpoint;
- expose any service other than SSH.

## 10. Definition of done

Met on `pi5home`: the tunnel starts on boot, recovers after a crash, announces the current endpoint on change, can be stopped and started cleanly, and installs and uninstalls through `setup.sh`.

Still required before calling the project complete:
1. Ethernet and Wi-Fi transition tests (Phase 3, Phase 5).
2. Real uninstall and reinstall on the Pi (Phase 4).
3. Clean install on a fresh supported Debian 13 arm64 system (Phase 4, Phase 5).
4. Decision on automating the ngrok binary install (Phase 4).
