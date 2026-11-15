# DEVELOPMENT_PLAN.md

## 1. Objective

Create a deployable Raspberry Pi project that exposes SSH on the Pi through an ngrok TCP tunnel and automatically recovers across boot, physical network changes, and Happ VPN transitions.

The project must be reproducible on a fresh supported Raspberry Pi OS / Debian ARM64 installation through an idempotent setup script.

**Current task boundary:** documentation and planning only. Do not implement, install, or modify services on the development Pi until explicitly authorized.

## 2. Confirmed environment (discovered 2026-11-15)

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
| Wi-Fi | `wlan0`, disconnected during discovery |
| VPN | Happ / Xray |
| VPN interface | `happ-xray`, `172.19.0.1/30` |
| Happ daemon | `/opt/happ/bin/happd`, `happd.service` |
| Happ GUI | `/opt/happ/bin/Happ` |
| Xray core | `/opt/happ/bin/core/xray` |
| SSH | `ssh.service`, listening on TCP/22 |
| ngrok | `/usr/local/bin/ngrok`, v3.39.10 |
| ngrok config | `/home/bliss/.config/ngrok/ngrok.yml` |
| Network event mechanism | NetworkManager dispatcher |

### Current IPv4 routes

```text
default dev happ-xray metric 1
default via 192.168.0.1 dev eth0 proto dhcp src 192.168.0.118 metric 100
172.19.0.0/30 dev happ-xray proto kernel scope link src 172.19.0.1
192.168.0.0/24 dev eth0 proto kernel scope link src 192.168.0.118 metric 100
```

The Happ route is preferred while installed; Ethernet is a fallback default route. The target behavior is to use the system's currently usable route, not to pin ngrok to a named interface.

### Existing system services

- `happd.service`: root-owned Happ daemon, `Restart=always`.
- `vpn-gateway-watch.service`: Python watcher for Happ GUI intent.
- `vpn-gateway-forward.service`: Python service applying the existing VPN gateway forwarding policy.
- `android-vpn-share.service` and `android-vpn-share.timer`: existing Android sharing integration.
- `NetworkManager-dispatcher.service`: enabled and invoked for NetworkManager events.

Existing custom VPN gateway files are under `/usr/local/lib/vpn-gateway/`.

### Existing dispatcher caveat

`/etc/NetworkManager/dispatcher.d/90-android-vpn-share` currently reacts to `wlp8s0` and `tun0`, whereas this Pi currently reports `eth0` and `happ-xray`. This mismatch belongs to the pre-existing Android-sharing integration and is out of scope. Do not modify it or assume its interface names are correct for the ngrok integration.

`NetworkManager-dispatcher.service` being inactive after completing an event is expected for this dispatcher service; it successfully starts and exits after processing events.

### ngrok account prerequisite

The installed CLI's `ngrok help tcp` says that a reserved TCP address is required for a stable public address and supports `--url=<reserved-host:port>`. The user reports a **free** ngrok account, so a reserved address is expected to be unavailable (see below). Payment-method status is unconfirmed. Account prerequisites cannot be provisioned by the setup script.

