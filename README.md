# Canberra Deployment Centre (CDC)

Root-controlled web console for a Linux deployment/tools server.

## One-line install (Ubuntu/Debian)

```bash
curl -fsSL https://raw.githubusercontent.com/vibhvesh/canberra-deployment-centre/main/install.sh | sudo bash
```

Open `http://SERVER_IP:1101`. The installer generates a strong root-console password and prints it once. It is stored in `/etc/canberra/console.env` with mode 600.

## Initial features

- Root-authenticated web console.
- Categorised uploads under `/opt/canberra/uploads/`.
- Root-only shared folder creation and browsing under `/opt/canberra/shared/`.
- Authenticated file downloads.
- System, disk, memory, Docker and service diagnostics.
- Audit log at `/opt/canberra/audit/console.log`.
- systemd service with automatic restart.

## Security

- HTTP only, no TLS/domain in this initial release, as requested.
- HTTP Basic authentication is not encrypted in transit. Restrict TCP/1101 to your trusted source IP in the cloud firewall. Do not expose it publicly.
- Prefer a private VPN or SSH tunnel when accessing over untrusted networks.
- The service runs as root. A compromise of the web service is a root-level compromise.
- The browser command panel only runs a fixed list of diagnostics; it is not an unrestricted shell.
- ZIP uploads are stored as files and are not automatically extracted or executed.
- No additional users, roles, or public share links are enabled.

## Service management

```bash
sudo systemctl status canberra-console
sudo journalctl -u canberra-console -f
sudo systemctl restart canberra-console
```

Configuration: `/etc/canberra/console.env`.
