FROM postgres:16-bookworm
LABEL org.opencontainers.image.title="Keraun synthetic JDE E1 IBM i cartridge"
LABEL io.keraun.cartridge.id="jde_e1_ibmi"
LABEL io.keraun.synthetic="true"
COPY data/jde_e1_ibmi/seed.yaml /opt/keraun/seed.yaml
COPY data/jde_e1_ibmi/init.sql /docker-entrypoint-initdb.d/10-jde-e1.sql
HEALTHCHECK --interval=15s --timeout=3s --retries=5 CMD pg_isready -U keraun -d keraun_jde
