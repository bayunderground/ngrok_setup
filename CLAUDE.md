# CLAUDE.md

## Project purpose

Build and maintain a small, reliable ngrok TCP tunnel that exposes the Raspberry Pi's SSH service (`127.0.0.1:22`) to remote clients.

The tunnel must start after boot and recover automatically after:
- Ethernet or Wi-Fi reconnects;
- Happ VPN/Xray starts, stops, or restarts;
- the default route changes;
- ngrok exits or loses connectivity.

The project must also include an **idempotent setup script** that can install the solution on a fresh, supported Raspberry Pi OS system. The setup script is a project deliverable. It has been run on `pi5home` with the user's authorization; any further install, uninstall, service restart, or VPN change on `pi5home` needs explicit authorization for that specific action.

## Current status (2026-11-15)

The project is implemented and installed on `pi5home`. Phase-by-phase status and the test matrix are in `DEVELOPMENT_PLAN.md`, sections 2 and 6.

- Installed: `ngrok-ssh.service`, `ngrok-ssh-recover.timer`, `ngrok-ssh-notify.timer`, and the NetworkManager dispatcher hook `50-ngrok-ssh`. The tunnel is up.
- Implemented and tested: `setup.sh check|status|install|uninstall` (`--dry-run`, `--user`), endpoint helper, recovery with debounce and lock, watchdog, Telegram notifier (state file, retries, 0600 credentials). 58 unit tests pass on the Pi.
- Verified on the Pi: tunnel starts after reboot; crash (`SIGKILL`) is restarted by systemd; watchdog recovers a missing endpoint within about two minutes; a disabled service stays disabled; endpoint changes are announced in Telegram; Telegram works with the VPN on.
- Not yet verified: Ethernet and Wi-Fi transitions; full VPN stop/start; real uninstall/reinstall on the Pi; clean install on a fresh Debian 13 arm64 system; automated ngrok binary install (not implemented).
- Development happens on the Pi, in `~/ngrok_setup`. Commit after each major change and push with the Pi's deploy key. The deploy key has write access to this repository only.
- Stop the tunnel with `sudo systemctl disable --now ngrok-ssh.service`. A plain `systemctl stop` is undone by the watchdog.
- Do not ask for or record the sudo password. Installs use a cached `sudo -v` session that the user starts on the Pi.

## Current reference environment

Discovery performed on 2026-11-15:

| Item | Observed value |
|---|---|
| Hardware | Raspberry Pi 5 |
| Hostname | `pi5home` |
| OS | Debian GNU/Linux 13 (Trixie), Raspberry Pi OS |
| Kernel | `6.18.29+rpt-rpi-2712` |
| Architecture | `arm64` |
| systemd | `257.13-1~deb13u1` |
| Network manager | NetworkManager |
| Ethernet | `eth0`, currently `192.168.0.118/24` |
| Wi-Fi | `wlan0`, currently disconnected |
| Happ VPN interface | `happ-xray` |
| Happ daemon | `/opt/happ/bin/happd`, `happd.service` |
| Happ GUI | `/opt/happ/bin/Happ` |
| VPN core | `/opt/happ/bin/core/xray` |
| SSH | `ssh.service`, listening on TCP/22 |
| ngrok | `/usr/local/bin/ngrok`, version `3.39.10` |
| ngrok config | `/home/bliss/.config/ngrok/ngrok.yml` |

This is the observed development machine, not a guarantee that every fresh installation has the same hostname, IP address, interfaces, Happ version, or installed software.

## Observed routing and network behavior

At discovery time:

```text
default dev happ-xray metric 1
default via 192.168.0.1 dev eth0 proto dhcp src 192.168.0.118 metric 100
172.19.0.0/30 dev happ-xray
192.168.0.0/24 dev eth0
```

The VPN default route has the lower metric and is preferred while present. Ethernet provides a higher-metric default route. The intended behavior is to use whichever usable route is currently available, without hardcoding ngrok to a specific interface.

Do not assume that interface names or metrics remain the same on a fresh system. Discover them at runtime.

## Existing services and integrations — preserve them

The Pi already has custom VPN gateway components:

- `happd.service`
- `vpn-gateway-watch.service`
- `vpn-gateway-forward.service`
- `/usr/local/lib/vpn-gateway/happ_watch.py`
- `/usr/local/lib/vpn-gateway/forward_apply.py`
- `/usr/local/lib/vpn-gateway/forward_policy.py`
- `/usr/local/lib/vpn-gateway/gateway_mode.py`

There is also an existing Android VPN-sharing integration:

- `/etc/NetworkManager/dispatcher.d/90-android-vpn-share`
- `/usr/local/sbin/android-vpn-share`
- `android-vpn-share.service`
- `android-vpn-share.timer`

