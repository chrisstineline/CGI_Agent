# Modeller i dokumenterne

## Intro modeller

| Simpelt flow
```mermaid
flowchart TD
    K["Kunde opretter opgave"]
    A1["Reaktiv Agent <br> Læser opgaven"]
    A2["Agent <br> Analyserer koden"]
    AS["Assistant <br> Hjælper udvikleren"]
    DEV["Udvikler <br> godkender"]
    DONE["Resultat valideret <br> og leveret"]

    K --> A1
    A1 -->|"Initierer automatisk"| A2
    A2 -->|"Præsenterer analyse"| AS
    AS -->|"Afventer godkendelse"| DEV
    DEV --> DONE
```
---------- 

| Flere typer modtagere baseret på task og rolle

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

## Advanced modeller

| Agent til assistant til developer
```mermaid
flowchart TD
Agent --> Assistant
Assistant --> Developer
Developer --> Assistant
Assistant --> Agent
```
--------------

| Fire lag, statememory

```mermaid
flowchart LR

User["User / Customer"]
Jira["Jira (Orchestrator)"]

Agents["AI Agents Layer"]
Assistants["Assistants Layer"]
DB["State / Memory"]

User --> Jira
Jira --> Agents
Agents --> Assistants
Agents --> DB
Assistants --> DB
Assistants --> User
```
----------------

| Flere agenter og assistants i serie

```mermaid
flowchart TD

A["Customer-request-agent"]
B["Product-owner-agent"]
C["Context-agent"]
D["Coding-assistant"]
E["Test-runner-agent"]
F["Pull-request-agent"]
G["Review-assistant"]
H["Delivery-assistant"]

A --> B --> C --> D --> E
E -->|pass| F --> G --> H
E -->|fail| D
G -->|changes| D
```
----------------

| Simpel chain

```mermaid
flowchart TD

A["Task Created"]
B["Agent Processes"]
C["Assistant Validates"]
D["Feedback"]
E["Update Task"]

A --> B --> C --> D --> E --> B
```
-----------------

| Super simpel chain

```mermaid
stateDiagram-v2

[*] --> Created
Created --> Processing
Processing --> Testing
Testing --> Review
Review --> Approved
Review --> ChangesRequested
ChangesRequested --> Processing
Approved --> Deployed
Deployed --> [*]
```
------------------

| Flere input, agenter, task databaser
```mermaid
flowchart TD
    EM["Email"]
    SL["Slack"]
    CA["Claude routing-agent <br> Klassificér · prioritér · rut"]

    EM --> CA
    SL --> CA

    BUS["Event bus <br> task.created · task.updated · sync.needed · agent.done"]
    CA --> BUS

    RDB[("routing_db <br> task_entries · routing")]
    ADB[("agent_db <br> registry · output · state")]
    UDB[("user_db <br> user_chain · assignment")]
    AUDB[("audit_db <br> immutable log")]

    BUS --> RDB
    BUS --> ADB
    BUS --> UDB
    BUS --> AUDB

    SYNC(["sync scripts <br> polling · CDC · webhooks"])
    %% CDC Change Data Capture

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
----------------

| Flere agenter, flere states, flere outcomes

``` mermaid
flowchart TD
    Jira(["Jira Task <br> Orchestrator Trigger"])

    CR["customer_request_skill <br> — Agent —"]
    PO["po_agent_skill <br> — Agent —"]
    CTX["context_agent_skill <br> — Agent —"]
    CA["coding_assistant_skill <br> — Assistant —"]
    DEV{"Developer <br> godkender?"}
    TDD["tdd_agent_skill <br> — Agent / Sandkasse —"]
    RETRY{"Retry <br> forsøg?"}
    BLOCKED(["Blocked <br> Eskaleret til menneske"])
    PRa["pr_agent_skill <br> — Agent —"]
    RA["review_assistant_skill <br> — Assistant / Supervisor —"]
    RISK{"Risiko- <br> niveau?"}
    RA_AUTO["Auto-godkend <br> Supervisor"]
    REVIEWER{"Reviewer <br> beslutning?"}
    DA["delivery_assistant_skill\ <br> — Assistant —"]
    PO_GATE{"PO\ <br> godkender?"}
    DONE(["Deployed"])

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

