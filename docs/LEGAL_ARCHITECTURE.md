# Legal agent architecture

```mermaid
flowchart TD
  W[User-supplied WIPO PDFs and official corpus] --> M[Source metadata and version flags]
  M --> T[Text extraction]
  T --> O{Readable page?}
  O -- no --> OCR[Local Arabic / French / English OCR]
  OCR --> Q[Quality checks and unresolved-page report]
  O -- yes --> C[Structural chunks: article, page, source]
  Q -- readable --> C
  Q -- unreadable --> X[Exclude page from evidence]
  C --> B[BM25 keyword index]
  C --> V[Multilingual E5 embeddings in Qdrant]
  U[Question and founder profile] --> R[Law-only retrieval and topic filtering]
  B --> R
  V --> R
  R --> CR[One bounded corrective local search]
  CR --> L[LLM: claims and exact quotes]
  L --> E[Quote checks and evidence review]
  E --> A[Cited answer or original-evidence fallback]
  CR -- insufficient --> F[Abstain and provide official research links]
  CR -- optional IP fallback --> WEB[One allowlisted WIPO legislative page]
  WEB --> L
  D[User document] --> I[In-memory extraction / optional OCR]
  I --> S[Attributed field suggestions]
  S --> UC[User confirms contract fields]
  U --> UC
  UC --> VAL[Mandatory facts and equity validation]
  VAL -- incomplete --> ASK[Ask for missing information]
  VAL -- complete --> DT[Project-authored drafting structure]
  DT --> REF[Optional wording refinement and equivalence checks]
  REF --> OUT[Unsigned preview and editable DOCX]
```

Shared `/api/chat` routes to the existing `legal` agent. Structured `legal_contract` input produces an artifact that the composer preserves. The dedicated `/legal.html` interface also calls the legal API directly. User uploads are not added to the authoritative evidence corpus.
