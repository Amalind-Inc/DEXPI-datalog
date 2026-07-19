#!/bin/sh
set -eu

mkdir -p /logs/verifier
cp /workspace/structured_answer.json /logs/verifier/structured_answer.json 2>/dev/null || true
cp /workspace/analysis.dl /logs/verifier/analysis.dl 2>/dev/null || true
if python3 /tests/test_outputs.py; then
  
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
