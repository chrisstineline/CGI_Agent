# Mindre MCP mere Postgres 

Når en agent får en opgave, sker der automatisk en ETL process, ekslusivt til den. Den ETL process kræver en del ressourcer (tokens), og forbliver ekslusivt i selve agenten. Det forhindrer potentielt proper logging og back-tracking af f.eks. opgaver eller behandlingen af dataene i en opgave. 

For at bevare en konstant record af hvad der sker i et større setup, og skrue ned for token-forbruget, kan en Postgres (eller anden DB) være "hjernen" i en pipeline. Det repræsenterer et deterministisk orkestreret system. Agenter møder aldrig rå data, og det løser nogle økonomiske og sikkerheds-mæssige aspekter.

Antag der skrives en ny opgave i Jira, hvor der er sat et automatisk script up, der oversætter opgaven til et kortere format. 

I diagrammet vises en overfladisk løsning, hvor AI agenten først får viden om opgaven, efter den er blevet scrapet med kontekst og gemt. 

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


Processen er automatiseret, men via scripts, frem for agenter der initierer hvert step. Agenterne tager først fat i dataene, når de er blevet konkretiseret (efter ETL processerne), og så kan initiere arbejdet. 

Dataene bliver statiske, og lettere at kontrollere. Ligeledes er der færre led i kæden, hvor AI har haft det begyndende arbejde, før opgaven kan løses. 

| **Postgres** | **AI swarm** |
|----------|----------|
| Intelligens starter efter data registreringen | "Intelligens" er brugt til at kunne finde dataene |
| Dataene er gemt som "intelligens" | "Intelligensen" konstituerer hvad dataene er | 
| Labels bestemmer hvad, hvor eller hvorfor dataene har relevans | AI'en skal regne det ud baseret på labels |
| Deterministisk system | Indbyrdes koordinering |
| Alt er auditabilitet | Ting kan forsvinde |
-----------


Er  "dataene gemt som intelligens" — det vil sige at de beslutninger der normalt kræver AI-inferens (hvad er dette, hvad betyder det, hvad er det relateret til?) allerede er konverteret til strukturerede felter og vektorer. Intelligensen er krystalliseret i databasen.

I Postgres-modellen er ingestion-scriptet skrevet til at prioritere Jira-labelens værdi og gemme den som priority: critical i **[TASK_ENTRIES*]**. Det er en menneskelig beslutning, nedfældet i kode, der gælder én gang for alle.


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


Product Owner kan også initere infomations-gathering. 

