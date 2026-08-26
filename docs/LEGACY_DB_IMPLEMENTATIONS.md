# Legacy Database Mock Implementations: Architecture & Challenges

To demonstrate the power of the Zero-Trust Migration Agents, we constructed three distinct containerized database mocks. These simulate the most notoriously difficult legacy backend architectures. 

By running these natively and parsing their proprietary formats with AI, we prove that our migration fleet can completely bypass expensive, licensed application layers (like SAP NetWeaver or JD Edwards EnterpriseOne).

## 1. JD Edwards on AS/400 (IBM Power Systems)
**Container Name:** `as400-mock` (PostgreSQL base)
**Target File Format:** EBCDIC & COMP-3 (Packed Decimal)

### The Unique Challenge
JD Edwards (JDE) running on an AS/400 uses the EBCDIC character encoding, which appears as pure gibberish to modern ASCII/UTF-8 systems. Furthermore, JDE stores dates in a proprietary "Julian Date" format (CYYDDD, where C is century, YY is year, DDD is day of year). Numerical values are often stored as COMP-3 packed decimals to save disk space on expensive 1980s mainframe drives.

### Implementation & Image Creation
While true IBM Power Systems AS/400 images require specialized LPAR hosting on Google Cloud, we created a lightweight mock using a PostgreSQL base image. We seeded it using a custom YAML file (`seed_data.yml`) with authentic JDE column headers (e.g., `ABAN8` for Address Book Number, `ABUPMJ` for the Julian date). The AI Agent is tasked with recognizing these column heuristics, interpreting the Julian date (e.g., `123165` -> `June 14, 2023`), and generating Apache Beam code to convert the EBCDIC stream into UTF-8 JSON.

## 2. SAP 7.9 on MaxDB
**Container Name:** `maxdb-mock` (MySQL base)
**Target File Format:** Clustered Tables / Proprietary B-Tree

### The Unique Challenge
SAP's application layer aggressively obfuscates its underlying data structure. SAP MaxDB uses "Pool" or "Cluster" tables where multiple logical tables are physically compressed into a single binary blob (e.g., the `KNA1` Customer Master table). Extracting this data usually requires buying expensive SAP middleware licenses or using OData APIs which throttle throughput.

### Implementation & Image Creation
We simulated the MaxDB environment using a MySQL 8.0 base image. The seed data mimics the clustered output of SAP's `KNA1` table. Our AI Researcher Agent is given the objective to identify the SAP table structure and write a Python pipeline that reads the raw clustered blobs and normalizes them into relational, structured data in Google BigQuery, completely circumventing the SAP NetWeaver application server.

## 3. Accpac (Sage 300) on Btrieve (Pervasive SQL)
**Container Name:** `btrieve-mock` (Alpine Linux base)
**Target File Format:** `.BTR` Pages & `DDF` Dictionaries

### The Unique Challenge
Before MS SQL Server became standard, accounting software like Accpac ran on Btrieve—a navigational database (not relational) that stores data in raw `.BTR` files. Without the Data Definition Files (`.DDF`), a `.BTR` file is just a stream of unformatted bytes with no schema. Extracting historical financial data when a company loses its Accpac application server is historically a forensic nightmare.

### Implementation & Image Creation
We created an ultra-lightweight Alpine Linux container to simply host the raw binary `.BTR` files. The `seed_data.yml` injects a raw hex dump (`00 01 00 00 41 52 43...`) representing an Accounts Receivable Customer (`ARCUS.BTR`) page. The AI fleet uses its Reverse-Engineer agent to analyze the hex signature, deduce the record length, and write a custom parser that reads the bytes directly from the block storage, saving companies hundreds of thousands of dollars in forensic recovery fees.
