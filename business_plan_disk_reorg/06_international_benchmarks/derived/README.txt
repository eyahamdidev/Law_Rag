benchmarks.sqlite is built from the Damodaran files in this pack by tools/build_benchmarks.py (bp_service).
Tables: margins (96 industries), wacc (96), country_tax (248 rows), country_risk (179).
US/global data: always label the region. Tunisia has two tax rows (15% and 25%) in the Damodaran file;
the Tunisian IS code (02_tn_tax_legal) says 20% general rate: use the code.
