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

FROM node:22.23.4-trixie-slim@sha256:8eb619e402eaede1748a3c8173bffab391592812e85136452f781741c7242ddf
# Production runs the standalone server directly. Package managers and their
# archive/network dependencies serve no purpose in this immutable runtime.
RUN rm -rf /usr/local/lib/node_modules /opt/yarn-* && rm -f /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/yarn /usr/local/bin/yarnpkg /usr/local/bin/corepack \
    && find / -xdev -type f -perm /6000 -exec chmod a-s {} +
WORKDIR /web
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000
COPY --from=build /web/.next/standalone ./
COPY --from=build /web/.next/static ./.next/static
COPY --from=build /web/public ./public
USER 10002:10002
# Standalone retains the exact compiled CSP/config, including poweredByHeader.
CMD ["node", "server.js"]