```mermaid
sequenceDiagram
    participant Dev as PO
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


## Postgres med agenter

Med Postgres løsningen, bliver der inkluderet flere led i kæden, der er menneske-bestemete, og kan sepereres ligesom ved microservice arkitektur under et monorepo-lignende system. Fordele er igen; kontrol og bestemmelse over setup, hvor ambiguøst arbejde ikke går tabt i agenternes funktioner og processer. 

Ved opdelingen af den monorepo-lignende struktur, kan der bevares strukturel sikkerhed, og isoleres mod andre isolerede agenter. 


------------ 

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

## Sammenspillet

Scriptet der tager og håndterer opgaver fra Jira, laver fundamentet for et nyt datalag for sematiske vektorer, hvor en routing agent, kunne tage opgaven at dirigere de opgaven via en event bus, til en passende modtager. Den sematiske vektor i opgaven beskrevet af en LLM (efter ETL-script delen), bliver også mere betydningsfuld mht. traceability og normaliseringen af processerne, fordi det er det eneste sted, hvor "rå data" bliver behandlet ud fra strenge regler. 

Agenterne der modtager det input, har også den samme forståelse af dette pga. normaliserignen, og den ensartede proess. 

Derefter kommer agent-fasen, hvor får opgaven, og stille spørgsmålene til *"har jeg brug for mere kontekst?"* (laver kald til knowledge base via Retrieval Tool(del af agent SKILL.md)), eller kører direkte ud med f.eks. en TDD-implementering. 

Postgres-laget fungerer som et monorepo-lignende fundament: én autoritativ kilde til opgave-state, routing-beslutninger og audit trail. Men de individuelle agenter — TDD-agenten, code review-agenten, PO-agenten og udvikler-agenten — kan isoleres og deployes som selvstændige services med egne databaser *(agent_db, user_db, audit_db)*, forbundet via en event bus. 
Der opnåes sammenspil og kontinuerlighed i et kontrolleret multi-isoleret system. 

Det er her den hybride styrke opstår. Postgres-fundamentet giver det deterministiske lag: **[TASK_ENTRIES]** er single source of truth, **[AGENT_REGISTRY]** definerer hvilke agenter der eksisterer og hvad der trigger dem, og **[AUDIT_LOG]** er den immutable kæde af hvad der skete. Event bus-laget giver det distribuerede lag: agenter abonnerer på events som task.created og task.assigned, handler uafhængigt, og publicerer *agent.done* tilbage til bussen uden at kende til hinandens interne tilstand.

Det kritiske designvalg er at **routing-agenten** — den agent der fordeler opgaver til de specialiserede agenter — ikke er en AI-agent i traditionel forstand. Den er et deterministisk script der læser **[agent_pointer]** fra **[TASK_ENTRIES]** og kalder den rette webhook. AI'en er allerede brugt til at sætte **[agent_pointer]**-værdien under klassificering. Routing-steget selv kræver ingen inferens — det er tabelopslag.
Det er den grundlæggende arkitektoniske indsigt: sæt AI der hvor der er reel ambiguitet, og sæt deterministisk kode alle andre steder. Postgres er det sted hvor de to mødes.

*Nedenunder er et diagram, der illustrerer opdelingen.*

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


## Skalerbarhed og gentagelser

Når den monorepo-lignende struktur splittes på tværs af fire databaser — **routing_db, agent_db, user_db, audit_db** — bevares den strukturelle sikkerhed fra det samlede system, men isolationen øges markant.
En fejl i agent_db påvirker ikke routing_dbs evne til at modtage nye opgaver. En tung load på TDD-agentens output-tabeller sænker ikke eskaleringslogikkens responstid. Og audit_db er append-only og isoleret, hvilket betyder at en kompromitteret agent aldrig kan slette sine egne spor.

Det kan kopires og genbruges, eller køres tilbage med databasernes elementer som backup, hvis nødvendigt. 



### Noter: 

Givet den seneste uodate fra Anthropic om Mythos modellen, og alle de angreb der sker via AI, er der en potentiel fremtidssikring ved Postgres-lag-på-lag løsningen --> isoleringen og opsætningen af auth. på access, kan (måske) minimere flere problemer: 

- Hvert lag er sit eget fortress --> uønsket adgang/ aktivitet kræver en del mere direkte arbejde, og hele "tæppet" kan ikke trækkes op, ved at hive i én tråd. 
- AI agenterne er isoleret fra hinanden og omverdenen: de kan ikke sladre om viden/ data/ lært viden fra AI brugen
- Jira opgaverne er isoleret i struktureret tables --> vidensflow er direkt og modtager-bestemt. 
    - Det samme med email, Slack beskeder, pull-requests. Jira agenten MÅ IKKE vide noget om emails, eller hvilken kode der sendes til prod - den må ikke blive forvirret, eller være i stand til at sende den viden videre. 
- Live, learn, do better --> det hele (agent in- og output) er struktureret gemt, og kan analyseres => forbedringer muliggøres, uden at uendelige eksperimenter skal køres, for at isolere specifikke pointers. (Føj en omgang tokens der skulle til, for at lære "Jira OG code-review agenterne tror alle opgaver er kritiske" -> log har tags, alt er oplyst). 
- Labels ift. en AI swarm (flere agenter) er spændende, fordi det måske er en difference mellem angivelsen på Slack vs. Jira. Har opgaven på Jira fået "Kritisk" label, og parsed igennem til Postgres DB'en, bliver det reglen for opgaven når den samles op af agenten, men kunne med anden fortolkning af en anden agent. 

## Bonus modeller



| Flow fra eventbus
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

<br>
<br>


