"""Local programs and the files already in this repository.

Eligibility rules are not encoded here. The matcher only filters this list
by company stage so the web shell can show the right checklists.
"""

from app.schemas.aid import AidProgram

CATALOG: list[AidProgram] = [
    AidProgram(
        id="bfpme-creation",
        name="BFPME financing request — creation",
        provider="BFPME",
        summary=(
            "Checklists and the 2024 financing form for creating a small or "
            "medium enterprise."
        ),
        stages=["creation"],
        local_files=[
            "grants_and_financial_aids/BFPME/Checklist_Creation_Entreprise.pdf",
            "grants_and_financial_aids/BFPME/Checklist_Demande_Financement.pdf",
            "grants_and_financial_aids/BFPME/Checklist_Notification_Financement.pdf",
            "grants_and_financial_aids/BFPME/Checklist_Deblocage.pdf",
            "grants_and_financial_aids/BFPME/Demande_Financement_BFPME_2024.doc",
            "grants_and_financial_aids/Business_Plan_Models/Modele_Business_Plan_Creation.xls",
        ],
    ),
    AidProgram(
        id="bfpme-extension",
        name="BFPME financing request — extension",
        provider="BFPME",
        summary="Checklists and business-plan model for extending an existing enterprise.",
        stages=["extension", "growth"],
        local_files=[
            "grants_and_financial_aids/BFPME/Checklist_Extension_Entreprise.pdf",
            "grants_and_financial_aids/BFPME/Checklist_Demande_Financement.pdf",
            "grants_and_financial_aids/BFPME/Checklist_Notification_Financement.pdf",
            "grants_and_financial_aids/BFPME/Checklist_Deblocage.pdf",
            "grants_and_financial_aids/Business_Plan_Models/Modele_Business_Plan_Extension.xls",
        ],
    ),
    AidProgram(
        id="giz-business-plan",
        name="GIZ business-plan model",
        provider="GIZ",
        summary="Plan-d'affaires template stored with the other financing models.",
        stages=["creation", "extension", "growth"],
        local_files=[
            "grants_and_financial_aids/Business_Plan_Models/Modele_Plan_Affaires_GIZ.doc",
        ],
    ),
    AidProgram(
        id="startup-act",
        name="Startup Act label and incentives",
        provider="Startup Tunisia / JORT",
        summary=(
            "Law 2018-20, decree 2018-840, and BCT startup circulars live in "
            "the legal corpus. Cited answers for those texts go through the RAG workers."
        ),
        stages=["creation", "growth"],
        local_files=[
            "law/TUNISIA_LEGAL_BUSINESS_CORPUS/01_STARTUPS",
        ],
    ),
    AidProgram(
        id="investment-incentives",
        name="Investment-law incentives",
        provider="JORT",
        summary=(
            "Law 2016-71, its 2017 decrees, and law 2019-47 are in the legal "
            "corpus. Use cited answers for what the text says."
        ),
        stages=["creation", "extension", "growth"],
        local_files=[
            "law/TUNISIA_LEGAL_BUSINESS_CORPUS/02_INVESTMENT",
        ],
    ),
]
