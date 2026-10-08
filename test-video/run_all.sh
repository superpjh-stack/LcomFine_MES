#!/bin/sh
# 시연 영상 4편을 한 사본 DB 로 차례로 녹화한다.
#   sh test-video/run_all.sh [--dry] [--only NN] [--from NN] [--keep]
#   --dry   음성·합성 없이 흐름과 검증만 점검      --only NN  그 편만
#   --from NN  그 편부터 — 앞 편이 끝난 시점의 DB 덤프(after-(NN-1).dump)를 되살려 이어 간다
#   --keep  끝나도 사본 DB 를 지우지 않는다
# 개발 DB(lcomfine_db)는 읽기만 한다 — pg_dump 로 사본(lcomfine_video)을 만들어 녹화하고 끝에 지운다.
# 편이 끝날 때마다 사본을 덤프해 두므로(after-NN.dump) 한 편만 고쳐 다시 돌릴 수 있다.
set -e
cd "$(dirname "$0")/.."
REC="$HOME/.claude/skills/test_video_maker/bin/record.mjs"
WORK="${VIDEO_WORK:-outputs/video/_work}"
DRY=""; ONLY=""; FROM=""; KEEP=""
prev=""
for a in "$@"; do
  case "$prev" in --only) ONLY="$a";; --from) FROM="$a";; esac
  case "$a" in --dry) DRY="--dry";; --keep) KEEP=1;; esac
  prev="$a"
done
export VIDEO_DB="${VIDEO_DB:-lcomfine_video}" VIDEO_STATE_DIR="$WORK"
mkdir -p "$WORK"
START="${FROM:-$ONLY}"
if [ -z "$START" ] || [ "$START" = "01" ]; then
  rm -f "$WORK/state.json"
  echo "사본 DB $VIDEO_DB 만드는 중 (pg_dump lcomfine_db)…"
  node -e "import('./test-video/lib/mes.mjs').then(m => m.makeDbCopy())"
else
  PREV=$(printf '%02d' $((10#$START - 1)))
  DUMP="$WORK/after-$PREV.dump"
  [ -f "$DUMP" ] || { echo "$DUMP 이 없다 — 앞 편($PREV)까지 먼저 돌린다"; exit 1; }
  echo "사본 DB $VIDEO_DB 를 $DUMP(편 $PREV 끝난 시점)로 되살린다"
  node -e "import('./test-video/lib/mes.mjs').then(m => m.dropDbCopy())"
  createdb -h /tmp "$VIDEO_DB"
  pg_restore -h /tmp -d "$VIDEO_DB" --no-owner "$DUMP"
  cp "$WORK/state-after-$PREV.json" "$WORK/state.json"
fi
export VIDEO_DB_READY=1
if [ -z "$KEEP" ]; then
  trap 'node -e "import(\"./test-video/lib/mes.mjs\").then(m => m.dropDbCopy())"; echo "사본 DB 지움"' EXIT
else
  echo "(--keep: 끝나도 사본 DB 를 남긴다 — 지우려면 dropdb -h /tmp $VIDEO_DB)"
fi
for s in test-video/0*.scenario.mjs; do
  n=$(basename "$s" | cut -c1-2)
  if [ -n "$ONLY" ] && [ "$n" != "$ONLY" ]; then continue; fi
  if [ -n "$FROM" ] && [ "$n" -lt "$FROM" ]; then continue; fi
  echo; echo "━━━ $s $DRY"
  node "$REC" "$s" $DRY --work "$WORK/$(basename "$s" .scenario.mjs)"
  pg_dump -h /tmp -Fc "$VIDEO_DB" -f "$WORK/after-$n.dump"
  cp "$WORK/state.json" "$WORK/state-after-$n.json" 2>/dev/null || true
done
