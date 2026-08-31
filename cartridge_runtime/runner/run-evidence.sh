#!/bin/sh
set -eu
export PGPASSWORD=synthetic-only-reader

: "${KERAUN_JDE_HOST:=jde-e1-ibmi}"
: "${KERAUN_AX_HOST:=dynamics-ax}"
: "${KERAUN_EBS_HOST:=oracle-ebs-19c}"

jde_invalid=$(psql -h "$KERAUN_JDE_HOST" -U cartridge_reader -d keraun_jde -Atqc "SELECT count(*) FROM f0911 WHERE fixture_class = 'invalid' AND upmj % 1000 > 365")
ax_orphans=$(psql -h "$KERAUN_AX_HOST" -U cartridge_reader -d keraun_ax -Atqc "SELECT count(*) FROM custtable c LEFT JOIN dirpartytable b ON b.data_area_id=c.data_area_id AND b.partition_id=c.partition_id AND b.rec_id=c.rec_id WHERE c.fixture_class='invalid' AND b.rec_id IS NULL")
ebs_unmapped=$(psql -h "$KERAUN_EBS_HOST" -U cartridge_reader -d keraun_ebs -Atqc "SELECT count(*) FROM hz_parties p LEFT JOIN fnd_descriptive_flexs f ON f.application_short_name='AR' AND f.table_name='HZ_PARTIES' AND f.context_value=p.attribute_category AND f.segment_column='ATTRIBUTE1' AND f.metadata_version='FND_DFF_2026_08_01' WHERE p.fixture_class='invalid' AND f.semantic_name IS NULL")
printf '{"schemaVersion":"keraun.cartridge-evidence/v1","synthetic":true,"checks":{"jdeInvalidCyyddd":%s,"axOrphanDerived":%s,"ebsUnmappedFlexfield":%s}}\n' "$jde_invalid" "$ax_orphans" "$ebs_unmapped"
