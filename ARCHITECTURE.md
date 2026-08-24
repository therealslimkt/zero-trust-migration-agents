# Zero-Trust Migration Fleet Architecture

This document outlines the architecture for the "Zero-Trust Migration Fleet," built for the All Things Agentic Hackathon. 

## 📌 Core Concept
A multi-agent system that autonomously reverse-engineers, parses, and migrates proprietary legacy data (e.g., JDE/Mainframe binary) into Google BigQuery. 

To solve the "Data Gravity" and privacy concerns of enterprise AI, this fleet operates on a **Zero-Trust** model. Agents operate with Least Privilege, and sensitive data is scrubbed at the edge before cloud processing.

---

## 🏗️ The Fleet (Agent Roles)

### 1. Orchestrator (Main Agent)
*   **Role:** The manager. Receives the migration task, tracks state, and delegates work to specialized subagents.
*   **Model:** Gemini 3.5 Pro (via Google Cloud Vertex AI).
*   **SDK Feature:** Uses native `invoke_subagent` to spawn child conversations.

### 2. Edge Security Agent (The "Privacy Buffer")
*   **Role:** Runs *locally* on the edge (e.g., MacBook M5 Max / DGX). Scans all legacy data for Personally Identifiable Information (PII) before it leaves the internal network.
*   **Model:** Gemma (Small Language Model).
*   **SDK Feature:** `LiteRTAgentConfig` / `LocalOpenAIAgentConfig`. Runs entirely offline. Intercepts data via SDK lifecycle hooks (`pre_turn`).

### 3. Researcher Agent
*   **Role:** Given a hex dump or legacy schema, searches the internet and documentation to find how to parse it.
*   **Policy:** Read-only web access. Cannot execute code.

### 4. Reverse-Engineer Agent
*   **Role:** Writes the Python parsing scripts based on the Researcher's findings.
*   **Policy:** Cannot execute code locally. Must pass code to the sandbox.

### 5. Execution Agent (Cloud Sandbox)
*   **Role:** Takes the code written by the Reverse-Engineer and tests it against sample data.
*   **Infrastructure:** Runs in an isolated **Google Cloud Run** container.
*   **Zero-Trust Aspect:** If the AI writes malicious or destructive code, the blast radius is confined to the ephemeral container.

### 6. Pipeline Agent
*   **Role:** Infers the final schema and pushes the parsed data to **Google BigQuery**.
*   **SDK Feature:** Uses Pydantic structured output to guarantee the generated schema matches BigQuery's strict requirements.

---

## 🛠️ Technology Stack
*   **Framework:** Google Antigravity (AGY) SDK
*   **Cloud Infrastructure:** Google Cloud Run, Google BigQuery, Vertex AI
*   **Tooling Protocol:** Model Context Protocol (MCP) for isolated tool execution.
*   **Observability:** Skin Studio Mission Control (Local React Dashboard)
