# Pinned Caddy rebuild

The official Caddy 2.11.7 image contains Go 1.26.8 and x/net 0.59.0.
The Docker candidate keeps Caddy 2.11.7 and its standard modules, rebuilding
with Go 1.26.10 and x/net 0.60.0 for published security fixes. There are no
third-party Caddy plugins or application-specific proxy source changes.

`main.go` uses the upstream entry point from
https://github.com/caddyserver/caddy/blob/v2.11.7/cmd/caddy/main.go.
Its Apache-2.0 license is included in LICENSE. `go.mod` and `go.sum` are
committed dependency inputs; builds use `-mod=readonly`, module checksum
verification, a digest-pinned compiler, and no network during compilation.
Do not run an unconstrained `go get -u` during production builds.

The base Alpine image still comes from the digest-pinned official Caddy
release. Re-scan the complete resulting image after any compiler, module,
or base digest change. The rebuild is a locally maintained security patch,
not a new upstream Caddy release. Keep its provenance with release images.

The runtime also pins Alpine's brotli-libs 1.2.1-r0 to remove the available
CVE-2026-111497 package finding in the pinned upstream base. This updates only
the image layer; it does not change the Caddy release or standard module set.
