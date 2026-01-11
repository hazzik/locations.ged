#!/bin/bash

# Script to get the next available ID for locations.ged data files
# Scans all YAML files in data/ for IDs like L<number>, finds the highest, and returns L<next>

max_id=$(grep -r "^- id: L" data/ | sed 's/.*id: L//' | sort -n | tail -1)

if [ -z "$max_id" ]; then
    echo "No IDs found, starting with L1"
    echo "L1"
else
    next_id=$((max_id + 1))
    echo "L$next_id"
fi