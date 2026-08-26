# Zero-Trust Migration Agents

A zero-trust, multi-agent system that autonomously reverse-engineers, parses, and migrates proprietary legacy data into Google BigQuery. Built for the **All Things Agentic Hackathon**.

## 📖 Overview
Enterprise companies want to use AI to migrate legacy data, but they cannot send sensitive PII to the cloud. This project solves "Data Gravity" by utilizing a Zero-Trust architecture:
1. **Edge AI:** A local Gemma model acts as a privacy firewall, scrubbing PII *before* it leaves the internal network.
2. **Cloud AI:** Gemini 3.5 Flash acts as the Orchestrator, dynamically spawning specialized subagents (Researcher, Reverse-Engineer, Pipeline).
3. **Trusted Execution:** Agents emit schema-validated declarative TransformPlans. After portfolio approval, a pre-registered Dataflow Flex Template interprets only allowlisted operations; generated code is never executed.

Read the full [ARCHITECTURE.md](ARCHITECTURE.md) for details on the agent fleet.

---

## 🚀 Spin-Up Instructions

### Prerequisites
- Python 3.10+
- Google Cloud CLI (`gcloud`) installed and authenticated
- Node.js & npm (for the Mission Control UI)
- `uv` (optional, for fast Python dependency management)

### 1. Local Setup
Clone the repository and install the dependencies:
```bash
git clone https://github.com/therealslimkt/zero-trust-migration-agents
cd zero-trust-migration-agents
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Authentication
This project requires Google Cloud Application Default Credentials (ADC) to interact with Vertex AI, Cloud Run, and BigQuery.
```bash
gcloud auth application-default login
```
Set up your environment variables:
```bash
cp .env.example .env
# Edit .env with your Google Cloud Project ID
```

### 3. Run the Mission Control Dashboard
The Skin Studio Mission Control dashboard provides a real-time view of agent-to-agent (A2A) communications and local execution state.
```bash
cd studio
npm install
npm run dev
```

### 4. Initialize the Orchestrator
In a new terminal window (with your venv activated), start the main orchestration agent:
```bash
python main.py
```
Upload a dummy hex file to the dashboard to watch the fleet autonomously scrub, reverse-engineer, and migrate the data!
