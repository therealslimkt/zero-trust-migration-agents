import { EventEmitter } from "node:events";

import type { A2AEvent } from "../../control/contracts.generated.js";

export type EventListener = (event: A2AEvent) => void;

export class ControlEventBus {
  readonly #emitter = new EventEmitter();

  publish(event: A2AEvent): void {
    this.#emitter.emit("event", event);
  }

  subscribe(listener: EventListener): () => void {
    this.#emitter.on("event", listener);
    return () => this.#emitter.off("event", listener);
  }
}

