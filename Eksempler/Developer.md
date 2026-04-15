# Developer Good Practice — Postgres Agent System

Best practices, mønstre og konkrete eksempler for udviklere der bygger agenter i Postgres-løsningen. Dokumentet fungerer som en reference: læs den relevante sektion når du implementerer, ikke nødvendigvis fra start til slut.

---

## Indhold

1. [Mappestruktur](#1-mappestruktur)
2. [SKILL.md — skriv kontrakten først](#2-skillmd--skriv-kontrakten-først)
3. [Database-adgang: MCP, ikke direkte SQL](#3-database-adgang-mcp-ikke-direkte-sql)
4. [Kontekst-hentning: ét kald, normaliseret data](#4-kontekst-hentning-ét-kald-normaliseret-data)
5. [Prompt-konstruktion: minimal, struktureret, reproducerbar](#5-prompt-konstruktion-minimal-struktureret-reproducerbar)
6. [Output-håndtering: struktureret JSON, altid valideret](#6-output-håndtering-struktureret-json-altid-valideret)
7. [Fejlhåndtering: retry → circuit breaker → eskalering](#7-fejlhåndtering-retry--circuit-breaker--eskalering)
8. [State machine: respektér statens regler](#8-state-machine-respektér-statens-regler)
9. [Event bus: publicér og lyt korrekt](#9-event-bus-publicér-og-lyt-korrekt)
10. [Metrics: instrument alt](#10-metrics-instrument-alt)
11. [Logging: JSON, altid](#11-logging-json-altid)
12. [Sikkerhed: secrets, permissions, audit](#12-sikkerhed-secrets-permissions-audit)
13. [Testing: agenten er kode, test den som kode](#13-testing-agenten-er-kode-test-den-som-kode)
14. [Anti-patterns: undgå disse fejl](#14-anti-patterns-undgå-disse-fejl)
15. [Komplet eksempel: ny agent fra scratch](#15-komplet-eksempel-ny-agent-fra-scratch)

---

## 1. Mappestruktur

Hver agent lever i sin egen mappe med en fast struktur. Ingen agent deler filer med andre agenter ud over `shared/`.

```
project/
├── .env                        # aldrig i Git
├── .env.example                # skabelon til nye udviklere
├── db/
│   ├── schema.sql              # alle CREATE TABLE statements
│   └── connections.py          # database-connection manager
├── bus/
│   ├── publisher.py            # event-publishing
│   └── consumer.py             # event-consumption
├── mcp/
│   ├── server.py               # MCP gateway
│   └── tools/                  # MCP tool-implementeringer
├── agents/
│   ├── shared/                 # ← delt kode, ALDRIG agent-specifik logik
│   │   ├── context.py          # get_task_context()
│   │   ├── retry.py            # with_retry()
│   │   ├── circuit_breaker.py  # CircuitBreaker klasse
│   │   ├── bulkhead.py         # prioritets-limiter
│   │   ├── metrics.py          # track_agent_call()
│   │   ├── notify.py           # notify_reviewer()
│   │   ├── mcp_client.py       # MCPClient wrapper
│   │   └── logging_config.py   # JSON-formateret logging
│   ├── tdd_agent/
│   │   ├── SKILL.md            # ← kontrakten
│   │   ├── agent.py            # ← kernelogik
│   │   ├── run.py              # ← event-loop
│   │   └── prompts/
│   │       └── system.md       # system-prompt
│   ├── review_agent/
│   │   ├── SKILL.md
│   │   ├── agent.py
│   │   ├── run.py
│   │   └── prompts/
│   │       └── system.md
│   └── po_agent/
│       ├── SKILL.md
│       ├── agent.py
│       ├── run.py
│       └── prompts/
│           └── system.md
└── tests/
    ├── test_tdd_agent.py
    ├── test_review_agent.py
    └── conftest.py             # fixtures: mock-db, mock-llm
```

### Regler

| Regel | Forklaring |
|-------|-----------|
| **Én agent = én mappe** | Gør det muligt at deploye, teste og skalere uafhængigt |
| **SKILL.md er det første** | Skrives før `agent.py` — kontrakten styrer koden, ikke omvendt |
| **`shared/` er infrastruktur** | Retry, metrics, logging, MCP-klient. Ingen domænelogik |
| **Prompts i filer, ikke i kode** | `prompts/system.md` kan ændres uden at deploye ny kode |
| **`.env` aldrig i Git** | Brug `.env.example` som skabelon |

---

## 2. SKILL.md — skriv kontrakten først

SKILL.md er agentens kontrakt. Den er **bindende** — ikke vejledende. Alt hvad agenten gør skal kunne spores tilbage til hvad SKILL.md tillader.

### ✅ God SKILL.md

```markdown
# Agent Name: Code Review Agent

## Purpose
Analysér code diffs og identificér bugs, security-issues og style-violations.
Aktiveres KUN på opgaver af type 'code_review' med status 'routed'.

## Capabilities
- Læse kodebase via MCP (read-only)
- Sammenligne med tidligere reviews (semantisk søgning)
- Generere struktureret review-rapport

## Allowed
- MCP tools: get_task_context, search_similar_tasks, save_agent_output
- Læse agent_output fra andre agenter på SAMME opgave
- Skrive til agent_output med agent_name = 'review_agent'

## Forbidden
- Modificere kode direkte
- Approve/merge pull requests
- Tilgå andre opgavers data
- Skrive til routing_db eller user_db
- Kalde eksterne APIs uden MCP

## Output Format
{
  "findings": [
    {
      "file": "string",
      "line": "int",
      "severity": "critical|warning|info",
      "category": "bug|security|style|performance",
      "description": "string",
      "suggestion": "string"
    }
  ],
  "summary": "string",
  "risk_level": "low|medium|high",
  "confidence": 0.0-1.0,
  "next_action": "human_review|auto_approve|escalate"
}

## Metrics
- Runtime < 60 sekunder
- Findings precision > 80% (målt via human feedback)
- Confidence < 0.6 → altid human_review

## Failure Handling
- LLM timeout → retry med eksponentiel backoff (max 3)
- Diff for stor (>10.000 linjer) → split i chunks
- Ukendt sprog → eskalér med reason = "unsupported_language"
- Retry max nået → eskalér til menneske
```

### ❌ Dårlig SKILL.md

```markdown
# Code Review Agent

Denne agent laver code review. Den kan læse kode og skrive resultater.
```

**Problemer:** Ingen Forbidden-sektion, ingen output-kontrakt, ingen failure-håndtering, intet scope-afgrænsning.

### Tommelfingerregler

1. **Forbidden > Allowed** — beskriv altid hvad der er forbudt, det er governance
2. **Output Format er en kontrakt** — LLM'en returnerer dette format, koden parser det
3. **Metrics er SLA** — de bruges i monitoring, ikke bare til dokumentation
4. **Failure Handling er arkitektur** — det er ikke noget der tilføjes bagefter

---

## 3. Database-adgang: MCP, ikke direkte SQL

Agenter tilgår **aldrig** databaser direkte. Al adgang går gennem MCP-serveren. Det giver:
- Centraliseret adgangskontrol (hvem må hvad)
- Automatisk audit logging (hvem gjorde hvad)
- Connection pooling (effektiv ressourcestyring)
- Input-validering (ingen SQL injection fra AI-genereret input)

### ✅ Korrekt: brug MCP-klienten

```python
from agents.shared.mcp_client import MCPClient

mcp = MCPClient()

def run(task_id: str) -> dict:
    # Hent kontekst via MCP — ét kald, normaliseret data
    ctx = mcp.call("get_task_context", {"task_id": task_id})

    # ... kald LLM med ctx ...

    # Gem output via MCP
    mcp.call("save_agent_output", {
        "task_id": task_id,
        "agent_name": "review_agent",
        "result": result,
        "status": "done",
    })
```

### ❌ Forkert: direkte database-adgang

```python
# ALDRIG gør dette i en agent
import psycopg2
conn = psycopg2.connect(os.environ["AGENT_DB_URL"])  # ← nej
cur = conn.cursor()
cur.execute("SELECT * FROM agent_output WHERE ...")   # ← nej
```

### MCP-klienten

```python
# agents/shared/mcp_client.py
"""
MCP-klient til agenter. Alle database-operationer og eksterne
ressourcer tilgås via denne klient.
"""
import os
import httpx
import logging

logger = logging.getLogger(__name__)

MCP_BASE_URL = os.environ["MCP_SERVER_URL"]   # f.eks. http://mcp-server:8000


class MCPClient:
    """Simpel, synkron MCP-klient med JWT-auth og timeout."""

    def __init__(self, agent_name: str | None = None):
        self.agent_name = agent_name or os.environ.get("AGENT_NAME", "unknown")
        self.token = os.environ["MCP_JWT_TOKEN"]
        self._client = httpx.Client(
            base_url=MCP_BASE_URL,
            timeout=30.0,
            headers={
                "Authorization": f"Bearer {self.token}",
                "X-Agent-Name": self.agent_name,
            },
        )

    def call(self, tool_name: str, params: dict) -> dict:
        """
        Kald et MCP tool. Returnerer resultatet som dict.
        Kaster MCPError ved fejl.
        """
        response = self._client.post(
            "/tools/call",
            json={"tool": tool_name, "params": params},
        )

        if response.status_code == 403:
            raise MCPPermissionError(
                f"Agent '{self.agent_name}' har ikke adgang til '{tool_name}'"
            )
        if response.status_code == 429:
            raise MCPRateLimitError(
                f"Rate limit nået for '{self.agent_name}' på '{tool_name}'"
            )

        response.raise_for_status()
        return response.json()["result"]

    def close(self):
        self._client.close()


class MCPError(Exception):
    """Base MCP-fejl."""
    pass

class MCPPermissionError(MCPError):
    """Agent har ikke tilladelse til dette tool."""
    pass

class MCPRateLimitError(MCPError):
    """Agent har nået rate limit."""
    pass
```

---

## 4. Kontekst-hentning: ét kald, normaliseret data

Agenten skal hente al nødvendig kontekst i **ét kald**. Ingen agent bør lave multiple database-opslag — det gøres af MCP/context-laget.

### ✅ Korrekt: ét kald, struktureret resultat

```python
# Agenten kalder:
ctx = mcp.call("get_task_context", {"task_id": task_id})

# ctx indeholder alt agenten har brug for:
# {
#     "task": {
#         "id": "...",
#         "source_ref": "PROJ-421",
#         "title": "Fix null pointer i payment module",
#         "type": "bug",
#         "priority": "high",
#         "raw_text": "...",
#         "summary": "...",
#         "assigned_name": "Lars Hansen",
#         "assigned_role": "senior_dev",
#         "sla_hours": 8
#     },
#     "prior_outputs": [...],      # tidligere forsøg (feedback-loop)
#     "similar_tasks": [...]       # semantisk lignende opgaver
# }
```

### ❌ Forkert: multiple kald i agenten

```python
# UNDGÅ dette — agenten skal ikke vide hvad der joines med hvad
task = mcp.call("get_task", {"task_id": task_id})
user = mcp.call("get_user", {"user_id": task["assigned_to"]})
history = mcp.call("get_outputs", {"task_id": task_id})
similar = mcp.call("search_similar", {"embedding": task["embedding"]})
```

**Hvorfor?** Flere kald = flere tokens i prompten til at forklare hvad der skal sammensættes. Flere round-trips = højere latency. Ét kontekst-kald holder agenten simpel.

---

## 5. Prompt-konstruktion: minimal, struktureret, reproducerbar

Prompts er kode — de skal versionsstyres, testes og holdes minimale.

### ✅ God prompt-konstruktion

```python
# agents/review_agent/agent.py
import json
from pathlib import Path

# System-prompt fra fil — kan ændres uden deploy
SYSTEM_PROMPT = Path("agents/review_agent/prompts/system.md").read_text()

def build_user_prompt(ctx: dict) -> str:
    """
    Byg user-prompt fra normaliseret kontekst.
    Kun felter der er relevante for opgaven.
    Ingen rå data — alt er filtreret af MCP-laget.
    """
    task = ctx["task"]

    # Kun inkludér lignende opgaver hvis de findes
    similar_section = ""
    if ctx.get("similar_tasks"):
        similar_section = (
            "\n\nLignende løste opgaver:\n"
            + json.dumps(ctx["similar_tasks"][:3], indent=2, default=str)
        )

    # Kun inkludér tidligere forsøg hvis de findes (feedback-loop)
    prior_section = ""
    if ctx.get("prior_outputs"):
        prior_section = (
            "\n\nTidligere forsøg (tilpas din tilgang):\n"
            + json.dumps(ctx["prior_outputs"][:2], indent=2, default=str)
        )

    return f"""Opgave: {task['source_ref']} — {task['title']}
Type: {task['type']} | Prioritet: {task['priority']}

Beskrivelse:
{task.get('raw_text') or task.get('summary') or '(ingen beskrivelse)'}
{prior_section}{similar_section}

Returnér output som valid JSON i det format der er defineret i SKILL.md."""
```

```markdown
<!-- agents/review_agent/prompts/system.md -->
Du er en code review agent. Du analyserer code diffs og returnerer
strukturerede findings.

REGLER:
1. Returnér KUN valid JSON — ingen forklaring, ingen markdown-wrapper
2. Hvert finding har: file, line, severity, category, description, suggestion
3. Severity-vurdering: critical = crash/security, warning = bug-risiko, info = style
4. Confidence under 0.6 → sæt next_action = "human_review"
5. Intet fund → returnér tom findings-liste, IKKE opdigtede issues
```

### Regler for prompts

| Regel | Forklaring |
|-------|-----------|
| **System-prompt i fil** | `prompts/system.md` — versionsstyret, uafhængig af kode |
| **Aldrig rå data i prompten** | Brug `ctx` fra kontekst-kaldet — det er allerede filtreret |
| **Fortæl hvad formatet er** | "Returnér valid JSON i SKILL.md-format" — eksplicit |
| **Ingen overflødige instruktioner** | Hvert ord i prompten koster tokens |
| **Konditionel inklusion** | Inkludér kun lignende opgaver / feedback hvis de eksisterer |

### Token-estimat

```
┌──────────────────────────────┬────────────┐
│ System prompt                │ ~200 tokens │
│ Opgave-kontekst              │ ~300 tokens │
│ Lignende opgaver (max 3)     │ ~400 tokens │
│ Feedback (max 2)             │ ~200 tokens │
│ ─────────────────────────────┼────────────│
│ Total input                  │ ~1.100      │
│ Output (JSON)                │ ~500        │
│ TOTAL per kald               │ ~1.600      │
└──────────────────────────────┴────────────┘
```

---

## 6. Output-håndtering: struktureret JSON, altid valideret

LLM'en returnerer JSON. Men "returnerer" og "garanterer" er ikke det samme — validér altid.

### ✅ Korrekt: parse, validér, gem

```python
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Forventet format baseret på SKILL.md
REQUIRED_FIELDS = {"findings", "summary", "risk_level", "confidence", "next_action"}
VALID_RISK_LEVELS = {"low", "medium", "high"}
VALID_NEXT_ACTIONS = {"human_review", "auto_approve", "escalate"}


def parse_and_validate(raw_text: str) -> dict[str, Any]:
    """
    Parse LLM-output og validér mod SKILL.md-kontrakten.
    Kaster ValueError hvis output er ugyldigt.
    """
    # 1. Fjern eventuel markdown-wrapper
    text = raw_text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    # 2. Parse JSON
    try:
        result = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM returnerede ugyldig JSON: {e}")

    # 3. Validér påkrævede felter
    missing = REQUIRED_FIELDS - set(result.keys())
    if missing:
        raise ValueError(f"Manglende felter i output: {missing}")

    # 4. Validér værdier
    if result["risk_level"] not in VALID_RISK_LEVELS:
        raise ValueError(f"Ugyldigt risk_level: {result['risk_level']}")

    if result["next_action"] not in VALID_NEXT_ACTIONS:
        raise ValueError(f"Ugyldig next_action: {result['next_action']}")

    if not isinstance(result["confidence"], (int, float)):
        raise ValueError(f"Confidence skal være numerisk: {result['confidence']}")

    if not 0.0 <= result["confidence"] <= 1.0:
        raise ValueError(f"Confidence uden for interval: {result['confidence']}")

    # 5. Validér findings-struktur
    for i, finding in enumerate(result.get("findings", [])):
        for field in ("file", "severity", "category", "description"):
            if field not in finding:
                raise ValueError(f"Finding [{i}] mangler '{field}'")

    return result


def safe_parse(raw_text: str, task_id: str) -> dict[str, Any] | None:
    """
    Parse med fallback-logging. Returnerer None hvis ugyldigt
    (triggerer retry i retry-wrapperen).
    """
    try:
        return parse_and_validate(raw_text)
    except ValueError as e:
        logger.warning(
            f"Output-validering fejlede for {task_id}: {e}",
            extra={"task_id": task_id, "error_type": "validation"},
        )
        return None
```

### ❌ Forkert: blind trust

```python
# ALDRIG gør dette
result = json.loads(response.content[0].text)
mcp.call("save_agent_output", {"result": result, ...})
# Hvad hvis result er {} ? Hvad hvis risk_level = "banana"?
```

---

## 7. Fejlhåndtering: retry → circuit breaker → eskalering

Fejlhåndtering er **tre lag** — retry for transiente fejl, circuit breaker for vedvarende fejl, eskalering til menneske som sidste udvej.

### Lag 1: Retry med eksponentiel backoff

```python
# agents/shared/retry.py
import time
import logging
from typing import Callable, Any

logger = logging.getLogger(__name__)

RETRY_DELAYS = [0, 2, 10]   # sekunder: øjeblikkeligt, 2s, 10s


def with_retry(fn: Callable, task_id: str, max_attempts: int = 4) -> Any:
    """
    Kør fn med retry. Eskalér til menneske efter max_attempts.

    Retries sker ved:
    - LLM timeout / rate limit
    - Ugyldig JSON-output (parse-fejl)
    - MCP transiente fejl

    Retries sker IKKE ved:
    - ForbiddenOperationError (SKILL.md violation)
    - MCPPermissionError (adgangs-fejl)
    """
    last_error = None

    for attempt in range(1, max_attempts + 1):
        try:
            return fn(task_id)
        except (ForbiddenOperationError, MCPPermissionError):
            raise   # aldrig retry på kontraktfejl
        except Exception as e:
            last_error = e
            logger.warning(
                f"Attempt {attempt}/{max_attempts} fejlede: {e}",
                extra={"task_id": task_id, "attempt": attempt},
            )
            if attempt < max_attempts:
                delay = RETRY_DELAYS[min(attempt - 1, len(RETRY_DELAYS) - 1)]
                if delay:
                    time.sleep(delay)
            else:
                _escalate(task_id, str(last_error))
                raise


def _escalate(task_id: str, reason: str) -> None:
    """Markér opgaven som blokeret og notificér menneske."""
    from agents.shared.mcp_client import MCPClient
    mcp = MCPClient()
    mcp.call("update_task_status", {
        "task_id": task_id,
        "status": "blocked",
        "reason": reason[:500],
    })
```

### Lag 2: Circuit breaker

```python
# agents/shared/circuit_breaker.py
import time
import threading


class CircuitBreaker:
    """
    Beskytter mod vedvarende fejl i eksterne services.

    States:
    - CLOSED: alt normalt, requests goes through
    - OPEN: for mange fejl, requests afvises
    - HALF_OPEN: recovery-forsøg, ét request tilladt
    """

    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = 0.0
        self.state = "CLOSED"
        self._lock = threading.Lock()

    def call(self, func, *args, **kwargs):
        with self._lock:
            if self.state == "OPEN":
                if time.time() - self.last_failure_time > self.recovery_timeout:
                    self.state = "HALF_OPEN"
                else:
                    raise CircuitOpenError(
                        f"Circuit breaker OPEN — retry om "
                        f"{int(self.recovery_timeout - (time.time() - self.last_failure_time))}s"
                    )

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise

    def _on_success(self):
        with self._lock:
            self.failure_count = 0
            self.state = "CLOSED"

    def _on_failure(self):
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()
            if self.failure_count >= self.failure_threshold:
                self.state = "OPEN"


class CircuitOpenError(RuntimeError):
    pass


# Én breaker per ekstern service — ALDRIG delt mellem services
llm_breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=60)
jira_breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=30)
```

### Lag 3: Eskalering

```mermaid
flowchart LR
    ERR["Fejl"] --> R1["Retry 1\n(0s)"]
    R1 -->|fejl| R2["Retry 2\n(2s)"]
    R2 -->|fejl| R3["Retry 3\n(10s)"]
    R3 -->|fejl| ESC["Eskalér til\nmenneske"]

    R1 -->|ok| DONE["✅ Done"]
    R2 -->|ok| DONE
    R3 -->|ok| DONE

    CB["Circuit Breaker\n5 fejl/60s"] -.->|OPEN| SKIP["Skip alle\nrequests"]
    SKIP -.->|60s recovery| CB

    style ESC fill:#4a1515,color:#ffffff,stroke:#ef4444
    style DONE fill:#1a3a2a,color:#ffffff,stroke:#22c55e
    style CB fill:#92400e,color:#ffffff,stroke:#f59e0b
```

### Sammensætning i agenten

```python
# agents/review_agent/agent.py
from agents.shared.circuit_breaker import llm_breaker
from agents.shared.metrics import track_agent_call
from agents.shared.mcp_client import MCPClient

mcp = MCPClient(agent_name="review_agent")


def run(task_id: str) -> dict:
    with track_agent_call("review_agent", task_id) as ctx:
        # 1. Hent kontekst (via MCP)
        task_ctx = mcp.call("get_task_context", {"task_id": task_id})

        # 2. Kald LLM (via circuit breaker)
        response = llm_breaker.call(
            client.messages.create,
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_user_prompt(task_ctx)}],
        )

        # 3. Registrér token-forbrug
        ctx.token_input = response.usage.input_tokens
        ctx.token_output = response.usage.output_tokens

        # 4. Parse og validér output
        result = parse_and_validate(response.content[0].text)

        # 5. Gem output (via MCP)
        mcp.call("save_agent_output", {
            "task_id": task_id,
            "agent_name": "review_agent",
            "result": result,
            "status": "done",
        })

        return result
```

---

## 8. State machine: respektér statens regler

Opgaver har en livscyklus. Agenter må **kun** agere i bestemte states.

```mermaid
stateDiagram-v2
    [*] --> new
    new --> routed            : router_script
    routed --> in_progress    : agent starter
    in_progress --> pending_review : agent.done
    pending_review --> done        : human.approved
    pending_review --> in_progress : human.changes_requested
    in_progress --> blocked        : retry max nået
    blocked --> in_progress        : menneske fjerner blokering
    done --> [*]
```

### ✅ Korrekt: tjek state før arbejde

```python
def run(task_id: str) -> dict:
    ctx = mcp.call("get_task_context", {"task_id": task_id})

    # Guard: agent må kun køre på opgaver i korrekt state
    if ctx["task"]["status"] not in ("routed", "in_progress"):
        raise InvalidStateError(
            f"Task {task_id} har status '{ctx['task']['status']}' "
            f"— review_agent kræver 'routed' eller 'in_progress'"
        )

    # Guard: agent_pointer skal matche denne agent
    if ctx["task"]["agent_pointer"] != "review_agent":
        raise InvalidStateError(
            f"Task {task_id} er tildelt '{ctx['task']['agent_pointer']}', "
            f"ikke 'review_agent'"
        )

    # ... fortsæt med arbejdet
```

### ❌ Forkert: ignorer state

```python
# ALDRIG gør dette — agenten kan overskrive andre agenters arbejde
def run(task_id: str) -> dict:
    ctx = mcp.call("get_task_context", {"task_id": task_id})
    # bare kør... hvad nu hvis status er 'done'?
    result = call_llm(ctx)
    mcp.call("save_agent_output", {"result": result, ...})
```

---

## 9. Event bus: publicér og lyt korrekt

Agenter kommunikerer via events — aldrig direkte.

### ✅ Korrekt: event-drevet run-loop

```python
# agents/review_agent/run.py
from bus.consumer import read_events, ack
from bus.publisher import publish
from agents.review_agent.agent import run
from agents.shared.retry import with_retry
from agents.shared.notify import notify_reviewer
from agents.shared.bulkhead import run_with_bulkhead

import logging

logger = logging.getLogger("review_agent.run")


def listen() -> None:
    """Event-drevet lytteloop for review_agent."""
    logger.info("review_agent lytter på event bus...")

    while True:
        for event in read_events(consumer_name="review_agent_1"):
            # 1. Filtrér: kun reagér på events denne agent skal håndtere
            if event["event_type"] != "task.routed":
                ack(event["id"])
                continue

            # 2. Tjek at opgaven er tildelt denne agent
            task_id = event["task_id"]
            payload = event.get("payload", {})
            if payload.get("agent_pointer") != "review_agent":
                ack(event["id"])
                continue

            # 3. Kør med bulkhead + retry
            try:
                priority = payload.get("priority", "normal")
                result = run_with_bulkhead(priority, with_retry, run, task_id)
                notify_reviewer(task_id)
                publish(
                    "agent.done", task_id,
                    payload={"agent": "review_agent", "risk_level": result.get("risk_level")},
                    actor="review_agent",
                )
            except Exception as e:
                logger.error(f"Fejl i review_agent for {task_id}: {e}")
                publish(
                    "task.escalated", task_id,
                    payload={"reason": str(e)[:200], "agent": "review_agent"},
                    actor="review_agent",
                )
            finally:
                # 4. ALTID ack — ellers reprocesses eventet
                ack(event["id"])


if __name__ == "__main__":
    listen()
```

### Regler for events

| Regel | Forklaring |
|-------|-----------|
| **Filtrér events tidligt** | `ack()` events der ikke er relevante — lad dem ikke hænge |
| **Altid `ack()` i `finally`** | Uanset success/failure — ellers reprocesses eventet |
| **Publicér outcome** | `agent.done` eller `task.escalated` — systemet skal vide hvad der skete |
| **Inkludér metadata i payload** | `agent_name`, `risk_level`, `reason` — bruges til monitoring |

---

## 10. Metrics: instrument alt

Brug `track_agent_call()` context manageren. Den logger automatisk: varighed, tokens, success/failure.

### ✅ Korrekt: wrap hele agent-kaldet

```python
from agents.shared.metrics import track_agent_call

def run(task_id: str) -> dict:
    with track_agent_call("review_agent", task_id) as ctx:
        task_ctx = mcp.call("get_task_context", {"task_id": task_id})

        response = llm_breaker.call(client.messages.create, ...)

        # Registrér token-forbrug — dette er vigtigt for cost-monitoring
        ctx.token_input = response.usage.input_tokens
        ctx.token_output = response.usage.output_tokens

        result = parse_and_validate(response.content[0].text)
        mcp.call("save_agent_output", {...})

        return result
```

### Hvad metrics bruges til

```sql
-- Grafana: gennemsnitlig latency per agent (seneste time)
SELECT agent_name, ROUND(AVG(duration_ms)) AS avg_ms
FROM agent_metrics
WHERE recorded_at > NOW() - INTERVAL '1 hour'
GROUP BY agent_name;

-- Alert: agenter med >10% fejlrate
SELECT agent_name,
    ROUND(100.0 * COUNT(*) FILTER (WHERE NOT success) /
          NULLIF(COUNT(*), 0), 1) AS error_pct
FROM agent_metrics
WHERE recorded_at > NOW() - INTERVAL '1 hour'
GROUP BY agent_name
HAVING COUNT(*) FILTER (WHERE NOT success) * 100.0 / COUNT(*) > 10;

-- Cost-monitoring: token-forbrug per agent per dag
SELECT agent_name,
    SUM(token_input) AS input_tokens,
    SUM(token_output) AS output_tokens,
    ROUND((SUM(token_input) * 0.000003 + SUM(token_output) * 0.000015)::numeric, 2)
        AS estimated_cost_usd
FROM agent_metrics
WHERE recorded_at > NOW() - INTERVAL '24 hours'
GROUP BY agent_name;
```

---

## 11. Logging: JSON, altid

Alle agenter bruger den fælles JSON-logger. Logs opsamles af Loki og vises i Grafana.

### Setup

```python
# I starten af run.py
from agents.shared.logging_config import setup_logging

setup_logging("review_agent")
logger = logging.getLogger("review_agent")
```

### ✅ Korrekt: struktureret logging med ekstra felter

```python
logger.info(
    "Agent startet",
    extra={"agent_name": "review_agent", "task_id": task_id},
)

logger.info(
    "LLM-kald afsluttet",
    extra={
        "agent_name": "review_agent",
        "task_id": task_id,
        "duration_ms": 4500,
        "tokens_used": 1600,
    },
)

logger.warning(
    "Output-validering fejlede, retry",
    extra={
        "agent_name": "review_agent",
        "task_id": task_id,
        "error_type": "validation",
    },
)
```

### Output i Loki

```json
{
  "timestamp": "2026-04-15T09:12:33.456Z",
  "level": "INFO",
  "logger": "review_agent",
  "message": "LLM-kald afsluttet",
  "module": "agent",
  "function": "run",
  "line": 42,
  "agent_name": "review_agent",
  "task_id": "a1b2c3d4-...",
  "duration_ms": 4500,
  "tokens_used": 1600
}
```

### ❌ Forkert: print-statements og ustrukturerede logs

```python
# ALDRIG
print(f"starting task {task_id}")
logging.info(f"result: {result}")   # hele resultatet i loggen = støj
```

---

## 12. Sikkerhed: secrets, permissions, audit

### Environment variables

```bash
# .env — ALDRIG i Git
DATABASE_URL=postgresql://user:pass@host:5432/db
MCP_SERVER_URL=http://mcp-server:8000
MCP_JWT_TOKEN=eyJ...
LLM_API_KEY=sk-ant-...
SLACK_BOT_TOKEN=xoxb-...
```

```bash
# .env.example — ALTID i Git (ingen reelle værdier)
DATABASE_URL=postgresql://user:password@localhost:5432/routing_db
MCP_SERVER_URL=http://localhost:8000
MCP_JWT_TOKEN=<your-jwt-token>
LLM_API_KEY=<your-api-key>
SLACK_BOT_TOKEN=<your-slack-token>
```

### Permissions via MCP

Agenter har **kun** adgang til de MCP-tools der er registreret i deres tilladelser:

```python
# I MCP-serverens registry.py
AGENT_PERMISSIONS = {
    "tdd_agent": [
        "get_task_context",
        "search_similar_tasks",
        "save_agent_output",
        "run_tests_in_sandbox",
    ],
    "review_agent": [
        "get_task_context",
        "search_similar_tasks",
        "save_agent_output",
        # IKKE run_tests_in_sandbox — review_agent kører ikke tests
    ],
    "po_agent": [
        "get_task_context",
        "save_agent_output",
        "get_user_chain",
        # IKKE search_similar_tasks — PO behøver ikke historik
    ],
}
```

### Audit trail

Alle operationer logges automatisk i `audit_db`. Du behøver ikke logge manuelt — MCP-serveren gør det.

```sql
-- Tjek hvad en agent har gjort på en opgave
SELECT occurred_at, event_type, actor, payload->>'tool_name' AS tool
FROM audit_log
WHERE entity_id = 'task-uuid-here'
ORDER BY occurred_at;
```

---

## 13. Testing: agenten er kode, test den som kode

### Test-struktur

```python
# tests/conftest.py
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def mock_mcp():
    """Mock MCP-klienten — ingen netværk i tests."""
    with patch("agents.shared.mcp_client.MCPClient") as mock:
        client = mock.return_value
        client.call.return_value = {
            "task": {
                "id": "test-task-001",
                "source_ref": "PROJ-TEST",
                "title": "Test opgave",
                "type": "bug",
                "priority": "normal",
                "status": "routed",
                "agent_pointer": "review_agent",
                "raw_text": "Fix the bug",
                "summary": "Bug in payment module",
                "assigned_name": "Test User",
                "assigned_role": "developer",
                "sla_hours": 24,
            },
            "prior_outputs": [],
            "similar_tasks": [],
        }
        yield client


@pytest.fixture
def mock_llm():
    """Mock LLM-klienten — deterministisk output i tests."""
    with patch("anthropic.Anthropic") as mock:
        client = mock.return_value
        client.messages.create.return_value = MagicMock(
            content=[MagicMock(text='{"findings": [], "summary": "No issues", '
                               '"risk_level": "low", "confidence": 0.95, '
                               '"next_action": "auto_approve"}')],
            usage=MagicMock(input_tokens=500, output_tokens=200),
        )
        yield client
```

### Agent-tests

```python
# tests/test_review_agent.py
import pytest
import json
from agents.review_agent.agent import run, parse_and_validate, build_user_prompt


class TestParseAndValidate:
    """Test output-validering mod SKILL.md-kontrakt."""

    def test_valid_output(self):
        raw = json.dumps({
            "findings": [],
            "summary": "No issues found",
            "risk_level": "low",
            "confidence": 0.9,
            "next_action": "auto_approve",
        })
        result = parse_and_validate(raw)
        assert result["risk_level"] == "low"
        assert result["confidence"] == 0.9

    def test_invalid_json(self):
        with pytest.raises(ValueError, match="ugyldig JSON"):
            parse_and_validate("this is not json")

    def test_missing_required_field(self):
        raw = json.dumps({"findings": [], "summary": "ok"})
        with pytest.raises(ValueError, match="Manglende felter"):
            parse_and_validate(raw)

    def test_invalid_risk_level(self):
        raw = json.dumps({
            "findings": [],
            "summary": "ok",
            "risk_level": "banana",
            "confidence": 0.5,
            "next_action": "escalate",
        })
        with pytest.raises(ValueError, match="Ugyldigt risk_level"):
            parse_and_validate(raw)

    def test_confidence_out_of_range(self):
        raw = json.dumps({
            "findings": [],
            "summary": "ok",
            "risk_level": "low",
            "confidence": 1.5,
            "next_action": "auto_approve",
        })
        with pytest.raises(ValueError, match="uden for interval"):
            parse_and_validate(raw)

    def test_markdown_wrapper_stripped(self):
        raw = '```json\n{"findings": [], "summary": "ok", "risk_level": "low", ' \
              '"confidence": 0.8, "next_action": "auto_approve"}\n```'
        result = parse_and_validate(raw)
        assert result["risk_level"] == "low"


class TestBuildUserPrompt:
    """Test prompt-konstruktion."""

    def test_basic_prompt(self, mock_mcp):
        ctx = mock_mcp.call("get_task_context", {"task_id": "test"})
        prompt = build_user_prompt(ctx)
        assert "PROJ-TEST" in prompt
        assert "Test opgave" in prompt
        assert "bug" in prompt

    def test_omits_empty_sections(self, mock_mcp):
        ctx = mock_mcp.call("get_task_context", {"task_id": "test"})
        prompt = build_user_prompt(ctx)
        assert "Tidligere forsøg" not in prompt     # tom liste → ikke inkluderet
        assert "Lignende løste opgaver" not in prompt


class TestAgentRun:
    """Integration-test for hele agent-flowet (mockt LLM + MCP)."""

    def test_successful_run(self, mock_mcp, mock_llm):
        result = run("test-task-001")
        assert result["next_action"] == "auto_approve"
        assert mock_mcp.call.call_count >= 2   # get_task_context + save_agent_output

    def test_state_guard(self, mock_mcp):
        mock_mcp.call.return_value["task"]["status"] = "done"
        with pytest.raises(InvalidStateError):
            run("test-task-001")
```

### Hvad skal testes

| Test-niveau | Hvad | Eksempel |
|-------------|------|---------|
| **Unit** | Output-validering | `test_invalid_risk_level` |
| **Unit** | Prompt-konstruktion | `test_omits_empty_sections` |
| **Unit** | State guards | `test_state_guard` |
| **Integration** | Hele run-flowet (mock LLM + MCP) | `test_successful_run` |
| **Contract** | SKILL.md-validering | Test at Forbidden-operationer rejser fejl |

---

## 14. Anti-patterns: undgå disse fejl

### ❌ 1. Direkte database-adgang

```python
# FORKERT
conn = psycopg2.connect(os.environ["AGENT_DB_URL"])
```

**Brug i stedet:** `mcp.call("get_task_context", ...)` — MCP-serveren håndterer adgang.

---

### ❌ 2. Ubegrænset LLM-kald

```python
# FORKERT — ingen circuit breaker, ingen timeout
response = client.messages.create(model="claude-opus-4-5", max_tokens=100000, ...)
```

**Brug i stedet:**

```python
response = llm_breaker.call(
    client.messages.create,
    model="claude-sonnet-4-20250514",   # brug mindste tilstrækkelige model
    max_tokens=4096,                    # begræns output
    ...
)
```

---

### ❌ 3. Hardcoded credentials

```python
# FORKERT
API_KEY = "sk-ant-123456789"
DB_URL = "postgresql://admin:password@prod-db:5432/routing_db"
```

**Brug i stedet:** Environment variables fra `.env`:

```python
API_KEY = os.environ["LLM_API_KEY"]
```

---

### ❌ 4. Ignorere state machine

```python
# FORKERT — ingen tjek af status/agent_pointer
def run(task_id):
    ctx = mcp.call("get_task_context", {"task_id": task_id})
    result = call_llm(ctx)   # Hvad hvis opgaven allerede er 'done'?
```

---

### ❌ 5. Hele resultatet i prompten

```python
# FORKERT — sender 50 lignende opgaver ind
similar = mcp.call("search_similar", {"limit": 50})
prompt = f"Her er 50 lignende opgaver: {json.dumps(similar)}"
# = tusindvis af overflødige tokens
```

**Brug i stedet:** Max 3 lignende opgaver, kun relevante felter.

---

### ❌ 6. Ingen output-validering

```python
# FORKERT
result = json.loads(response.content[0].text)
# Hvad hvis LLM returnerer {"error": "I can't do this"}?
```

---

### ❌ 7. Glemmer at `ack()` events

```python
# FORKERT — eventet reprocesses ved næste iteration
for event in read_events("agent_1"):
    if event["event_type"] != "task.routed":
        continue   # ← glemmer ack()!
```

---

### ❌ 8. Print i stedet for logging

```python
# FORKERT — usynligt i Loki, ingen strukturering
print(f"Processing task {task_id}")
```

---

### ❌ 9. Delt state mellem agenter

```python
# FORKERT — global variabel der deles
GLOBAL_CACHE = {}

def run(task_id):
    if task_id in GLOBAL_CACHE:
        return GLOBAL_CACHE[task_id]
```

**Brug i stedet:** Postgres er state-lagriet. `agent_output` indeholder alt.

---

### ❌ 10. Retry på kontraktfejl

```python
# FORKERT — hvis SKILL.md forbyder det, hjælper retry ikke
try:
    result = run(task_id)
except ForbiddenOperationError:
    time.sleep(5)
    result = run(task_id)   # ← stadig forbudt
```

---

## 15. Komplet eksempel: ny agent fra scratch

Lad os bygge en `qa_agent` fra nul — trin for trin, med alle best practices.

### Trin 1: SKILL.md

```markdown
# Agent Name: QA Agent

## Purpose
Verificér at agent-output fra andre agenter overholder kvalitetskrav.
Aktiveres KUN på opgaver med status 'pending_review' og type 'qa_check'.

## Capabilities
- Læse agent_output fra andre agenter (read-only via MCP)
- Sammenligne output mod SKILL.md-kontrakten for den producerende agent
- Generere en QA-rapport med pass/fail per kvalitetskriterium

## Allowed
- MCP tools: get_task_context, get_agent_outputs, save_agent_output
- Læse SKILL.md-filer for referencerede agenter

## Forbidden
- Modificere andre agenters output
- Ændre task status direkte
- Tilgå eksterne systemer (Jira, Git)
- Godkende opgaver (det gør mennesker)

## Output Format
{
  "qa_result": "pass|fail|needs_review",
  "checks": [
    {
      "criterion": "string",
      "status": "pass|fail",
      "details": "string"
    }
  ],
  "overall_confidence": 0.0-1.0,
  "recommendation": "approve|reject|escalate",
  "summary": "string"
}

## Metrics
- Runtime < 30 sekunder
- False positive rate < 5%
- overall_confidence < 0.7 → altid recommendation = "escalate"

## Failure Handling
- Manglende agent_output → eskalér med reason = "missing_output"
- Output-format ukendt → eskalér med reason = "unknown_format"
- Retry max nået → eskalér til QA-lead
```

### Trin 2: System prompt

```markdown
<!-- agents/qa_agent/prompts/system.md -->
Du er en QA-agent. Du verificerer kvaliteten af andre agenters output.

REGLER:
1. Returnér KUN valid JSON i det definerede format
2. Hvert check har: criterion, status (pass/fail), details
3. qa_result = "pass" KUN hvis ALLE checks er "pass"
4. qa_result = "needs_review" hvis confidence < 0.7
5. Vær konservativ: hellere én falsk "fail" end én overset fejl
6. Inkludér aldrig output fra den originale agent i din rapport — referer til det
```

### Trin 3: Agent-kode

```python
# agents/qa_agent/agent.py
import json
import logging
from pathlib import Path
from typing import Any

import anthropic

from agents.shared.mcp_client import MCPClient
from agents.shared.circuit_breaker import llm_breaker
from agents.shared.metrics import track_agent_call

logger = logging.getLogger("qa_agent")

SYSTEM_PROMPT = Path("agents/qa_agent/prompts/system.md").read_text()
mcp = MCPClient(agent_name="qa_agent")
client = anthropic.Anthropic()

# ─── Output-validering ──────────────────────────────────────────

REQUIRED_FIELDS = {"qa_result", "checks", "overall_confidence", "recommendation", "summary"}
VALID_QA_RESULTS = {"pass", "fail", "needs_review"}
VALID_RECOMMENDATIONS = {"approve", "reject", "escalate"}


def parse_and_validate(raw_text: str) -> dict[str, Any]:
    text = raw_text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    result = json.loads(text)

    missing = REQUIRED_FIELDS - set(result.keys())
    if missing:
        raise ValueError(f"Manglende felter: {missing}")

    if result["qa_result"] not in VALID_QA_RESULTS:
        raise ValueError(f"Ugyldigt qa_result: {result['qa_result']}")

    if result["recommendation"] not in VALID_RECOMMENDATIONS:
        raise ValueError(f"Ugyldig recommendation: {result['recommendation']}")

    conf = result["overall_confidence"]
    if not isinstance(conf, (int, float)) or not 0.0 <= conf <= 1.0:
        raise ValueError(f"Ugyldig confidence: {conf}")

    # Enforce SKILL.md: lav confidence → altid escalate
    if conf < 0.7 and result["recommendation"] != "escalate":
        result["recommendation"] = "escalate"
        logger.info("Confidence < 0.7 — overrider recommendation til 'escalate'")

    return result


# ─── Prompt-konstruktion ────────────────────────────────────────

def build_user_prompt(ctx: dict) -> str:
    task = ctx["task"]
    prior = ctx.get("prior_outputs", [])

    outputs_section = ""
    if prior:
        # Vis kun de seneste 2 outputs
        outputs_section = (
            "\n\nAgent-output til QA-review:\n"
            + json.dumps(prior[:2], indent=2, default=str)
        )

    return f"""QA-tjek: {task['source_ref']} — {task['title']}
Type: {task['type']} | Prioritet: {task['priority']}
Producerende agent: {task.get('agent_pointer', 'ukendt')}
{outputs_section}

Verificér output mod agentens SKILL.md-kontrakt.
Returnér QA-rapport som valid JSON."""


# ─── Hovedfunktion ──────────────────────────────────────────────

class InvalidStateError(Exception):
    pass


def run(task_id: str) -> dict:
    """Kør QA-tjek på en opgave."""
    with track_agent_call("qa_agent", task_id) as metrics:

        # 1. Hent kontekst
        ctx = mcp.call("get_task_context", {"task_id": task_id})

        # 2. State guard
        if ctx["task"]["status"] not in ("pending_review",):
            raise InvalidStateError(
                f"qa_agent kræver status 'pending_review', "
                f"fik '{ctx['task']['status']}'"
            )

        # 3. Guard: der skal være output at reviewe
        if not ctx.get("prior_outputs"):
            mcp.call("save_agent_output", {
                "task_id": task_id,
                "agent_name": "qa_agent",
                "result": {
                    "qa_result": "fail",
                    "checks": [],
                    "overall_confidence": 1.0,
                    "recommendation": "escalate",
                    "summary": "Ingen agent-output fundet til QA-review",
                },
                "status": "done",
            })
            raise ValueError(f"Ingen output at reviewe for {task_id}")

        # 4. Kald LLM via circuit breaker
        response = llm_breaker.call(
            client.messages.create,
            model="claude-sonnet-4-20250514",
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_user_prompt(ctx)}],
        )

        # 5. Registrér tokens
        metrics.token_input = response.usage.input_tokens
        metrics.token_output = response.usage.output_tokens

        # 6. Parse og validér
        result = parse_and_validate(response.content[0].text)

        # 7. Gem QA-rapport
        mcp.call("save_agent_output", {
            "task_id": task_id,
            "agent_name": "qa_agent",
            "result": result,
            "status": "done",
        })

        logger.info(
            "QA-rapport gemt",
            extra={
                "task_id": task_id,
                "qa_result": result["qa_result"],
                "recommendation": result["recommendation"],
                "confidence": result["overall_confidence"],
            },
        )

        return result
```

### Trin 4: Event-loop

```python
# agents/qa_agent/run.py
import logging

from agents.shared.logging_config import setup_logging
from agents.shared.retry import with_retry
from agents.shared.bulkhead import run_with_bulkhead
from agents.shared.notify import notify_reviewer
from bus.consumer import read_events, ack
from bus.publisher import publish
from agents.qa_agent.agent import run

setup_logging("qa_agent")
logger = logging.getLogger("qa_agent.run")


def listen() -> None:
    logger.info("qa_agent lytter på event bus...")

    while True:
        for event in read_events(consumer_name="qa_agent_1"):
            # Filtrér: QA-agenten lytter på 'agent.done' events
            if event["event_type"] != "agent.done":
                ack(event["id"])
                continue

            task_id = event["task_id"]

            try:
                priority = event.get("payload", {}).get("priority", "normal")
                result = run_with_bulkhead(priority, with_retry, run, task_id)

                # Publicér QA-resultat
                publish(
                    "qa.completed", task_id,
                    payload={
                        "agent": "qa_agent",
                        "qa_result": result["qa_result"],
                        "recommendation": result["recommendation"],
                    },
                    actor="qa_agent",
                )

                # Notificér menneske hvis nødvendigt
                if result["recommendation"] in ("reject", "escalate"):
                    notify_reviewer(task_id)

            except Exception as e:
                logger.error(f"qa_agent fejlede for {task_id}: {e}")
                publish(
                    "task.escalated", task_id,
                    payload={"reason": str(e)[:200], "agent": "qa_agent"},
                    actor="qa_agent",
                )
            finally:
                ack(event["id"])


if __name__ == "__main__":
    listen()
```

### Trin 5: Tests

```python
# tests/test_qa_agent.py
import json
import pytest
from unittest.mock import MagicMock, patch

from agents.qa_agent.agent import parse_and_validate, run, InvalidStateError


VALID_OUTPUT = {
    "qa_result": "pass",
    "checks": [
        {"criterion": "Output format", "status": "pass", "details": "Valid JSON"},
        {"criterion": "Required fields", "status": "pass", "details": "All present"},
    ],
    "overall_confidence": 0.92,
    "recommendation": "approve",
    "summary": "All checks passed",
}


class TestParseAndValidate:

    def test_valid_output(self):
        result = parse_and_validate(json.dumps(VALID_OUTPUT))
        assert result["qa_result"] == "pass"

    def test_low_confidence_forces_escalate(self):
        output = {**VALID_OUTPUT, "overall_confidence": 0.5, "recommendation": "approve"}
        result = parse_and_validate(json.dumps(output))
        assert result["recommendation"] == "escalate"

    def test_missing_fields(self):
        with pytest.raises(ValueError, match="Manglende felter"):
            parse_and_validate(json.dumps({"qa_result": "pass"}))

    def test_invalid_qa_result(self):
        output = {**VALID_OUTPUT, "qa_result": "maybe"}
        with pytest.raises(ValueError, match="Ugyldigt qa_result"):
            parse_and_validate(json.dumps(output))


class TestQAAgentRun:

    @pytest.fixture
    def setup_mocks(self):
        with patch("agents.qa_agent.agent.mcp") as mock_mcp, \
             patch("agents.qa_agent.agent.llm_breaker") as mock_breaker:

            mock_mcp.call.side_effect = lambda tool, params: {
                "get_task_context": {
                    "task": {
                        "id": "test-001",
                        "source_ref": "PROJ-42",
                        "title": "Test",
                        "type": "qa_check",
                        "priority": "normal",
                        "status": "pending_review",
                        "agent_pointer": "tdd_agent",
                    },
                    "prior_outputs": [
                        {"agent_name": "tdd_agent", "result": {"test_suite": ["test.py"]}}
                    ],
                    "similar_tasks": [],
                },
            }.get(tool, {})

            mock_response = MagicMock()
            mock_response.content = [MagicMock(text=json.dumps(VALID_OUTPUT))]
            mock_response.usage = MagicMock(input_tokens=400, output_tokens=150)
            mock_breaker.call.return_value = mock_response

            yield mock_mcp, mock_breaker

    def test_successful_qa_run(self, setup_mocks):
        mock_mcp, _ = setup_mocks
        result = run("test-001")
        assert result["qa_result"] == "pass"

    def test_wrong_state_rejected(self, setup_mocks):
        mock_mcp, _ = setup_mocks
        mock_mcp.call.side_effect = lambda tool, params: {
            "get_task_context": {
                "task": {"status": "done", "id": "x"},
                "prior_outputs": [],
                "similar_tasks": [],
            },
        }.get(tool, {})

        with pytest.raises(InvalidStateError):
            run("test-001")
```

### Trin 6: Registrér agenten

```sql
-- routing_db: tilføj qa_agent til agent_registry
INSERT INTO agent_registry (agent_name, handles_types, active)
VALUES ('qa_agent', ARRAY['qa_check'], true);
```

```python
# mcp/registry.py: tilføj tilladelser
AGENT_PERMISSIONS["qa_agent"] = [
    "get_task_context",
    "get_agent_outputs",
    "save_agent_output",
]
```

---

## Opsummering: checkliste for nye agenter

```
□  SKILL.md skrevet — Forbidden-sektion defineret
□  System prompt i prompts/system.md — ikke hardcoded i kode
□  Agent bruger MCPClient — ingen direkte database-adgang
□  Kontekst hentes med ét kald — get_task_context
□  Output valideres mod SKILL.md-kontrakt — parse_and_validate()
□  LLM-kald wrapped i circuit breaker — llm_breaker.call()
□  Hele run() wrapped i track_agent_call() — metrics gemmes
□  State guard i starten af run() — tjek status + agent_pointer
□  Event loop: filtrér → kør med bulkhead + retry → ack altid
□  Logging: JSON via setup_logging() — aldrig print()
□  Tests: output-validering + state guards + mock integration
□  Agent registreret i agent_registry + MCP permissions
□  .env.example opdateret med nye variables
□  Secrets ALDRIG i Git
```
