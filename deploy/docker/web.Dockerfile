FROM node:22.23.4-trixie-slim@sha256:8eb619e402eaede1748a3c8173bffab391592812e85136452f781741c7242ddf AS build
WORKDIR /web
ENV NEXT_TELEMETRY_DISABLED=1 FAMILY_FINANCE_DOCKER=1
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# Keep Next lockfile validation enabled; compilation must not rewrite the lock.
RUN --network=none sha256sum package-lock.json > /tmp/lock.sha256 && npm run build && sha256sum -c /tmp/lock.sha256 \
    && npm prune --omit=dev --offline --ignore-scripts --no-audit --no-fund

FROM build AS test
RUN npm ci --no-audit --no-fund
CMD ["sh", "-c", "npm run lint && npm run typecheck && npm run test:health && npm run test:components -- --maxWorkers=2"]

FROM gcr.io/distroless/cc-debian13:nonroot@sha256:3ee00291cf386ec52a552e6a858d555debd74776eb4bfa53fa3df2cd6677515e
# Preserve the repository-pinned Node release; omit unrelated distro tools.
COPY --from=build /usr/local/bin/node /usr/local/bin/node
COPY --from=build /usr/local/LICENSE /usr/share/doc/node/LICENSE
WORKDIR /web
ENV PATH=/usr/local/bin:/usr/bin:/bin NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000
COPY --from=build /web/.next/standalone ./
COPY --from=build /web/.next/static ./.next/static
COPY --from=build /web/public ./public
USER 10002:10002
# Standalone retains the exact compiled CSP/config, including poweredByHeader.
CMD ["node", "server.js"]
