# Stage 1 — Postgres som fundament for AI-agenter

> **Målgruppe:** Tekniske beslutningstagere og udviklere der ønsker at sætte et kontrolleret, auditerbart og skalerbart AI agent-system op — applicerbart for næsten enhver virksomhed.
>
> **Scope:** Stage 1 etablerer *fundamentet*. Ingen agenter kører endnu. Målet er at have et deterministisk datalag klar, så agenter i Stage 2 altid møder strukturerede, traceable data — aldrig rå støj.

---

## Hvad vi bygger i Stage 1

```mermaid
flowchart LR
    subgraph SOURCES["Dine datakilder"]
        A["Opgave-system\n(Jira / Linear / Azure DevOps)"]
        B["Kommunikation\n(Slack / Teams / Email)"]
        C["Valgfrit\n(CRM / ERP / andre)"]
    end

    subgraph SCRIPTS["Sync-scripts"]
        S1["Ingestion script\nFetching & cleaning"]
        S2["Embedding script\nGenererer vektorer"]
    end

    subgraph PG["Postgres (fundamentet)"]
        T1[("Strukturerede tabeller\nTask, Users, Registry")]
        T2[("pgvector\nSemantiske embeddings")]
        T3[("Audit log\nImmutable log")]
    end

    SOURCES --> SCRIPTS --> PG
```


**Resultatet af Stage 1:**
- Et Postgres-skema der er single source of truth for alle opgaver og hændelser
- Sync-scripts der automatisk henter og normaliserer data fra dine eksisterende værktøjer
- En routing-tabel der deterministisk afgør hvilken agent der skal håndtere hvilken opgavetype
- En immutable audit-log der fanger alt fra dag ét

---

## Forudsætninger

| Krav | Beskrivelse |
|------|-------------|
| **Postgres 15+** | Med `pgvector`-extension installeret |
| **Python 3.11+** | Til sync-scripts og ingestion |
| **API-adgang** | Til mindst ét eksisterende værktøj (opgavesystem og/eller kommunikation) |
| **LLM API-nøgle** | Til embedding-generering (OpenAI, Anthropic, Cohere eller tilsvarende) |
| **Miljøvariabler** | Alle nøgler i `.env` — aldrig hardcodet |

---

## Trin 1 — Installer Postgres med pgvector

```bash
# Via Docker (anbefalet til hurtig opstart)
docker run -d \
  --name agent-db \
  -e POSTGRES_PASSWORD=dit_password \
  -e POSTGRES_DB=agent_foundation \
  -p 5432:5432 \
  pgvector/pgvector:pg16

# Aktiver pgvector i databasen
psql -U postgres -d agent_foundation -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

> **Sikkerhed:** Brug aldrig standard-passwords i produktion. Sæt `POSTGRES_PASSWORD` som miljøvariabel og begræns netværksadgang til databaseporten.

---

## Trin 2 — Opret kernetabellerne

Dette er fundamentet. Alle agenter og scripts læser og skriver til disse tabeller.

```sql
-- 1. Opgave-registret: single source of truth for alle indkomne opgaver
CREATE TABLE task_entries (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source          TEXT NOT NULL,          -- 'jira', 'slack', 'email', 'teams'
    source_ref      TEXT NOT NULL,          -- ekstern ID (issue key, thread_id, email_id)
    title           TEXT,
    raw_text        TEXT,
    summary         TEXT,                   -- LLM-genereret opsummering (udfyldes i Stage 2)
    type            TEXT,                   -- 'bug', 'feature', 'review', 'general'
    priority        TEXT DEFAULT 'normal',  -- 'critical', 'high', 'normal', 'low'
    status          TEXT DEFAULT 'new',     -- 'new', 'routed', 'in_progress', 'done'
    agent_pointer   TEXT,                   -- FK til agent_registry.agent_name
    assigned_to     UUID,                   -- FK til user_chain.id
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    routed_at       TIMESTAMPTZ,
    UNIQUE(source, source_ref)              -- forhindrer dubletter
);

-- 2. Agent-registret: hvilke agenter findes, og hvad aktiverer dem
CREATE TABLE agent_registry (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_name      TEXT UNIQUE NOT NULL,
    trigger_on      TEXT NOT NULL,          -- opgavetype der aktiverer agenten
    webhook_url     TEXT,                   -- endpoint agenten lytter på
    active          BOOLEAN DEFAULT TRUE,
    description     TEXT
);

