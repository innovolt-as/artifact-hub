# Contributing

Bug reports, ideas and pull requests are welcome. For anything larger than a small fix, open an issue first so we can agree on the approach.

## Running the tests

```bash
scripts/test.sh
tests/test_scripts.sh
```

Both must pass before you open a pull request. CI runs both the Python suite and `tests/test_scripts.sh` on every push and pull request.

## Rules

- New features are off by default. A hub that upgrades without changing its settings must behave exactly as before.
- The database only changes by adding (new tables, new columns with defaults). Never rename, drop or rewrite existing data.
- Anything that requires action from whoever hosts the hub goes in `CHANGELOG.md`, under "Before you upgrade" for the version that introduces it.

## Adding an e-mail provider

Outgoing e-mail goes through `app/mail.py`. Its contract is two functions: `configured()` says whether the provider has the settings it needs, and `send(to, subject, text, html=None, images=None, sender_name=None) -> bool` sends one message (`html` and `images` are optional; `sender_name` is used when the configured sender is only an address). `send` returns `False` only when no provider is configured (the hub then logs the login link instead); when a send fails it must raise, otherwise magic links would be written to the log with a misleading message. That is the whole contract; the module docstring describes how to add an API-based provider next to SMTP. Settings go in `.env.example` with a short comment, and the provider stays off unless its settings are present.

## Adding a language

The hub's text lives in `app/lang/`. English (`en.json`) is the default; Norwegian (`nb.json`) is built in.

1. Copy `app/lang/en.json` to `app/lang/<code>.json`.
2. Translate the values. Keep the `{placeholders}` and do not touch the keys.
3. Set `HUB_LANG=<code>` in `.env`.

Texts that are missing from your file are shown in English. Run `scripts/test.sh`; it checks the language files against each other and fails if Norwegian text turns up in the code outside `app/lang/`.
