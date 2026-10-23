. (Join-Path $PSScriptRoot 'common.ps1')
& python -c "import sys; sys.path.insert(0,sys.argv[1]); from manage import engine; engine()" $PSScriptRoot
if ($LASTEXITCODE -ne 0) { throw 'Local Docker engine verification failed.' }
Push-Location (Join-Path $PSScriptRoot '../..')
try {
    & docker compose -f deploy/docker/compose.yaml config --quiet
    if ($LASTEXITCODE -ne 0) { throw 'Invalid Compose configuration.' }
    & docker build --target test -f deploy/docker/api.Dockerfile -t familyfin-m1-tests:local .
    if ($LASTEXITCODE -ne 0) { throw 'Python test build failed.' }
    # Launcher regressions execute disposable scripts under /tmp. This test-only
    # container has no network/data mounts; production tmpfs remains noexec.
    & docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges --memory 2g --cpus 2 --pids-limit 256 --tmpfs /tmp:rw,exec,size=512m,mode=1777 familyfin-m1-tests:local
    if ($LASTEXITCODE -ne 0) { throw 'Python tests failed.' }
    & docker build --target test -f deploy/docker/web.Dockerfile -t familyfin-m1-web-tests:local .
    if ($LASTEXITCODE -ne 0) { throw 'Frontend test build failed.' }
    & docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges --user 10002:10002 --tmpfs /tmp:rw,size=512m,mode=1777 --tmpfs /web/node_modules/.vite:size=64m,uid=10002,gid=10002 --tmpfs /web/node_modules/.vite-temp:size=64m,uid=10002,gid=10002 --tmpfs /web/node_modules/.vitest-cache:size=64m,uid=10002,gid=10002 --env XDG_DATA_HOME=/tmp/xdg --env npm_config_cache=/tmp/npm familyfin-m1-web-tests:local
    if ($LASTEXITCODE -ne 0) { throw 'Frontend checks failed.' }
} finally { Pop-Location }
