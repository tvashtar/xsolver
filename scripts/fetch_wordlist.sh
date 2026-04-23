#!/usr/bin/env bash
# Fetch UKACD wordlist into data/ukacd.txt.
set -euo pipefail

OUT="data/ukacd.txt"
if [[ -s "$OUT" ]]; then
  echo "Wordlist already present at $OUT ($(wc -l < "$OUT") lines)"
  exit 0
fi

mkdir -p data

CANDIDATES=(
  "https://www.crossword-dictionary.com/ukacd18.txt"
  "https://raw.githubusercontent.com/jmlewis/valett/master/scrabble/ukacd.txt"
  "https://www.bryght.com/cryptic/UKACD18plus.txt"
)

for url in "${CANDIDATES[@]}"; do
  echo "Trying $url..."
  if curl -fsSL --max-time 30 "$url" -o "$OUT.tmp"; then
    # Basic sanity: non-empty and reasonable size
    if [[ $(wc -l < "$OUT.tmp") -gt 50000 ]]; then
      mv "$OUT.tmp" "$OUT"
      echo "Fetched $(wc -l < "$OUT") entries into $OUT"
      exit 0
    fi
    rm -f "$OUT.tmp"
  fi
done

echo "ERROR: could not fetch UKACD. Please place a wordlist at $OUT manually." >&2
echo "Fallback: cat /usr/share/dict/words > $OUT  (less coverage but works)" >&2
exit 1
