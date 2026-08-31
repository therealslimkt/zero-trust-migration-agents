# M5 outbound-mTLS release binding

Status: **implemented as a local, pure validation adapter; no enrollment or
network operation is implemented or claimed.**

`M5OutboundMTLSEnrollmentBinding` is a non-secret record that binds one
already-established client identity to one M3 production release:

- tenant and run scope;
- production approval ID and release ID;
- plan (M3 subject) digest and artifact digest;
- SHA-256 client-certificate fingerprint;
- exact DNS TLS server name; and
- a bounded validity interval.

`M5ValidateOutboundMTLSReleaseBinding` fails closed unless every one of those
facts exactly matches the `M3ReleaseCommand` and the injected clock falls
within the interval. The function has no I/O or mutable state. A success only
means that the supplied facts are internally bound; it neither creates an M3
release nor authorizes a connection.

## Deliberate limits

This repository holds no certificate bytes, private keys, bearer tokens, CA
roots, socket URL, proxy configuration, credential lookup, network client, or
enrollment protocol. `EnrollmentID` is opaque correlation evidence and must
not be treated as proof that an enrollment occurred.

M6 deployment composition must separately use an approved CA/workload identity
integration, obtain the credential outside this record, configure TLS with the
same `ServerName`, verify the peer chain and identity, and call M3
`CreateRelease` through its normal transactional authority. It must record a
sanitized release/evidence reference only after those checks. No caller may
substitute a release, approval, plan, artifact, client fingerprint, or server
identity after a binding is issued.

The adapter also intentionally rejects URLs, raw addresses, and `localhost` as
server identities; the release is bound to one DNS TLS ServerName rather than a
general-purpose outbound destination.
