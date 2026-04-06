/**
 * NBA Backend — k6 load test
 *
 * Usage:
 *   k6 run k6/load_test.js
 *   k6 run -e BASE_URL=https://api.nba.cards k6/load_test.js
 *
 * PRD targets (§12):
 *   - p99 latency < 3 s on all endpoints
 *   - Error rate   < 1 %
 *   - 500+ concurrent users per revision via auto-scaling
 */
import http from 'k6/http';
import { check, group, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';

// ── Configuration ─────────────────────────────────────────────────────────────
const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const MEMBER_TOKEN = __ENV.MEMBER_TOKEN || '';   // pre-minted JWT for load tests
const MEMBER_UID  = __ENV.MEMBER_UID  || 'NBA-LOADTEST-00000000';

// ── Custom metrics ────────────────────────────────────────────────────────────
const errorRate   = new Rate('errors');
const p99Latency  = new Trend('p99_latency', true);

// ── Load profile ──────────────────────────────────────────────────────────────
export const options = {
  stages: [
    { duration: '30s', target: 20  },  // ramp up to 20 VUs
    { duration: '1m',  target: 50  },  // ramp up to 50 VUs
    { duration: '2m',  target: 50  },  // hold at 50 VUs
    { duration: '30s', target: 100 },  // spike to 100 VUs
    { duration: '1m',  target: 100 },  // hold at 100 VUs
    { duration: '30s', target: 0   },  // ramp down
  ],
  thresholds: {
    // PRD §12 — p99 < 3 s globally
    'http_req_duration{scenario:default}': ['p(99)<3000'],
    // Error rate < 1 %
    'http_req_failed': ['rate<0.01'],
    // Custom: track separately
    'p99_latency': ['p(99)<3000'],
  },
};

// ── Helpers ───────────────────────────────────────────────────────────────────
function authHeaders() {
  return MEMBER_TOKEN
    ? { Authorization: `Bearer ${MEMBER_TOKEN}` }
    : {};
}

function record(res) {
  p99Latency.add(res.timings.duration);
  errorRate.add(res.status >= 500);
}

// ── Virtual user scenario ─────────────────────────────────────────────────────
export default function () {
  // 1. Health check — must always be fast
  group('healthz', () => {
    const res = http.get(`${BASE_URL}/v1/healthz`);
    record(res);
    check(res, {
      'healthz 200':           (r) => r.status === 200,
      'healthz has status ok': (r) => r.json('status') === 'ok',
      'healthz < 200ms':       (r) => r.timings.duration < 200,
    });
  });

  sleep(0.5);

  // 2. Branch list — public, cached-friendly
  group('branches', () => {
    const res = http.get(`${BASE_URL}/v1/branches`);
    record(res);
    check(res, {
      'branches 200':      (r) => r.status === 200,
      'branches is array': (r) => Array.isArray(r.json()),
    });
  });

  sleep(0.5);

  // 3. Public profile lookup (QR scan simulation) — no auth
  group('public profile', () => {
    const res = http.get(`${BASE_URL}/v1/profiles/${MEMBER_UID}`);
    record(res);
    // Profile may be 404 in load test environment — just check it's not 500
    check(res, {
      'public profile not 5xx': (r) => r.status < 500,
    });
  });

  sleep(0.5);

  // 4. QR code PNG — no auth, image response
  group('qr code', () => {
    const res = http.get(`${BASE_URL}/v1/qr/${MEMBER_UID}`);
    record(res);
    check(res, {
      'qr not 5xx':             (r) => r.status < 500,
      'qr < 3s (PRD p99 SLA)':  (r) => r.timings.duration < 3000,
    });
  });

  sleep(1);

  // 5. Authenticated: own profile (only if token available)
  if (MEMBER_TOKEN) {
    group('my profile', () => {
      const res = http.get(`${BASE_URL}/v1/profiles/me`, { headers: authHeaders() });
      record(res);
      check(res, {
        'my profile 200 or 404': (r) => r.status === 200 || r.status === 404,
      });
    });

    sleep(0.5);

    // 6. Payment history
    group('payment history', () => {
      const res = http.get(`${BASE_URL}/v1/payments/history`, { headers: authHeaders() });
      record(res);
      check(res, {
        'payment history 200': (r) => r.status === 200,
      });
    });
  }

  sleep(1);
}

// ── Summary ───────────────────────────────────────────────────────────────────
export function handleSummary(data) {
  return {
    'k6/summary.json': JSON.stringify(data, null, 2),
  };
}
