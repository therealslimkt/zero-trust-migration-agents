#!/bin/bash

# Name of the tmux session
SESSION="zero-trust-demo"

# Start a new tmux session in the background
tmux new-session -d -s $SESSION

# Pane 1 (left): Database Stream
tmux send-keys -t $SESSION:0 "docker logs -f database_stream" C-m

# Split vertically twice to create 3 columns
tmux split-window -h -t $SESSION:0
tmux split-window -h -t $SESSION:0

# Pane 2 (middle): Agent Translation (backend)
tmux send-keys -t $SESSION:0.1 "docker logs -f zero_trust_backend" C-m

# Pane 3 (right): BigQuery Output
tmux send-keys -t $SESSION:0.2 "docker logs -f bigquery_output" C-m

# Evenly distribute panes
tmux select-layout -t $SESSION:0 even-horizontal

# Attach to the session
tmux attach-session -t $SESSION
