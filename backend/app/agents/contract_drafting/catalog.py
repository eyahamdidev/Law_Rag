"""Project-authored drafting structures, never presented as legal authorities."""

LANGUAGES = ("en", "fr", "ar")

def words(text: str) -> dict[str, str]:
    return dict(zip(LANGUAGES, text.split("|")))

def field(key: str, label: str):
    return {"id": key, "label": words(label), "required": True}

COMMON = [
    field("duration_termination", "Duration and termination|Durée et résiliation|المدة والإنهاء"),
    field("disputes", "Dispute resolution and forum|Règlement des différends et juridiction|تسوية النزاعات والاختصاص"),
]

def spec(title, fields, query, equity=False):
    return {"title": words(title), "fields": fields + COMMON, "search_query": query, "equity_required": equity}

CATALOG = {
    "nda": spec("Non-disclosure agreement|Accord de confidentialité|اتفاقية عدم الإفشاء", [
        field("disclosure_mode", "Mutual or one-way (mutual / one_way)|Réciproque ou unilatéral (mutual / one_way)|متبادل أو أحادي (mutual / one_way)"),
        field("confidential_information", "Confidential information and exclusions|Informations confidentielles et exclusions|المعلومات السرية والاستثناءات"),
        field("permitted_use", "Permitted use and recipients|Usage autorisé et destinataires|الاستخدام المسموح والمتلقون"),
        field("protection_return", "Protection, compelled disclosure and return/deletion|Protection, divulgation imposée et restitution/suppression|الحماية والإفشاء الإلزامي والإرجاع والحذف"),
        field("confidentiality_period", "Confidentiality period|Durée de confidentialité|مدة السرية"),
    ], "Code obligations contrats convention confidentialité secret affaires"),
    "founders": spec("Founders' agreement|Accord entre fondateurs|اتفاقية المؤسسين", [
        field("roles", "Founders' roles and time commitments|Rôles et engagement des fondateurs|أدوار المؤسسين والتزامهم"),
        field("contributions", "Contributions and expenses|Apports et dépenses|المساهمات والمصاريف"),
        field("governance", "Decisions and deadlock process|Décisions et résolution des blocages|اتخاذ القرارات وحل التعثر"),
        field("ip_terms", "Existing and future IP ownership and formalities|Propriété intellectuelle antérieure et future et formalités|ملكية الحقوق الفكرية السابقة والمستقبلية والإجراءات"),
        field("departure", "Departure, vesting if agreed, and transfer arrangements|Départ, acquisition progressive si convenue et cession|المغادرة والاستحقاق التدريجي إن اتفق عليه ونقل الحصص"),
    ], "Code sociétés commerciales associés apports gérance cession parts", True),
    "shareholders": spec("Shareholders' agreement|Pacte d'associés ou d'actionnaires|اتفاقية المساهمين", [
        field("company", "Company identity and share classes|Identité de la société et catégories de titres|هوية الشركة وفئات الأسهم"),
        field("governance", "Voting and reserved decisions|Votes et décisions réservées|التصويت والقرارات المحجوزة"),
        field("transfers", "Transfers, pre-emption and exit terms|Cessions, préemption et sortie|نقل الأسهم والأولوية والخروج"),
        field("information", "Information and distribution policy|Information et politique de distribution|المعلومات وسياسة التوزيع"),
        field("ip_terms", "IP and confidentiality arrangements|Propriété intellectuelle et confidentialité|الملكية الفكرية والسرية"),
    ], "Code sociétés commerciales associés actions cession vote", True),
    "investment": spec("Investment agreement|Accord d'investissement|اتفاقية استثمار", [
        field("instrument", "Investment instrument and company|Instrument d'investissement et société|أداة الاستثمار والشركة"),
        field("amount_currency", "Amount, currency and payment schedule|Montant, devise et échéancier|المبلغ والعملة وجدول الدفع"),
        field("valuation_rights", "Valuation/conversion and investor rights|Valorisation/conversion et droits de l'investisseur|التقييم والتحويل وحقوق المستثمر"),
        field("conditions", "Conditions precedent, disclosures and approvals|Conditions préalables, informations et autorisations|الشروط المسبقة والإفصاحات والموافقات"),
        field("closing_exit", "Closing, use of funds and exit terms|Réalisation, emploi des fonds et sortie|الإتمام واستخدام الأموال والخروج"),
    ], "Code sociétés commerciales investissement capital souscription autorisations change"),
    "grant": spec("Grant or donor agreement|Convention de subvention ou de don|اتفاقية منحة أو تبرع", [
        field("amount_currency", "Amount, currency and disbursement|Montant, devise et versement|المبلغ والعملة والصرف"),
        field("activities_budget", "Funded activities and eligible budget|Activités financées et budget éligible|الأنشطة الممولة والميزانية المؤهلة"),
        field("milestones", "Milestones and deliverables|Étapes et livrables|المراحل والمخرجات"),
        field("reporting_audit", "Reporting, records and audit|Rapports, justificatifs et audit|التقارير والسجلات والتدقيق"),
        field("suspension_repayment", "Suspension and repayment conditions|Suspension et conditions de remboursement|التعليق وشروط الاسترداد"),
    ], "Code obligations contrats convention financement don subvention"),
    "services": spec("Services agreement|Contrat de prestation de services|عقد تقديم خدمات", [
        field("deliverables", "Services, milestones and acceptance|Prestations, étapes et réception|الخدمات والمراحل والقبول"),
        field("fees", "Fees, currency, tax treatment and payment|Honoraires, devise, traitement fiscal et paiement|الأتعاب والعملة والمعاملة الجبائية والدفع"),
        field("ip_terms", "Deliverable ownership and licences|Propriété des livrables et licences|ملكية المخرجات والتراخيص"),
        field("confidentiality", "Confidentiality and personal data handling|Confidentialité et traitement des données personnelles|السرية ومعالجة البيانات الشخصية"),
        field("liability", "Responsibility, remedies and liability allocation|Responsabilités, recours et répartition des risques|المسؤولية والتعويضات وتوزيع المخاطر"),
    ], "Code obligations contrats prestation services responsabilité"),
    "partnership": spec("Partnership agreement|Accord de partenariat|اتفاقية شراكة", [
        field("contributions", "Each party's contributions and responsibilities|Apports et responsabilités de chaque partie|مساهمات ومسؤوليات كل طرف"),
        field("governance", "Governance and representation limits|Gouvernance et limites de représentation|الحوكمة وحدود التمثيل"),
        field("finances", "Costs, revenue and loss allocation|Répartition des coûts, recettes et pertes|توزيع التكاليف والإيرادات والخسائر"),
        field("ip_terms", "Background IP, results and use rights|Droits antérieurs, résultats et droits d'usage|الحقوق السابقة والنتائج وحقوق الاستخدام"),
        field("confidentiality", "Confidentiality and external communications|Confidentialité et communication externe|السرية والاتصال الخارجي"),
    ], "Code obligations contrats partenariat responsabilité représentation"),
    "consortium": spec("Consortium agreement|Accord de consortium|اتفاقية ائتلاف", [
        field("programme", "Project, funder and main agreement reference|Projet, financeur et référence de la convention principale|المشروع والممول ومرجع الاتفاقية الرئيسية"),
        field("work_packages", "Work packages, deliverables and members|Lots de travail, livrables et membres|حزم العمل والمخرجات والأعضاء"),
        field("governance", "Coordinator, decisions and escalation|Coordinateur, décisions et escalade|المنسق والقرارات والتصعيد"),
        field("finances", "Budget, payments, reporting and audits|Budget, paiements, rapports et audits|الميزانية والمدفوعات والتقارير والتدقيق"),
        field("ip_terms", "Background IP, results, access and publication|Droits antérieurs, résultats, accès et publication|الحقوق السابقة والنتائج والوصول والنشر"),
        field("liability", "Member default, withdrawal and liability|Défaillance, retrait et responsabilité des membres|إخلال الأعضاء والانسحاب والمسؤولية"),
    ], "Code obligations contrats consortium convention responsabilité"),
    "ip_licence": spec("IP licence agreement|Contrat de licence de propriété intellectuelle|عقد ترخيص ملكية فكرية", [
        field("ip_assets", "Identified IP, owner and evidence of title|Droits identifiés, titulaire et justificatifs|الحقوق المحددة والمالك وإثبات الملكية"),
        field("scope", "Exclusivity, territory, field of use and sublicensing|Exclusivité, territoire, domaine et sous-licence|الحصرية والإقليم ومجال الاستخدام والترخيص الفرعي"),
        field("fees", "Royalties, currency, payment and audit|Redevances, devise, paiement et audit|الإتاوات والعملة والدفع والتدقيق"),
        field("quality", "Quality, maintenance, enforcement and improvements|Qualité, maintien, défense et améliorations|الجودة والصيانة والإنفاذ والتحسينات"),
        field("formalities", "Required approvals, registration and responsibilities to verify|Autorisations, inscriptions et responsabilités à vérifier|الموافقات والتسجيل والمسؤوليات الواجب التثبت منها"),
    ], "brevet marque licence exploitation redevance inscription"),
    "ip_assignment": spec("IP assignment agreement|Contrat de cession de propriété intellectuelle|عقد إحالة ملكية فكرية", [
        field("ip_assets", "Identified IP and chain of ownership|Droits identifiés et chaîne de titularité|الحقوق المحددة وسلسلة الملكية"),
        field("scope", "Transferred rights, territory and exclusions|Droits transférés, territoire et exclusions|الحقوق المنقولة والإقليم والاستثناءات"),
        field("consideration", "Consideration, currency and payment|Contrepartie, devise et paiement|المقابل والعملة والدفع"),
        field("warranties", "Disclosures, warranties and responsibility|Informations, garanties et responsabilités|الإفصاحات والضمانات والمسؤوليات"),
        field("formalities", "Execution, recordal and assistance to verify|Signature, inscription et assistance à vérifier|الإمضاء والترسيم والمساعدة الواجب التثبت منها"),
    ], "brevet marque cession inscription droits auteur"),
}

def catalog(language="fr"):
    return [{"id": key, "title": value["title"][language], "template_version": "2026-10-16.v1",
             "fields": [{"id": f["id"], "label": f["label"][language], "required": True} for f in value["fields"]],
             "equity_required": value["equity_required"]} for key, value in CATALOG.items()]
