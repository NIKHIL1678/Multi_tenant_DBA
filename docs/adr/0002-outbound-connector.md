# ADR 0002 — Customer-side connector with outbound tunnel

- **Status:** Accepted
- **Date:** 2026-09-28

## Context

Agents need to inspect customer databases that sit behind firewalls and NAT. SME
customers often cannot, or will not, open inbound ports or whitelist IPs, and are
uncomfortable handing database passwords to a third party.

## Decision

Ship a **connector** (Docker image) that runs inside the customer network, connects to
databases locally, and opens an **outbound** TLS WebSocket to ZipZy. Commands flow from
ZipZy to the connector over that connection as JSON-RPC 2.0 messages. Direct inbound
connections may be offered later as an advanced option.

## Why

- Zero network changes for the customer (outbound HTTPS is almost always allowed).
- Database credentials never leave the customer's network.
- Safety checks can be enforced on the customer side, where ZipZy cannot bypass them.
- One place to add engine adapters, caching, redaction and local audit.

## Consequences

- We must build, version, publish and support the connector image.
- The control plane must track long-lived sockets and route across instances (Redis).
- Connector identity needs key management (Ed25519, enrollment, revocation).

## Rejected

- **Direct connection with IP whitelisting:** requires firewall changes and exposes DBs.
- **Customers upload credentials to ZipZy:** unacceptable trust and breach risk.
- **VPN / site-to-site tunnel:** too heavy for SMEs to set up.
