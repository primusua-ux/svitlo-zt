#!/usr/bin/env bash
# Правило пропуску деплою на Netlify (netlify.toml, [build] ignore).
# Код 0 = пропустити деплой, код 1 = деплоїти.
#
# Навіщо: безкоштовний план Netlify має 300 кредитів на місяць на весь акаунт
# (спільно для svitlo-zt і svitlo-od), а кожен продакшн-деплой коштує 15.
# Тому зміни накопичуються і виходять на Netlify не частіше, ніж раз на PAGE_H годин.
#
# Як це працює:
#   1. Коміт з міткою [netlify] у повідомленні деплоїться одразу.
#   2. Зміни сторінки (PAGE) деплояться, якщо попередній деплой старший за PAGE_H годин.
#   3. Зміни лише даних (DATA) деплояться, якщо попередній деплой старший за DATA_H годин.
#   4. Усе інше (графік, службові файли, скрипти) деплой не запускає ніколи.
# Відкладені зміни підхоплює наступний коміт після спливу інтервалу.

# Після переїзду на svitloe.net Netlify публікує лише сторінку «Сайт переїхав» (moved/),
# тож деплоїться тільки вона, одразу після зміни. Сайт і дані на Netlify більше не потрапляють.
PAGE="moved netlify.toml scripts/netlify-ignore.sh"
DATA=""
PAGE_H=0      # сторінка переїзду: одразу після зміни
DATA_H=336

HEAD_REF="${COMMIT_REF:-HEAD}"
BASE="${CACHED_COMMIT_REF:-}"

skip()   { echo "netlify-ignore: пропуск, $1"; exit 0; }
deploy() { echo "netlify-ignore: деплой, $1"; exit 1; }

case "$(git log -1 --format=%B "$HEAD_REF" 2>/dev/null)" in
  *"[netlify]"*) deploy "мітка [netlify] у повідомленні коміту" ;;
esac

# Попередній деплой невідомий (перша збірка або немає історії): дивимось лише на цей коміт.
# Коміти ботів з даними не деплоїмо за жодних умов, щоб збій не спалив кредити.
if [ -z "$BASE" ] || ! git cat-file -e "$BASE^{commit}" 2>/dev/null; then
  case "$(git log -1 --format=%an "$HEAD_REF" 2>/dev/null)" in
    *-bot) skip "попередній деплой невідомий, коміт бота" ;;
  esac
  if git cat-file -e "$HEAD_REF~1^{commit}" 2>/dev/null && git diff --quiet "$HEAD_REF~1" "$HEAD_REF" -- $PAGE; then
    skip "попередній деплой невідомий, коміт не змінює сторінку"
  fi
  deploy "попередній деплой невідомий, коміт змінює сторінку"
fi

base_ts=$(git log -1 --format=%ct "$BASE" 2>/dev/null)
[ -n "$base_ts" ] || skip "не вдалося визначити час попереднього деплою"
age_h=$(( ( $(date +%s) - base_ts ) / 3600 ))

if ! git diff --quiet "$BASE" "$HEAD_REF" -- $PAGE; then
  [ "$age_h" -ge "$PAGE_H" ] && deploy "сторінка змінилась, попередній деплой $age_h год тому"
  skip "сторінка змінилась, але попередній деплой лише $age_h год тому (поріг $PAGE_H)"
fi
if [ -n "$DATA" ] && ! git diff --quiet "$BASE" "$HEAD_REF" -- $DATA; then
  [ "$age_h" -ge "$DATA_H" ] && deploy "база адрес змінилась, попередній деплой $age_h год тому"
  skip "змінилась лише база адрес, попередній деплой $age_h год тому (поріг $DATA_H)"
fi
skip "сторінка і база адрес без змін"
