# Security policy

## Reporting a vulnerability

Please do not open a public issue. Report privately by either:

- e-mailing hub@innovolt.no, or
- using GitHub's private vulnerability reporting on this repository (Security tab, "Report a vulnerability").

We aim to reply within 7 days.

## Scope

In scope: everything under `app/`.

Out of scope: apps on a hub run with the visitor's login, so an app can reach that person's data in other apps, and an app opened by an admin can act as that admin. That is how the hub works, not a bug; see the [security model](README.md#security-model).
