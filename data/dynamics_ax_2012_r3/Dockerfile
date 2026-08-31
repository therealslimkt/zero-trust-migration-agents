FROM postgres:16-bookworm
LABEL org.opencontainers.image.title="Keraun synthetic Dynamics AX 2012 R3 cartridge"
LABEL io.keraun.cartridge.id="dynamics_ax_2012_r3"
LABEL io.keraun.synthetic="true"
COPY data/dynamics_ax_2012_r3/seed.yaml /opt/keraun/seed.yaml
COPY data/dynamics_ax_2012_r3/init.sql /docker-entrypoint-initdb.d/10-dynamics-ax.sql
HEALTHCHECK --interval=15s --timeout=3s --retries=5 CMD pg_isready -U keraun -d keraun_ax
