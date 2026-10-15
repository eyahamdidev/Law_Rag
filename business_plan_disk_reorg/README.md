# bp dataset pack (business plan module)

Real source files from your corpus zip, sorted by topic, plus a script that downloads the public files I could not fetch.

## folders
| folder | what is inside |
| --- | --- |
| `01_plan_structures` | SBA guide, Business Model Canvas page, Lean Canvas page (BFPME and GIZ models are in your repo: copy them here) |
| `02_tn_tax_legal` | Tunisian IS and IRPP code (edition up to LF 2024). Later: LF 2026, VAT code |
| `03_tn_accounting` | Law 96-112, NCT 42, NC 01 to NC 38, conceptual framework (42 sources) |
| `04_tn_bct_ins_macro` | BCT publications (annual report, conjuncture, banking and FX regulation, methodology notes) and INS yearbook 2022 |
| `05_tn_guides` | guide for expats: legal forms, procedures, support |
| `06_international_benchmarks/damodaran` | `1_sector_margins`, `2_cost_of_capital_by_region`, `3_country_risk_and_tax`, plus `derived/benchmarks.sqlite` |
| `07_firm_data/wbes` | World Bank Enterprise Surveys indicator description (microdata needs a login: see manifest) |
| `_empty_captures` | 9 web pages saved with menus only (BCT rates and FX, INS yearbook page, etc.): NOT data, do not index |
| `_to_download` | `download_manifest.csv` and `download.py` for everything that is still missing |
| `catalog` | `bp_datasets_catalog.csv` (40 datasets ranked), `bp_tailoring_map.csv`, `file_index.csv` (every file here with source URL and hash) |

Folders 08 to 12 appear after you run the download script.

## how to use
1. `cd _to_download && python download.py --csv` (needs internet; standard library only). Check `download_log.csv`.
2. Do the manual checklist the script prints (BCT tables, INS, official gazette texts, CNSS, VAT code, WBES microdata).
3. For RAG: index files with `use = rag` in `catalog/file_index.csv`. Skip any folder starting with `_`.
4. For numbers: use the `tables` rows (Damodaran) through `derived/benchmarks.sqlite`, not through embeddings.

## cautions
* Damodaran data is US/global. Always label the region. Tunisia's two tax rows (15% and 25%) conflict with the IS code (20% general rate): use the code.
* `02_tn_tax_legal` here stops at the 2024 finance law. Rates and contributions for 2026 come from secondary sources until you get the official texts.
* Files keep their original names (source id first) and each has a `.meta.json` with the source URL, date and hash: cite from those.
* These are third-party public documents: respect each publisher's terms of use.