**Do not modify, replace, disable, or take ownership of these components.** The ngrok project must be isolated and coexist with them. In particular, do not modify global routes, policy routing, iptables/nftables, forwarding, or NAT to make ngrok work.

### Existing dispatcher caveat

The current `/etc/NetworkManager/dispatcher.d/90-android-vpn-share` script reacts to interface names `wlp8s0` and `tun0`, while the current Pi reports `eth0` and `happ-xray`. This is an observation to document, not permission to repair that unrelated script. Do not copy its interface assumptions into the ngrok integration.

`NetworkManager-dispatcher.service` being `inactive (dead)` after events is normal for this oneshot-style dispatcher service; it was enabled and successfully started/deactivated in its journal.

## ngrok behavior and prerequisites

- Use an ngrok **TCP** endpoint forwarding to the local SSH listener, preferably `127.0.0.1:22`.
- `ngrok tcp 22` is the basic CLI form.
- The installed CLI reports that a reserved TCP address is required for a stable public address and supports `--url=<reserved-host:port>`.
- Confirmed on 2026-11-15: the free plan creates TCP endpoints (a temporary `ngrok tcp 22` received a random address). Reserved TCP addresses are still unavailable on the free plan, so the project does not use one.
- Documentation check (ngrok docs, 2026-11-15): TCP endpoints are available on a free plan only after a valid payment method (credit/debit card, not prepaid; not charged on free tier) is added to the account. **Reserved TCP Addresses are not available on the free plan** (they are a paid-plan feature, billed per address). Free accounts get a randomly assigned hostname:port, which should be assumed to change whenever the endpoint is recreated. The ngrok FAQ says the agent is robust to network changes; whether the address survives an in-process reconnect versus an agent restart must be tested, not assumed. These are documentation findings; the actual account state is still unverified (user reports a free account; payment-method status unknown).
- ngrok supports IP restriction both via CLI (`--cidr-allow`) and via an agent-config `endpoints:` entry (`url: tcp://<reserved-address>`, `upstream.url: 22`, `traffic_policy.on_tcp_connect` with `restrict-ips`). IP restriction is not used in this project (see Decisions); this note is kept only for the `endpoints:` config form, which on a free plan must use a random address (`tcp://`) rather than a reserved one. Verify against the installed agent version (3.39.10) before relying on it.
- A setup script cannot create an account, accept terms, add a payment method, or reserve an endpoint on the user's behalf.
- **Paid option for a static address (ngrok docs, 2026-11-15):** TCP Addresses are available on the Hobbyist and Pay-as-you-go plans, 1 included on each; extra addresses are $0.005/hour. Third-party sources list Hobbyist at about $8/month billed annually or $10/month billed monthly; verify the current price on ngrok's pricing page. Hobbyist limits per docs: 5,000 TCP connections/month included, 150 connections/min; third-party sources list 5 GB/month data transfer. The address is chosen by ngrok (you cannot pick host or port) and is tied to a point of presence chosen at creation; a CNAME from the user's own domain to the ngrok hostname can give a friendlier name. The setup script cannot buy a plan or reserve the address.
- **Free dev domain is not a TCP address:** every ngrok account gets one free static dev domain (`*.ngrok-free.dev`), but it is a Domain for HTTP(S) endpoints. ngrok's docs state that TCP Addresses carry only TCP endpoints and that other endpoint types use Domains, so the dev domain should not be assumed usable as the SSH tunnel address. Verify by testing before relying on it; do not design around it.
- **Free plan limits (ngrok docs, 2026-11-15):** 1 GB/month data transfer out, 5,000 TCP connections/month, 100 TCP connections/min. Heavy SSH use (large transfers, scripted or frequent connections) may exhaust these; document in the README.
- **Credential types:** the ngrok *authtoken* is what the agent needs to run. An ngrok *API key* is a different credential used only for the ngrok REST API (for example, listing online endpoints). Do not ask the user to paste either one into chat, docs, or logs. The API key is not required by the tunnel itself; if used at all (for example, to look up the current endpoint remotely), it must be stored with restrictive permissions outside the repository and never printed.
- **Free plan consequence:** the public address is not stable. Endpoint discovery and out-of-band delivery of the new address after each change are core requirements, not extras.
- Do not embed an authtoken in source code, scripts, unit files, command-line arguments, logs, or documentation.
- Reuse an existing valid ngrok configuration where appropriate. On a fresh system, explain how the user supplies the token securely, then validate the configuration.
- Never print or request the user's token in diagnostic output.

The discovered config file passed `ngrok config check`. The sanitized inspection showed `version: "3"` and an `agent:` section; authentication details were intentionally not disclosed. Do not infer that the token is absent.

