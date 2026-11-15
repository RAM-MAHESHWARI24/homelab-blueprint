# Security Policy

## Supported versions

Only the latest release receives fixes. Version 2.0.0 is the first release with token authentication; earlier versions should not be run on a shared network.

## Reporting a vulnerability

Please report security problems privately through GitHub's **Report a vulnerability** button on the repository's Security tab. Do not open a public issue for them.

Include what you found, how to reproduce it, and which version or commit you tested. You should get a reply within a week.

## Security model

Knowing these limits helps judge whether something is a vulnerability:

- **The Control Hub is root-equivalent by design.** It runs as the `homelab` system user, which is in the `docker` group, and it can run a small set of exact commands through sudo. Anyone holding its bearer token controls the host.
- **The bearer token is the boundary.** All Control Hub and Setup Wizard API routes require it, except health probes and the API description. The token lives in `/etc/homelab/control-hub.token`, mode 0640, `root:homelab`.
- **Secrets are generated, never shipped.** Rendered env files in `/etc/homelab/` are mode 0600. The Prowlarr API key copy for the indexer picker is 0640 `root:homelab`.
- **LAN only.** Nothing is designed to face the internet. There is no TLS, rate limiting or account lockout. Remote access should go through a VPN such as Tailscale.
- **Images are pinned.** Updates arrive as Dependabot pull requests, not automatic pulls.

In scope: bypassing the token, reading secrets without it, privilege escalation beyond what the token already grants, command injection through the wizard or Control Hub, and installer steps that leave files more permissive than documented.

Out of scope: anything that requires the token or root, and vulnerabilities in the upstream container images. Report those upstream.
