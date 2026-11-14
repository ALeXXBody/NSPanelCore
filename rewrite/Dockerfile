# HACS + Docker: Go core daemon image.
# Single static binary: builds in seconds, no Conan/CMake/Boost.
FROM golang:1.24-bookworm AS build
WORKDIR /src
COPY rewrite/nspanelcore/ ./rewrite/nspanelcore/
WORKDIR /src/rewrite/nspanelcore
RUN go vet ./... && go test ./... -count=1 && \
    CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/nspanelcore ./cmd/nspanelcore

FROM gcr.io/distroless/static-debian12
COPY --from=build /out/nspanelcore /nspanelcore
ENTRYPOINT ["/nspanelcore"]
