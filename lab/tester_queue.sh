#!/bin/sh
# Sequential tester-role runs, 1 repetition each; resumes already finished runs.
for pair in "mimo26p:opencode-go/mimo-v2.6-pro" "glmf:opencode-go/glm-5.3-flash" "qwen37:opencode-go/qwen3.7-plus" "kimi27:opencode-go/kimi-k2.7-code" "longcat2:opencode-go/longcat-2.0"; do
  l=${pair%%:*}; m=${pair#*:}
  echo "=== $l $(date -u +%H:%M:%S)"
  python3 -I tester_lab.py run "$l" "$m" 1 >> "tester_$l.log" 2>&1
done
echo QUEUE_DONE
