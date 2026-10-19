# Tunisia data inventory

Download date for every file below: **2026-10-06**. Checksums and byte sizes are also in `fraud_detection/data/metadata/tunisia/downloaded_files.json`. Raw PDFs, XML, CSV, and parquet extracts are kept on disk and are gitignored. HTML, Excel workbooks, JSON metadata, and the processed JSON context tables are in the tree.

Nothing in this inventory is a Tunisian card, transfer, or cash transaction with a fraud label.

## What was downloaded

| File | Bytes | Level | Fraud labels | ML training rows |
| --- | ---: | --- | --- | --- |
| `data/raw/tunisia/ctaf/ctaf_rapport_activite_2024_fr.pdf` | 2,054,773 | CASE_BASED | no | no |
| `data/raw/tunisia/ctaf/ctaf_rapport_activite_2023_fr.pdf` | 824,623 | CASE_BASED | no | no |
| `data/raw/tunisia/ctaf/ctaf_typologies_2020_2025_fr.pdf` | 883,966 | CASE_BASED | no | no |
| `data/raw/tunisia/bct/DCS.xls` | 53,341 | AGGREGATE | no | no |
| `data/raw/tunisia/bct/CBS.xls` | 41,992 | AGGREGATE | no | no |
| `data/raw/tunisia/bct/BOP6.xls` | 48,393 | AGGREGATE | no | no |
| `data/raw/tunisia/bct/ILV1.xls` | 32,544 | AGGREGATE | no | no |
| `data/raw/tunisia/bct/ILV2.xls` | 75,240 | AGGREGATE | no | no |
| `data/raw/tunisia/bct/MET.xls` | 28,794 | AGGREGATE | no | no |
| `data/raw/tunisia/bct/IIP6.xls` | 61,118 | AGGREGATE | no | no |
| `data/raw/tunisia/bct/EXD.xls` | 41,163 | AGGREGATE | no | no |
| `data/raw/tunisia/bct/gosdmx_catalog_fr.html` | catalog page | AGGREGATE index | no | no |
| `data/raw/tunisia/payments/bct_pl202020_nombre_transactions.html` | 141,356 | AGGREGATE | no | no |
| `data/raw/tunisia/payments/bct_pl202010_volume_transactions.html` | 141,352 | AGGREGATE | no | no |
| `data/raw/tunisia/findex/wb_FX.OWN.*.json` | about 20 KB each | AGGREGATE from a survey | no | no |
| `data/raw/tunisia/enterprise_survey/wb_enterprise_survey_tunisia_2024.html` | 29 KB | portal shell, not the survey | no | no |
| `data/raw/tunisia/entities/rne_public.html` | 23,054 | site shell, not a register | no | no |

Companion SDMX XML files sit next to each Excel workbook. They are the same series in XML.

### CTAF

- 2024 French activity report: https://www.ctaf.gov.tn/data/uploads/pdf/68ed20ef1333f7.67071673.pdf
  - A second homepage link, `68ed1fe9a608d8.67857585.pdf`, returned the same bytes (SHA-256 `e8526bc3ea2e072c9522e9984d54daf2e3909c3297b082c40a2745dca7445e77`). One copy was kept.
  - 45 pages. Chapter III contains **seven** typology cases from reports sent to the prosecutor in 2024. The report also says the CTAF received 1,236 suspicious-activity reports and treated 452. Those counts are annual totals, not rows.
- 2023 French activity report: https://www.ctaf.gov.tn/data/uploads/pdf/66aa02b723c2e3.57823642.pdf
  - 42 pages. Five typology titles are in the table of contents. They were not turned into training rows.
- 2020–2025 bulletin: https://www.ctaf.gov.tn/data/uploads/pdf/6a26c622d81294.49709769.pdf
  - 23 pages. Declarative statistics, one described international-money-order case, and warning signs. Age, gender, and nationality charts in that bulletin are not used as rules.

Structured extract: `fraud_detection/data/processed/tunisia/ctaf_typologies.json`. Each pattern has `confidence = documented_case`.

No separate open-data license is printed on the CTAF download page. The reports are public official publications. They are legal to read and to cite. They are not a legal or technical training set of transactions.

### Banque Centrale de Tunisie

Catalog: https://gosdmx.bct.gov.tn/gosdmx/pnrd?lang=FR

