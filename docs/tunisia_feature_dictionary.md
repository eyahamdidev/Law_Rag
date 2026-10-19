# Tunisia feature dictionary

A feature is listed as used only when a downloaded source supports it. Simulator columns and the dataset name are not features. Nothing here was added to `FEATURE_NAMES`, so the global LightGBM and Isolation Forest artifacts were not invalidated.

| Feature | Status | Provenance | How it is used |
| --- | --- | --- | --- |
| `amount_tnd` | used as the existing `amount` when currency is TND | payment field | global model and rules already see `amount`. No new column. |
| `log_amount_tnd` | not added | would be a transform of `amount` | not required for the CTAF rules |
| `hour`, `day_of_week`, `weekend`, `night` | already in the global portable model | timestamp | unchanged. The night rule still does not fire when the timestamp was missing. |
| `holiday` | not added | no official holiday calendar was downloaded | a holiday flag would be invented |
| `domestic` / `cross_border` | used | `country_from` and `country_to` | routing and CTAF rules. Country alone is not a fraud score. |
| `destination_country` | used only inside a cross-border pattern | `country_to` | not a model feature |
| `new_beneficiary` | existing `new_counterparty` rule | sender history | unchanged. Not Tunisia-specific. |
| `beneficiary_frequency` | partial | ledger counts inside CTAF rules | money-order and fan-in rules count distinct parties |
| `amount_vs_customer_median` | existing global feature | customer history | not refit |
| `amount_percentile_customer` | existing global feature | customer history | not refit |
| `amount_percentile_population` | context only | BCT PL202010 / PL202020, April–September 2025 | `amount / published channel average` when the channel maps. Aggregate. Does not change `tunisia_score`. |
| `velocity_1h`, `velocity_24h`, `velocity_7d` | existing global features | ledger | not refit |
| `counterparties_24h`, `counterparties_7d` | partial | ledger, inside specific CTAF rules | 30-day and 120-day windows used by the documented patterns |
| `beneficiary_age` | not added | no register file | RNE was not obtained |
| `account_age` | only if the caller sends `company_age_days` or entity `registered_on` | caller payload, not a national register | older Tunisia rules already read it |
| `time_since_previous_transaction` | existing behavior | ledger | not a new Tunisia column |
| `inbound_outbound_ratio` | used inside pass-through rules | ledger | CTAF-2024-T2 and T3 |
| `cash_withdrawal_frequency` | not a market feature | BCT table has no ATM row | a withdrawal is scored by global rules only |
| `ATM_velocity` | not added | no ATM series and no ATM hash in public data | |
| `TPE_velocity` | not added | card totals mix TPE and other card use | |
| `ecommerce_velocity` | not added | electronic-payment totals are monthly aggregates | |
| `mobile_payment_velocity` | not added | no separate mobile series in the saved BCT table | channel `mobile` is compared with the electronic-payment aggregate only as context |
| `foreign_currency` | used | `currency` and countries | cross-border detection |
| `unusual_currency` | existing global coverage flag | currency code | unknown currencies lower global coverage. They do not create a Tunisia score. |
| `business_registered` | not from a national file | caller-supplied `entities` only | a match means the request included the entity. It does not mean the RNE confirmed it. |
| `business_age` | same limitation | caller-supplied registration date | |
| `activity_mismatch` | CTAF-2024-T6 | declared activity on the entity or metadata, plus cash and a cross-border payment | fires only when all three are present. Activity text alone does not fire. |
| `geographic_anomaly` | not added as a new feature | existing `sudden_geography_change` | country change after a stable history. Not a Tunisia model. |
| `cross_border_behavior_change` | CTAF-2024-T3 | ledger | foreign in and foreign out within 24 hours. |

## Rule provenance

| Rule id | Pattern | Source |
| --- | --- | --- |
| `ctaf_zero_declared_revenue_fan_in` | CTAF-2024-T1 | 2024 report, pp. 20–22 |
| `ctaf_synchronized_cash_cheque` | CTAF-2024-T2 | 2024 report, pp. 22–23 |
| `ctaf_cross_border_pass_through` | CTAF-2024-T3 | 2024 report, pp. 23–25 |
| `ctaf_betting_money_orders` | CTAF-2024-T4 | 2024 report, pp. 25–26 |
| `ctaf_cyberfraud_money_orders` | CTAF-2024-T5 | 2024 report, pp. 26–27 |
| `ctaf_activity_mismatch_cash_cross_border` | CTAF-2024-T6 | 2024 report, pp. 27–28 |
| `ctaf_repeated_international_money_orders` | CTAF-2024-T7 | 2024 report, pp. 28–29, and the 2020–2025 bulletin, p. 16 |

Demographic charts in the bulletin (age, gender, nationality, residence) are not features.