Documentation findings (ngrok docs, checked 2026-11-15; not a test of the actual account):
- TCP endpoints on a free plan require a valid payment method on the account.
- Free plan: TCP endpoints require a valid payment method (credit/debit, not prepaid; card not charged on free tier).
- A static public TCP endpoint requires a reserved TCP Address (dashboard: Gateway > TCP Addresses), but **TCP Addresses are not available on the free plan**; free accounts get randomly assigned addresses. Hostname and port cannot be chosen.
- The free static dev domain (`*.ngrok-free.dev`) every account gets is for HTTP(S) endpoints, not TCP. Docs say only TCP endpoints go on TCP Addresses and other types use Domains; do not assume the dev domain can front SSH. Test before relying on it.
- Static option: TCP Addresses are included (1 each) on Hobbyist and Pay-as-you-go plans; extras $0.005/hour. Hobbyist is listed by third parties at about $8/month annual or $10/month monthly (verify on ngrok's pricing page). A reserved address is a fixed host and port with no static IP. User requirement: static hostname; upgrade decision pending.
- Free limits: 1 GB/month data out, 5,000 TCP connections/month, 100 TCP connections/min.
- Consequence for this project: the public address is not stable and may change on every endpoint (re)creation. Endpoint discovery and out-of-band delivery of the new address are core requirements.
- ngrok's FAQ says the agent is robust to network changes; whether the address persists across an in-process reconnect, an agent restart, and VPN route changes must be tested.
- Credentials: the agent needs the *authtoken*; the ngrok *API key* is separate (REST API only) and is not needed by the tunnel. Never paste either into chat or docs.
- Source-IP restriction is supported with `--cidr-allow` or with a config `endpoints:` entry using `traffic_policy` / `on_tcp_connect` / `restrict-ips`.

## 3. Desired behavior

1. SSH is exposed only by a TCP ngrok endpoint forwarding to local port 22.
2. The tunnel starts automatically after boot.
3. The tunnel becomes active when any supported internet path becomes usable.
4. When Happ VPN is active and its default route is preferred, ngrok normally follows that route.
5. When Happ VPN stops or restarts, ngrok recovers through the remaining usable route.
6. Ethernet/Wi-Fi reconnects trigger recovery.
7. A crashed ngrok process is restarted.
8. The currently active public endpoint is easy to retrieve.
9. Existing VPN gateway and Android-sharing behavior is left untouched.
10. The same project can be installed on a fresh supported system using the setup script.

## 4. Proposed architecture

Keep the design small and isolated:

- **ngrok systemd service:** owns the ngrok agent process and starts at boot.
- **NetworkManager dispatcher hook:** sends a restart/recheck request for relevant interface and connectivity events. It must be quick and must not block NetworkManager.
- **Recovery/watchdog helper:** debounces events, checks usable route/connectivity, and requests recovery if an event was missed or the tunnel is stale.
- **Endpoint/status helper:** obtains the active TCP endpoint from a supported ngrok local API or another documented source, validates it, and exposes it through a status command or state file.
- **Setup script:** validates OS/architecture, installs missing prerequisites and ngrok if needed, installs project-owned files, configures systemd and dispatcher integration, and enables the service.
- **Uninstall script or setup-script uninstall mode:** removes only project-owned artifacts.

Prefer one clear owner for process lifecycle. Avoid designs where the dispatcher, watchdog, and systemd independently launch multiple ngrok instances. Event handlers should signal a single supervisor or use a single lock/debounce mechanism.

### Route and failover strategy

- Do not hardcode `eth0`, `wlan0`, `tun0`, or `happ-xray`.
- Do not add routes, policy rules, firewall rules, NAT, or forwarding rules.
- Let the kernel's active routing table choose the path.
- Use NetworkManager events for `up`, `down`, `connectivity-change`, and relevant VPN interface changes.
- Verify actual behavior for Happ's externally managed TUN device; do not assume all VPN transitions emit the same dispatcher events as a standard NetworkManager VPN profile.
- Add a low-frequency health/recovery check as a backstop for missed events.
- Debounce transition bursts and avoid unnecessary restarts when the effective route and tunnel are healthy.
- Decide whether an ngrok restart is required on every route transition or whether the agent reliably reconnects itself. Validate this experimentally before finalizing the policy.

### Endpoint change notification (Telegram)

A single-owner helper reads the active endpoint from the local ngrok agent API, compares it with a state file holding the last successfully notified endpoint, and sends a Telegram message only on change. It uses Python stdlib with explicit timeouts, never puts the token in arguments or logs, retries with bounded backoff, and never blocks or restarts the tunnel. See `CLAUDE.md` for requirements.

## 5. Implementation phases

### Phase 0 — Prerequisite and design verification

Tasks:
- Verify ngrok account supports TCP endpoints (docs say a payment method is required on a free plan; confirm against the actual account).
- Confirm the free account has a payment method added (required for TCP endpoints). Reserved TCP Addresses are unavailable on the free plan, so plan for a changing address.
- Measure experimentally whether the public address changes on: ngrok restart, VPN start/stop, Ethernet reconnect. Record results.
- Telegram is the chosen channel for changed-address notifications. Verify Telegram reachability with VPN on and off, and verify the stored-secret handling (0600 file, no secrets in args/logs).
- Decide between CLI flags (`ngrok tcp 22 --url=...`) and a project-owned config with an `endpoints:` entry; test against agent 3.39.10. Prefer a project-owned config file layered with the user's existing config so credentials are never overwritten.
- Confirm how the installed ngrok version exposes active endpoint information (local API, agent status, or supported CLI output).
- Confirm ngrok configuration/authentication behavior on a fresh system.
- Verify Happ route transitions and NetworkManager dispatcher events using logs and read-only observation.
- Supported fresh-install OS: Debian 13 (Trixie) arm64 only (decided); other releases fail clearly.
- Service user and config ownership: existing user `bliss` with its existing ngrok config (decided); setup script takes the user as a parameter defaulting to `bliss`.

Exit criteria:
- No unresolved blocker concerning TCP endpoint entitlement, credentials, endpoint discovery, or route recovery design.
- No changes made to existing VPN gateway or Android-sharing components.

### Phase 1 — Project skeleton and documentation

Tasks:
- Keep `CLAUDE.md` and this `DEVELOPMENT_PLAN.md` at the project root.
- Add a README with prerequisites, installation, configuration, operation, troubleshooting, update, and uninstall.
- Define project-owned paths and file ownership.
- Define supported OS versions and explicit unsupported-system behavior.

Exit criteria:
- A new developer/agent can understand the architecture and safely implement it without relying on undocumented machine state.

### Phase 2 — Runtime service and endpoint reporting

Tasks:
- Implement the ngrok TCP service forwarding to `127.0.0.1:22`.
- Use a reserved TCP address only if one is configured (not available on the free plan); otherwise request a random TCP endpoint and report the assigned address.
- Add systemd startup ordering without treating `network-online.target` as proof of internet or VPN readiness.
- Configure restart behavior and sensible rate limits/backoff.
- Add endpoint discovery and a concise status command.
- Add the Telegram change notifier (state file, dedupe, retry, no secrets in args/logs).
- Ensure secrets never appear in process arguments, logs, or status output.

Exit criteria:
- Manual start works.
- Boot startup works.
- Exactly one agent instance is managed.
- The endpoint is reported accurately after initial connection and reconnect.

### Phase 3 — Network and VPN recovery

Tasks:
- Add a project-owned NetworkManager dispatcher hook with a unique filename.
- Handle relevant interface `up`/`down` and connectivity changes without assuming interface names.
- Ensure dispatcher actions are fast and asynchronous.
- Implement a debounced recovery signal/queue or equivalent single-owner mechanism.
- Add a modest watchdog for missed events and stale tunnels.
- Check that a usable default route and external connectivity exist before starting/restarting.
- Test Happ VPN transitions separately from physical Ethernet/Wi-Fi transitions.

Exit criteria:
- VPN start/stop/restart and physical network reconnect restore the tunnel without manual intervention.
- No restart storm or duplicate ngrok process.
- Existing route policy is unchanged.

### Phase 4 — Idempotent fresh-system setup

Tasks:
- Implement a setup script for fresh Raspberry Pi OS / Debian ARM64.
- Validate root privileges, OS ID/version, architecture, systemd, and NetworkManager availability.
- Install only missing dependencies.
- Install ngrok only when absent, using an official verifiable distribution method.
- Detect existing ngrok and avoid destructive replacement.
- Configure credentials securely without embedding or echoing the token.
- Validate ngrok config and TCP endpoint prerequisites (payment method; reserved address optional).
- Install service/helper/dispatcher files atomically.
- Validate systemd unit syntax before enabling.
- Enable and start only project-owned units.
- Support safe reruns and a project-only uninstall mode.
- Preserve user ngrok config and all unrelated system configuration.

Exit criteria:
- Clean install succeeds on a fresh supported image.
- Second run makes no harmful changes.
- Existing ngrok installation/configuration is preserved according to documented policy.
- Uninstall removes only project-owned files and units.

### Phase 5 — Testing and hardening

Run and record:
- clean install on fresh supported image;
- repeated setup;
- existing ngrok binary and config;
- missing credentials;
- invalid credentials;
- missing payment method / insufficient account entitlement for TCP endpoints;
- address change behaviour after each recovery path (record whether it changes and whether the notification fires);
- boot with Ethernet only;
- boot with Wi-Fi only;
- boot with VPN already active;
- VPN starts after boot;
- VPN stops while Ethernet remains;
- VPN restarts;
- Ethernet disconnect/reconnect;
- Wi-Fi disconnect/reconnect;
- default-route replacement;
- ngrok process crash;
- external connectivity interruption;
- SSH daemon unavailable initially and started later;
- endpoint discovery after every recovery;
- uninstall and reinstall;
- verify Happ and existing gateway/Android-sharing units and configuration remain unchanged.

Security checks:
- SSH uses key-based authentication; do not weaken sshd settings.
- Tunnel forwards to loopback port 22 only.
- No secret in logs, process arguments, shell history, or generated documentation.
- No ngrok IP restriction by decision; SSH key authentication is the access control. Verify password authentication is disabled on the Pi (read-only check; do not change sshd settings).

Exit criteria:
- All mandatory tests pass or have documented, accepted limitations.
- No regression in existing VPN or Android-sharing behavior.
- Recovery and endpoint status are observable.

## 6. Setup script interface (proposed)

The implementation should provide a documented interface similar to:

```text
sudo ./setup.sh install
sudo ./setup.sh check
sudo ./setup.sh status
sudo ./setup.sh uninstall
```

Exact commands may change during implementation, but the script must clearly separate installation, non-destructive validation, status, and removal.

A dry-run option is desirable. Do not make the setup script silently reset networking or modify VPN settings.

## 7. Operational interface (proposed)

Document commands for:
- service status;
- current endpoint;
- recent service logs;
- recovery/watchdog logs;
- configuration validation;
- restart/reconnect request;
- update;
- uninstall.

Use the final unit and command names consistently across README, setup script, and tests.

## 8. Risks and unresolved decisions

| Risk / unknown | Required action |
|---|---|
| TCP endpoint entitlement unknown | Docs: payment method required on free plan; reserved addresses unavailable on free plan. Verify the payment method is on the account |
| Sanitized ngrok config did not reveal auth fields | Preserve config; inspect securely without printing secrets |
| Happ TUN is externally managed | Observe actual route and dispatcher events during VPN transitions |
| Existing dispatcher uses different interface names | Keep existing script out of scope; design a separate generic hook |
| ngrok may reconnect itself after route changes | Test before deciding whether to restart the agent |
| Public address is random on the free plan and may change | Treat as expected; implement reliable discovery plus out-of-band notification; measure when it changes. A paid plan with a reserved address is the alternative if stability is required |
| Happ present on the target host with VPN on | Required to work with Happ, but keep recovery generic (no hardcoded Happ names); Happ stays optional for fresh images without it |
| Debian/Raspberry Pi OS versions may differ | Explicitly define and validate supported versions |

## 8a. Decisions and open questions

Decided (2026-11-15):
- Service user: existing `bliss`, reusing `/home/bliss/.config/ngrok/ngrok.yml`.
- Supported OS: Debian 13 (Trixie) arm64 only.
- No ngrok source-IP restriction; rely on SSH key authentication.

- Plan: free plan only (user decision). Public address is random and may change; reserved-address mode is optional and not implemented/tested now.
- Change notification: Telegram message from the Pi when the public endpoint changes (bot token and chat ID supplied by the user, never shared in chat).
- Happ runs on the host with the VPN on; the tunnel must work with it.

Still open:
1. (Likely resolved) Dashboard reportedly shows Identity Verification: Verified. Confirm by starting a real TCP endpoint in Phase 0.
2. (Resolved) Free plan only; Telegram notification on endpoint change.
3. Telegram secrets storage (proposed: 0600 environment file readable only by `bliss`, created by setup without echoing) and Telegram reachability with the Happ VPN on and off.
3. Is the existing authtoken in the ngrok config valid (checked without printing it)?

## 9. Scope exclusions

Unless explicitly requested, this project will not:
- install or configure Happ VPN;
- modify Happ's service or Xray configuration;
- repair the existing Android VPN-sharing setup;
- modify the existing VPN gateway watcher/forwarder;
- change global routing, policy routing, firewall, NAT, or IP forwarding;
- change SSH authentication policy or authorized keys;
- create an ngrok account or reserve a TCP endpoint;
- expose any service other than SSH.

## 10. Definition of done

The project is complete when a fresh supported Raspberry Pi OS system can be provisioned with the idempotent setup script, the SSH TCP endpoint starts on boot, network/VPN transitions recover automatically, the current endpoint is discoverable, logs explain failures, uninstall is safe, and existing VPN gateway functionality remains unchanged.
