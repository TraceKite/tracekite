# Security policy

## Supported versions

TraceKite is currently a public-preview project. Security fixes are made on the
latest released version and the default branch. Older preview releases are not
maintained after a replacement is published.

| Version | Supported |
|---|---|
| Latest release | Yes |
| Default branch | Yes, until the next release |
| Older releases | No |

## Report a vulnerability

Do not open a public issue for a vulnerability or include secrets, private
source, access tokens, or exploit details in an issue.

Use GitHub's **Security → Report a vulnerability** form:

<https://github.com/TraceKite/tracekite/security/advisories/new>

Include:

- the affected version or commit;
- the deployment mode (core library, CLI, MCP, or server);
- reproduction steps and the security impact;
- whether the report contains sensitive repository data; and
- any suggested mitigation.

Maintainers will acknowledge a report within seven days, keep discussion in the
private advisory, and coordinate disclosure after a fix is available. Please
allow a reasonable remediation period before public disclosure.

## Deployment boundary

The bundled Docker Compose stack binds to loopback and runs without API
authentication by default. If `BIND_ADDR` is changed from `127.0.0.1`, enable
authentication and set a strong `API_TOKEN` before starting the stack. See
[`docs/security-and-privacy.md`](docs/security-and-privacy.md) for the full data
and network boundary.
