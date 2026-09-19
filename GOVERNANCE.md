# Governance

TraceKite uses a maintainer-led governance model during public preview.

## Decisions

Routine changes are decided through pull-request review. Changes to the public
wire contract, evidence semantics, storage model, security boundary, or
supported release surface must also agree with
[`docs/design/architecture.md`](docs/design/architecture.md) and include tests
for the affected contract.

Maintainers seek technical consensus. When consensus is not possible, the
maintainers make the final decision and record the reason in the pull request
or architecture decision record.

## Roles

- **Contributors** open issues, propose changes, review code, and improve
  documentation.
- **Maintainers** triage reports, review and merge changes, manage releases,
  moderate project spaces, and protect the project's evidence guarantees.

Maintainer access is granted based on sustained, constructive contributions and
sound judgment around correctness, security, and the project's
“never invent an edge” invariant. Maintainers may step down at any time.

## Contributions and licensing

No contributor license agreement is required. Under section 5 of the Apache
License 2.0, intentionally submitted contributions are provided under the
project license unless explicitly marked otherwise.

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the development workflow,
[`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) for community expectations, and
[`SECURITY.md`](SECURITY.md) for confidential vulnerability reporting.

## Releases

Maintainers authorize releases from a reviewed commit. The package version,
Git tag, release source commit, built distributions, and published checksums
must agree. The release workflow may publish only through the protected `pypi`
environment.
