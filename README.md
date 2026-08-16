# NHL Season Scheduler API

A high-performance REST API built with **FastAPI**, **SQLModel**, and **SQLite** designed to generate, balance, and query regular-season NHL schedules using a 3NF-normalized database architecture and circular round-robin algorithms.

## Features
- **3NF Relational Architecture:** Normalized `Conference -> Division -> Team` data model with strict foreign key constraints.
- **Round-Robin Scheduling Engine:** Polygon rotation algorithm balancing home/away match distribution and preventing scheduling conflicts.
- **Granular REST API:** Query league hierarchy, filter divisional matchups, and retrieve team calendars.
- **100% Offline Capable:** Self-hosted Swagger UI documentation and local embedded SQLite storage with zero external runtime dependencies.

## Setup & Running

1. **Install dependencies:**
   ```bash
   uv sync