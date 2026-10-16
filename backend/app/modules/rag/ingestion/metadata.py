"""Fields preserved with every passage.

Publication date and effective date stay empty until a source establishes them.
Filename guesses are not accepted as version dates.
"""

PASSAGE_FIELDS = (
    "document_id",
    "publisher",
    "language",
    "document_hash",
    "edition",
    "article",
    "page",
    "highlight",
    "publication_date",
    "effective_date",
    "domain",
)
