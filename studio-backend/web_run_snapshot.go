package main

// WebRunSnapshot reads the run and its ordered events while holding the
// control-plane store lock once, preventing a browser response from combining
// state and evidence from different durable revisions.
func (s *cpStore) WebRunSnapshot(runID string) (*ControlPlaneRun, []*ControlPlaneEvent, error) {
	if !cpRunIDRe.MatchString(runID) {
		return nil, nil, cpErrNotFound
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	run := cpFindRun(s.snap, runID)
	if run == nil {
		return nil, nil, cpErrNotFound
	}
	events := make([]*ControlPlaneEvent, 0)
	for _, event := range s.snap.Events {
		if event.RunID == runID {
			events = append(events, event.clone())
		}
	}
	return run.clone(), events, nil
}
