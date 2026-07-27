-- Public, non-secret earnings research verified on 2026-07-27.
-- This seed updates only the informational earnings release catalog.

INSERT INTO earnings_release_catalog (
    event_key,
    ticker,
    release_date,
    market_session,
    scheduled_release_at,
    conference_call_at,
    schedule_status,
    schedule_source_url,
    integration_status,
    document_format,
    metric_options,
    source_options,
    notes,
    verified_at
)
VALUES
(
    'PYPL:2026-07-28',
    'PYPL',
    DATE '2026-07-28',
    'PRE_MARKET',
    NULL,
    TIMESTAMPTZ '2026-07-28 12:00:00+00',
    'CONFIRMED',
    'https://investor.pypl.com/news-and-events/events/event-details/2026/PayPals-Second-Quarter-2026-Earnings-Call/default.aspx',
    'NEEDS_DOCUMENT_RESOLVER',
    'LINK_ONLY',
    $json${
      "market_basis": "unverified",
      "reported": []
    }$json$::jsonb,
    $json$[
      {
        "delivery": "websocket",
        "provider": "sec",
        "status": "available"
      },
      {
        "delivery": "rss",
        "listing_url": "https://investor.pypl.com/rss/pressrelease.aspx",
        "provider": "company_ir",
        "status": "verified_listing",
        "document_status": "materials_link_only"
      }
    ]$json$::jsonb,
    'IR RSS works from the VPS, but the announcement links to separate earnings materials.',
    now()
),
(
    'UPS:2026-07-28',
    'UPS',
    DATE '2026-07-28',
    'PRE_MARKET',
    TIMESTAMPTZ '2026-07-28 10:00:00+00',
    TIMESTAMPTZ '2026-07-28 12:30:00+00',
    'CONFIRMED',
    'https://investors.ups.com/news-events/press-releases/detail/2163/ups-to-release-second-quarter-2026-results-on-tuesday-july',
    'SOURCE_BLOCKED',
    'UNKNOWN',
    $json${
      "market_basis": "unverified",
      "reported": []
    }$json$::jsonb,
    $json$[
      {
        "delivery": "websocket",
        "provider": "sec",
        "status": "available"
      },
      {
        "delivery": "rss",
        "provider": "company_ir",
        "status": "listing_unavailable"
      },
      {
        "delivery": "html",
        "provider": "businesswire",
        "status": "blocked_from_vps"
      }
    ]$json$::jsonb,
    'Official release is expected around 06:00 ET; no usable public full-text listing was verified.',
    now()
),
(
    'HLT:2026-07-28',
    'HLT',
    DATE '2026-07-28',
    'PRE_MARKET',
    NULL,
    TIMESTAMPTZ '2026-07-28 13:00:00+00',
    'CONFIRMED',
    'https://ir.hilton.com/events-and-presentations/2026/07-28-2026',
    'NEEDS_DOCUMENT_RESOLVER',
    'MIXED',
    $json${
      "market_basis": "unverified",
      "reported": []
    }$json$::jsonb,
    $json$[
      {
        "delivery": "websocket",
        "provider": "sec",
        "status": "available"
      },
      {
        "delivery": "rss",
        "listing_url": "https://stories.hilton.com/feed/",
        "provider": "company_ir",
        "status": "verified_listing",
        "document_status": "earnings_pdf_expected"
      }
    ]$json$::jsonb,
    'General company RSS is reachable, but historical earnings materials use PDF documents.',
    now()
),
(
    'IVZ:2026-07-28',
    'IVZ',
    DATE '2026-07-28',
    'PRE_MARKET',
    NULL,
    TIMESTAMPTZ '2026-07-28 13:00:00+00',
    'CONFIRMED',
    'https://www.invesco.com/corporate/en/home.html',
    'SOURCE_BLOCKED',
    'UNKNOWN',
    $json${
      "market_basis": "unverified",
      "reported": []
    }$json$::jsonb,
    $json$[
      {
        "delivery": "websocket",
        "provider": "sec",
        "status": "available"
      },
      {
        "delivery": "unknown",
        "provider": "company_ir",
        "status": "stable_listing_not_found"
      }
    ]$json$::jsonb,
    'Official schedule is confirmed, but no stable public RSS or REST listing was found.',
    now()
),
(
    'KO:2026-07-28',
    'KO',
    DATE '2026-07-28',
    'PRE_MARKET',
    NULL,
    TIMESTAMPTZ '2026-07-28 12:30:00+00',
    'CONFIRMED',
    'https://investors.coca-colacompany.com/news-events/press-releases/detail/1163/the-coca-cola-company-announces-timing-of-second-quarter-2026-earnings-release',
    'SOURCE_BLOCKED',
    'UNKNOWN',
    $json${
      "market_basis": "unverified",
      "reported": []
    }$json$::jsonb,
    $json$[
      {
        "delivery": "websocket",
        "provider": "sec",
        "status": "available"
      },
      {
        "delivery": "rss",
        "provider": "company_ir",
        "status": "listing_unavailable"
      },
      {
        "delivery": "html",
        "provider": "businesswire",
        "status": "blocked_from_vps"
      }
    ]$json$::jsonb,
    'The official IR announcement is Business Wire-backed; no usable full-text feed was verified.',
    now()
),
(
    'RCL:2026-07-28',
    'RCL',
    DATE '2026-07-28',
    'PRE_MARKET',
    NULL,
    TIMESTAMPTZ '2026-07-28 14:00:00+00',
    'CONFIRMED',
    'https://www.rclinvestor.com/press-releases/release/?id=1841',
    'NEEDS_LISTING_ADAPTER',
    'FULL_HTML',
    $json${
      "market_basis": "unverified",
      "reported": ["gaap_eps", "adjusted_eps"]
    }$json$::jsonb,
    $json$[
      {
        "delivery": "websocket",
        "provider": "sec",
        "status": "available"
      },
      {
        "delivery": "html",
        "provider": "company_ir",
        "status": "verified_document",
        "listing_status": "adapter_required"
      },
      {
        "delivery": "html",
        "provider": "prnewswire",
        "status": "not_integrated"
      }
    ]$json$::jsonb,
    'Full company HTML contains GAAP and adjusted EPS, but the current RSS and WordPress listing kinds cannot discover it.',
    now()
),
(
    'BA:2026-07-28',
    'BA',
    DATE '2026-07-28',
    'PRE_MARKET',
    NULL,
    TIMESTAMPTZ '2026-07-28 14:30:00+00',
    'CONFIRMED',
    'https://investors.boeing.com/investors/news/press-release-details/2026/Boeing-to-Release-Second-Quarter-Results-on-July-28/default.aspx',
    'PARSER_ONLY',
    'FULL_HTML',
    $json${
      "market_basis": "unverified",
      "reported": ["gaap_eps", "core_eps"]
    }$json$::jsonb,
    $json$[
      {
        "delivery": "websocket",
        "provider": "sec",
        "status": "available"
      },
      {
        "delivery": "rss",
        "listing_url": "https://investors.boeing.com/rss/pressrelease.aspx",
        "provider": "company_ir",
        "status": "verified_full_html"
      },
      {
        "delivery": "html",
        "provider": "prnewswire",
        "status": "mirrored_by_company_ir"
      }
    ]$json$::jsonb,
    'Company IR RSS and full HTML work from the VPS; a ticker-specific EPS parser is the remaining source task.',
    now()
),
(
    'JBLU:2026-07-28',
    'JBLU',
    DATE '2026-07-28',
    'PRE_MARKET',
    NULL,
    TIMESTAMPTZ '2026-07-28 14:00:00+00',
    'CONFIRMED',
    'https://investor.jetblue.com/news/news-details/2026/JetBlue-Announces-Webcast-of-Second-Quarter-2026-Earnings-Conference-Call/default.aspx',
    'SOURCE_BLOCKED',
    'UNKNOWN',
    $json${
      "market_basis": "unverified",
      "reported": []
    }$json$::jsonb,
    $json$[
      {
        "delivery": "websocket",
        "provider": "sec",
        "status": "available"
      },
      {
        "delivery": "rss",
        "provider": "company_ir",
        "status": "blocked_from_vps"
      },
      {
        "delivery": "html",
        "provider": "businesswire",
        "status": "blocked_from_vps"
      }
    ]$json$::jsonb,
    'Both the Q4-hosted listing and direct Business Wire path were unavailable from the VPS.',
    now()
),
(
    'SPGI:2026-07-28',
    'SPGI',
    DATE '2026-07-28',
    'PRE_MARKET',
    TIMESTAMPTZ '2026-07-28 11:15:00+00',
    TIMESTAMPTZ '2026-07-28 12:30:00+00',
    'CONFIRMED',
    'https://investor.spglobal.com/news-releases/news-details/2026/SP-Global-Schedules-Second-Quarter-2026-Earnings-Announcement-and-Conference-Call-for-Tuesday-July-28-2026/default.aspx',
    'NEEDS_DOCUMENT_RESOLVER',
    'LINK_ONLY',
    $json${
      "market_basis": "unverified",
      "reported": []
    }$json$::jsonb,
    $json$[
      {
        "delivery": "websocket",
        "provider": "sec",
        "status": "available"
      },
      {
        "delivery": "rss",
        "listing_url": "https://investor.spglobal.com/rss/pressrelease.aspx",
        "provider": "company_ir",
        "status": "verified_listing",
        "document_status": "materials_link_only"
      },
      {
        "delivery": "html",
        "provider": "prnewswire",
        "status": "mirrored_announcement_only"
      }
    ]$json$::jsonb,
    'The RSS listing works, but the release page delegates the actual figures to separate earnings materials.',
    now()
),
(
    'CZR:2026-07-28',
    'CZR',
    DATE '2026-07-28',
    'POST_MARKET',
    NULL,
    NULL,
    'CONFIRMED',
    'https://investor.caesars.com/node/36206/pdf',
    'PARSER_ONLY',
    'FULL_HTML',
    $json${
      "market_basis": "unverified",
      "reported": ["gaap_eps"]
    }$json$::jsonb,
    $json$[
      {
        "delivery": "websocket",
        "provider": "sec",
        "status": "available"
      },
      {
        "delivery": "rss",
        "listing_url": "https://investor.caesars.com/rss/news-releases.xml",
        "provider": "company_ir",
        "status": "verified_full_html"
      },
      {
        "delivery": "html",
        "provider": "businesswire",
        "status": "mirrored_by_company_ir"
      }
    ]$json$::jsonb,
    'Company IR RSS exposes a full HTML statement; the GAAP diluted EPS table needs a ticker-specific parser.',
    now()
),
(
    'SBUX:2026-07-29',
    'SBUX',
    DATE '2026-07-29',
    'POST_MARKET',
    NULL,
    TIMESTAMPTZ '2026-07-29 20:15:00+00',
    'CONFIRMED',
    'https://investor.starbucks.com/news/financial-releases/news-details/2026/Starbucks-Announces-Q3-Fiscal-Year-2026-Results-Conference-Call/default.aspx',
    'PARSER_ONLY',
    'FULL_HTML',
    $json${
      "market_basis": "unverified",
      "reported": ["gaap_eps", "non_gaap_eps"]
    }$json$::jsonb,
    $json$[
      {
        "delivery": "websocket",
        "provider": "sec",
        "status": "available"
      },
      {
        "delivery": "rss",
        "listing_url": "https://investor.starbucks.com/rss/pressrelease.aspx",
        "provider": "company_ir",
        "status": "verified_full_html"
      },
      {
        "delivery": "html",
        "provider": "businesswire",
        "status": "mirrored_by_company_ir"
      }
    ]$json$::jsonb,
    'The official date is Wednesday July 29, not Tuesday July 28; direct Business Wire access is unnecessary.',
    now()
),
(
    'CSGP:2026-07-28',
    'CSGP',
    DATE '2026-07-28',
    'POST_MARKET',
    NULL,
    TIMESTAMPTZ '2026-07-28 21:00:00+00',
    'CONFIRMED',
    'https://investors.costargroup.com/news-releases/news-release-details/costar-group-report-financial-results-second-quarter-july-28',
    'PARSER_ONLY',
    'FULL_HTML',
    $json${
      "market_basis": "unverified",
      "reported": ["gaap_eps", "adjusted_eps"]
    }$json$::jsonb,
    $json$[
      {
        "delivery": "websocket",
        "provider": "sec",
        "status": "available"
      },
      {
        "delivery": "rss",
        "listing_url": "https://investors.costargroup.com/rss/news-releases.xml",
        "provider": "company_ir",
        "status": "verified_full_html"
      },
      {
        "delivery": "html",
        "provider": "businesswire",
        "status": "mirrored_by_company_ir"
      }
    ]$json$::jsonb,
    'Company IR RSS and full HTML work from the VPS; market GAAP versus adjusted basis must be confirmed.',
    now()
),
(
    'V:2026-07-28',
    'V',
    DATE '2026-07-28',
    'POST_MARKET',
    NULL,
    TIMESTAMPTZ '2026-07-28 21:00:00+00',
    'CONFIRMED',
    'https://investor.visa.com/news/news-details/2026/Visa-to-Announce-Fiscal-Third-Quarter-2026-Financial-Results-on-July-28-2026/default.aspx',
    'NEEDS_DOCUMENT_RESOLVER',
    'LINK_ONLY',
    $json${
      "market_basis": "unverified",
      "reported": []
    }$json$::jsonb,
    $json$[
      {
        "delivery": "websocket",
        "provider": "sec",
        "status": "available"
      },
      {
        "delivery": "rss",
        "listing_url": "https://investor.visa.com/rss/pressrelease.aspx",
        "provider": "company_ir",
        "status": "verified_listing",
        "document_status": "quarterly_materials_link_only"
      }
    ]$json$::jsonb,
    'The IR feed is reachable, but the announcement page does not contain the EPS figure.',
    now()
),
(
    'F:2026-07-28',
    'F',
    DATE '2026-07-28',
    'POST_MARKET',
    TIMESTAMPTZ '2026-07-28 21:00:00+00',
    TIMESTAMPTZ '2026-07-28 21:00:00+00',
    'CONFIRMED',
    'https://shareholder.ford.com/home/default.aspx',
    'NEEDS_DOCUMENT_RESOLVER',
    'PDF',
    $json${
      "market_basis": "unverified",
      "reported": []
    }$json$::jsonb,
    $json$[
      {
        "delivery": "websocket",
        "provider": "sec",
        "status": "available"
      },
      {
        "delivery": "rss",
        "listing_url": "https://shareholder.ford.com/rss/pressrelease.aspx",
        "provider": "company_ir",
        "status": "verified_listing",
        "document_status": "direct_pdf"
      }
    ]$json$::jsonb,
    'The listing works, but historical earnings releases resolve directly to PDF documents.',
    now()
),
(
    'NXPI:2026-07-28',
    'NXPI',
    DATE '2026-07-28',
    'POST_MARKET',
    NULL,
    TIMESTAMPTZ '2026-07-28 20:30:00+00',
    'CONFIRMED',
    'https://investors.nxp.com/events/',
    'PARSER_ONLY',
    'FULL_HTML',
    $json${
      "market_basis": "unverified",
      "reported": ["gaap_eps", "non_gaap_eps"]
    }$json$::jsonb,
    $json$[
      {
        "delivery": "websocket",
        "provider": "sec",
        "status": "available"
      },
      {
        "delivery": "rss",
        "listing_url": "https://investors.nxp.com/rss/news-releases.xml",
        "provider": "company_ir",
        "status": "verified_full_html"
      },
      {
        "delivery": "rss",
        "listing_url": "https://www.globenewswire.com/RssFeed/subjectcode/13-Earnings%20Releases%20And%20Operating%20Results/feedTitle/GlobeNewswire%20-%20Earnings%20Releases%20And%20Operating%20Results",
        "provider": "globenewswire",
        "status": "verified_full_html"
      }
    ]$json$::jsonb,
    'Exact NVTS-like pattern: SEC, company IR RSS, and GlobeNewswire full HTML.',
    now()
)
ON CONFLICT (event_key) DO UPDATE
SET
    ticker = EXCLUDED.ticker,
    release_date = EXCLUDED.release_date,
    market_session = EXCLUDED.market_session,
    scheduled_release_at = EXCLUDED.scheduled_release_at,
    conference_call_at = EXCLUDED.conference_call_at,
    schedule_status = EXCLUDED.schedule_status,
    schedule_source_url = EXCLUDED.schedule_source_url,
    integration_status = EXCLUDED.integration_status,
    document_format = EXCLUDED.document_format,
    metric_options = EXCLUDED.metric_options,
    source_options = EXCLUDED.source_options,
    notes = EXCLUDED.notes,
    verified_at = EXCLUDED.verified_at,
    updated_at = now();