## Postgres modeller

| Flere typer input, script til datahåndtering, --> agent
```mermaid
flowchart LR
    subgraph Data-Sources [1: Data Sources]
        J["Jira Cloud API"]
        S[Slack API]
        E[Email/SMTP]
    end
    subgraph ETL_Scripts [2: ETL & Embeddings Pipeline]
        JS[Ingestion Script: Fetching & Cleaning]
        LP["Embedding Process: Generates Vectors (LLM)"]
    end
    subgraph Data_Layer [3: Data Layer: Postgres]
        V[(Postgres pgvector)]
        T[(Structured Data / Text)]
    end
    subgraph AI_Execution [4: Agent Interaction Loop]
        A[Primary AI Agent]
        Q{Needs Context?}
        K[Knowledge Base Retrieval Tool]
    end

    %% Flow: Data Collection
    J -->|Task Details| JS
    S -->|Channels/Messages| JS
    E -->|Email Body| JS

    JS -->|Cleaned Text Data| T
    JS -->|Cleaned Text Data| LP
    LP -->|Semantic Embeddings| V

    %% Flow: Agent Operation
    A --> Q
    Q -- Yes --> K
    Q -- No --> X[Task Complete]

    K <--> |1: Search Queries| V
    K <--> |2: Key Lookups| T
    K --> |3: Comprehensive Context Bundle| A
```
------------------

| Claude ex. ud fra projekt-opgave m. ID

```mermaid
flowchart TD
    Q["Claude modtager\nget_task_context('PROJ-421')"]

    Q --> P1["SELECT * FROM jira_tasks WHERE issue_key = 'PROJ-421'"]
    Q --> P2["SELECT * FROM slack_threads WHERE text ILIKE '%PROJ-421%' ORDER BY ts DESC LIMIT 5"]
    Q --> P3["SELECT * FROM emails WHERE subject ILIKE '%PROJ-421%'"]
    Q --> P4["SELECT c.* FROM crm_contacts c JOIN jira_tasks j ON j.client_ref = c.id\nWHERE j.issue_key = 'PROJ-421'"]

    P1 --> R["Samlet kontekst → <br> Claude svarer"]
    P2 --> R
    P3 --> R
    P4 --> R
```
-------------------

| PO til Jira Agent "Hvad sker der med Projekt 421? (Tak, gør det rigtigt, ingen fejl.)" 

```mermaid
sequenceDiagram
    participant Dev as PO
    participant CL as Agent
    participant PG as Postgres

    Dev->>CL: "hvad sker der med PROJ-421?"
    CL->>PG: get_task_context("PROJ-421")

    par Parallelle queries
        PG-->>CL: jira_tasks WHERE issue_key = 'PROJ-421'
    and
        PG-->>CL: slack_threads WHERE text '%PROJ-421%'
    and
        PG-->>CL: emails WHERE subject '%PROJ-421%'
    and
        PG-->>CL: crm_contacts + crm_deals via client_ref
    end

    CL->>CL: Aggregér til samlet kontekst
    CL-->>Dev: Fuld status: Jira + Slack + Email + CRM
```

---------------

| Ex. data struktur til input til agent

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
-------------

