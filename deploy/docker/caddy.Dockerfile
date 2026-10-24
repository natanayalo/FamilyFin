FROM golang:1.26.10-alpine3.23@sha256:0525c952defebc693cdaf62cdf43afa32be5a7f377e99260642ea19c240c708e AS build
ENV GOTOOLCHAIN=local CGO_ENABLED=0
WORKDIR /build
COPY deploy/docker/caddy-build/go.mod deploy/docker/caddy-build/go.sum ./
RUN go mod download && go mod verify
COPY deploy/docker/caddy-build/main.go ./
RUN --network=none go build -mod=readonly -trimpath -ldflags="-s -w" -o /out/caddy . \
    && go list -mod=readonly -deps . > /out/compiled-packages.unsorted \
    && sort /out/compiled-packages.unsorted > /out/compiled-packages.txt \
    && test -s /out/compiled-packages.txt \
    && ! grep -Eq '^golang.org/x/crypto/openpgp(/|$)' /out/compiled-packages.txt \
    && sha256sum /out/caddy /out/compiled-packages.txt > /out/caddy.sha256

FROM caddy:2.11.7-alpine@sha256:eb4d35b7452d1ab6171fbdbe8d9275b2301dad6dad92115d91e19fb9b24d510f
# Keep the pinned Alpine trust/timezone environment, replace the older binary
# with the same Caddy release built against patched, locked Go dependencies.
# COPY produces a new executable inode without the upstream file capability.
RUN apk add --no-cache --upgrade brotli-libs=1.2.1-r0 \
    && rm /usr/bin/caddy && find / -xdev -type f -perm /6000 -exec chmod a-s {} +
COPY --from=build /out/caddy /usr/bin/caddy
COPY --from=build /out/compiled-packages.txt /out/caddy.sha256 /usr/share/familyfin/
COPY deploy/docker/Caddyfile /etc/caddy/Caddyfile
USER 10003:10003
CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
