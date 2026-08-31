FROM postgres:16-bookworm
LABEL org.opencontainers.image.title="Keraun synthetic cartridge evidence runner"
LABEL io.keraun.role="sandboxed-parser-certifier"
COPY cartridge_runtime/runner/run-evidence.sh /usr/local/bin/run-evidence
USER 65534:65534
ENTRYPOINT ["/usr/local/bin/run-evidence"]
