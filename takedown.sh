#!/bin/bash
# End-of-day cleanup. Frees all resources.
set -e

echo "Killing port-forwards..."
pkill -f "kubectl port-forward" 2>/dev/null || true

echo "Deleting kind cluster 'vaultly'..."
kind delete cluster --name vaultly

echo "Done. Docker Desktop can now be stopped."  