-- 3. Agent-output: hvad producerede en agent til en given opgave
CREATE TABLE agent_output (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_entry_id   UUID REFERENCES task_entries(id),
    agent_name      TEXT REFERENCES agent_registry(agent_name),
    result          JSONB,                  -- fleksibelt output-format per agent
    status          TEXT DEFAULT 'pending', -- 'pending', 'done', 'failed'
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 4. Brugerkæden: roller, ansvar og eskaleringsrækkefølge
CREATE TABLE user_chain (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    role            TEXT NOT NULL,          -- 'developer', 'senior_dev', 'product_owner', 'qa'
    external_user_id TEXT,                  -- Slack user_id, Teams-id, email-adresse
    escalation_level INTEGER DEFAULT 1,
    fallback_user_id UUID REFERENCES user_chain(id),
    sla_hours       INTEGER DEFAULT 24
);

-- 5. Eskaleringslog: hvem eskalerede hvad og hvornår
CREATE TABLE escalation_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_entry_id   UUID REFERENCES task_entries(id),
    from_user_id    UUID REFERENCES user_chain(id),
    to_user_id      UUID REFERENCES user_chain(id),
    reason          TEXT,
    escalated_at    TIMESTAMPTZ DEFAULT NOW()
);

-- 6. Audit-log: immutable log af alle hændelser — aldrig UPDATE eller DELETE
CREATE TABLE audit_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type      TEXT NOT NULL,          -- 'task.created', 'agent.done', 'human.approved'
    entity_id       UUID,
    actor           TEXT,                   -- hvem/hvad udførte handlingen
    payload         JSONB,
    occurred_at     TIMESTAMPTZ DEFAULT NOW()
);

-- 7. Embeddings-tabel: semantisk søgning over opgaver
CREATE TABLE task_embeddings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_entry_id   UUID REFERENCES task_entries(id),
    embedding       vector(1536),           -- tilpas til din LLM (1536 = OpenAI text-embedding-3-small)
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX ON task_embeddings USING ivfflat (embedding vector_cosine_ops);
```

---

## Trin 3 — Populér agent-registret

Definer hvilke agents der skal håndtere hvilke opgavetyper. Dette er den deterministiske routing — ingen AI involveret her.

```sql
INSERT INTO agent_registry (agent_name, trigger_on, description) VALUES
    ('tdd_agent',       'bug',      'Skriver tests og implementerer fix for bugs'),
    ('review_agent',    'review',   'Udfører code review og genererer findings'),
    ('po_agent',        'feature',  'Opretter user stories og acceptancekriterier'),
    ('general_agent',   'general',  'Håndterer opgaver der ikke passer i andre kategorier');
```

> **Tilpasning:** Tilføj eller fjern agents efter jeres setup. `trigger_on` matcher `type`-feltet i `task_entries`. Routing er et simpelt tabelopslag — det kræver ingen AI-inferens.

---

## Trin 4 — Populér brugerkæden

```sql
INSERT INTO user_chain (name, role, external_user_id, escalation_level, sla_hours) VALUES
    ('Anna Andersen',   'product_owner',  '@anna',    3, 48),
    ('Bo Bergmann',     'senior_dev',     '@bo',      2, 24),
    ('Clara Claussen',  'developer',      '@clara',   1, 16),
    ('David Dam',       'qa',             '@david',   1, 24);

-- Sæt fallback: Clara eskalerer til Bo
UPDATE user_chain SET fallback_user_id = (SELECT id FROM user_chain WHERE name = 'Bo Bergmann')
WHERE name = 'Clara Claussen';
```

---

## Trin 5 — Skriv dit første sync-script

Nedenfor er et generaliseret template. Tilpas `fetch_tasks()` til din datakilde.

```python
# sync/task_sync.py
import os
import psycopg2
import requests
from datetime import datetime, timezone

DB_URL = os.environ["DATABASE_URL"]  # postgresql://user:pass@host/db
API_TOKEN = os.environ["TASK_API_TOKEN"]
API_BASE  = os.environ["TASK_API_BASE_URL"]  # eks. https://yourcompany.atlassian.net

