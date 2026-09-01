// Real captured evidence from `scripts/demo_cluster_to_bigquery.py --load`,
// run against project ztm-agent-9049c3 on 2026-08-31. Nothing here is invented:
// the hexdump, the decoded rows, and the load job id are the recorded output.

const HEX = [
  "00000000  4d 58 44 42 4b 4e 41 31 01 01 04 00 58 00 00 00  |MXDBKNA1....X...|",
  "00000010  52 00 00 00 d2 c7 dc f0 78 da ab 56 f2 0e f5 f3  |R.......x..V....|",
  "00000020  0b 52 b2 52 32 80 01 43 25 1d 25 1f 47 3f 17 43  |.R.R2..C%.%.G?.C|",
  "00000030  a0 60 68 30 90 e3 e7 e8 eb 0a e2 f8 e5 17 95 64  |.`h0...........d|",
  "00000040  14 97 24 16 29 38 e7 e7 16 e4 e7 a5 e6 95 14 2b  |..$.)8.........+|",
  "00000050  f8 f8 38 03 95 f8 07 85 18 80 94 38 67 64 26 27  |..8........8gd&'|",
];

const ROWS = [
  { n: "0000000001", name: "Northstar Components LLC", city: "Chicago", c: "US", o: 0 },
  { n: "0000000002", name: "Blue Heron Manufacturing Ltd", city: "Toronto", c: "CA", o: 1 },
  { n: "0000000003", name: "Juniper Industrial GmbH", city: "Berlin", c: "DE", o: 2 },
  { n: "0000000004", name: "Copper Finch Systems KK", city: "Tokyo", c: "JP", o: 3 },
];

const MAP = [
  ["KUNNR", "customer_number", "STRING", "financialAccount"],
  ["NAME1", "name", "STRING", "name"],
  ["ORT01", "city", "STRING", "address"],
  ["LAND1", "country", "STRING", "public"],
];

export function ClusterDecodePanel() {
  return (
    <section className="cluster-panel" aria-labelledby="cluster-heading">
      <div className="landing-control__heading">
        <span className="landing-control__eyebrow">THE HARDEST CASE</span>
        <h2 id="cluster-heading">Clustered binary in. Typed BigQuery columns out.</h2>
        <p>
          A SAP-style cluster export packs every record as its own compressed blob. Point a
          warehouse loader at it and you get one opaque <code>BYTES</code> column. Code-owned
          adapters — never the model — decode it under a fixed schema.
        </p>
      </div>

      <div className="cluster-panel__flow">
        <article className="cluster-stage cluster-stage--raw">
          <header><span className="cluster-stage__num">01</span><h3>On the legacy host</h3></header>
          <p className="cluster-stage__note">386 bytes · unreadable · every record separately zlib-compressed</p>
          <pre className="cluster-hex">{HEX.join("\n")}</pre>
        </article>

        <article className="cluster-stage cluster-stage--gate">
          <header><span className="cluster-stage__num">02</span><h3>Deterministic decode</h3></header>
          <ul className="cluster-gates">
            <li><b>MXDBKNA1</b> magic and version validated</li>
            <li>Per record: declared length <b>and CRC32 verified before decompressing</b></li>
            <li>Bounded: ≤10,000 records, ≤16 KiB uncompressed each</li>
            <li>Keys outside <code>{"{KUNNR, NAME1, ORT01, LAND1}"}</code> rejected</li>
            <li className="cluster-gates__fail">Malformed input produces <b>no partial output</b></li>
          </ul>
          <table className="cluster-map">
            <thead><tr><th>SAP</th><th>Column</th><th>Type</th><th>Data class</th></tr></thead>
            <tbody>{MAP.map(([a, b, c, d]) => <tr key={a}><td>{a}</td><td>{b}</td><td>{c}</td><td className="cluster-map__cls">{d}</td></tr>)}</tbody>
          </table>
          <p className="cluster-stage__note">The data class is assigned by the adapter, not the model. It is what the redaction policy keys off.</p>
        </article>

        <article className="cluster-stage cluster-stage--out">
          <header><span className="cluster-stage__num">03</span><h3>Landed in BigQuery</h3></header>
          <table className="cluster-rows">
            <thead><tr><th>customer_number</th><th>name</th><th>city</th><th>country</th><th>#</th></tr></thead>
            <tbody>{ROWS.map((r) => <tr key={r.n}><td>{r.n}</td><td>{r.name}</td><td>{r.city}</td><td>{r.c}</td><td>{r.o}</td></tr>)}</tbody>
          </table>
          <dl className="cluster-proof">
            <div><dt>Table</dt><dd>keraun_demo.sap_kna1_clustered</dd></div>
            <div><dt>Load job</dt><dd>ce235d05-810e-4457-b134-76dc9dfa4717</dd></div>
            <div><dt>Reconciliation</dt><dd className="cluster-proof__ok">4 decoded = 4 loaded · OK</dd></div>
          </dl>
        </article>
      </div>
      <p className="cluster-panel__foot">
        Recorded output of <code>scripts/demo_cluster_to_bigquery.py --load</code> against project
        <b> ztm-agent-9049c3</b>. Fixture data is synthetic and deidentified; the structure reproduces
        SAP cluster-table packing and is not a licensed SAP database.
      </p>
    </section>
  );
}
