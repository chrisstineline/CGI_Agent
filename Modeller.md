
# Overskrift

### Claude Agent: Analyse og entry-oprettelse

```mermaid

flowchart TD

    IN["Normaliseret payload\nankommer til Claude Agent"]

  

    subgraph ANALYSE["Claude analyserer"]

        C1["Klassificér type bug · feature · review · spørgsmål"]

        C2["Hent kontekst fra Postgres -> slack_threads, jira_tasks, emails, crm_contacts"]

        C3["Bestem prioritet: kritisk · høj · normal · lav"]

        C4["Vælg agent_pointer baseret på type"]

        C5["Vælg assigned_to baseret på type + prioritet"]

    end

  

    C1 --> C2 --> C3 --> C4 --> C5

  

    ENTRY["Opret ny entry INSERT INTO task_entries"]

  

    IN --> C1

    C5 --> ENTRY

  

    ENTRY --> ROUTE["Rut til agent og send notifikation"]

```
---

### Postgres-drevet Pipeline (Pseudo_toolset.py)

```mermaid
flowchart TD
    JIRA["Jira Cloud API\nGET /rest/api/3/search"]

    subgraph SCRAPER["jira_scraper.py — Deterministisk ETL (cron hvert 5. min)"]
        S1["1 · Hent nye opgaver\nRawJiraTask"]
        S2["2 · Rens og normaliser\nStrip HTML · normaliser priority\nUdled domain + task_type (regelbaseret)"]
        S3["3 · Komprimér beskrivelse\nLLM-kald · max 3 sætninger\nbatch op til 20 opgaver"]
        S4["4 · Generer embedding\ntext-embedding-3-small · 1536 dim\ninput: title + summary"]
        S5["5 · Upsert til Task_DB\nINSERT ... ON CONFLICT DO NOTHING\nOpdater scrape_log"]
        S1 --> S2 --> S3 --> S4 --> S5
    end

    JIRA --> S1

    TASK_DB[("Task_DB\ntask_records\nvector(1536)\nrouting_status = pending")]
    S5 --> TASK_DB

    subgraph ROUTING["Routing Agent (poll hvert 30 sek)"]
        R1["Hent næste pending TaskRecord\ntask_type · priority · embedding"]
        R2{"Regelbaseret\nrouting"}
        R3["Semantisk fallback\ncosine similarity\nmod seneste 100 routed records"]
        R4["Byg AgentTaskPayload\nmed agent-specifik kontekst"]
        R5["Opdater Task_DB\nrouting_status = routed\nrouted_to · routed_at"]
        R1 --> R2
        R2 -- "Ingen regel matcher" --> R3
        R3 --> R4
        R2 -- "Regel matcher" --> R4
        R4 --> R5
    end

    TASK_DB -- "routing_status = pending\ntrigger" --> R1

    TDD_DB[("TDD_agent_db\ntdd_tasks\nstatus: pending")]
    CR_DB[("code_review_db\nreview_tasks\nstatus: pending")]
    PO_DB[("PO_agent_db\npo_tasks\nstatus: pending")]

    R2 -- "task_type = test\neller bug + high priority" --> TDD_DB
    R2 -- "task_type = review" --> CR_DB
    R2 -- "task_type = feature/chore\neller bug + lav prioritet" --> PO_DB
    R3 -- "similarity < 0.75 (fallback)" --> PO_DB

    TDD_DB --> TDD_AGENT["TDD Agent\nTest-first implementering\ntest_coverage_target: 80%"]
    CR_DB --> CR_AGENT["Code Review Agent\nOWASP Top 10 checklist\npr_url · checklist"]
    PO_DB --> PO_AGENT["PO Agent\nScope-evaluering · prioritering\nvalue_score · sprint_target"]

    style SCRAPER fill:#1e3a5f,color:#fff
    style ROUTING fill:#3a1e5f,color:#fff
    style TASK_DB fill:#2d5016,color:#fff
    style TDD_DB fill:#5f3a1e,color:#fff
    style CR_DB fill:#5f3a1e,color:#fff
    style PO_DB fill:#5f3a1e,color:#fff
```

# Build My Brain — Postgres Agent Setup
**Softwareteam-edition** · Slack · Jira · Email · CRM