def fetch_tasks() -> list[dict]:
    """Hent opgaver fra dit opgavesystem. Tilpas URL og feltnavne."""
    headers = {"Authorization": f"Bearer {API_TOKEN}"}
    response = requests.get(
        f"{API_BASE}/rest/api/3/search",
        headers=headers,
        params={"jql": "updated >= -1d ORDER BY updated DESC", "maxResults": 50},
        timeout=10
    )
    response.raise_for_status()
    return response.json().get("issues", [])

def classify_type(labels: list[str], issue_type: str) -> str:
    """Deterministisk klassificering — ingen AI."""
    label_lower = [l.lower() for l in labels]
    if "bug" in label_lower or issue_type.lower() == "bug":
        return "bug"
    if "review" in label_lower:
        return "review"
    if issue_type.lower() in ("story", "feature", "epic"):
        return "feature"
    return "general"

def classify_priority(priority_name: str) -> str:
    mapping = {"highest": "critical", "high": "high", "medium": "normal",
               "low": "low", "lowest": "low"}
    return mapping.get(priority_name.lower(), "normal")

def sync_to_postgres(tasks: list[dict]) -> None:
    conn = psycopg2.connect(DB_URL)
    cur  = conn.cursor()

    for task in tasks:
        fields   = task.get("fields", {})
        source_ref = task["key"]
        title    = fields.get("summary", "")
        raw_text = fields.get("description", "") or ""
        labels   = [l["name"] for l in fields.get("labels", [])]
        task_type = classify_type(labels, fields.get("issuetype", {}).get("name", ""))
        priority  = classify_priority(
            fields.get("priority", {}).get("name", "medium")
        )

        cur.execute("""
            INSERT INTO task_entries (source, source_ref, title, raw_text, type, priority)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (source, source_ref) DO UPDATE
                SET title    = EXCLUDED.title,
                    raw_text = EXCLUDED.raw_text,
                    priority = EXCLUDED.priority
        """, ("jira", source_ref, title, raw_text, task_type, priority))

        cur.execute("""
            INSERT INTO audit_log (event_type, actor, payload)
            VALUES ('task.synced', 'task_sync_script', %s::jsonb)
        """, (f'{{"source_ref": "{source_ref}", "type": "{task_type}"}}',))

    conn.commit()
    cur.close()
    conn.close()
    print(f"[{datetime.now(timezone.utc).isoformat()}] Synced {len(tasks)} tasks")

if __name__ == "__main__":
    tasks = fetch_tasks()
    sync_to_postgres(tasks)
```

> **Kør som cron-job:** Tilføj til crontab eller en scheduler (f.eks. hvert 5. minut):
> ```
> */5 * * * * python /app/sync/task_sync.py >> /var/log/task_sync.log 2>&1
> ```

---

## Trin 6 — Deterministisk routing

Routing er et tabelopslag — ikke AI. Scriptet læser `agent_pointer`-feltet og kalder den rette webhook.

```python
# sync/router.py
import os
import psycopg2
import requests

DB_URL = os.environ["DATABASE_URL"]

def route_new_tasks() -> None:
    conn = psycopg2.connect(DB_URL)
    cur  = conn.cursor()

    cur.execute("""
        SELECT te.id, te.type, ar.agent_name, ar.webhook_url
        FROM task_entries te
        JOIN agent_registry ar ON ar.trigger_on = te.type AND ar.active = TRUE
        WHERE te.status = 'new'
        LIMIT 20
    """)
    tasks = cur.fetchall()

    for task_id, task_type, agent_name, webhook_url in tasks:
        if webhook_url:
            try:
                requests.post(webhook_url,
                              json={"task_id": str(task_id), "agent": agent_name},
                              timeout=5)
            except requests.RequestException as e:
                print(f"Webhook failed for {task_id}: {e}")
                continue

        cur.execute("""
            UPDATE task_entries
            SET status = 'routed', agent_pointer = %s, routed_at = NOW()
            WHERE id = %s
        """, (agent_name, task_id))

        cur.execute("""
            INSERT INTO audit_log (event_type, entity_id, actor, payload)
            VALUES ('task.routed', %s, 'router_script', %s::jsonb)
        """, (task_id, f'{{"agent": "{agent_name}"}}'))

    conn.commit()
    cur.close()
    conn.close()

if __name__ == "__main__":
    route_new_tasks()
