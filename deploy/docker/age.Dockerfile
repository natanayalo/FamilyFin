FROM golang:1.26.10-alpine3.23@sha256:0525c952defebc693cdaf62cdf43afa32be5a7f377e99260642ea19c240c708e AS build
ENV GOTOOLCHAIN=local CGO_ENABLED=0
WORKDIR /build
COPY deploy/docker/age-build/go.mod deploy/docker/age-build/go.sum ./
RUN go mod download all && go mod verify
RUN --network=none go test -mod=readonly filippo.io/age
RUN --network=none GOOS=windows GOARCH=amd64 go build -mod=readonly -trimpath -buildvcs=false -ldflags="-s -w -X main.Version=v1.3.2" -o /out/age.exe filippo.io/age/cmd/age \
    && GOOS=windows GOARCH=amd64 go build -mod=readonly -trimpath -buildvcs=false -ldflags="-s -w -X main.Version=v1.3.2" -o /out/age-keygen.exe filippo.io/age/cmd/age-keygen \
    && GOOS=linux GOARCH=amd64 go build -mod=readonly -trimpath -buildvcs=false -ldflags="-s -w -X main.Version=v1.3.2" -o /out/age filippo.io/age/cmd/age \
    && GOOS=linux GOARCH=amd64 go build -mod=readonly -trimpath -buildvcs=false -ldflags="-s -w -X main.Version=v1.3.2" -o /out/age-keygen filippo.io/age/cmd/age-keygen
RUN go list -mod=readonly -deps filippo.io/age/cmd/age filippo.io/age/cmd/age-keygen > /out/compiled-packages.txt

FROM scratch AS export
COPY --from=build /out/ /
COPY deploy/docker/age-build/licenses/ /licenses/

FROM scratch AS runtime
COPY --from=build --chmod=0555 /out/age /age
COPY --from=build --chmod=0555 /out/age-keygen /age-keygen
COPY --from=build /out/age.exe /age.exe
COPY --from=build /out/age-keygen.exe /age-keygen.exe
COPY deploy/docker/age-build/licenses/ /licenses/
USER 10004:10004
ENTRYPOINT ["/age"]
