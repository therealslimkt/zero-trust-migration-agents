import type { FastifyInstance } from "fastify";

import type { OrchestratorServices } from "../services.js";

export async function registerEventStream(app: FastifyInstance, services: OrchestratorServices): Promise<void> {
  app.get("/api/v1/events/stream", async (request, reply) => {
    reply.hijack();
    reply.raw.writeHead(200, {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    });
    reply.raw.write(": connected\n\n");

    const unsubscribe = services.events.bus.subscribe((event) => {
      reply.raw.write(`id: ${event.eventId}\n`);
      reply.raw.write(`data: ${JSON.stringify(event)}\n\n`);
    });
    const heartbeat = setInterval(() => reply.raw.write(": heartbeat\n\n"), 15_000);

    request.raw.on("close", () => {
      clearInterval(heartbeat);
      unsubscribe();
      reply.raw.end();
    });
  });
}
