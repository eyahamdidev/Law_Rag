#!/usr/bin/env bash
# Download public fraud, sanctions, and Tunisia reference files.
# Skips a file that already exists and is non-trivial. Never invents data.
set -u
ROOT="/workspace/fraud_detection/data/raw"
mkdir -p \
  "$ROOT/ibm_aml" "$ROOT/tabformer" "$ROOT/saml_d" "$ROOT/paysim" \
  "$ROOT/banksim" "$ROOT/elliptic" "$ROOT/ulb" "$ROOT/handbook" \
  "$ROOT/tunisia" "$ROOT/sanctions" "$ROOT/ctaf" "$ROOT/ieee_cis"
LOG="/workspace/fraud_detection/data/download.log"
: > "$LOG"

fetch() {
  local url="$1"
  local dest="$2"
  local min_bytes="${3:-1000}"
  if [[ -f "$dest" ]] && [[ "$(stat -c%s "$dest")" -ge "$min_bytes" ]]; then
    echo "SKIP $dest" | tee -a "$LOG"
    return 0
  fi
  echo "GET $url" | tee -a "$LOG"
  if curl -L --fail --retry 4 --retry-delay 3 --connect-timeout 30 -o "${dest}.partial" "$url"; then
    local size
    size="$(stat -c%s "${dest}.partial" || echo 0)"
    if [[ "$size" -lt "$min_bytes" ]]; then
      echo "TOO_SMALL $dest bytes=$size" | tee -a "$LOG"
      rm -f "${dest}.partial"
      return 1
    fi
    mv "${dest}.partial" "$dest"
    echo "OK $dest bytes=$size" | tee -a "$LOG"
    return 0
  fi
  echo "FAIL $url" | tee -a "$LOG"
  rm -f "${dest}.partial"
  return 1
}

# Real public files. Mirrors are recorded in DATA_SOURCES.md with the upstream license.
fetch "https://storage.googleapis.com/download.tensorflow.org/data/creditcard.csv" \
  "$ROOT/ulb/creditcard.csv" 1000000 &
fetch "https://huggingface.co/datasets/bbfizp/AMLSim-HI-Small/resolve/main/HI-Small_Trans.csv?download=true" \
  "$ROOT/ibm_aml/HI-Small_Trans.csv" 1000000 &
fetch "https://huggingface.co/datasets/theman10/paysim/resolve/main/paysim.csv?download=true" \
  "$ROOT/paysim/paysim.csv" 1000000 &
fetch "https://huggingface.co/datasets/LordNR/AMLGraphX-SAML-D/resolve/main/SAML-D.zip?download=true" \
  "$ROOT/saml_d/SAML-D.zip" 1000000 &
fetch "https://huggingface.co/datasets/LordNR/AMLGraphX-Banksim/resolve/main/Banksim.zip?download=true" \
  "$ROOT/banksim/Banksim.zip" 100000 &
fetch "https://huggingface.co/datasets/SuodhanJ6/elliptic_txs_classes/resolve/main/elliptic_txs_classes.csv?download=true" \
  "$ROOT/elliptic/elliptic_txs_classes.csv" 10000 &
fetch "https://huggingface.co/datasets/SuodhanJ6/elliptic_txs_edgelist/resolve/main/elliptic_txs_edgelist.csv?download=true" \
  "$ROOT/elliptic/elliptic_txs_edgelist.csv" 10000 &
fetch "https://huggingface.co/datasets/SuodhanJ6/elliptic_txs_features/resolve/main/elliptic_txs_features.csv?download=true" \
  "$ROOT/elliptic/elliptic_txs_features.csv" 100000 &
fetch "https://www.treasury.gov/ofac/downloads/sdn.csv" \
  "$ROOT/sanctions/ofac_sdn.csv" 10000 &
fetch "https://www.treasury.gov/ofac/downloads/alt.csv" \
  "$ROOT/sanctions/ofac_alt.csv" 1000 &
fetch "https://scsanctions.un.org/resources/xml/en/consolidated.xml" \
  "$ROOT/sanctions/un_consolidated.xml" 10000 &
fetch "https://webgate.ec.europa.eu/fsd/fsf/public/files/csvFullSanctionsList/content?token=dG9rZW4tMjAxNw" \
  "$ROOT/sanctions/eu_sanctions.csv" 10000 &
wait
echo "DOWNLOAD_BATCH_DONE" | tee -a "$LOG"
ls -lh \
  "$ROOT/ulb" "$ROOT/ibm_aml" "$ROOT/paysim" "$ROOT/saml_d" "$ROOT/banksim" \
  "$ROOT/elliptic" "$ROOT/sanctions" | tee -a "$LOG"
