# =============================================================================
# ADK Pseudocode: Postgres-drevet Pipeline
# =============================================================================
# Filosofi:
#   Agenter møder aldrig rå data. Al ingestion, rensning og embedding
#   sker i deterministiske scripts INDEN agenten aktiveres.
#   Postgres er "hjernen" — det centrale, persistente hukommelseslag.
#
# Flow:
#   Jira API → [Scraper Script] → Task_DB (pgvector + structured)
#                                      ↓
#                             [Routing Agent]
#                            /       |        \
#               TDD_agent_db  Code_review_db  PO_agent_db
#
# Fordele vs. MCP-tung arkitektur:
#   - Lavere token-forbrug (agenter læser komprimerede records, ikke rå API-svar)
#   - Fuld audit trail — alle states skrives til DB, ikke kun i agent-hukommelse
#   - Deterministisk routing — regelbaseret, ikke prompt-baseret
# =============================================================================


# =============================================================================
# SHARED TYPES
# =============================================================================

# Rå opgave fra Jira Cloud API
RawJiraTask = {
    "id":          str,          # f.eks. "PROJ-42"
    "title":       str,
    "description": str,
    "labels":      list[str],
    "priority":    str,          # Jira-prioritet: "Highest" | "High" | "Medium" | "Low"
    "reporter":    str,
    "created_at":  str,          # ISO 8601
}

# Renset og komprimeret task-record klar til embedding
CleanedTask = {
    "id":             str,
    "title":          str,
    "summary":        str,       # LLM-komprimeret beskrivelse (max 3 sætninger)
    "domain":         str,       # Udledt domæne, f.eks. "backend" | "frontend" | "infra"
    "task_type":      str,       # "feature" | "bug" | "review" | "test" | "chore"
    "priority":       str,       # normaliseret: "high" | "medium" | "low"
    "labels":         list[str],
    "created_at":     str,
    "routing_status": str,       # "pending" | "routed" | "blocked"
}

# Fuldt beriget record med semantisk embedding — gemmes i Task_DB
TaskRecord = {
    "id":             str,
    "cleaned_task":   CleanedTask,
    "embedding":      list[float],  # pgvector-kompatibel vektor (f.eks. 1536-dim)
    "embedding_model": str,         # f.eks. "text-embedding-3-small"
    "routed_to":      str,          # agent-DB der modtager opgaven, eller None
    "routed_at":      str,          # ISO 8601 eller None
}

# Routing-beslutning produceret af RoutingAgent
RoutingDecision = {
    "task_id":     str,
    "target_db":   str,   # "TDD_agent_db" | "code_review_db" | "PO_agent_db"
    "reason":      str,   # kortfattet begrundelse
    "confidence":  float, # 0.0 – 1.0
}

# Payload skrevet til den valgte agent-DB
AgentTaskPayload = {
    "task_id":    str,
    "task_type":  str,
    "summary":    str,
    "priority":   str,
    "embedding":  list[float],  # viderestilles til agent-DB til similarity-søgning
    "context":    dict,         # agent-specifik kontekst (se skemaer nedenfor)
    "created_at": str,
}


# =============================================================================
# DATABASE-SKEMAER
# =============================================================================
# Alle databaser er Postgres med pgvector-extension.
# Embeddings gemmes som vector(1536) til semantisk søgning.

Task_DB = PostgresDatabase(
    name="task_db",
    description=(
        "Central indgangsbase. Modtager alle scrappede Jira-opgaver. "
        "Routing Agent læser herfra og skriver aldrig rå data videre til agenter — "
        "kun opsummerede AgentTaskPayloads sendes til agent-DBer."
    ),
    tables={
        "task_records": {
            "id":              "TEXT PRIMARY KEY",
            "title":           "TEXT NOT NULL",
            "summary":         "TEXT NOT NULL",
            "domain":          "TEXT",
            "task_type":       "TEXT",
            "priority":        "TEXT",
            "labels":          "TEXT[]",
            "embedding":       "vector(1536)",
            "embedding_model": "TEXT",
            "routing_status":  "TEXT DEFAULT 'pending'",
            "routed_to":       "TEXT",
            "routed_at":       "TIMESTAMPTZ",
            "created_at":      "TIMESTAMPTZ NOT NULL",
        },
        "scrape_log": {
            "run_id":      "UUID PRIMARY KEY DEFAULT gen_random_uuid()",
            "started_at":  "TIMESTAMPTZ",
            "finished_at": "TIMESTAMPTZ",
            "tasks_found": "INTEGER",
            "tasks_new":   "INTEGER",
            "errors":      "TEXT[]",
        },
    },
    extensions=["pgvector"],
)

