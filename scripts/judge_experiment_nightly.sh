#!/bin/zsh
# Per-judge reliability experiment (python -m access.bench judges), run overnight 22:00-07:00 so it competes
# with the critic for free-tier quota only at night. Resumes each night until all votes are in (max 3 nights).
cd "$(dirname "$0")/.."
LOG=data/agents/experiment.log
complete() { python3 -c "
import json; from access.bench import JUDGE_RAW, _judge_items; from access.bench import EXPERIMENT_JUDGES
need = len(_judge_items()) * len(EXPERIMENT_JUDGES)
have = len({(r['key'], r['judge']) for r in map(json.loads, open(JUDGE_RAW))}) if JUDGE_RAW.exists() else 0
print(have, '/', need); raise SystemExit(have < need)"; }
for night in 1 2 3; do
  now=$(date +%s); start=$(date -j -f "%H:%M:%S" "22:00:00" +%s)
  if [ $(date +%H) -lt 7 ]; then start=$now; elif [ $now -ge $start ]; then start=$now; fi
  echo "$(date '+%F %T') night $night: waiting until $(date -r $start '+%F %T')" >> $LOG
  # We poll the wall clock because one long `sleep` does not advance while the Mac is asleep.
  while [ $(date +%s) -lt $start ]; do sleep 300; done
  echo "$(date '+%F %T') night $night: starting" >> $LOG
  python3 -m access.bench judges 07:00 >> $LOG 2>&1
  if complete >> $LOG 2>&1; then echo "$(date '+%F %T') complete" >> $LOG; exit 0; fi
  echo "$(date '+%F %T') night $night: incomplete, resuming next night" >> $LOG
  while [ $(date +%H) -lt 8 ]; do sleep 300; done   # past 07:00: the next loop computes tonight's 22:00
done
