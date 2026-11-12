---
title: Authentication
author: Platform Team
tags: security, api
---

# Authentication

The Notes API uses short-lived **JWT access tokens** plus long-lived **refresh tokens**.
Every request to a protected endpoint must send an `Authorization: Bearer <token>` header.

## Token issuance

Clients exchange a username and password at `POST /auth/token`. On success the server
returns an access token that expires after 15 minutes and a refresh token that expires
after 30 days. Access tokens are signed with RS256 using the private key stored in the
secrets manager; the public key is published at `/.well-known/jwks.json`.

## Validation middleware

The `authMiddleware` function validates the signature, the `exp` claim and the audience
(`notes-api`) of every access token. Requests with a missing or malformed header are
rejected with HTTP 401. Tokens whose signature is valid but that have expired return
HTTP 401 with the error code `token_expired`, which tells the client to refresh.

The middleware attaches the decoded claims to the request as `req.user`, so handlers can
read the user id and roles without decoding the token again.

## Refreshing tokens

Clients call `POST /auth/refresh` with the refresh token to obtain a new access token.
Refresh tokens are rotated: each refresh invalidates the previous refresh token, and
reuse of an old refresh token revokes the whole token family as a precaution against theft.

## Roles

Each token carries a `roles` claim. The `admin` role can manage users; the `editor` role
can create and edit notes; the `viewer` role is read-only.
