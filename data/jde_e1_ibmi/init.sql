-- Project-owned synthetic JDE/IBM i-shaped data. This is not JDE or Db2 for i.
CREATE TABLE f9860 (
  object_name text PRIMARY KEY,
  object_type text NOT NULL,
  object_library text NOT NULL
);
CREATE TABLE f98711 (
  table_name text NOT NULL,
  field_name text NOT NULL,
  data_type text NOT NULL,
  ordinal integer NOT NULL,
  PRIMARY KEY (table_name, field_name)
);
CREATE TABLE f0911 (
  company text NOT NULL,
  document_type text NOT NULL,
  document_number bigint NOT NULL,
  line_number integer NOT NULL,
  ledger_type text NOT NULL,
  upmj integer NOT NULL,
  upmt integer NOT NULL,
  amount_minor bigint NOT NULL,
  fixture_class text NOT NULL CHECK (fixture_class IN ('snapshot', 'invalid')),
  PRIMARY KEY (company, document_type, document_number, line_number, ledger_type)
);
CREATE TABLE f0911_delta (
  sequence integer PRIMARY KEY,
  operation text NOT NULL CHECK (operation IN ('insert', 'update', 'delete')),
  company text NOT NULL,
  document_type text NOT NULL,
  document_number bigint NOT NULL,
  line_number integer NOT NULL,
  ledger_type text NOT NULL,
  upmj integer NOT NULL,
  upmt integer NOT NULL
);
INSERT INTO f9860 VALUES ('F0911', 'TBLE', 'PRODDTA');
INSERT INTO f98711 VALUES
  ('F0911', 'UPMJ', 'CYYDDD', 1),
  ('F0911', 'UPMT', 'HHMMSS', 2),
  ('F0911', 'AA', 'INTEGER_MINOR_UNITS', 3);
INSERT INTO f0911 VALUES
  ('00001','JE',700101,1,'AA',123165,93015,128450,'snapshot'),
  ('00001','JE',700102,1,'AA',115351,81500,-4200,'snapshot'),
  ('00002','PV',700103,2,'AA',0,0,9000,'snapshot'),
  ('00002','JE',700104,1,'AA',121366,101500,700,'invalid');
INSERT INTO f0911_delta VALUES
  (1,'insert','00001','JE',700105,1,'AA',123166,94500),
  (2,'update','00001','JE',700101,1,'AA',123167,101500),
  (3,'delete','00001','JE',700102,1,'AA',123168,110000);
CREATE ROLE cartridge_reader LOGIN PASSWORD 'synthetic-only-reader';
GRANT CONNECT ON DATABASE keraun_jde TO cartridge_reader;
GRANT USAGE ON SCHEMA public TO cartridge_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO cartridge_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO cartridge_reader;
