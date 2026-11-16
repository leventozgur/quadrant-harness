#!/bin/zsh
cd "/Users/leventozgur/Desktop/Projects/quadrant-harness/lab"
( WORKER_TEMPLATE=/Users/leventozgur/Desktop/Projects/quadrant-harness/templates/worker-v1.md EFFORT='#low' python3 -I run_oc.py ds_v1low opencode-go/deepseek-v4.1-flash 1 > ab_ds_v1low.log 2>&1 ) &
( WORKER_TEMPLATE=/Users/leventozgur/Desktop/Projects/quadrant-harness/templates/worker.md python3 -I run_oc.py ds_v2def opencode-go/deepseek-v4.1-flash 1 > ab_ds_v2def.log 2>&1 ) &
( TESTER_TEMPLATE=/Users/leventozgur/Desktop/Projects/quadrant-harness/templates/tester-v1.md python3 -I tester_lab.py run qw_v1rules opencode-go/qwen3.7-plus 1 > ab_qw_v1rules.log 2>&1 ) &
( TESTER_TEMPLATE=/Users/leventozgur/Desktop/Projects/quadrant-harness/templates/tester.md python3 -I tester_lab.py run qw_v2high 'opencode-go/qwen3.7-plus#high' 1 > ab_qw_v2high.log 2>&1 ) &
wait
echo AB_DONE
