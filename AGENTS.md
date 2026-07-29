# Repository instructions

## Secret handling (mandatory)

Treat `.env`, deployment secret stores, database URLs, API tokens, encryption
keys, private keys, cookies, and authenticated form values as confidential.

- Never print, paste, hash, summarize, or otherwise echo secret values into a
  command, tool argument, log, test output, screenshot, browser snapshot, chat,
  commit, or generated file.
- Never inspect `.env` with `Get-Content`, `type`, `cat`, `env`, `printenv`,
  `set`, or an equivalent environment dump. Inspect only `.env.example` and
  key names. A purpose-built validator may check whether a value is present,
  but it must not return the value, its length, or a reversible derivative.
- Never take a browser snapshot, screenshot, DOM export, or accessibility
  snapshot on deployment `/secrets` routes, service Environment pages,
  protected-content pages, password forms, authentication settings, or pages
  that can reveal credentials. This prohibition applies even when values look
  hidden or the group is empty: browser/password-manager autofill can populate
  the DOM without warning.
- Secret and password entry is a human-only step. Automation may navigate to
  the page and must then hand control to the user without inspecting its DOM.
  Navigate to a known non-sensitive route before resuming automation.
- Never place secrets in shell command-line arguments. Use the platform secret
  store or process environment populated outside the Codex session.
- Sanitize exception text with `cbr_trading.secret_guard` before logging,
  persisting, returning from a CLI, or including it in Telegram.
- If a secret appears unexpectedly, stop handling the value, do not repeat it,
  identify only the affected key and location, and recommend rotation.
- Rotation, deletion, or migration of production secrets requires explicit
  user authorization. `ACCOUNTS_MASTER_KEY` must not be rotated without a
  migration of encrypted trading-account records.

For Northflank, keep confidential runtime values in a restricted Secret Group.
The regular Codex/browser workflow must not have permission to reveal secret
values. Direct service variables are for non-secret configuration only.

Before committing, run:

```text
python scripts/check_no_secrets.py
python -m unittest discover -s tests -q
```

## Resolution trading priorities (mandatory)

Every new resolution source, parser, strategy, market binding, and executor
change has two ordered goals:

1. semantic correctness: an ambiguous, stale, wrong-period, or unsupported
   document must fail closed and must never create a tradable signal;
2. extreme end-to-end latency: once evidence is valid, the already prepared
   order must reach the exchange with no avoidable serial I/O.

Correctness is the gate; latency is optimized inside that gate. Never weaken
validation to gain speed.

Before designing or reviewing a resolution-trading change, read and apply:

- `cbr_trading/ARCHITECTURE.md`;
- `cbr_trading/SOURCE_DESIGN_CHECKLIST.md`.

In particular:

- independent official providers are raced in parallel, not implemented as a
  serial fallback chain;
- all static market and account work, both outcome alternatives, and signing
  are completed before the expected publication;
- one publication is evaluated as one event batch: strategies select every
  applicable intent, the coordinator calls the executor once, and the
  executor uses one exchange batch submission where supported;
- balance, book, account, metadata, database discovery, signing, Telegram,
  and nonessential journaling are forbidden on the post-signal hot path;
- every route and every hot-path stage must expose safe latency telemetry and
  have replay tests proving parsing correctness, route independence, and
  batching.
