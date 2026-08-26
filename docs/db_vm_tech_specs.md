# Legacy Database VM Specifications

## Overview
This document outlines the technical specifications for the virtual machines hosting our simulated legacy databases. These instances serve as the target data sources for the zero-trust migration agents.

## Virtual Machines (Compute Engine)
Both instances are provisioned on Google Cloud Platform to optimize for minimal cost and sustainable long-term running.

* **Zone**: `us-central1-a`
* **Machine Type**: `e2-micro` (Shared-core, 2 vCPU, 1 GB memory, Google Cloud Free Tier eligible)
* **OS Image**: Debian 12 (Bookworm)
* **Network Tags**: `legacy-db`

### 1. Pervasive SQL / Btrieve Simulator
* **Hostname**: `legacy-btrieve-db`
* **Data File**: `~/dummy_accpac.mkd`
* **Data Characteristics**:
  * Simulates a page-based MicroKernel Database Engine (MKDE) file.
  * Contains a 4096-byte File Control Block (FCB) and binary C-struct data pages.
  * Represents unstructured/schema-less raw navigational database outputs commonly found in legacy Sage Accpac/MAS 90 systems.

### 2. JD Edwards (AS/400) Simulator
* **Hostname**: `legacy-jde-db`
* **Data File**: `~/F0101_address_book.bin`
* **Data Characteristics**:
  * Simulates an authentic AS/400 EBCDIC binary dump.
  * Contains EBCDIC encoded strings and COBOL COMP-3 packed decimals.
  * Includes mock PII (Personally Identifiable Information) such as Tax IDs/SSNs which requires zero-trust handling and redaction.

## Security & Networking (Zero Trust Foundation)
* **IAP SSH Access**: Direct SSH access via port 22 from the public internet is disabled. Inbound SSH is only permitted via Google Cloud Identity-Aware Proxy (IAP) from the IP range `35.235.240.0/20`.
* **Zero Trust IAM & Networking**: *(Currently being provisioned)*
  * External IPs will be removed from the VMs.
  * Dedicated least-privilege IAM Service Accounts will be attached to each VM.
