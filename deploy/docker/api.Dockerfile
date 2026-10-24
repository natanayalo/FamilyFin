FROM ghcr.io/astral-sh/uv:0.9.5@sha256:f459f6f73a8c4ef5d69f4e6fbbdb8af751d6fa40ec34b39a1ab469acd6e289b7 AS uv
FROM python:3.12.15-slim-trixie@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704 AS build
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
# Use the locked dependency environment with source imports, avoiding an
# unpinned isolated build-backend download. Migration lookup stays under /app.
RUN find /app/src -type f -name '*.py' -exec chmod 0644 {} + && uv sync --locked --no-dev --no-install-project

# Test-only target. Never used by Compose and never mounts financial volumes.
FROM build AS test
RUN uv sync --locked --no-install-project
ENV PYTHONPATH=/app/src PYTHONDONTWRITEBYTECODE=1
COPY .nvmrc dev ./
COPY alembic.ini ./
COPY alembic ./alembic
COPY tests ./tests
COPY streamlit_app.py ./
COPY deploy ./deploy
COPY docs ./docs
COPY frontend/package.json frontend/next.config.ts ./frontend/
# Windows autocrlf must not affect syntax validation of original Linux scripts.
RUN find /app/tests -type f -name '*.py' -exec chmod 0644 {} + && chmod 0644 /app/streamlit_app.py \
    && sed -i 's/\r$//' /app/deploy/bin/* /app/dev && chmod 755 /app/dev
USER 10001:10001
CMD ["/app/.venv/bin/pytest", "-o", "cache_dir=/tmp/pytest-cache", "tests", "-rs"]

FROM gcr.io/distroless/cc-debian13:nonroot@sha256:3ee00291cf386ec52a552e6a858d555debd74776eb4bfa53fa3df2cd6677515e AS minimal
FROM build AS python-runtime
COPY --from=minimal / /runtime-base/
COPY deploy/docker/python_rootfs.py /python_rootfs.py
RUN python /python_rootfs.py /runtime-base /runtime-overlay

FROM minimal AS runtime
COPY --from=python-runtime /runtime-overlay/ /
WORKDIR /app
ENV PATH=/app/.venv/bin:/usr/local/bin:/usr/bin:/bin PYTHONPATH=/app/src PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY --from=build /app /app
COPY alembic.ini ./
COPY alembic ./alembic
COPY deploy/docker/runtime.py deploy/docker/operations.py ./deploy/docker/
USER 0
RUN ["python", "-c", "import os; [(os.makedirs(p,exist_ok=True),os.chown(p,10001,10001),os.chmod(p,0o700)) for p in ('/var/lib/familyfin','/backups')]"]
USER 10001:10001
ENTRYPOINT ["python", "/app/deploy/docker/runtime.py"]
CMD ["serve"]
