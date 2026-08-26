import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import type { A2AEvent } from "../../../control/contracts.generated.js";
import { useUiStore } from "../model/uiStore.js";
import { queryKeys } from "./queries.js";

export function useEventStream(): void {
  const queryClient = useQueryClient();
  const streamPaused = useUiStore((state) => state.streamPaused);

  useEffect(() => {
    if (streamPaused) return undefined;
    const stream = new EventSource("/api/v1/events/stream");

    stream.onmessage = (message) => {
      const event = JSON.parse(message.data) as A2AEvent;
      queryClient.setQueryData<A2AEvent[]>(queryKeys.events, (current = []) => [...current.slice(-249), event]);
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks });
      if (event.type.startsWith("provider.")) void queryClient.invalidateQueries({ queryKey: queryKeys.providers });
      if (event.type.startsWith("approval.")) void queryClient.invalidateQueries({ queryKey: queryKeys.approvals });
      if (event.type.startsWith("feedback.") || event.type.startsWith("memory.")) void queryClient.invalidateQueries({ queryKey: queryKeys.feedback });
    };

    return () => stream.close();
  }, [queryClient, streamPaused]);
}

