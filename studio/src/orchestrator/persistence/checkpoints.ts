import { PostgresSaver } from "@langchain/langgraph-checkpoint-postgres";

export async function createCheckpointSaver(databaseUrl: string): Promise<PostgresSaver> {
  const checkpointer = PostgresSaver.fromConnString(databaseUrl);
  await checkpointer.setup();
  return checkpointer;
}

