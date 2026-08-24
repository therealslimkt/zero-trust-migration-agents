# Zero-Trust Migration Fleet Architecture

This document outlines the architecture for the "Zero-Trust Migration Fleet," built for the All Things Agentic Hackathon. 

## 📌 Core Concept
A multi-agent system that autonomously reverse-engineers, parses, and migrates proprietary legacy data (e.g., JDE/Mainframe binary) into Google BigQuery. 

To solve the "Data Gravity" and privacy concerns of enterprise AI, this fleet operates on a **Zero-Trust** model. Agents operate with Least Privilege, and sensitive data is scrubbed at the edge before cloud processing.

---

## 🏗️ The Infrastructure Layer (GCP vs Snowflake)
A massive competitive advantage of this architecture is its native reliance on Google Cloud's infrastructure, which inherently supports legacy compute hosting—something pure data warehouses like Snowflake cannot do.

*   **AS/400 & Mainframes:** Hosted natively using **IBM Power Systems on Google Cloud**.
*   **Legacy Windows/Linux ERPs:** Hosted natively using **Google Cloud VMware Engine (GCVE)**.

By hosting the "Cartridges" directly in GCP, the Agentic Fleet translates the proprietary streams (EBCDIC, Btrieve) entirely within the Google Cloud perimeter, eliminating the need for expensive 3rd-party integration middleware.

---

## 🤖 The Fleet (Agent Roles)

### 1. Orchestrator (Main Agent)
*   **Role:** The manager. Receives the migration task, tracks state, and delegates work to specialized subagents.
*   **Model:** Gemini 3.5 Pro (via Google Cloud Vertex AI).

### 2. Edge Security Agent (The "Privacy Firewall")
*   **Role:** Runs *locally* on edge hardware (Jetson Nano/Sparky). Scans all legacy data for Personally Identifiable Information (PII) before it leaves the internal network.
*   **Model:** Gemma 2B (Local LLM) and SpaCy (NER).

### 3. Researcher Agent
*   **Role:** Given a hex dump or legacy schema, searches the internet to find open-source decoders.

### 4. Reverse-Engineer Agent
*   **Role:** Writes the Google Cloud Dataflow (Apache Beam) pipelines based on the Researcher's findings.

### 5. Execution Agent (Cloud Sandbox)
*   **Role:** Takes the code written by the Reverse-Engineer and executes it in an isolated Google Cloud Run container.