TDD_agent_db = PostgresDatabase(
    name="tdd_agent_db",
    description=(
        "Opgaver der kræver test-first implementering. "
        "TDD-agenten poller denne DB og henter pending tasks."
    ),
    tables={
        "tdd_tasks": {
            "task_id":      "TEXT PRIMARY KEY REFERENCES task_db.task_records(id)",
            "summary":      "TEXT NOT NULL",
            "priority":     "TEXT",
            "embedding":    "vector(1536)",
            "test_coverage_target": "FLOAT DEFAULT 80.0",
            "status":       "TEXT DEFAULT 'pending'",  # "pending" | "in_progress" | "done" | "blocked"
            "agent_output": "JSONB",                   # Udfyldes af TDD-agenten
            "created_at":   "TIMESTAMPTZ NOT NULL",
            "updated_at":   "TIMESTAMPTZ",
        },
    },
    extensions=["pgvector"],
)

code_review_db = PostgresDatabase(
    name="code_review_db",
    description=(
        "Opgaver der kræver code review. "
        "Code Review-agenten poller denne DB og henter pending reviews."
    ),
    tables={
        "review_tasks": {
            "task_id":      "TEXT PRIMARY KEY REFERENCES task_db.task_records(id)",
            "summary":      "TEXT NOT NULL",
            "priority":     "TEXT",
            "embedding":    "vector(1536)",
            "pr_url":       "TEXT",                    # Kan sættes manuelt eller via pr_agent_skill
            "checklist":    "TEXT[]",                  # OWASP Top 10 + performance-punkter
            "status":       "TEXT DEFAULT 'pending'",
            "agent_output": "JSONB",
            "created_at":   "TIMESTAMPTZ NOT NULL",
            "updated_at":   "TIMESTAMPTZ",
        },
    },
    extensions=["pgvector"],
)

PO_agent_db = PostgresDatabase(
    name="po_agent_db",
    description=(
        "Opgaver der kræver product owner-analyse: nye features, scope-vurdering "
        "og stakeholder-kommunikation. PO-agenten poller denne DB."
    ),
    tables={
        "po_tasks": {
            "task_id":         "TEXT PRIMARY KEY REFERENCES task_db.task_records(id)",
            "summary":         "TEXT NOT NULL",
            "priority":        "TEXT",
            "embedding":       "vector(1536)",
            "value_score":     "FLOAT",                # Udfyldes af PO-agenten
            "risk_level":      "TEXT",                 # "low" | "medium" | "high"
            "sprint_target":   "TEXT",                 # Foreslået sprint
            "status":          "TEXT DEFAULT 'pending'",
            "agent_output":    "JSONB",
            "created_at":      "TIMESTAMPTZ NOT NULL",
            "updated_at":      "TIMESTAMPTZ",
        },
    },
    extensions=["pgvector"],
)


# =============================================================================
# SCRAPER SCRIPT — jira_scraper.py
# Rolle: Deterministisk ETL-script (ingen agent-logik, kører på cron)
# Trigger: Planlagt (f.eks. hvert 5. minut) eller webhook fra Jira
# =============================================================================

