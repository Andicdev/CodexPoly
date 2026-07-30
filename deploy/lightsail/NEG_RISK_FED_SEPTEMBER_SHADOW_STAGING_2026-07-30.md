# September FED neg-risk shadow staging checkpoint

Date: 2026-07-30

## Deployment

The read-only neg-risk recorder is running on `codexpoly-host-02` in staging
for `fed-decision-in-september-762`.

The deployed source revision is `59c9d64`. The rootless Docker image is pinned
by immutable ID:

```text
sha256:5f60a4a524526f58e96be9de5409b59ed1feeb6521d860c2a2b6142b9321106c
```

Its OCI revision label is `59c9d64`. The source archive SHA-256 is:

```text
b770d80aaaaa50ce1e5e6ba1ccb5e886a64c55a97e73443c517123d58b2abdde
```

The service is installed at
`/opt/codexpoly/staging/apps/neg-risk/compose.yml`. It runs as a read-only
container with no published ports, all Linux capabilities dropped, a bounded
temporary filesystem, and separate database and egress networks.

## Data path

The recorder subscribes every YES and NO asset in the five-market event to
the public Polymarket market WebSocket and maintains local L2 books. It stores:

1. session readiness and reconnect aggregates;
2. append-only raw public WebSocket messages for deterministic replay;
3. append-only full-basket route observations for quantity `200`.

Database writes are performed by a bounded asynchronous batch writer outside
the WebSocket callback. Route observations are sampled at most every `250 ms`;
the local books still process every accepted update.

The transactional schema migration and schema check passed against the
isolated staging database `codexpoly_neg_risk`. The post-start aggregate check
also passed: the latest September FED session is `READY`, has persisted
messages and route observations, and has `live_orders_enabled=false`. The
check emits no stored rows or payload values.

## Safety boundary

The service receives only the staging database application-password file. It
has no trading-account secret, private key, CLOB credential, or Telegram
credential. The application configuration requires shadow mode, the database
constraint rejects live-enabled sessions, and no order executor exists in
this package.

Production schema and services were not changed. No production recorder or
live trading service was created.

## Verification

The repository secret scan passed. The complete Python 3.12 suite passed:
`898` tests with one skip. The image build repeated both checks successfully
inside the clean source archive.