## Required project deliverables

1. `CLAUDE.md` — this file, containing project context and agent constraints.
2. `DEVELOPMENT_PLAN.md` — phased design, implementation tasks, and acceptance tests.
3. An idempotent setup script for a fresh supported Raspberry Pi OS / Debian ARM64 installation.
4. Any small runtime helper(s), service unit(s), and dispatcher integration needed by the design.
5. A concise README or usage section describing setup, configuration, status, logs, endpoint discovery, update, and uninstall.

Changes to `pi5home` (installs, service changes, VPN toggles) need explicit authorization for each action. Do not stop, restart, or reconfigure Happ, the VPN gateway, or the Android-sharing setup as a side effect of testing.

## Setup script requirements

The setup script must:

- target Raspberry Pi OS / Debian 13 (Trixie) on ARM64 only, and explicitly validate this (Debian 12 and other releases are unsupported by decision);
- detect unsupported architectures/OS versions and fail clearly rather than making partial changes;
- check prerequisites and install only missing packages;
- detect an existing ngrok installation and avoid overwriting a newer or user-managed installation without an explicit policy;
- install ngrok using a documented, official, verifiable method if absent;
- run the ngrok service as the existing user `bliss` (decision), reusing that user's ngrok config; do not create a new service account. Hardening via systemd sandboxing options is encouraged where compatible. The setup script must take the target user from a variable/argument (default `bliss`) and fail clearly if the user or its home directory is missing;
- preserve existing user ngrok configuration and never overwrite credentials;
- prompt for or document secure token provisioning without echoing secrets;
- install files atomically, validate configuration and unit syntax, and make repeated runs safe;
- back up files it owns before replacing them;
- avoid editing Happ, NetworkManager connection profiles, global routes, firewall, NAT, or Android-sharing configuration;
- provide a dry-run or clearly separated validation mode if practical;
- support uninstalling only project-owned files and units, preserving user credentials and unrelated configuration;
- produce clear success/failure messages and useful logs.

Do not use `curl | sh`. Pin or verify downloaded artifacts and checksums/signatures where the upstream distribution method supports it.

## Runtime design constraints

- Use systemd for boot startup and process supervision.
- Use `Restart=always` or an equally robust policy with bounded restart behavior appropriate to the ngrok agent.
- Do not rely solely on `network-online.target`; it does not guarantee that the VPN route or internet path is usable.
- Integrate with NetworkManager events for physical network and VPN interface changes, but also provide a recovery mechanism for missed events or route changes not surfaced as expected.
- Debounce bursts of events so one network transition does not trigger many simultaneous restarts.
- Use bounded retries/backoff and avoid tight restart loops.
- Before declaring the tunnel healthy, verify that a usable default route and external connectivity exist.
- Let normal kernel routing choose the active route unless testing proves an explicit binding is necessary. Do not hardcode `eth0`, `wlan0`, `tun0`, or `happ-xray` as the ngrok egress interface.
- Ensure an ngrok reconnect does not alter system routing.
- Capture the current public TCP endpoint in a machine-readable or easily parseable status mechanism, without exposing credentials. Because the free plan gives a randomly assigned address, also provide a way to learn a changed address without being able to SSH in (see Open questions).
- Clearly distinguish local process health, ngrok control-plane connectivity, and actual SSH reachability.
- Keep logs in journald; avoid logging secrets or sensitive tunnel credentials.

## SSH security

- Forward only to the local SSH daemon, not to all interfaces or unrelated ports.
- Do not weaken `sshd_config`, enable password authentication, or change authorized keys.
- The observed SSH server currently listens on `0.0.0.0:22` and `[::]:22`; the tunnel should nevertheless target loopback.
- Decision: no ngrok source-IP restriction (`restrict-ips` / `--cidr-allow`) is used; SSH key authentication is the access control. Keep the design able to add it later, but do not implement it now.
- Document that a public TCP endpoint makes SSH reachable from the internet. Recommend key-based authentication, strong account security, updates, and ngrok traffic restrictions where supported.
- Do not claim that ngrok endpoint obscurity is an access-control mechanism.

## Engineering preferences

- Prefer Python for helper logic; use shell only for small, transparent wrappers and setup tasks.
- Keep dependencies minimal; prefer Python standard library and installed system tools.
- Use explicit timeouts, subprocess argument arrays (not shell interpolation), structured logs, and clear exit codes.
- Keep responsibilities separated: setup, event handling, health/recovery, endpoint/status reporting.
- Avoid unnecessary daemons or polling when event-driven mechanisms are reliable; use a modest watchdog as a safety net.
- Make behavior observable and testable.
- Document assumptions and distinguish observed facts from design choices.

