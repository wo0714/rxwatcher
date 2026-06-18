#!/bin/bash
# seed_clinics.sh — Create test clinic folders for local development
# Run once: ./seed_clinics.sh

BASE="data/ios_base"
mkdir -p "$BASE"

clinics=(
  "109 Dental"
  "All smiles Dentistry"
  "Beaumont Dental Care"
  "Chime Dental"
  "Clean smiles"
  "Delta Dental"
  "Diamond Dental"
  "Keswick Dental"
  "Sherwood Park - Salisbury"
  "Wittmeir Dental(82)"
)

for c in "${clinics[@]}"; do
  mkdir -p "$BASE/$c"
  echo "  ✓ $c"
done

mkdir -p "data/inbox"
echo ""
echo "Created ${#clinics[@]} clinic folders in $BASE/"
echo "Inbox folder: data/inbox/"