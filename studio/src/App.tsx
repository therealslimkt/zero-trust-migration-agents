import React, { useEffect, useState, useRef } from 'react';

// --- Types & Data Models ---
type ErpType = 'JDE_AS400' | 'SAP_MAXDB' | 'SAGE_ACCPAC' | 'NONE';

interface Cartridge {
  id: ErpType;
  name: string;
  dbType: string;
  encoding: string;
  description: string;
}

const CARTRIDGES: Record<ErpType, Cartridge> = {
  NONE: { id: 'NONE', name: 'Select ERP...', dbType: 'Unknown', encoding: 'Unknown', description: 'Mount a legacy VM cartridge to begin.' },
  JDE_AS400: {
    id: 'JDE_AS400',
    name: 'JD Edwards (World)',
    dbType: 'IBM Db2 AS/400',
    encoding: 'EBCDIC (COMP-3)',
    description: 'Proprietary EBCDIC format with packed decimal logic. High PII risk.'
  },
  SAP_MAXDB: {
    id: 'SAP_MAXDB',
    name: 'SAP ERP (Legacy)',
    dbType: 'SAP MaxDB 7.9',
    encoding: 'ASCII / Binary',
    description: 'Complex proprietary clustering. Bypassing ABAP layer required.'
  },
  SAGE_ACCPAC: {
    id: 'SAGE_ACCPAC',
    name: 'Sage Accpac 200',
    dbType: 'Pervasive PSQL v11',
    encoding: 'Btrieve Binary Pages',
    description: 'Btrieve transactional page format. Requires deep reversing.'
  }
};