| Series | What it is | Span | Series with numbers |
| --- | --- | --- | ---: |
| DCS | Banking-sector analytical accounts (M1, M2, M3, foreign assets, domestic claims) | 2001-12 to 2026-08, monthly | 7 |
| CBS | Central-bank analytical accounts | 2001-12 to 2026-08, monthly | 5 |
| BOP6 | Balance of payments | 2018 to 2025, annual | 23 |
| ILV1 | Official reserve assets | 2015-01 to 2026-08, monthly | 6 |
| ILV2 | Reserve template | 2015-01 to 2026-08, monthly | 19 |
| MET | Goods exports and imports | 2014-01 to 2026-07, monthly | 2 |
| IIP6 | International investment position | 2019 to 2025, annual | 88 |
| EXD | External debt position (workbook domain code IIP5) | 2018-Q1 to 2026-Q2, quarterly | 50 |

Latest DCS M3 cell: 155,243 (millions of dinars, 2026-08). Latest MET export and import cells: 5,993.3 and 8,381.4 (millions of dinars, 2026-07).

ILV1's official-reserve cell for 2026-08 is 28,013,777.26. ILV2's matching line for the same month is 28,013.78, and both workbooks say the scale is millions. Those two published numbers are not the same unit in practice. They are stored as published. They are not converted into a fraud feature.

The catalog lists an exchange-rate dataset with no Excel or SDMX download link. No TND quote file was saved. `change_m.jsp?params=PL140010` and `PL140040` were saved and are FX-market turnover pages, not exchange rates.

Payment statistics, the only window that actually contains numbers:

- Counts, thousands: https://www.bct.gov.tn/bct/siteprod/tableau_statistique.jsp?params=PL202020
- Values, millions of dinars: https://www.bct.gov.tn/bct/siteprod/tableau_statistique.jsp?params=PL202010

The on-page table is April–September 2025 for cheques, bills, transfers, direct debits, bank cards, electronic payments, and the total. Cards and electronic payments are blank for July–September 2025 in that saved page. The historical `stat_mens_csv.jsp` export for 2003–2025 returned date labels and no indicator values, with and without a session cookie. Those empty exports were kept. They were not filled in.

Example published cells, not transactions:

- April 2025 bank cards: 13,774.9 thousand transactions and 2,429.2 million TND. Derived average 176.35 TND.
- April 2025 transfers: 3,081.2 thousand transactions and 6,432.7 million TND. Derived average 2,087.73 TND.

`tunisia_payment_market_baseline.json` has 42 aggregate rows (7 instruments × 6 months). The parquet twin has the same rows. There is no ATM/DAB/GAB or TPE-only column in this table.

### Global Findex

Indicator API, Tunisia only. `lastupdated` in the payload is 2026-07-13. Non-null account-ownership (`FX.OWN.TOTL.ZS`) values: 2014 = 27.43, 2017 = 36.91, 2021 = 36.85, 2024 = 37.84 percent of the population ages 15+. Female, young-adult, secondary-education, and older-adult series were saved the same way. 24 non-null aggregate points are in `tunisia_findex_context.json`.

These are survey estimates published as country indicators. Respondents were not turned into payments.

Microdata catalogs found, files not downloaded:

- Tunisia Global Findex 2021, public catalog id 4718.
- Tunisia Global Findex 2024/2025 study, catalog id 7989, access mode `direct`.

### Not obtained

Recorded in `fraud_detection/data/metadata/tunisia/not_obtained.json`.

- `catalog.data.gov.tn` company register: TLS chain does not verify. Verification was not disabled.
- RNE public site: application shell only. No company extract.
- Enterprise Survey Tunisia 2024 (`TUN_2024_WBES_v01_M`, catalog 6706): remote access. The explore page did not contain firm rows.
- Monétique Tunisie: `www.smt.tn` timed out, `www.monetique.tn` did not resolve, `www.smt.com.tn` failed hostname verification.

## Classification

| Question | Answer |
| --- | --- |
| Transaction-level payments | none |
| Entity-level register | not obtained |
| Aggregate | BCT SDMX series and BCT payment tables; Findex indicators |
| Survey microdata | not obtained. Findex indicators are aggregates computed from the survey |
| Case-based | three CTAF PDFs |
| Real fraud or AML labels | none |
| Usable as supervised fraud-training rows | none |
| Usable as context | BCT series, the six-month payment window, Findex indicators, CTAF patterns as rules |
