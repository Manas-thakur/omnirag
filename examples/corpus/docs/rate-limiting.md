# Rate Limiting

To protect the Notes API from abusive clients, the gateway applies a per-client
**token bucket** rate limiter.

## Algorithm

Each client (identified by API key, or by IP address for anonymous traffic) owns a
bucket that holds up to `burst` tokens. Tokens are refilled continuously at `rate`
tokens per second. Every request consumes one token; when the bucket is empty the
request is rejected with HTTP 429 and a `Retry-After` header.

The token bucket allows short bursts of traffic while enforcing a sustainable average
rate, which is friendlier to real clients than a fixed window counter.

## Default limits

| Plan       | rate (req/s) | burst |
|------------|--------------|-------|
| free       | 5            | 20    |
| pro        | 50           | 200   |
| enterprise | 500          | 1000  |

## Implementation notes

The reference implementation lives in `src/rate_limiter.py` (`TokenBucket` and
`RateLimiter`). Buckets are kept in memory per gateway replica; a Redis-backed variant
is planned so that limits are shared across replicas.