> Fire datakilder, én hjerne, én query-interface.  
> Claude stiller ét spørgsmål — og kender hele konteksten. Ingen manuel tab-jumping.

---

## Indhold

1. [Overordnet arkitektur](#overordnet-arkitektur)
2. [Databaseskema — The Brain](#databaseskema--the-brain)
3. [Synkroniseringsflow per datakilde](#synkroniseringsflow-per-datakilde)
4. [Claude query-interface](#claude-query-interface)
5. [Fejlhåndtering og resiliens](#fejlhåndtering-og-resiliens)
6. [/build-my-brain prompt](#build-my-brain-prompt)
7. [Eksempel-output: Claude ved](#eksempel-output-claude-ved)

---

## Overordnet arkitektur

Fire uafhængige sync-agenter skriver til Postgres. Claude læser derfra med ét kald.

```mermaid
flowchart TD
    subgraph SOURCES["Datakilder"]
        SL["Slack\nextract_threads"]
        JI["Jira\nget_tasks · get_issues"]
        EM["Email\nparse_inbox"]
        CR["CRM\nfetch_contacts · deals"]
    end

    subgraph SYNC["Sync-agenter (uafhængige)"]
        SA["slack_sync_agent\nReal-time webhook"]
        JA["jira_sync_agent\nHvert 5. minut"]
        EA["email_sync_agent\nHver time"]
        CA["crm_sync_agent\nReal-time webhook"]
    end

    subgraph BRAIN["Postgres — The Brain"]
        ST[("slack_threads")]
        JT[("jira_tasks")]
        EM2[("emails")]
        CC[("crm_contacts")]
        CD[("crm_deals")]
        CTX[("client_context")]
    end

    subgraph CLAUDE["Claude — Query Interface"]
        Q1["get_task_context(issue_key)"]
        Q2["get_client_context(client_name)"]
    end

    SL --> SA --> ST
    JI --> JA --> JT
    EM --> EA --> EM2
    CR --> CA --> CC
    CA --> CD

    ST  --> CTX
    JT  --> CTX
    EM2 --> CTX
    CC  --> CTX
    CD  --> CTX

    CTX --> Q1
    CTX --> Q2
    ST  --> Q1
    JT  --> Q1
    EM2 --> Q2
    CC  --> Q2
    CD  --> Q2
```

---

## Databaseskema — The Brain

### Tabel-oversigt og afhængigheder

```mermaid
erDiagram
    SLACK_THREADS {
        uuid id PK
        string channel
        string ts
        string user_id
        text text
        string client_ref FK
        timestamp synced_at
    }
    JIRA_TASKS {
        uuid id PK
        string issue_key UK
        string title
        string status
        string assignee
        string sprint
        timestamp updated_at
        string client_ref FK
    }
    EMAILS {
        uuid id PK
        string subject
        string from_addr
        string thread_id
        text body
        string client_ref FK
        timestamp ts
    }
    CRM_CONTACTS {
        uuid id PK
        string name
        string company
        string deal_stage
        integer arr
        timestamp last_activity
    }
    CRM_DEALS {
        uuid id PK
        string title
        string stage
        integer value
        string owner
        date close_date
        uuid contact_id FK
    }
    CLIENT_CONTEXT {
        uuid id PK
        string client_id UK
        text summary
        string risk_level
        timestamp last_updated
    }

    CRM_CONTACTS ||--o{ CRM_DEALS : "har"
    CRM_CONTACTS ||--o{ SLACK_THREADS : "refereres i"
    CRM_CONTACTS ||--o{ JIRA_TASKS : "knyttes til"
    CRM_CONTACTS ||--o{ EMAILS : "modtager"
    CRM_CONTACTS ||--|| CLIENT_CONTEXT : "aggregeres i"
```

### Loading order

```mermaid
flowchart LR
    A["1. crm_contacts\n(ingen afhængigheder)"]
    B["2. crm_deals\n(kræver crm_contacts)"]
    C["3. jira_tasks\n(ingen afhængigheder)"]
    D["4. emails\n(kræver crm_contacts)"]
    E["5. slack_threads\n(kræver crm_contacts)"]
    F["6. client_context\n(kræver alle)"]

    A --> B
    A --> D
    A --> E
    A --> F
    B --> F
    C --> F
    D --> F
    E --> F
```

---

## Synkroniseringsflow per datakilde

### Slack — extract_threads

```mermaid
sequenceDiagram
    participant WH as Slack Webhook
    participant SA as slack_sync_agent
    participant PG as Postgres

    WH->>SA: POST /webhook {channel, ts, user, text}
    SA->>SA: Identificér client_ref fra kanal-navn
    SA->>PG: UPSERT slack_threads ON CONFLICT (ts)
    SA->>PG: UPDATE client_context.last_updated
    SA-->>WH: 200 OK
```

### Jira — get_tasks + get_issues

```mermaid
sequenceDiagram
    participant CR as Cron (5 min)
    participant JA as jira_sync_agent
    participant JI as Jira API
    participant PG as Postgres

    CR->>JA: trigger
    JA->>PG: SELECT MAX(updated_at) FROM jira_tasks
    JA->>JI: GET /issues?updatedSince={last_sync}
    JI-->>JA: [{issue_key, title, status, assignee, sprint}]
    loop For hvert issue
        JA->>PG: UPSERT jira_tasks ON CONFLICT (issue_key)
    end
    JA->>PG: UPDATE client_context WHERE linked
```

### Email — parse_inbox

```mermaid
sequenceDiagram
    participant CR as Cron (1 time)
    participant EA as email_sync_agent
    participant GM as Gmail/IMAP
    participant PG as Postgres

    CR->>EA: trigger
    EA->>GM: Hent emails siden sidste sync
    GM-->>EA: [{subject, from, thread_id, body}]
    loop For hver email
        EA->>PG: SELECT id FROM crm_contacts WHERE email = from_addr
        EA->>PG: INSERT emails (client_ref fra kontakt)
    end
```

### CRM — fetch_contacts + deals

```mermaid
sequenceDiagram
    participant WH as CRM Webhook
    participant CA as crm_sync_agent
    participant PG as Postgres

    WH->>CA: POST {event: deal_stage_changed, contact_id, deal}
    CA->>PG: UPSERT crm_contacts ON CONFLICT (id)
    CA->>PG: UPSERT crm_deals ON CONFLICT (id)
    CA->>PG: UPDATE client_context SET risk_level, last_updated
    CA-->>WH: 200 OK
```

---

## Claude query-interface

### get_task_context — flow

```mermaid
flowchart TD
    Q["Claude modtager\nget_task_context('PROJ-421')"]

    Q --> P1["SELECT * FROM jira_tasks\nWHERE issue_key = 'PROJ-421'"]
    Q --> P2["SELECT * FROM slack_threads\nWHERE text ILIKE '%PROJ-421%'\nORDER BY ts DESC LIMIT 5"]
    Q --> P3["SELECT * FROM emails\nWHERE subject ILIKE '%PROJ-421%'"]
    Q --> P4["SELECT c.* FROM crm_contacts c\nJOIN jira_tasks j ON j.client_ref = c.id\nWHERE j.issue_key = 'PROJ-421'"]

    P1 --> R["Samlet kontekst\n→ Claude svarer"]
    P2 --> R
    P3 --> R
    P4 --> R
```

### get_client_context — flow

```mermaid
flowchart TD
    Q["Claude modtager\nget_client_context('Acme Corp')"]

    Q --> L["SELECT * FROM client_context\nWHERE client_id = 'acme-corp'"]
    L --> C{Frisk nok?}

    C -->|"last_updated < 1 time"| CACHED["Returnér cached\nclient_context.summary"]
    C -->|"Forældet"| REBUILD["Rebuild summary\nfra alle 4 tabeller"]

    REBUILD --> S["SELECT nyeste Slack,\nJira, Email, CRM\nfor denne klient"]
    S --> UP["UPDATE client_context\nMED ny summary + risk_level"]
    UP --> CACHED
```

---

## Fejlhåndtering og resiliens

```mermaid
flowchart TD
    TRIGGER["Sync trigger"]
    AGENT["Sync-agent kører"]
    SUCCESS["Skriv til Postgres\nOK"]
    TIMEOUT["Timeout / 5xx fejl"]
    RETRY["Exponential backoff\nmax 3 forsøg"]
    SCHEMA_ERR["Schema-fejl\nugyldigt output"]
    ESCALATE["Eskalér til\nmenneskeligt review"]
    DLQ["Dead Letter Queue\ning intet tabes"]
    CB_OPEN["Circuit Breaker åbner\nefter 5 fejl / 60 sek"]
    FALLBACK["Fallback: log\nmanuel notifikation"]
    HALFOPEN["Halfopen state\ntest-request efter 120 sek"]

    TRIGGER --> AGENT
    AGENT --> SUCCESS
    AGENT --> TIMEOUT
    AGENT --> SCHEMA_ERR

    TIMEOUT --> RETRY
    RETRY -->|"Pass"| SUCCESS
    RETRY -->|"Max retries nået"| DLQ
    DLQ --> FALLBACK

    SCHEMA_ERR --> ESCALATE

    SUCCESS --> CB_OPEN
    TIMEOUT --> CB_OPEN
    CB_OPEN --> HALFOPEN
    HALFOPEN -->|"OK"| AGENT
    HALFOPEN -->|"Fejl"| CB_OPEN
```

---

## /build-my-brain Prompt

Kopiér denne prompt direkte ind i Claude. Udfyld de tre sektioner — Claude stiller opfølgende spørgsmål, inden den genererer schema + loading order + sync-scripts.

```
/build-my-brain

// Mine værktøjer og MCP-forbindelser:
MCP_tools: [Slack, Jira, Gmail, HubSpot]

// Hvad vi laver som team:
business: [beskriv jeres primære arbejde og workflows]

// Hvilken kontekst mister AI'en oftest:
biggest_gap: [fx "ved ikke hvad der sker i en Jira-task
             uden at åbne tre forskellige tools"]

---

Design min Postgres-hjerne.

1. Schema (tabeller + kolonner + typer)
2. Loading order (afhængigheder)
3. Én sync-funktion per datakilde
4. get_task_context([issue_key])     — Claude-tool
5. get_client_context([client_name]) — Claude-tool

// Start med jira_tasks og slack_threads.
// Stil mig spørgsmål først.
// Generer derefter fuld SQL + Python-sync.
```

---

## Eksempel-output: Claude ved

Når en udvikler spørger **"hvad sker der med PROJ-421?"** trækker Claude fra alle fire kilder og svarer med fuld kontekst:

| Kilde | Felt | Værdi |
|---|---|---|
| **Jira** | Issue | PROJ-421 · In Review |
| | Assignee | Kode Karsten |
| | Sprint | Sprint 14 · 2 dage tilbage |
| **Slack** | Kanal | #proj-421-review |
| | Seneste besked | "Venter på QA sign-off" |
| | Tidspunkt | 23 minutter siden |
| **Email** | Emne | PROJ-421 review notes |
| | Fra | kunde@acme.com |
| | Tidspunkt | I dag 09:14 |
| **CRM** | Klient | Acme Corp |
| | Deal | Negotiation · 85k ARR |
| | Risiko | Medium — følg op |

### Dataflow for dette eksempel

```mermaid
sequenceDiagram
    participant Dev as Udvikler
    participant CL as Claude
    participant PG as Postgres

    Dev->>CL: "hvad sker der med PROJ-421?"
    CL->>PG: get_task_context("PROJ-421")

    par Parallelle queries
        PG-->>CL: jira_tasks WHERE issue_key = 'PROJ-421'
    and
        PG-->>CL: slack_threads WHERE text ILIKE '%PROJ-421%'
    and
        PG-->>CL: emails WHERE subject ILIKE '%PROJ-421%'
    and
        PG-->>CL: crm_contacts + crm_deals via client_ref
    end

    CL->>CL: Aggregér til samlet kontekst
    CL-->>Dev: Fuld status: Jira + Slack + Email + CRM
```

---

*Genereret som del af AI Agenter og Assistenter — Level 3 · Softwareteam-edition*
# Knowledge Maps from Build My Brain v2

This file contains knowledge maps extracted and converted from the mindmap-style diagrams in build_my_brain_v2.md.

## Task Status Lifecycle Knowledge Map

```mermaid
mindmap
  Task_Status((Task Status Lifecycle))
    new
      routed
        in_progress
          done
```

## Task Type to Agent to Person Routing Knowledge Map

```mermaid
mindmap
  Task_Types((Task Types))
    bug
      Bug_Triage_Agent
        Junior_Dev
    review
      Code_Review_Agent
        Senior_Dev
    feature
      PO_Assistant
        Product_Owner
    general
      TDD_Agent
        Junior_Dev
```

## SLA Escalation Chain Knowledge Map

```mermaid
mindmap
  Escalation((SLA Escalation))
    Assigned
      Senior_Dev
        Product_Owner
          On_call_Management
```

## Agent Output Knowledge Map

```mermaid
mindmap
  Agents((Agents))
    Bug_Triage_Agent
      root_cause_suggested_fix
    Code_Review_Agent
      issues_verdict
    PO_Assistant
      user_story_acceptance_criteria
    TDD_Agent
      tests_coverage_target
```

## Message Normalization Knowledge Map

```mermaid
mindmap
  Sources((Message Sources))
    Email
      Normalized_Payload
        Claude_Agent
    Slack
      Normalized_Payload
```

## Message Processing Flow Knowledge Map

```mermaid
mindmap
  Processing((Message Processing))
    New_Message
      Type_Determined
        Bug
          Bug_Agent_Junior
        Review
          CR_Agent_Senior
        Feature
          PO_Agent_Product_Owner
        General
          TDD_Agent_Junior
      Routed
        In_Progress
          Done
```
# Multi-database arkitektur — Mermaid diagrammer
**Splittet Postgres · Event Bus · AI Agenter · Bruger-kæde**

---

## Diagram 1 — Overordnet arkitektur

```mermaid
flowchart TD
    EM["Email"]
    SL["Slack"]
    CA["Claude routing-agent\nKlassificér · prioritér · rut"]

    EM --> CA
    SL --> CA

    BUS["Event bus\ntask.created · task.updated · sync.needed · agent.done"]
    CA --> BUS

    RDB[("routing_db\ntask_entries · routing")]
    ADB[("agent_db\nregistry · output · state")]
    UDB[("user_db\nuser_chain · assignment")]
    AUDB[("audit_db\nimmutable log")]

    BUS --> RDB
    BUS --> ADB
    BUS --> UDB
    BUS --> AUDB

    SYNC(["sync scripts\npolling · CDC · webhooks"])

    RDB -.-> SYNC
    ADB -.-> SYNC
    UDB -.-> SYNC
    AUDB -.-> SYNC

    TDD["TDD agent"]
    CR["Code review agent"]
    PO["PO agent"]
    DEV["Udvikler agent"]

    SYNC --> TDD
    SYNC --> CR
    SYNC --> PO
    SYNC --> DEV

    TDD & CR & PO & DEV -.->|agent.done| BUS

    JR["Junior dev"]
    SR["Senior developer"]
    PROD["Product owner"]
    QA["QA engineer"]

    TDD -->|"notify"| JR
    CR  -->|"notify"| SR
    PO  -->|"notify"| PROD
    DEV -->|"notify"| QA
```

---

## Diagram 2 — Sync-lag og scripts

```mermaid
flowchart TD
    BUS["Event bus"]

    subgraph DBS["Databaser"]
        RDB[("routing_db\ntask_entries")]
        ADB[("agent_db\nagent_output")]
        UDB[("user_db\nuser_chain")]
        AUDB[("audit_db\nimmutable log")]
    end

    BUS -->|"task.assigned"| RDB
    BUS -->|"agent.triggered"| ADB
    BUS -->|"user.resolved"| UDB
    BUS -->|"audit.written"| AUDB

    subgraph SCRIPTS["Sync scripts"]
        CDC["cdc_routing_sync.py\nLytter på WAL · CDC"]
        POLL["poll_agent_output.py\nPoller hvert 30s"]
        WHOOK["sync_user_assignment.py\nWebhook-drevet"]
        AW["audit_writer.py\nAlle events · append-only"]
    end

    RDB  --> CDC
    ADB  --> POLL
    UDB  --> WHOOK
    AUDB --> AW

    CDC   -->|"task.created / task.updated"| BUS
    POLL  -->|"agent.done"| BUS
    WHOOK -->|"user.assigned"| BUS
    AW    -->|"audit.write"| AUDB
```

---

## Diagram 3 — Agent-kommunikation og event-flow

```mermaid
sequenceDiagram
    participant RDB as routing_db
    participant ADB as agent_db
    participant UDB as user_db
    participant AUDB as audit_db
    participant BUS as Event bus
    participant TDD as TDD agent
    participant CR as Code review agent
    participant PO as PO agent
    participant DEV as Udvikler agent
    participant USR as Bruger-kæde

    Note over BUS: task.created modtaget fra Claude routing-agent

    BUS->>RDB: Gem task_entry (type, prioritet, agent_pointer)
    BUS->>AUDB: audit.write — task oprettet

    RDB->>BUS: task.assigned (cdc_routing_sync.py)

    par Parallel agent-routing baseret på type
        BUS->>TDD: task.assigned — type: general
        TDD->>ADB: INSERT test_suite output
        TDD->>BUS: agent.done
        TDD->>USR: notify — Junior dev

    and
        BUS->>CR: task.assigned — type: review
        CR->>ADB: INSERT review_findings
        CR->>BUS: agent.done
        CR->>USR: notify — Senior developer

    and
        BUS->>PO: task.assigned — type: feature
        PO->>ADB: INSERT user_story
        PO->>BUS: agent.done
        PO->>USR: notify — Product owner

    and
        BUS->>DEV: task.assigned — type: bug
        DEV->>ADB: INSERT code_draft
        DEV->>BUS: agent.done
        DEV->>USR: notify — Junior dev / Senior dev
    end

    ADB->>BUS: agent.done (poll_agent_output.py · 30s)
    BUS->>RDB: UPDATE task_entries SET status = in_progress
    BUS->>AUDB: audit.write — agent færdig

    Note over UDB: Eskalering ved SLA-overskridelse
    UDB->>BUS: user.escalated (sync_user_assignment.py)
    BUS->>RDB: UPDATE assigned_to → næste niveau
    BUS->>USR: notify — eskaleret bruger
    BUS->>AUDB: audit.write — eskalering logget
```

---

## Diagram 4 — Databaseskema og relationer

```mermaid
erDiagram
    TASK_ENTRIES {
        uuid id PK
        string source "email eller slack"
        string source_ref "thread_id eller slack_ts"
        text claude_summary
        string type "bug, feature, review, general"
        string priority "critical, high, normal, low"
        string status "new, routed, in_progress, done"
        string agent_pointer FK "agent_registry.agent_name"
        uuid assigned_to FK "user_chain.id"
        timestamp created_at
        timestamp routed_at
    }

    AGENT_REGISTRY {
        uuid id PK
        string agent_name UK
        string trigger_on "type der aktiverer agenten"
        string webhook_url
        boolean active
    }

    AGENT_OUTPUT {
        uuid id PK
        uuid task_entry_id FK
        string agent_name FK
        jsonb result "test_suite, review_findings, user_story, code_draft"
        string status "pending, done, failed"
        timestamp created_at
    }

    USER_CHAIN {
        uuid id PK
        string name
        string role "junior_dev, senior_dev, product_owner, qa"
        string slack_user_id
        integer escalation_level
        uuid fallback_user_id FK
        integer sla_hours
    }

    ESCALATION_LOG {
        uuid id PK
        uuid task_entry_id FK
        uuid from_user_id FK
        uuid to_user_id FK
        string reason
        timestamp escalated_at
    }

    AUDIT_LOG {
        uuid id PK
        string event_type
        uuid entity_id
        jsonb payload
        timestamp occurred_at
    }

    TASK_ENTRIES ||--|| AGENT_REGISTRY : "agent_pointer"
    TASK_ENTRIES ||--|| USER_CHAIN     : "assigned_to"
    TASK_ENTRIES ||--o{ AGENT_OUTPUT   : "producerer"
    TASK_ENTRIES ||--o{ ESCALATION_LOG : "eskaleres via"
    USER_CHAIN   ||--o{ ESCALATION_LOG : "involveret i"
    USER_CHAIN   ||--o| USER_CHAIN     : "fallback_user"
```

---

## Diagram 5 — Fejlhåndtering og resiliens

```mermaid
flowchart TD
    BUS["Event bus\ntask.assigned"]

    AG["Agent trigges\nvia webhook"]

    BUS --> AG

    AG --> OK["Output skrevet\ntil agent_db"]
    AG --> TIMEOUT["Timeout / 5xx"]
    AG --> SCHEMA["Schema-fejl\nugyldigt output"]

    TIMEOUT --> RETRY["Exponential backoff\nmax 3 forsøg · jitter"]
    RETRY -->|"Pass"| OK
    RETRY -->|"Max retries"| DLQ["Dead letter queue\nIntet tabes"]

    SCHEMA --> ESC["Eskalér til\nmenneskeligt review"]

    OK --> CB{"Circuit breaker\ncheck"}
    TIMEOUT --> CB

    CB -->|"5 fejl / 60 sek"| OPEN["Breaker åbner\nAgent lukkes ned"]
    OPEN --> FALLBACK["Fallback:\nHuman-in-the-loop"]
    OPEN --> HALF["Halfopen state\nEfter 120 sek"]
    HALF -->|"Test OK"| AG
    HALF -->|"Test fejl"| OPEN

    OK --> AUDB[("audit_db\nEvent logget")]
    DLQ --> AUDB
    ESC --> AUDB
```

---

*Genereret fra multi-database agent-arkitektur · Splittet Postgres-model*
```mermaid
flowchart TD
    Jira(["🔔 Jira Task\nOrchestrator Trigger"])

    CR["customer_request_skill\n— Agent —"]
    PO["po_agent_skill\n— Agent —"]
    CTX["context_agent_skill\n— Agent —"]
    CA["coding_assistant_skill\n— Assistant —"]
    DEV{"Developer\ngodkender?"}
    TDD["tdd_agent_skill\n— Agent / Sandkasse —"]
    RETRY{"Retry\nforsøg?"}
    BLOCKED(["🚨 Blocked\nEskaleret til menneske"])
    PRa["pr_agent_skill\n— Agent —"]
    RA["review_assistant_skill\n— Assistant / Supervisor —"]
    RISK{"Risiko-\nniveau?"}
    RA_AUTO["Auto-godkend\nSupervisor"]
    REVIEWER{"Reviewer\nbeslutning?"}
    DA["delivery_assistant_skill\n— Assistant —"]
    PO_GATE{"PO\ngodkender?"}
    DONE(["✅ Deployed"])

    Jira --> CR
    CR -->|StructuredSpec| PO
    PO -->|ContextPackage| CTX
    CTX -->|EnrichedContext| CA
    CA -->|Præsenter CodeDraft| DEV
    DEV -->|"Afvis + feedback"| CA
    DEV -->|Godkend| TDD

    TDD -->|"pass — coverage ≥80%"| PRa
    TDD -->|fail| RETRY
    RETRY -->|"Forsøg 1–3"| CA
    RETRY -->|"Forsøg 4"| BLOCKED

    PRa -->|PullRequest| RA
    RA --> RISK
    RISK -->|Lav-risiko| RA_AUTO
    RISK -->|Høj-risiko| REVIEWER
    RA_AUTO --> DA
    REVIEWER -->|approve| DA
    REVIEWER -->|changes| CA

    DA -->|Præsenter DeliveryPackage| PO_GATE
    PO_GATE -->|"Afvis"| DA
    PO_GATE -->|Godkend| DONE

    classDef agent fill:#1e3a5f,color:#ffffff,stroke:#3b82f6,stroke-width:2px
    classDef assistant fill:#3b1f5e,color:#ffffff,stroke:#a855f7,stroke-width:2px
    classDef gate fill:#1a3a2a,color:#ffffff,stroke:#22c55e,stroke-width:2px
    classDef terminal fill:#374151,color:#ffffff,stroke:#6b7280,stroke-width:2px
    classDef blocked fill:#4a1515,color:#ffffff,stroke:#ef4444,stroke-width:2px

    class CR,PO,CTX,TDD,PRa,RA_AUTO agent
    class CA,RA,DA assistant
    class DEV,RISK,REVIEWER,RETRY,PO_GATE gate
    class Jira,DONE terminal
    class BLOCKED blocked
```
