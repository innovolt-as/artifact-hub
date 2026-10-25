# Contributing

Bug reports, ideas and pull requests are welcome. For anything larger than a small fix, open an issue first so we can agree on the approach.

## Running the tests

```bash
scripts/test.sh
tests/test_scripts.sh
```

Both must pass before you open a pull request. CI runs the Python suite on every push; run `tests/test_scripts.sh` locally.

## Rules

- New features are off by default. A hub that upgrades without changing its settings must behave exactly as before.
- The database only changes by adding (new tables, new columns with defaults). Never rename, drop or rewrite existing data.
- Anything that requires action from whoever hosts the hub goes in `CHANGELOG.md`, under "Before you upgrade" for the version that introduces it.

## Adding an e-mail provider

Outgoing e-mail goes through `app/mail.py`. Its contract is two functions: `configured()` says whether the provider has the settings it needs, and `send(to, subject, body) -> bool` sends one message and returns whether it succeeded. That is the whole contract; the module docstring describes how to add an API-based provider next to SMTP. Settings go in `.env.example` with a short comment, and the provider stays off unless its settings are present.