## Mandatory validation before completion

Test on a disposable or freshly imaged supported system as well as the reference Pi where authorized:

- clean installation;
- repeated setup (idempotency);
- missing ngrok;
- existing ngrok and existing config;
- missing/invalid token;
- missing payment method / unsupported account entitlement for TCP endpoints;
- public address change after agent restart and after VPN/route transitions (record whether it changes);
- boot with Ethernet;
- boot with Wi-Fi;
- boot with VPN already active;
- VPN starts after boot;
- VPN stops while Ethernet remains;
- VPN restarts;
- Ethernet disconnects/reconnects;
- default route changes;
- ngrok process crashes;
- ngrok control-plane connectivity is interrupted;
- SSH daemon unavailable at startup and later becomes available;
- endpoint reporting after every reconnect;
- uninstall and reinstall;
- confirm existing VPN gateway and Android-sharing services remain unchanged.

Never report a test as passed unless it was actually executed and its result recorded.

## Decisions (recorded 2026-11-15)

- Service identity: existing user `bliss`, reusing `/home/bliss/.config/ngrok/ngrok.yml`.
- Supported OS: Debian 13 (Trixie) arm64 only.
- Source-IP restriction: not used; rely on SSH key authentication only.
- **Plan decision: free plan only.** The user wanted a static hostname, but a reserved TCP Address needs a paid plan and the user chose to stay free. The public address is therefore random (`tcp://` with no fixed address) and may change. Do not require or assume a reserved address. Keep the config able to accept an optional reserved address later, but implement and test the random-address mode.
- **Change notification: Telegram.** The Pi sends the user a Telegram message whenever the public endpoint changes (and on first establishment). The user has a bot token and chat ID (values not shared in chat and must not be requested or logged).
- Happ: the host runs Happ with the VPN on; the tunnel must work with it (compatibility is required, but Happ is still not installed/configured by this project, and the generic network recovery must not depend on Happ-specific names).
- **Telegram credentials (2026-11-15):** the bot token and chat ID live in the repository's `.env` (gitignored, mode 600 on the Pi). `setup.sh install` copies only the two `TELEGRAM_*` keys to `~/.config/ngrok-ssh/telegram.env` (mode 600, owned by `bliss`). Reinstalls keep the existing file.
- **Stop behaviour (2026-11-15):** recovery and the watchdog respect `systemctl disable`. The documented way to stop the tunnel is `systemctl disable --now ngrok-ssh.service`.
- **Telegram with the VPN off:** not required (user decision, 2026-11-15). Telegram with the VPN on is verified.
- **VPN-off measurements:** deferred by user decision (2026-11-15). Do not stop Happ for testing without a new explicit request.

## Open questions

Record answers here as they are given; do not guess.

1. **Resolved:** a TCP endpoint starts on the free plan (verified 2026-11-15).
2. **Resolved:** free plan only; changed addresses are delivered by Telegram.
3. **Resolved:** the authtoken in `/home/bliss/.config/ngrok/ngrok.yml` is valid. The agent starts and receives an endpoint. The token was never printed.
4. **Resolved:** Telegram storage uses the 0600 file described above, created by `setup.sh install` without echoing values.
5. **Partly resolved:** Telegram reachable with the VPN on: yes. With the VPN off: not tested, and not required by the user.
6. **Open:** ngrok binary installation. `setup.sh` does not install ngrok. Choose an official, verifiable method (signed apt repository or a pinned, checksum-verified release) or keep it as a manual prerequisite.
7. **Open:** Ethernet and Wi-Fi transition tests. Needs an explicit go-ahead and a rescue plan (physical access or a second network path) before running, because SSH may drop.
8. **Open:** a fresh-system test. Needs a disposable Debian 13 arm64 system (VM or SD image) to run `check`, `install`, and `uninstall`.

## Telegram notification requirements

- Send via the Telegram Bot API HTTPS endpoint using Python standard library (`urllib`), with explicit timeouts. Never pass the bot token on a command line (so no `curl` with the token in arguments).
- Notify only when the endpoint differs from the last successfully notified endpoint; keep that state in a project-owned state file so restarts do not cause duplicate messages or missed changes.
- Message content: the new `host:port`, a ready-to-use `ssh -p <port> <user>@<host>` line, and a timestamp. No tokens, no authtoken, no config contents.
- Retry with bounded backoff if Telegram or the network is unreachable; deliver the latest endpoint only (drop stale queued ones). If sending fails, keep the change marked as unnotified and retry on the next recovery cycle or watchdog tick.
- Do not let notification failures block or restart the tunnel.
- Treat the notification path (Telegram reached through whichever route is active, including Happ's VPN) as a tested requirement, not an assumption.
