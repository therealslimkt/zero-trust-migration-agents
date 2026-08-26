import type { A2AEvent } from "../../control/contracts.generated.js";
import { ControlEventBus } from "./bus.js";
import { JsonlEventLedger } from "./ledger.js";

export class EventService {
  constructor(
    readonly bus: ControlEventBus,
    private readonly ledger: JsonlEventLedger,
    private readonly persist: (event: A2AEvent) => Promise<void>,
  ) {}

  async publish(event: A2AEvent): Promise<void> {
    await this.persist(event);
    await this.ledger.append(event);
    this.bus.publish(event);
  }
}

