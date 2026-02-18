#!/bin/sh
# Ensure the data directory exists and is writable
mkdir -p "${DATA_DIR:-/data}"

# Test that we can write to it
if ! touch "${DATA_DIR:-/data}/.write_test" 2>/dev/null; then
    echo "ERROR: Cannot write to ${DATA_DIR:-/data}. Check volume permissions."
    exit 1
fi
rm -f "${DATA_DIR:-/data}/.write_test"

echo "Data directory ${DATA_DIR:-/data} is ready."

# Start the application
exec python -m uvicorn backend.main:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8080}"