```

---

## Trin 7 — Generér embeddings (valgfrit i Stage 1)

Embeddings gør semantisk søgning muligt i Stage 2. Sæt det op nu, så data er klar.

```python
# sync/embed_tasks.py
import os
import psycopg2
from openai import OpenAI  # udskift med din LLM-udbyder

DB_URL   = os.environ["DATABASE_URL"]
client   = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

def embed_pending_tasks() -> None:
    conn = psycopg2.connect(DB_URL)
    cur  = conn.cursor()

    # Find opgaver uden embeddings endnu
    cur.execute("""
        SELECT te.id, te.title, te.raw_text
        FROM task_entries te
        LEFT JOIN task_embeddings emb ON emb.task_entry_id = te.id
        WHERE emb.id IS NULL
        LIMIT 50
    """)
    tasks = cur.fetchall()

    for task_id, title, raw_text in tasks:
        text = f"{title}\n{raw_text or ''}".strip()[:8000]  # token-grænse
        response = client.embeddings.create(
            input=text,
            model="text-embedding-3-small"
        )
        embedding = response.data[0].embedding

        cur.execute("""
            INSERT INTO task_embeddings (task_entry_id, embedding)
            VALUES (%s, %s)
        """, (task_id, embedding))

    conn.commit()
    cur.close()
    conn.close()
    print(f"Embedded {len(tasks)} tasks")

if __name__ == "__main__":
    embed_pending_tasks()
```

---

## Trin 8 — Verificér opsætningen

Kør disse queries for at bekræfte at fundamentet er på plads:

```sql
-- Er der opgaver i systemet?
SELECT type, priority, status, COUNT(*)
FROM task_entries
GROUP BY type, priority, status
ORDER BY COUNT(*) DESC;

-- Er routing sket korrekt?
SELECT agent_pointer, COUNT(*) as antal
FROM task_entries
WHERE status = 'routed'
GROUP BY agent_pointer;

-- Er audit-loggen aktiv?
SELECT event_type, actor, occurred_at
FROM audit_log
ORDER BY occurred_at DESC
LIMIT 10;

-- Er embeddings ved at blive genereret?
SELECT COUNT(*) as med_embedding FROM task_embeddings;
SELECT COUNT(*) as uden_embedding
FROM task_entries te
LEFT JOIN task_embeddings emb ON emb.task_entry_id = te.id
WHERE emb.id IS NULL;
```

---

## Hvad er Stage 1 IKKE?

| Ikke inkluderet i Stage 1 | Kommer i næste Stages |
|---------------------------|-----------------|
| AI-agenter der læser/skriver opgaver | ✓ Stage 2 |
| LLM-genererede opsummeringer | ✓ Stage 2 |
| Human-in-the-loop godkendelsesflows | ✓ Stage 2 |
| Event bus (Kafka / Redis) | ✓ Stage 3 |
| Multi-database isolation | ✓ Stage 3 |
| Sikkerheds-lag (WAF, Zero Trust) | ✓ Stage 3 |

---

## Mappestruktur efter Stage 1

```
project/
├── .env                    # Hemmeligheder — aldrig i git
├── .env.example            # Skabelon til teamet
├── db/
│   └── schema.sql          # Alt fra Trin 2
├── sync/
│   ├── task_sync.py        # Trin 5
│   ├── router.py           # Trin 6
│   └── embed_tasks.py      # Trin 7
└── README.md
```

---

## Stage 1 — Tjekliste

- [ ] Postgres installeret og `pgvector` aktiveret
- [ ] Alle 7 tabeller oprettet (`task_entries`, `agent_registry`, `agent_output`, `user_chain`, `escalation_log`, `audit_log`, `task_embeddings`)
- [ ] `agent_registry` populeret med mindst ét agent-entry per opgavetype
- [ ] `user_chain` populeret med teamets roller og eskaleringsrækkefølge
- [ ] `task_sync.py` kører og indsætter opgaver fra mindst én datakilde
- [ ] `router.py` opdaterer `status = 'routed'` og sætter `agent_pointer`
- [ ] `audit_log` indeholder entries — alt er sporbart
- [ ] Alle API-nøgler er environment variables — ingen secrets i kode

---

> **Næste skridt (Stage 2):** Tilslut din første AI-agent. Den henter en `status = 'routed'`-opgave, bygger sin kontekst via `get_task_context()`, udfører sit arbejde og skriver output til `agent_output`. Al routing er allerede på plads.
