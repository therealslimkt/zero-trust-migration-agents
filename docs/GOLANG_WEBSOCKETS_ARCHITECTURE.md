# Mission Control Backend: Architecture & Design Decisions

This document outlines the architectural decisions behind the **Mission Control Backend**, specifically addressing why we chose **Golang** and **WebSockets** over a traditional REST API.

## 1. Why Golang?

The Mission Control backend acts as the central nervous system of our agentic fleet. It must handle high-throughput telemetry, real-time logging, and agent state management simultaneously.

*   **Concurrency Model (Goroutines):** The primary reason for choosing Go is its lightweight concurrency model. A single Go backend can handle tens of thousands of simultaneous WebSocket connections and agent streams using goroutines and channels, with minimal memory overhead compared to Node.js or Python.
*   **Performance & Compilation:** Go compiles to a single, statically linked binary. It offers near-C performance, which is critical when processing high-volume, real-time logging streams from multiple autonomous agents simultaneously.
*   **Strong Typing & Safety:** Managing state across a distributed multi-agent system requires strict data contracts. Go's strong typing ensures that our telemetry payloads, agent states, and command messages are validated at compile-time.

## 2. Why WebSockets instead of a REST API?

For an interactive, real-time "Matrix-style" agent dashboard, a traditional REST API is fundamentally the wrong tool for the job.

### The Problem with REST for Multi-Agent Systems
*   **Polling Overhead:** With REST, the React UI would have to constantly poll the server (e.g., every 500ms) to check if an agent has new thoughts, logs, or state changes. This creates massive unnecessary HTTP overhead and network congestion.
*   **Unidirectional Communication:** REST is strictly client-to-server. If the Orchestrator agent suddenly encounters a fatal error, it cannot "push" that error to the UI; the UI must wait until its next polling cycle to find out.

### The WebSocket Advantage
*   **Bidirectional, Persistent Connection:** WebSockets keep a single TCP connection open. The moment an agent generates a "thought" or a chunk of data, the Go backend pushes it instantly to the React UI. 
*   **Low Latency (Real-time):** Because there is no HTTP handshake overhead for every message, latency is reduced to sub-milliseconds. This is what allows the dashboard to feel like a live terminal.
*   **Event-Driven Architecture:** The Go backend utilizes channels to route events. When `main.py` pushes an update to Go, Go immediately broadcasts that update across the WebSocket channel to all connected React clients.

## 3. Architecture Flow

1.  **Agents (Python):** The Google Antigravity SDK runs the agents in Python. As they think and execute, they send their telemetry data to the Go backend.
2.  **Mission Control (Golang):** The Go server maintains an in-memory state of the entire fleet. It acts as a high-speed router, receiving agent logs via internal HTTP/gRPC and instantly broadcasting them over WebSockets.
3.  **Dashboard (React):** The Vite/React frontend connects to the Go server via WebSockets `ws://localhost:8080/ws`. It listens for incoming events and reactively updates the UI in real-time, displaying the streaming thoughts of the agent fleet.