| Flere input, flere db's
```mermaid

flowchart TD
    subgraph SOURCES["Datakilder"]
        SL["Slack extract_threads"]
        JI["Jira get_tasks · get_issues"]
        EM["Email parse_inbox"]
        %% CR["CRM fetch_contacts · deals"]
    end

    subgraph SYNC["Sync-scripts (uafhængige)"]
        SA["slack_sync_script Real-time webhook"]
        JA["jira_sync_script Hvert 5. minut"]
        EA["email_sync_script Hver time"]
        %% CA["crm_sync_script Real-time webhook"]
    end

    subgraph BRAIN["Postgres DBs / Agent input layer"]
        ST[("slack_threads")]
        JT[("jira_tasks")]
        EM2[("emails")]
        %% CC[("crm_contacts")]
        %% CD[("crm_deals")]
        CTX[("client_context")]
    end

    subgraph CLAUDE["AI Agent — Query Interface"]
        Q1["get_task_context(issue_key)"]
        Q2["get_client_context(client_name)"]
    end

    SL --> SA --> ST
    JI --> JA --> JT
    EM --> EA --> EM2
    %% CR --> CA --> CC
    %% CA --> CD

    %% ST  --> CTX
    %% JT  --> CTX
    %% EM2 --> CTX
    %% CC  --> CTX
    %% CD  --> CTX

    CTX --> Q1
    CTX --> Q2
    ST  --> Q1
    JT  --> Q1
    EM2 --> Q2
    %% CC  --> Q2
    %% CD  --> Q2
```

--------------------

| Den store med agenter, automatiseret led, flere modtagere, godkendt/ ikke godkendt

```mermaid
flowchart TD
    BUS["Event bus <br> agent.done · task.assigned · user.escalated"]

    subgraph AGENTS["Agenter"]
        TDD["TDD agent <br> type: general / bug + høj prioritet"]
        CR["Code review agent <br> type: review"]
        PO["PO agent <br> type: feature / chore"]
        DEV["Udvikler agent <br> type: bug"]
    end

    BUS -->|"task.assigned"| TDD
    BUS -->|"task.assigned"| CR
    BUS -->|"task.assigned"| PO
    BUS -->|"task.assigned"| DEV

    subgraph NOTIF["Notifikationskanal (Slack)"]
        N1["notify_slack(user_id, message, task_ref)"]
    end

    TDD -->|"agent.done · opgave klar til review"| N1
    CR  -->|"agent.done · review findings klar"| N1
    PO  -->|"agent.done · user story klar"| N1
    DEV -->|"agent.done · code draft klar"| N1

    subgraph USERS["Brugere"]
        JR["Junior Dev <br> Modtager: TDD output · code draft"]
        SR["Senior Developer <br> Modtager: Code review findings"]
        PROD["Product Owner <br> Modtager: User story · delivery package"]
        QA["QA Engineer <br> Modtager: Dev output til test"]
    end

    N1 -->|"@junior_dev — ny opgave klar"| JR
    N1 -->|"@senior_dev — review klar"| SR
    N1 -->|"@product_owner — story klar"| PROD
    N1 -->|"@qa_engineer — klar til test"| QA

    subgraph ESCALATION["SLA-eskalering"]
        E1{"SLA <br> overholdt?"}
        ESC1["Eskalér til <br> Senior Dev"]
        ESC2["Eskalér til <br> Product Owner"]
        ESC3["Eskalér til <br> On-call Management"]
    end

    JR -->|"SLA overskredet"| E1
    SR -->|"SLA overskredet"| E1
    E1 -->|"Niveau 1"| ESC1
    ESC1 -->|"Stadig ikke løst"| ESC2
    ESC2 -->|"Stadig ikke løst"| ESC3

    AUDB[("audit_db <br> Alle notifikationer logget")]
    N1 -->|"audit.godkendt"| AUDB
    ESC1 & ESC2 & ESC3 -->|"audit.godkendt"| AUDB

    classDef agent fill:#1e3a5f,color:#ffffff,stroke:#3b82f6,stroke-width:2px
    classDef user fill:#1a3a2a,color:#ffffff,stroke:#22c55e,stroke-width:2px
    classDef escalate fill:#4a1515,color:#ffffff,stroke:#ef4444,stroke-width:2px
    classDef infra fill:#374151,color:#ffffff,stroke:#6b7280,stroke-width:2px

    class TDD,CR,PO,DEV agent
    class JR,SR,PROD,QA user
    class ESC1,ESC2,ESC3 escalate
    class BUS,N1,AUDB infra
```