jira_scraper_script = Script(
    name="jira_scraper",
    description=(
        "Henter nye Jira-opgaver, renser dem, komprimerer beskrivelsen via LLM, "
        "genererer semantisk embedding og gemmer i Task_DB. "
        "Dette er et deterministisk script — ingen agent-beslutninger træffes her."
    ),
    trigger="cron(*/5 * * * *)",  # Hvert 5. minut, eller Jira-webhook
    steps=[

        # ── Step 1: Hent nye opgaver fra Jira ──────────────────────────────
        Step(
            name="fetch_from_jira",
            action="Kald Jira Cloud REST API",
            detail=[
                "GET /rest/api/3/search?jql=status=Open AND created>=-5m",
                "Paginer med maxResults=50 og startAt-cursor.",
                "Filtrer duplikater mod task_db.task_records (check by id).",
                "Returnér liste af RawJiraTask.",
            ],
            output=list[RawJiraTask],
        ),

        # ── Step 2: Rens og normaliser ──────────────────────────────────────
        Step(
            name="clean_and_normalize",
            action="Rens RawJiraTask til CleanedTask",
            detail=[
                "Strip HTML/Markdown fra description.",
                "Normaliser priority: Jira 'Highest'/'High' → 'high', 'Medium' → 'medium', etc.",
                "Udled domain og task_type fra labels og title-nøgleord (regelbaseret, ingen LLM):",
                "  - labels indeholder 'test' eller 'tdd'         → task_type='test'",
                "  - labels indeholder 'review' eller 'pr'        → task_type='review'",
                "  - labels indeholder 'feature' eller 'story'    → task_type='feature'",
                "  - labels indeholder 'bug' eller 'hotfix'       → task_type='bug'",
                "  - ellers                                        → task_type='chore'",
                "Sæt routing_status='pending'.",
            ],
            output=list[CleanedTask],
        ),

        # ── Step 3: Komprimér beskrivelse (LLM-kald) ──────────────────────
        Step(
            name="summarize_description",
            action="Kald LLM for at komprimere description til max 3 sætninger",
            detail=[
                "Prompt: 'Opsummer følgende Jira-opgave i max 3 sætninger på dansk. "
                "Fokus: hvad skal gøres, hvorfor og i hvilken kontekst.'",
                "Indsæt komprimeret tekst i CleanedTask.summary.",
                "Token-budget: max 200 output tokens pr. opgave.",
                "Kald LLM i batch (max 20 opgaver pr. request) for at reducere latency.",
            ],
            output=list[CleanedTask],  # CleanedTask.summary er nu udfyldt
        ),

        # ── Step 4: Generer semantisk embedding ────────────────────────────
        Step(
            name="generate_embedding",
            action="Generer vektor-embedding for hver CleanedTask",
            detail=[
                "Input til embedding: f'{task.title}. {task.summary}'",
                "Kald embedding-model (f.eks. text-embedding-3-small, 1536 dim).",
                "Gem embedding i TaskRecord.embedding som list[float].",
                "Registér embedding_model-navn i TaskRecord.embedding_model.",
            ],
            output=list[TaskRecord],
        ),

        # ── Step 5: Skriv til Task_DB ───────────────────────────────────────
        Step(
            name="upsert_to_task_db",
            action="Gem TaskRecord i Task_DB",
            detail=[
                "INSERT INTO task_records ... ON CONFLICT (id) DO NOTHING.",
                "Gem embedding som pgvector vector(1536).",
                "Opdater scrape_log med tasks_found, tasks_new og eventuelle errors.",
            ],
            output=None,  # Skriver til DB, returnerer intet
        ),
    ],
    error_handling=[
        "Ved Jira API-fejl (4xx/5xx): log til scrape_log.errors, spring opgaven over.",
        "Ved LLM-fejl: gem RawJiraTask.description uændret som summary, fortsæt.",
        "Ved DB-fejl: log og re-kø opgaven til næste scraper-kørsel.",
    ],
    forbidden=[
        "Skriv til agent-DBer (TDD, code_review, PO) — det er Routing Agentens ansvar",
        "Træf routing-beslutninger",
        "Kald andre APIs end Jira og embedding-modellen",
    ],
)


# =============================================================================
# ROUTING AGENT
# Rolle: Agent (automatisk — ingen menneskelig godkendelse)
# Trigger: Ny record med routing_status='pending' i Task_DB
# =============================================================================

