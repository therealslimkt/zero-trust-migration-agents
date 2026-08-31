-- Project-owned synthetic EBS/Oracle 19c-shaped data. This is not EBS or Oracle Database.
CREATE TABLE fnd_tables (
  application_short_name text NOT NULL,
  table_name text NOT NULL,
  PRIMARY KEY (application_short_name, table_name)
);
CREATE TABLE fnd_columns (
  application_short_name text NOT NULL,
  table_name text NOT NULL,
  column_name text NOT NULL,
  data_type text NOT NULL,
  PRIMARY KEY (application_short_name, table_name, column_name)
);
CREATE TABLE fnd_descriptive_flexs (
  application_short_name text NOT NULL,
  table_name text NOT NULL,
  context_value text NOT NULL,
  segment_column text NOT NULL,
  semantic_name text NOT NULL,
  data_type text NOT NULL,
  metadata_version text NOT NULL,
  PRIMARY KEY (application_short_name, table_name, context_value, segment_column, metadata_version)
);
CREATE TABLE hz_parties (
  party_id bigint PRIMARY KEY,
  party_name text NOT NULL,
  attribute_category text NOT NULL,
  attribute1 text,
  attribute2 text,
  attribute3 text,
  attribute4 text,
  attribute5 text,
  last_update_date timestamptz NOT NULL,
  last_updated_by bigint NOT NULL,
  fixture_class text NOT NULL CHECK (fixture_class IN ('snapshot', 'invalid'))
);
CREATE TABLE hz_parties_delta (
  sequence integer PRIMARY KEY,
  operation text NOT NULL CHECK (operation IN ('insert', 'update', 'delete')),
  party_id bigint NOT NULL,
  last_update_date timestamptz NOT NULL,
  last_updated_by bigint NOT NULL
);
INSERT INTO fnd_tables VALUES ('AR','HZ_PARTIES');
INSERT INTO fnd_columns VALUES
  ('AR','HZ_PARTIES','ATTRIBUTE_CATEGORY','VARCHAR2'),
  ('AR','HZ_PARTIES','ATTRIBUTE1','VARCHAR2'),
  ('AR','HZ_PARTIES','ATTRIBUTE2','VARCHAR2');
INSERT INTO fnd_descriptive_flexs VALUES
  ('AR','HZ_PARTIES','CUSTOMER_EXT','ATTRIBUTE1','customer_tier','string','FND_DFF_2026_08_01'),
  ('AR','HZ_PARTIES','CUSTOMER_EXT','ATTRIBUTE2','regulatory_region','string','FND_DFF_2026_08_01'),
  ('AR','HZ_PARTIES','SUPPLIER_EXT','ATTRIBUTE1','payment_profile','string','FND_DFF_2026_08_01');
INSERT INTO hz_parties VALUES
  (501,'Apollo Synthetic','CUSTOMER_EXT','GOLD','NA',NULL,NULL,NULL,'2026-08-01T10:00:00Z',101,'snapshot'),
  (502,'Hermes Synthetic','SUPPLIER_EXT','NET30',NULL,NULL,NULL,NULL,'2026-08-01T10:01:00Z',102,'snapshot'),
  (599,'Invalid Synthetic','UNKNOWN_CONTEXT','AMBIGUOUS',NULL,NULL,NULL,NULL,'2026-08-01T10:02:00Z',103,'invalid');
INSERT INTO hz_parties_delta VALUES
  (1,'insert',503,'2026-08-01T10:03:00Z',101),
  (2,'update',501,'2026-08-01T10:04:00Z',102),
  (3,'delete',502,'2026-08-01T10:05:00Z',102);
CREATE ROLE cartridge_reader LOGIN PASSWORD 'synthetic-only-reader';
GRANT CONNECT ON DATABASE keraun_ebs TO cartridge_reader;
GRANT USAGE ON SCHEMA public TO cartridge_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO cartridge_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO cartridge_reader;
