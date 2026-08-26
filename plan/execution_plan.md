# 🏃 Execution Plan: Project Implementation

This document breaks down the implementation of the Zero-Trust Migration Agents into four distinct phases, prioritizing the "Wow" factor for the hackathon demo video.

## Phase 1: The "Cartridge" Simulator (Authentic Legacy DB Mocking)
*Goal: Create authentic VM/Container environments that simulate exact legacy backend file formats (e.g., AS/400 Db2) so we can prove our agents can bypass the proprietary application layer entirely.*

1.  **AS/400 & JDE Cartridge:** 
    *   Instead of random strings, we will generate an authentic **EBCDIC-encoded binary file** with COBOL-style packed decimals (COMP-3).
    *   This will simulate a raw export of a JD Edwards core table (like `F0101` - Address Book).
2.  **Containerize/VM:** Package this binary file into a Docker container or local VM. The UI will have a "Mount Cartridge" button that exposes this raw binary file to the agent fleet.

## Phase 2: The Studio UI ("The Matrix View")
*Goal: Build the interactive React dashboard that the end-user uses to orchestrate the translation.*

1.  **Cartridge Selection View:** A sleek UI where the user selects their ERP (JD Edwards, SAP, Accpac) and DB versions. 
2.  **The Translation Matrix (The Hero UI):** 
    *   *Left Column (The Past):* A scrolling view showing the terrifying raw EBCDIC/Binary hex data.
    *   *Middle Column (The Agents):* Live status board showing the Nano Firewall, the Sparky Gemma LLM, and the Cloud Orchestrator working in real-time.
    *   *Right Column (The Future):* Clean, structured JSON rows appearing in real-time as they hit Google BigQuery.

## Phase 3: Core Agent Fleet ("Defense in Depth" Dual-Edge Architecture)
*Goal: A two-factor Zero-Trust pipeline using both physical edge hardware and heavy local compute.*

1.  **The Jetson Nano (Layer 1: Hardware Firewall):** 
    *   The raw legacy stream hits the Nano first. 
    *   It runs a blazing-fast, lightweight SpaCy/Regex NER model to scrub obvious, structured PII (e.g., standard SSN formats, Credit Cards, EINs).
    *   It also classifies the data type (e.g., "This is AS/400 EBCDIC") and routes it forward.
2.  **Sparky (Layer 2: Contextual Edge LLM):** 
    *   The partially scrubbed stream arrives at Sparky. 
    *   Sparky runs the Antigravity `LiteRTAgentConfig` powering the **Gemma 2B LLM**.
    *   Gemma performs "Contextual Redaction", catching complex PII that regex missed (e.g., "Please forward the invoice to Mr. Bruce Wayne" -> "...to [REDACTED]").
3.  **The Cloud Orchestrator (Layer 3: Gemini 3.5 Pro):** 
    *   Initializes in the cloud via `LocalAgentConfig(vertex=True)`. 
    *   Only receives 100% sanitized data. It coordinates the Researcher and Reverse-Engineer subagents to build the translation pipeline.

## Phase 4: The Google Cloud Runtime (Replacing OpenFlow)
*Goal: Safely execute a trusted, pre-registered pipeline from an approved declarative plan and push to BigQuery.*

1.  **Google Cloud Dataflow (Apache Beam):** This is Google's equivalent to OpenFlow. 
    *   The Reverse-Engineer agent writes an **Apache Beam** pipeline script.
    *   This script utilizes open-source JARs to decode the proprietary binary into ASCII.
2.  **Trusted Template Dispatch:** The approved plan supplies typed parameters to a pre-registered Google Cloud Dataflow Flex Template; no generated code is accepted.
3.  **BigQuery Ingestion:** The Dataflow pipeline streams the decoded, PII-scrubbed JSON directly into Google BigQuery.

## Post-Hackathon / Access Unlocked
*   **[PENDING] Migrate to Gemini 3.5 Pro:** The `gemini-2.5-pro` model is currently serving as our production fallback on Vertex AI while our `ztm-agent-9049c3` project awaits preview access to `gemini-3.5-pro`. Once Google Cloud grants access in Model Garden, update `main.py` and `local_gemma_agent.py` to target the 3.5 generation for enhanced planning and orchestration.
