# Earnings public sources checkpoint — 2026-07-27

## Release

- Source archive SHA256:
  `ff1f72ef4a270e8285300aa64800afd80760d94ede79506c907756e38d706971`.
- Image archive SHA256:
  `e4da66a957dcc3bd222c48c08243a42c82c8fda116dabbeda8e5ea4f946e8b91`.
- Immutable runtime image:
  `codexpoly@sha256:b0f81019a5ee673f846779625c990f06ea6ced1f646b1a3616811c287f088163`.
- Docker build passed the secret scan and all `561` tests.

Only `earnings-worker` was recreated in staging and production. The base
`notification-worker` and `resolution-worker` were not changed. The trading
overlay was not started, and the production earnings container has only the
database and SEC file-secret mounts.

## Runtime state

The staging and production heartbeat both report:

```text
connected=True
watches=4
processed=0
signals=0
public_active=False
public_scopes=0
public_watches=0
public_polls=0
```

All three earnings execution profiles remain `DISABLED`. Consequently, the
SEC WebSocket stays connected, while the company-site and press-wire pollers
make no external requests.

## NVTS

The existing source policy has three independent paths:

1. SEC-API WebSocket and SEC exhibit fetch;
2. Navitas investor-relations RSS and document;
3. GlobeNewswire earnings RSS and document.

The official Q2 call is scheduled for 17:00 ET, or 23:00 in Budapest. The
release is expected after the US market close, likely near 22:00 Budapest.
The guarded profile preparation window starts at 21:00 Budapest, but the
profile remains disabled pending explicit activation approval.

## WWD

The WWD rule now has three independent paths:

1. SEC-API WebSocket and SEC exhibit fetch;
2. the official Woodward WordPress REST press-release collection and the
   corresponding `woodward.com` document;
3. GlobeNewswire earnings RSS and document.

`wordpress_rest` is a checked public-listing kind with the same safeguards as
RSS: HTTPS-only exact host allowlists, bounded responses, content-type checks,
conditional requests, exact title filters, and profile-window gating.

Historical Q2 replay succeeded independently through both the company site
and GlobeNewswire. Both documents produced:

```text
status=accepted
reason=official_woodward_gaap_diluted_eps
value=2.19
```

The WWD policy migration and its fail-closed read-only check passed in both
staging and production. The profile remains disabled.

## BBBY

BBBY currently retains the SEC path only.

The official company-specific Business Wire RSS URL is public and reachable
from the server, but currently returns an empty feed. Direct Business Wire
release HTML and the Q4-hosted investor-relations HTML both return HTTP 403
from the VPS. A headline-only feed is not sufficient for EPS resolution, so
no non-functional source policy was added.

A second and third executable BBBY path needs one of:

- an approved Q4 API credential stored as a file-secret;
- a verified Business Wire full-text Atom/feed entitlement;
- another official company-controlled machine-readable endpoint that exposes
  the complete release document from the VPS.

No API credential was inspected or copied during this investigation.
