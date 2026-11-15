# ngrok SSH tunnel for pi5home

Exposes SSH on a Raspberry Pi through an ngrok TCP endpoint and recovers after reboots, network changes, and Happ VPN transitions. The endpoint is random on the free ngrok plan and can change, so the current address is announced over Telegram when it changes.

Design and phases: see `DEVELOPMENT_PLAN.md`. Agent rules: see `CLAUDE.md`.

For a user guide in Russian (how to connect, what to do when the address changes, how to stop the tunnel), see `README_RU.md`.

## Prerequisites

- Raspberry Pi OS / Debian 13 (Trixie), arm64. Other systems fail `check`.
- NetworkManager active.
- ngrok agent installed at `/usr/local/bin/ngrok`. The setup script does **not** install ngrok yet.
- A working ngrok config for the service user, at `~/.config/ngrok/ngrok.yml`, containing a valid authtoken. Check it with `ngrok config check`.
- OpenSSH server listening on port 22, with key-based authentication. Password login is allowed only for user `bliss` (`Match User bliss` at the end of `/etc/ssh/sshd_config`). Global `PasswordAuthentication` stays `no`. Because SSH is publicly reachable through ngrok, use a strong password for `bliss`.
- A Telegram bot token and chat ID in `.env` (see `.env.example`). `.env` must never be committed.

## Installation

Run from the project directory:

```bash
sudo ./setup.sh check                  # read-only validation
sudo ./setup.sh --dry-run install      # show what would change, write nothing
sudo ./setup.sh install                # install and enable
```

`install` runs `check` first and refuses to continue if any check fails. It:

- copies scripts to `/usr/local/lib/ngrok-ssh/` and the ngrok config to `/usr/local/lib/ngrok-ssh/config/`;
- installs the systemd units to `/etc/systemd/system/`;
- installs the NetworkManager dispatcher hook to `/etc/NetworkManager/dispatcher.d/50-ngrok-ssh`;
- creates `~/.config/ngrok-ssh/telegram.env` (mode 600) from the `TELEGRAM_*` keys in `.env`, only if it does not already exist;
- adds a managed `Match User bliss` block with `PasswordAuthentication yes` to the end of `/etc/ssh/sshd_config` (backup at `sshd_config.bak-ngrok-ssh`, validated with `sshd -t`, then `ssh` is reloaded). Other users keep password login off;
- enables `ngrok-ssh.service`, `ngrok-ssh-recover.timer`, and `ngrok-ssh-notify.timer`.

Re-running `install` is safe. It overwrites project files and keeps existing credentials.

The service user defaults to `bliss`. Use `--user NAME` to change it.

## Configuration

- `.env`: Telegram credentials, read only at install time. Copied to `~/.config/ngrok-ssh/telegram.env`.
- `config/ngrok-ssh.yml`: the TCP endpoint definition (forwards to `127.0.0.1:22`). Layered on top of the user's ngrok config.
- `NGROK_SSH_ENV`, `NGROK_SSH_USER`: environment overrides used by the notify job.

## Operation

```bash
sudo ./setup.sh status                       # endpoint state and unit states
python3 /usr/local/lib/ngrok-ssh/scripts/ngrok-endpoint.py   # print host:port
systemctl status ngrok-ssh.service
journalctl -u ngrok-ssh.service -n 100
journalctl -u ngrok-ssh-recover.service -n 50
journalctl -u ngrok-ssh-notify.service -n 50
journalctl -t ngrok-ssh-dispatch -n 50       # NetworkManager events
```

Restart the tunnel manually:

```bash
sudo systemctl restart ngrok-ssh.service
```

Stop the tunnel for real:

```bash
sudo systemctl disable --now ngrok-ssh.service
```

A disabled tunnel stays off after a reboot, and the recovery check leaves it alone. A plain `systemctl stop` does not work for this: the recovery check starts the tunnel again within about two minutes whenever it is enabled. To start it again:

```bash
sudo systemctl enable --now ngrok-ssh.service
```

Running `sudo ./setup.sh install` also enables it again.

Connect:

```bash
ssh -p PORT bliss@HOST                       # from the endpoint printed above
```

## How recovery works

- The NetworkManager dispatcher hook records `up`, `down`, `vpn-up`, `vpn-down`, `connectivity-change`, and `dhcp4-change` events. It never restarts ngrok and does not depend on interface names.
- `ngrok-ssh-recover.timer` runs every minute. If a default route exists but no endpoint is up, it requests recovery. A recovery run acts only after events have settled for 5 seconds, takes a lock, and restarts the agent only when no endpoint is up. It does nothing while `ngrok-ssh.service` is disabled.
- `ngrok-ssh-notify.timer` runs every minute. It announces the endpoint over Telegram only when it changes. If the send fails, the change is retried on the next run.

## Troubleshooting

- `check` fails on OS or architecture: this project supports Debian 13 arm64 only.
- `check` fails on ngrok: install ngrok and run `ngrok config check` as the service user.
- `status` shows `state=down`: the agent is not running or has no endpoint. Look at `journalctl -u ngrok-ssh.service`.
- Telegram not announcing: check `~/.config/ngrok-ssh/telegram.env` permissions (600) and `journalctl -u ngrok-ssh-notify.service`.

## Update

```bash
git pull
sudo ./setup.sh check
sudo ./setup.sh install
```

## Uninstall

```bash
sudo ./setup.sh uninstall
```

This stops and disables the project units and removes only the files install placed and the managed `sshd_config` block. It keeps `~/.config/ngrok-ssh/telegram.env`, the notifier state under `~/.local/state/ngrok-ssh/`, the ngrok binary, and the ngrok configuration. A dispatcher file that was edited after install is kept.

Existing VPN gateway and Android-sharing components are not touched by this project.
