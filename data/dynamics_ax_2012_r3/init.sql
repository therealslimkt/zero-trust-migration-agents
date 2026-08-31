-- Project-owned synthetic AX/SQL Server-shaped data. This is not Dynamics or SQL Server.
CREATE TABLE sqldictionary (
  table_id integer PRIMARY KEY,
  physical_name text NOT NULL,
  logical_name text NOT NULL
);
CREATE TABLE modelelement (
  element_name text PRIMARY KEY,
  extends_element text,
  table_id integer NOT NULL REFERENCES sqldictionary(table_id)
);
CREATE TABLE dirpartytable (
  data_area_id text NOT NULL,
  partition_id bigint NOT NULL,
  rec_id bigint NOT NULL,
  party_name text NOT NULL,
  modified_datetime timestamptz NOT NULL,
  PRIMARY KEY (data_area_id, partition_id, rec_id)
);
CREATE TABLE custtable (
  data_area_id text NOT NULL,
  partition_id bigint NOT NULL,
  rec_id bigint NOT NULL,
  customer_group text NOT NULL,
  modified_datetime timestamptz NOT NULL,
  fixture_class text NOT NULL CHECK (fixture_class IN ('snapshot', 'invalid')),
  PRIMARY KEY (data_area_id, partition_id, rec_id)
);
CREATE TABLE ax_cdc (
  sequence integer PRIMARY KEY,
  operation text NOT NULL CHECK (operation IN ('insert', 'update')),
  data_area_id text NOT NULL,
  partition_id bigint NOT NULL,
  rec_id bigint NOT NULL,
  modified_datetime timestamptz NOT NULL
);
INSERT INTO sqldictionary VALUES (77, 'DIRPARTYTABLE', 'DirPartyTable'), (88, 'CUSTTABLE', 'CustTable');
INSERT INTO modelelement VALUES ('DirPartyTable', NULL, 77), ('CustTable', 'DirPartyTable', 88);
INSERT INTO dirpartytable VALUES
  ('usmf',5637144576,1001,'Acme Synthetic','2026-08-01T10:00:00Z'),
  ('demf',5637144576,1002,'Northwind Synthetic','2026-08-01T10:05:00Z');
INSERT INTO custtable VALUES
  ('usmf',5637144576,1001,'RETAIL','2026-08-01T10:00:00Z','snapshot'),
  ('demf',5637144576,1002,'WHOLESALE','2026-08-01T10:05:00Z','snapshot'),
  ('usmf',5637144576,9001,'RETAIL','2026-08-01T10:07:00Z','invalid'),
  ('usmf',9999999999,1001,'RETAIL','2026-08-01T10:08:00Z','invalid');
INSERT INTO ax_cdc VALUES
  (1,'insert','usmf',5637144576,1003,'2026-08-01T10:10:00Z'),
  (2,'update','usmf',5637144576,1001,'2026-08-01T10:11:00Z');
CREATE ROLE cartridge_reader LOGIN PASSWORD 'synthetic-only-reader';
GRANT CONNECT ON DATABASE keraun_ax TO cartridge_reader;
GRANT USAGE ON SCHEMA public TO cartridge_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO cartridge_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO cartridge_reader;
