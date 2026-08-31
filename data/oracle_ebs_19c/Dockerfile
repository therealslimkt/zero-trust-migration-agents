FROM postgres:16-bookworm
LABEL org.opencontainers.image.title="Keraun synthetic Oracle EBS Oracle 19c cartridge"
LABEL io.keraun.cartridge.id="oracle_ebs_19c"
LABEL io.keraun.synthetic="true"
COPY data/oracle_ebs_19c/seed.yaml /opt/keraun/seed.yaml
COPY data/oracle_ebs_19c/init.sql /docker-entrypoint-initdb.d/10-oracle-ebs.sql
HEALTHCHECK --interval=15s --timeout=3s --retries=5 CMD pg_isready -U keraun -d keraun_ebs