# Routing-regler: regelbaseret + semantisk fallback
ROUTING_RULES = RoutingRules(
    rules=[
        Rule(
            condition="task_type == 'test'",
            target_db="TDD_agent_db",
            reason="Opgaven kræver test-first implementering.",
        ),
        Rule(
            condition="task_type == 'review'",
            target_db="code_review_db",
            reason="Opgaven kræver code review.",
        ),
        Rule(
            condition="task_type in ('feature', 'chore')",
            target_db="PO_agent_db",
            reason="Opgaven kræver scope-evaluering og prioritering af PO.",
        ),
        Rule(
            condition="task_type == 'bug' AND priority == 'high'",
            target_db="TDD_agent_db",
            reason="Høj-prioritet bug kræver hurtig TDD-løsning.",
        ),
        Rule(
            condition="task_type == 'bug' AND priority != 'high'",
            target_db="PO_agent_db",
            reason="Lav/medium-prioritet bug evalueres af PO for sprint-placering.",
        ),
    ],
    fallback=SemanticFallback(
        description=(
            "Hvis ingen regel matcher: brug cosine similarity mod eksisterende records "
            "i agent-DBerne for at finde den mest lignende historiske opgave og rut derhen."
        ),
        similarity_threshold=0.75,  # Minimum cosine similarity for automatisk routing
        on_below_threshold="route_to_PO_agent_db",  # PO vurderer uklare opgaver
    ),
)

routing_agent = Agent(
    model="claude_Megasej",
    name="routing_agent",
    description=(
        "Læser pending TaskRecords fra Task_DB, træffer routing-beslutning "
        "og skriver AgentTaskPayload til den korrekte agent-DB. "
        "Agenten møder kun komprimerede summaries og embeddings — aldrig rå Jira-data."
    ),
    trigger=DatabaseTrigger(
        db=Task_DB,
        table="task_records",
        condition="routing_status = 'pending'",
        poll_interval_seconds=30,
    ),
    instruction=[
        # ── Læs opgave ─────────────────────────────────────────────────────
        "Hent næste TaskRecord med routing_status='pending' fra Task_DB.",
        "Læs task_type, priority, domain og embedding.",

        # ── Bestem destination ─────────────────────────────────────────────
        "Anvend ROUTING_RULES i prioriteret rækkefølge:",
        "  1. Evaluer regelbaserede betingelser (deterministisk).",
        "  2. Hvis ingen regel matcher: foretag semantisk søgning med embedding.",
        "     → Beregn cosine similarity mod seneste 100 routed records i agent-DBerne.",
        "     → Rut til DB med højeste gennemsnitlige similarity (threshold: 0.75).",
        "     → Under threshold: rut til PO_agent_db.",

        # ── Byg og skriv payload ───────────────────────────────────────────
        "Byg AgentTaskPayload med summary, priority, embedding og agent-specifik kontekst:",
        "  → TDD_agent_db:    tilføj context.test_coverage_target = 80.0",
        "  → code_review_db:  tilføj context.checklist = OWASP_TOP_10_CHECKLIST",
        "  → PO_agent_db:     tilføj context.sprint_history = hent seneste 5 sprints fra Task_DB",
        "Skriv AgentTaskPayload til target_db.",

        # ── Opdater Task_DB ────────────────────────────────────────────────
        "Opdater task_records: sæt routing_status='routed', routed_to=target_db, routed_at=now().",
        "Log RoutingDecision til routing_log-tabel.",
    ],
    resources=[
        Task_DB,
        TDD_agent_db,
        code_review_db,
        PO_agent_db,
    ],
    routing_rules=ROUTING_RULES,
    forbidden=[
        "Læs rå Jira-data (kun summaries og embeddings fra Task_DB)",
        "Skriv til task_records udover routing_status, routed_to og routed_at",
        "Modificer AgentTaskPayload efter det er skrevet til agent-DB",
        "Deploy eller merge kode",
        "Godkend eller afvis opgaver",
    ],
)


# =============================================================================
# ASSEMBLE
# =============================================================================

postgres_pipeline = Pipeline(
    name="postgres_pipeline",
    description=(
        "Deterministisk Postgres-drevet pipeline. "
        "Scraper-scriptet og Routing Agenten kører uafhængigt. "
        "Agent-DBerne fungerer som separate indbakker for hvert specialistlag."
    ),
    components=[
        jira_scraper_script,  # Kron-job: Jira → Task_DB
        routing_agent,        # Lytter på Task_DB, ruter til agent-DBer
    ],
    databases=[
        Task_DB,          # Central indgang med pgvector
        TDD_agent_db,     # TDD-agentens indbakke
        code_review_db,   # Code Review-agentens indbakke
        PO_agent_db,      # PO-agentens indbakke
    ],
    protocol="SAP",  # Shared Agent Protocol — AgentTaskPayload er fælles kontrakt
)
