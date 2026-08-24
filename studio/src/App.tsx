import React, { useEffect, useState } from 'react';

const App: React.FC = () => {
  const [data, setData] = useState<string[]>([]);
  
  // Simulate incoming EBCDIC data stream
  useEffect(() => {
    const interval = setInterval(() => {
      setData(prev => {
        const newData = [...prev, `0x${Math.random().toString(16).substr(2, 8).toUpperCase()} EBCDIC RECORD READ...`];
        return newData.length > 50 ? newData.slice(newData.length - 50) : newData; // Keep last 50 lines
      });
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="h-screen w-full bg-black text-green-500 font-mono flex flex-col p-4 overflow-hidden">
      <h1 className="text-3xl font-bold mb-6 text-center tracking-widest text-white">
        [ MISSION CONTROL : ZERO-TRUST MIGRATION AGENTS ]
      </h1>
      <div className="flex-1 grid grid-cols-1 md:grid-cols-3 gap-6 min-h-0">
        
        {/* Column 1: AS/400 Database View */}
        <div className="bg-gray-900 border-2 border-green-700 rounded-lg p-4 flex flex-col shadow-[0_0_15px_rgba(34,197,94,0.2)]">
          <h2 className="text-xl font-bold mb-4 border-b-2 border-green-700 pb-2 text-green-400">
            &gt; AS/400_DB_VIEW
          </h2>
          <div className="flex-1 overflow-y-auto flex flex-col-reverse">
            <div>
              {data.map((line, i) => (
                <div key={i} className="animate-pulse">{line}</div>
              ))}
            </div>
          </div>
        </div>

        {/* Column 2: Agent Translation & Security */}
        <div className="bg-gray-900 border-2 border-blue-700 rounded-lg p-4 flex flex-col text-blue-400 shadow-[0_0_15px_rgba(59,130,246,0.2)]">
          <h2 className="text-xl font-bold mb-4 border-b-2 border-blue-700 pb-2 text-blue-300">
            &gt; AGENT_TRANSLATION_SEC
          </h2>
          <div className="flex-1 overflow-y-auto space-y-2">
            <div>[SYSTEM] Gemma initialized...</div>
            <div>[AGENT] Intercepting EBCDIC stream...</div>
            <div className="text-yellow-400">[PII_AGENT] Analyzing payload for sensitive data...</div>
            <div className="text-yellow-400">[PII_AGENT] Redacting sensitive fields (SSN, DOB)...</div>
            <div>[SYSTEM] Translation to structured JSON format complete.</div>
            <div className="animate-pulse mt-4">_ Awaiting next payload...</div>
          </div>
        </div>

        {/* Column 3: BigQuery Destination */}
        <div className="bg-gray-900 border-2 border-purple-700 rounded-lg p-4 flex flex-col text-purple-400 shadow-[0_0_15px_rgba(168,85,247,0.2)]">
          <h2 className="text-xl font-bold mb-4 border-b-2 border-purple-700 pb-2 text-purple-300">
            &gt; BIGQUERY_DEST
          </h2>
          <div className="flex-1 overflow-y-auto">
            <pre className="text-sm">
{`{
  "status": "INGESTED",
  "table": "migration_db.records",
  "timestamp": "${new Date().toISOString()}",
  "data": {
    "id": "[REDACTED]",
    "ssn": "[REDACTED]",
    "payload": "Valid JSON Payload Transformed",
    "confidence_score": 0.99
  }
}`}
            </pre>
            <div className="mt-4 text-purple-500">INSERT INTO migration_db.records OK.</div>
          </div>
        </div>

      </div>
    </div>
  );
};

export default App;
