# P3 aid and grants report

## Scope and safety boundary

The aid module separates eligibility from language generation. A founder
profile is validated as `AidProfile`, then every catalog entry is evaluated by
pure Python predicates in the order stage, sector, size/investment, need, and
specific conditions. The result contains one `RuleTraceEntry` for every
predicate, including passing predicates. This makes an exclusion inspectable:
the response identifies the exact criterion and the source document attached to
the catalog entry. An LLM may extract facts from free text and draft a
grounded explanation, but it cannot add, remove, or override an eligible
program.

This boundary is important for Tunisian financial and tax guidance. A fluent
classification model can invent a funding ceiling, treat a commercial
activity as an industrial activity, or turn a general Startup Act statement
into an individual entitlement. Those errors are difficult to detect in a
plain natural-language answer. The deterministic trace instead gives the
orchestrator and the founder a reproducible decision record. Unknown intake
fields are returned as clarification signals; they are not filled with
defaults.

## Catalog and provenance

The catalog is versioned YAML. Each program has an identifier, provider,
instrument type, supported stages and sectors, limits, conditions, official
form link, required documents, and a source file/page. Source paths are
validated against the checked-in corpus. The catalog intentionally keeps
unknown conditions unconstrained rather than guessing. A document checklist is
returned only for programs that pass all predicates.

The current catalog covers BFPME creation and extension, BTS/FONAPRAM,
SOTUGAR Dhamen Express, Startup Act, AIR/startup programme material, regional
investment premiums, investment tax incentives, GIZ business-plan support, and
green-transition material. The source inventory should be reviewed whenever
new corpus files are ingested; a catalog entry must not be promoted from
unverified material to a legal rule without a page-level source.

The main application now exposes this workflow in the **Aid and financing**
tab. It accepts structured fields and founder free text, then renders eligible
and excluded programmes, source pages, required documents, official links,
legal handoffs, and the complete rule trace.

## Prompt versions

`aid.extract_profile` and `aid.explain_match` each have v1 and v2 entries in
the prompt library. Version 2 adds canonical sector constraints, missing-field
clarification, no-number-invention rules, and an explicit prohibition against
recommending excluded programmes. The prompt files record the observed
failure modes and the safeguards added to address them.

## Operational plan

The standalone service is containerized on port 8103 and exposes `/health`,
`/v1/meta`, and `/v1/run`. `/v1/run` returns the frozen response shape with
status, answer, citations, signals, artifacts, handoff, trace, and latency.
Legal statute questions are handed to the law module before aid matching. The
default service path is deterministic and therefore remains within the
five-second budget; provider-backed explanation is an optional separate
concern rather than a dependency of eligibility.

The main UI includes an English/French/Arabic interface switch. Arabic mode
sets right-to-left document direction, while founder questions can be entered
in all three supported languages. The extractor normalizes Arabic governorates
and common green-technology terms before deterministic matching.

## Integration changes (merge into integration/agents, 2026-10-18)

Each catalogue figure was checked against the page it cites, and against the rest of that document.

- **Quarantined** under a new `unverified` field: the BFPME creation and extension ranges (100,000 to 15,000,000 TND), the SOTUGAR range (100,000 to 5,000,000 TND), the BTS/FONAPRAM cap (150,000 TND) and the AIR headcount (10). None of these appears in the cited document. The rules engine ignores `unverified` (the criterion stays unconstrained), and answers show these figures as "to confirm with the provider". To restore a figure, give a source_file and page that state it.
- **Re-cited**: the Startup Act limits are correct, but the cited page did not contain them. The 100 employees is in Décret 2018-840 art. 3 (law corpus, page 24); the 8 years is in Loi 2018-20 art. 3.
- **Regional zones**: Annexe 2 of décret 2017-389 (pages 16-19) lists 18 governorates, not 14; Tozeur, Bizerte, Sfax and Sousse were missing. Within a governorate, only the listed delegations qualify, and answers say so. The names now match the extractor's (`sidi bouzid`, not `sidi_bouzid`), so Sidi Bouzid profiles match again.
- **Citations**: a matched programme cites the indexed chunk of its source page (that document's real doc_id and text). Previously it cited catalogue text written as a quote and marked supported. Required-document lists are labelled indicative, because most do not appear on the cited page.
- **Chat agent**: eligibility answers come from the match itself, with no LLM explanation. General grants questions go to the RAG agent. `aid.extract_profile` is used in the chat. `aid.explain_match` is still used by `/api/aid/match`.