const App: React.FC = () => {
  const [mountedCartridge, setMountedCartridge] = useState<ErpType>('NONE');
  const [isRunning, setIsRunning] = useState(false);
  
  // Terminal logs state
  const [rawDbLogs, setRawDbLogs] = useState<string[]>([]);
  const [agentLogs, setAgentLogs] = useState<string[]>([]);
  const [bqLogs, setBqLogs] = useState<string[]>([]);

  // Auto-scroll refs
  const rawRef = useRef<HTMLDivElement>(null);
  const agentRef = useRef<HTMLDivElement>(null);
  const bqRef = useRef<HTMLDivElement>(null);

  // Auto-scroll effect
  useEffect(() => {
    if (rawRef.current) rawRef.current.scrollTop = rawRef.current.scrollHeight;
    if (agentRef.current) agentRef.current.scrollTop = agentRef.current.scrollHeight;
    if (bqRef.current) bqRef.current.scrollTop = bqRef.current.scrollHeight;
  }, [rawDbLogs, agentLogs, bqLogs]);

  // Simulation Logic
  useEffect(() => {
    if (!isRunning || mountedCartridge === 'NONE') return;

    const encoding = CARTRIDGES[mountedCartridge].encoding;
    
    // 1. Raw DB Stream (Left Column) - Fires rapidly
    const rawInterval = setInterval(() => {
      const hex = Math.random().toString(16).substr(2, 12).toUpperCase();
      const newLog = `[${new Date().toISOString().split('T')[1].slice(0, -1)}] READ 0x${hex} [${encoding} STREAM]`;
      setRawDbLogs(prev => [...prev.slice(-30), newLog]);
    }, 400);

    // 2. Agent Fleet (Middle Column) - Fires periodically to simulate agent thought
    let agentStep = 0;
    const agentInterval = setInterval(() => {
      const steps = [
        `> [NANO_FIREWALL] Intercepting binary packet...`,
        `> [NANO_FIREWALL] NER Regex triggered. Stripping standard PII...`,
        `> [SPARKY_GEMMA] Contextual Edge Analysis started...`,
        `> [SPARKY_GEMMA] Redacting complex entities (Mr. Wayne, Gotham Branch)...`,
        `> [CLOUD_ORCHESTRATOR] Scrubbed payload received. Invoking Researcher Agent...`,
        `> [RESEARCHER] Identified ${CARTRIDGES[mountedCartridge].name} format. Open-source JTOpen JAR matched.`,
        `> [REVERSE-ENG] Generating Apache Beam pipeline translation...`,
        `> [CLOUD_ORCHESTRATOR] Dataflow pipeline active. Pushing to BigQuery.`
      ];
      
      const newLog = steps[agentStep % steps.length];
      setAgentLogs(prev => [...prev.slice(-40), newLog]);
      agentStep++;
    }, 1500);

    // 3. BigQuery Output (Right Column) - Fires after agent pipeline
    const bqInterval = setInterval(() => {
      const mockJson = `{
  "tx_id": "TXN-${Math.floor(Math.random() * 90000) + 10000}",
  "erp_source": "${CARTRIDGES[mountedCartridge].name}",
  "status": "SECURE_INGEST",
  "client_name": "[REDACTED_BY_GEMMA]",
  "tax_id": "[REDACTED_BY_NANO]"
}`;
      setBqLogs(prev => [...prev.slice(-10), mockJson, '-----------------------------------']);
    }, 3000);

    return () => {
      clearInterval(rawInterval);
      clearInterval(agentInterval);
      clearInterval(bqInterval);
    };
  }, [isRunning, mountedCartridge]);

  const handleMount = () => {
    if (mountedCartridge === 'NONE') {
      alert("Please select a legacy ERP cartridge first!");
      return;
    }
    setIsRunning(true);
    setAgentLogs([`SYSTEM: Connecting to ${CARTRIDGES[mountedCartridge].dbType} via Antigravity SDK...`]);
  };

  const handleEject = () => {
    setIsRunning(false);
    setMountedCartridge('NONE');
    setRawDbLogs([]);
    setAgentLogs([]);
    setBqLogs([]);
  };

  return (
    <div className="h-screen w-full bg-[#0a0a0a] font-mono flex flex-col p-4 overflow-hidden text-gray-300">
      
      {/* Header / Cartridge Bay */}
      <div className="bg-[#121212] border border-gray-700 rounded-lg p-6 mb-6 flex flex-col md:flex-row items-center justify-between shadow-2xl">
        <div className="flex flex-col">
          <h1 className="text-2xl font-bold tracking-widest text-white mb-2">
            🚀 ZERO-TRUST AGENTIC FLEET
          </h1>
          <p className="text-sm text-gray-500">Universal Legacy AI-Middleware Simulator</p>
        </div>

        <div className="flex items-center space-x-4 mt-4 md:mt-0">
          <select 
            className="bg-black border border-gray-600 text-white p-2 rounded focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
            value={mountedCartridge}
            onChange={(e) => setMountedCartridge(e.target.value as ErpType)}
            disabled={isRunning}
          >
            {Object.values(CARTRIDGES).map(cart => (
              <option key={cart.id} value={cart.id}>{cart.name} ({cart.dbType})</option>
            ))}
          </select>

          {!isRunning ? (
            <button 
              onClick={handleMount}
              className="bg-green-600 hover:bg-green-500 text-white font-bold py-2 px-6 rounded transition-colors"
            >
              MOUNT CARTRIDGE
            </button>
          ) : (
            <button 
              onClick={handleEject}
              className="bg-red-600 hover:bg-red-500 text-white font-bold py-2 px-6 rounded transition-colors animate-pulse"
            >
              EJECT (STOP)
            </button>
          )}
        </div>
      </div>

      {/* Cartridge Metadata Bar */}
      {mountedCartridge !== 'NONE' && (
        <div className="mb-4 text-xs flex space-x-8 text-gray-400">
          <span><strong className="text-gray-200">DB Type:</strong> {CARTRIDGES[mountedCartridge].dbType}</span>
          <span><strong className="text-gray-200">Encoding:</strong> {CARTRIDGES[mountedCartridge].encoding}</span>
          <span><strong className="text-gray-200">Analysis:</strong> {CARTRIDGES[mountedCartridge].description}</span>
        </div>
      )}

      {/* The 3-Column Matrix */}
      <div className="flex-1 grid grid-cols-1 md:grid-cols-3 gap-6 min-h-0">
        
        {/* Column 1: Raw VM / Database */}
        <div className="bg-[#050505] border border-red-900 rounded-lg flex flex-col shadow-[0_0_20px_rgba(220,38,38,0.1)] relative">
          <div className="bg-red-950/40 p-3 border-b border-red-900/50 flex justify-between items-center">
            <h2 className="text-sm font-bold text-red-500">1. LEGACY VM STREAM</h2>
            <div className={`h-2 w-2 rounded-full ${isRunning ? 'bg-red-500 animate-pulse' : 'bg-gray-700'}`}></div>
          </div>
          <div ref={rawRef} className="flex-1 p-4 overflow-y-auto text-red-700 text-xs leading-relaxed">
            {rawDbLogs.map((log, i) => <div key={i}>{log}</div>)}
          </div>
        </div>

        {/* Column 2: Agent Fleet */}
        <div className="bg-[#050505] border border-blue-900 rounded-lg flex flex-col shadow-[0_0_20px_rgba(59,130,246,0.1)] relative">
          <div className="bg-blue-950/40 p-3 border-b border-blue-900/50 flex justify-between items-center">
            <h2 className="text-sm font-bold text-blue-500">2. ZERO-TRUST AGENT FLEET</h2>
            <div className={`h-2 w-2 rounded-full ${isRunning ? 'bg-blue-500 animate-ping' : 'bg-gray-700'}`}></div>
          </div>
          <div ref={agentRef} className="flex-1 p-4 overflow-y-auto text-blue-400 text-xs leading-relaxed font-semibold">
            {agentLogs.map((log, i) => {
              // Color code the different agents
              if (log.includes('NANO_FIREWALL')) return <div key={i} className="text-pink-400 mt-2">{log}</div>;
              if (log.includes('SPARKY_GEMMA')) return <div key={i} className="text-emerald-400 mt-2">{log}</div>;
              if (log.includes('CLOUD_ORCHESTRATOR')) return <div key={i} className="text-blue-300 mt-2">{log}</div>;
              if (log.includes('RESEARCHER') || log.includes('REVERSE-ENG')) return <div key={i} className="text-purple-400 ml-4">{log}</div>;
              return <div key={i}>{log}</div>;
            })}
          </div>
        </div>

        {/* Column 3: BigQuery Destination */}
        <div className="bg-[#050505] border border-green-900 rounded-lg flex flex-col shadow-[0_0_20px_rgba(34,197,94,0.1)] relative">
          <div className="bg-green-950/40 p-3 border-b border-green-900/50 flex justify-between items-center">
            <h2 className="text-sm font-bold text-green-500">3. GOOGLE BIGQUERY</h2>
            <div className={`h-2 w-2 rounded-full ${isRunning ? 'bg-green-500 animate-pulse' : 'bg-gray-700'}`}></div>
          </div>
          <div ref={bqRef} className="flex-1 p-4 overflow-y-auto text-green-400 text-xs">
            {bqLogs.map((log, i) => (
              <pre key={i} className="mb-2 whitespace-pre-wrap">{log}</pre>
            ))}
          </div>
        </div>

      </div>
    </div>
  );
};

export default App;
