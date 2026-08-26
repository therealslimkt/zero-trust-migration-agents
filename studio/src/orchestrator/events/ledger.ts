import { appendFile, mkdir } from "node:fs/promises";
import { dirname } from "node:path";

import type { A2AEvent } from "../../control/contracts.generated.js";

export class JsonlEventLedger {
  constructor(private readonly ledgerPath: string) {}

  async append(event: A2AEvent): Promise<void> {
    await mkdir(dirname(this.ledgerPath), { recursive: true });
    await appendFile(this.ledgerPath, `${JSON.stringify(event)}\n`, { encoding: "utf8", mode: 0o600 });
  }
}

