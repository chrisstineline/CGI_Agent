# Stage 3 — Event Bus, Multi-Database Isolation og Resiliens

> **Forudsætning:** Stage 1 (Postgres-fundament) og Stage 2 (første agent + human-in-the-loop) er gennemført.
>
> **Scope:** Stage 3 erstatter polling med en event bus, splitter den enkelt-database fra Stage 1 op i fire isolerede databaser, og tilføjer circuit breaker, bulkhead og auto-scaling. Resultatet er et system der er fault-tolerant, skalerbart og klar til produktion.

---

## Hvad vi bygger i Stage 3

```mermaid
flowchart TD
    subgraph SOURCES["Triggers"]
        W["Webhook\n(Jira / email)"]
        T["Timer\n(scheduler)"]
        H["Human\n(godkendelse)"]
    end

    subgraph BUS["Event Bus (Redis Streams)"]
        E1["task.created"]
        E2["task.routed"]
        E3["agent.done"]
        E4["human.approved"]
        E5["task.escalated"]
    end

    subgraph DBS["4 isolerede databaser"]
        RDB[("routing_db\ntask_entries\nagent_registry")]
        ADB[("agent_db\nagent_output\nagent_metrics")]
        UDB[("user_db\nuser_chain\nsessions")]
        AUDB[("audit_db\naudit_log\nimmutable")]
    end

    subgraph AGENTS["Agent Pool"]
        TDD["tdd_agent"]
        REV["review_agent"]
        PO["po_agent"]
    end

    subgraph RESILIENCE["Resiliens-lag"]
        CB["Circuit Breaker"]
        BH["Bulkhead\n(prioritet-limits)"]
        AS["Auto-scaling"]
    end

    SOURCES --> BUS
    BUS --> RDB & ADB & UDB & AUDB
    BUS --> AGENTS
    AGENTS --> BUS
    RESILIENCE --> AGENTS
```

---

## Trin 1 — Skift fra polling til Event Bus

I Stage 2 pollede `run.py` aktivt Postgres hvert N sekund. Det er ineffektivt og skalerer dårligt. En event bus giver reaktiv, asynkron kommunikation: agenter handler *kun* når et event ankommer.

### Start Redis med Streams

```bash
# Docker (Redis er tilstrækkeligt til de fleste setups — Kafka ved >10.000 events/sek)
docker run -d \
  --name agent-bus \
  -p 6379:6379 \
  redis:7-alpine \
  redis-server --appendonly yes  # persist events til disk
```

### Event-publisher

```python
# bus/publisher.py
import os
import json
import redis
from datetime import datetime, timezone

r = redis.from_url(os.environ["REDIS_URL"])   # redis://localhost:6379

EVENT_STREAM = "agent_events"

def publish(event_type: str, task_id: str, payload: dict | None = None, actor: str = "system") -> str:
    """Publicér et event til bussen. Returnerer event-ID."""
    message = {
        "event_type": event_type,
        "task_id":    task_id,
        "actor":      actor,
        "timestamp":  datetime.now(timezone.utc).isoformat(),
        "payload":    json.dumps(payload or {}),
    }
    event_id = r.xadd(EVENT_STREAM, message)
    return event_id.decode()
```

### Event-consumer (agent-siden)

```python
# bus/consumer.py
import os
import json
import redis

r = redis.from_url(os.environ["REDIS_URL"])

EVENT_STREAM   = "agent_events"
CONSUMER_GROUP = "tdd_agent_group"

def ensure_group() -> None:
    try:
        r.xgroup_create(EVENT_STREAM, CONSUMER_GROUP, id="0", mkstream=True)
    except redis.exceptions.ResponseError:
        pass   # gruppe eksisterer allerede

def read_events(consumer_name: str, count: int = 5, block_ms: int = 5000) -> list[dict]:
    """
    Bloker i op til block_ms ms og returnér nye events.
    Brug XACK efter behandling for at markere dem som færdige.
    """
    ensure_group()
    raw = r.xreadgroup(
        CONSUMER_GROUP, consumer_name,
        {EVENT_STREAM: ">"},
        count=count, block=block_ms
    )
    if not raw:
        return []

    events = []
    for stream, messages in raw:
        for msg_id, fields in messages:
            events.append({
                "id":         msg_id.decode(),
                "event_type": fields[b"event_type"].decode(),
                "task_id":    fields[b"task_id"].decode(),
                "payload":    json.loads(fields[b"payload"]),
            })
    return events

def ack(event_id: str) -> None:
    r.xack(EVENT_STREAM, CONSUMER_GROUP, event_id)
```

### Opdatér agentens run-loop

Erstat Stage 2's polling-loop med en event-driven løkke:

```python
# agents/tdd_agent/run.py  (Stage 3 version)
from bus.consumer   import read_events, ack
from bus.publisher  import publish
from agents.tdd_agent.agent import run, write_output
from agents.shared.retry    import with_retry
from agents.shared.notify   import notify_reviewer

def listen() -> None:
    print("[tdd_agent] Lytter på event bus...")
    while True:
        for event in read_events(consumer_name="tdd_agent_1"):
            if event["event_type"] != "task.routed":
                ack(event["id"])
                continue

            task_id = event["task_id"]
            try:
                result = with_retry(run, task_id)
                write_output(task_id, result)
                notify_reviewer(task_id)
                publish("agent.done", task_id, payload={"agent": "tdd_agent"}, actor="tdd_agent")
            except Exception as e:
                publish("task.escalated", task_id,
                        payload={"reason": str(e)[:200]}, actor="tdd_agent")
            finally:
                ack(event["id"])

if __name__ == "__main__":
    listen()
```

---

## Trin 2 — Multi-database isolation

En enkelt Postgres-instans er en single point of failure. Stage 3 splitter databasen fra Stage 1 op i fire uafhængige databaser. En fejl i `agent_db` stopper ikke routing. En kompromitteret agent kan ikke slette `audit_db`.

### Opret de fire databaser

```bash
psql -U postgres -c "CREATE DATABASE routing_db;"
psql -U postgres -c "CREATE DATABASE agent_db;"
psql -U postgres -c "CREATE DATABASE user_db;"
psql -U postgres -c "CREATE DATABASE audit_db;"
```

### Migrer tabeller

```sql
-- routing_db: task orchestration
-- (kør i routing_db)
CREATE TABLE task_entries    ( ... );   -- fra Stage 1, Trin 2
CREATE TABLE agent_registry  ( ... );
CREATE TABLE escalation_log  ( ... );
CREATE TABLE task_embeddings ( ... );

-- agent_db: hvad agenter producerer
-- (kør i agent_db)
CREATE TABLE agent_output (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_entry_id   UUID NOT NULL,           -- ingen FK på tværs af databaser
    agent_name      TEXT NOT NULL,
    result          JSONB,
    status          TEXT DEFAULT 'pending',
    attempt_count   INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE agent_metrics (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_name      TEXT NOT NULL,
    task_entry_id   UUID NOT NULL,
    duration_ms     INTEGER,
    llm_tokens_used INTEGER,
    success         BOOLEAN,
    recorded_at     TIMESTAMPTZ DEFAULT NOW()
);

-- user_db: brugere og roller
-- (kør i user_db)
CREATE TABLE user_chain      ( ... );   -- fra Stage 1, Trin 2

-- audit_db: immutable log — aldrig UPDATE eller DELETE
-- (kør i audit_db)
CREATE TABLE audit_log (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type   TEXT NOT NULL,
    entity_id    UUID,
    actor        TEXT,
    payload      JSONB,
    occurred_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Forhindre sletning på database-niveau
REVOKE DELETE ON audit_log FROM PUBLIC;
REVOKE UPDATE ON audit_log FROM PUBLIC;
```

### Database-connection manager

```python
# db/connections.py
import os
import psycopg2
import psycopg2.extras
from contextlib import contextmanager

_URLS = {
    "routing": os.environ["ROUTING_DB_URL"],
    "agent":   os.environ["AGENT_DB_URL"],
    "user":    os.environ["USER_DB_URL"],
    "audit":   os.environ["AUDIT_DB_URL"],
}

@contextmanager
def db(name: str):
    """
    Brug som: with db('routing') as (conn, cur): ...
    Sikrer commit og close uanset undtagelser.
    """
    conn = psycopg2.connect(_URLS[name],
                            cursor_factory=psycopg2.extras.RealDictCursor)
    cur  = conn.cursor()
    try:
        yield conn, cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()
```

Opdatér alle eksisterende funktioner til at bruge `db(name)` i stedet for den fælles `DATABASE_URL`:

```python
# Eksempel: write_output i agents/tdd_agent/agent.py
from db.connections import db

def write_output(task_id: str, result: dict, status: str = "done") -> None:
    with db("agent") as (conn, cur):
        cur.execute("""
            INSERT INTO agent_output (task_entry_id, agent_name, result, status)
            VALUES (%s, 'tdd_agent', %s::jsonb, %s)
        """, (task_id, json.dumps(result), status))

    with db("routing") as (conn, cur):
        cur.execute("""
            UPDATE task_entries SET status = 'in_progress' WHERE id = %s
        """, (task_id,))

    with db("audit") as (conn, cur):
        cur.execute("""
            INSERT INTO audit_log (event_type, entity_id, actor, payload)
            VALUES ('agent.done', %s, 'tdd_agent', %s::jsonb)
        """, (task_id, json.dumps({"status": status})))
```

### Failure impact per database

| Database | Hvad fejler | Hvad fortsætter | Genopretning |
|----------|-------------|-----------------|-------------|
| **routing_db** | Nye opgaver kan ikke oprettes | Igangværende agenter kører færdig | < 5 min |
| **agent_db** | Agent-output kan ikke skrives | Routing og notifikationer virker | < 10 min |
| **user_db** | Brugerassignering fejler | Fallback til default-bruger | < 2 min |
| **audit_db** | Audit-logging stopper midlertidigt | Alt andet virker | Øjeblikkeligt (append-only) |

---

## Trin 3 — Circuit Breaker

En agent der kalder en ekstern service (LLM API, Jira) skal ikke blive ved med at fejle og belaste systemet. Circuit Breaker åbner kredsen efter gentagne fejl og lader den restituere.

```mermaid
stateDiagram-v2
    [*] --> CLOSED
    CLOSED --> OPEN    : 5 fejl inden for 60 sek
    OPEN --> HALF_OPEN : recovery_timeout (60 sek) udløbet
    HALF_OPEN --> CLOSED : første kald lykkes
    HALF_OPEN --> OPEN   : første kald fejler
```

```python
# agents/shared/circuit_breaker.py
import time
import threading

class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60):
        self.failure_threshold  = failure_threshold
        self.recovery_timeout   = recovery_timeout
        self.failure_count      = 0
        self.last_failure_time  = 0.0
        self.state              = "CLOSED"   # CLOSED | OPEN | HALF_OPEN
        self._lock              = threading.Lock()

    def call(self, func, *args, **kwargs):
        with self._lock:
            if self.state == "OPEN":
                if time.time() - self.last_failure_time > self.recovery_timeout:
                    self.state = "HALF_OPEN"
                else:
                    raise RuntimeError("Circuit breaker OPEN — venter på recovery")

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
            self.failure_count    += 1
            self.last_failure_time = time.time()
            if self.failure_count >= self.failure_threshold:
                self.state = "OPEN"

# Én circuit breaker per ekstern service
llm_breaker   = CircuitBreaker(failure_threshold=5, recovery_timeout=60)
jira_breaker  = CircuitBreaker(failure_threshold=3, recovery_timeout=30)
slack_breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=120)
```

Wrap LLM-kald i circuit breaker:

```python
# I agents/tdd_agent/agent.py
from agents.shared.circuit_breaker import llm_breaker

response = llm_breaker.call(
    client.messages.create,
    model="claude-opus-4-5",
    max_tokens=4096,
    system=SYSTEM_PROMPT,
    messages=[{"role": "user", "content": user_message}]
)
```

---

## Trin 4 — Bulkhead: prioritetsbaserede concurrency-limits

Bulkhead-mønstret sikrer at lavprioritets-opgaver ikke kan sulte kritiske opgaver for ressourcer.

```python
# agents/shared/bulkhead.py
import threading
from typing import Callable

_LIMITS = {
    "critical": threading.Semaphore(10),
    "high":     threading.Semaphore(25),
    "normal":   threading.Semaphore(50),
    "low":      threading.Semaphore(100),
}

def run_with_bulkhead(priority: str, fn: Callable, *args, **kwargs):
    """
    Blokér hvis concurrency-limit for prioriteten er nået.
    Frigiv semaphore automatisk efter kørsel.
    """
    sem = _LIMITS.get(priority, _LIMITS["normal"])
    acquired = sem.acquire(blocking=False)

    if not acquired:
        raise RuntimeError(f"Bulkhead overload for priority '{priority}' — task queued")

    try:
        return fn(*args, **kwargs)
    finally:
        sem.release()
```

Opdatér `listen()` i `run.py`:

```python
from agents.shared.bulkhead import run_with_bulkhead
from db.connections import db

def get_priority(task_id: str) -> str:
    with db("routing") as (_, cur):
        cur.execute("SELECT priority FROM task_entries WHERE id = %s", (task_id,))
        row = cur.fetchone()
        return row["priority"] if row else "normal"

# I event-loopet:
priority = get_priority(task_id)
try:
    result = run_with_bulkhead(priority, with_retry, run, task_id)
    ...
except RuntimeError:
    # Overload — re-kø eventet til næste iteration
    r.xadd("agent_events", {"event_type": "task.queued", "task_id": task_id, ...})
```

---

## Trin 5 — Metrics og observabilitet

Uden metrics er Stage 3 en sort boks. Gem nøglemålinger i `agent_db`.

```python
# agents/shared/metrics.py
import time
from db.connections import db

def record(agent_name: str, task_id: str, duration_ms: int,
           tokens_used: int, success: bool) -> None:
    with db("agent") as (_, cur):
        cur.execute("""
            INSERT INTO agent_metrics
                (agent_name, task_entry_id, duration_ms, llm_tokens_used, success)
            VALUES (%s, %s, %s, %s, %s)
        """, (agent_name, task_id, duration_ms, tokens_used, success))
```

Wrap agentens kød i timing:

```python
# I agents/tdd_agent/agent.py
import time
from agents.shared.metrics import record

start   = time.monotonic()
result  = llm_breaker.call(client.messages.create, ...)
elapsed = int((time.monotonic() - start) * 1000)

record(
    agent_name="tdd_agent",
    task_id=task_id,
    duration_ms=elapsed,
    tokens_used=response.usage.input_tokens + response.usage.output_tokens,
    success=True
)
```

### Nøgle-queries til drift-overvågning

```sql
-- Gennemsnitlig agentvarighed og fejlrate (seneste 24 timer)
SELECT agent_name,
       ROUND(AVG(duration_ms))    AS avg_ms,
       ROUND(AVG(llm_tokens_used)) AS avg_tokens,
       ROUND(100.0 * SUM(CASE WHEN NOT success THEN 1 END) / COUNT(*), 1) AS error_pct,
       COUNT(*)                   AS total_runs
FROM agent_metrics
WHERE recorded_at > NOW() - INTERVAL '24 hours'
GROUP BY agent_name
ORDER BY error_pct DESC;

-- Opgaver der overskrider SLA
SELECT te.source_ref, te.priority, te.status,
       EXTRACT(EPOCH FROM (NOW() - te.created_at))/3600 AS hours_open,
       uc.sla_hours
FROM task_entries te
JOIN user_chain uc ON uc.id = te.assigned_to
WHERE te.status NOT IN ('done', 'blocked')
  AND EXTRACT(EPOCH FROM (NOW() - te.created_at))/3600 > uc.sla_hours
ORDER BY hours_open DESC;

-- Circuit breaker status (indirekte via fejlrater)
SELECT agent_name,
       COUNT(*) FILTER (WHERE NOT success AND recorded_at > NOW() - INTERVAL '1 minute') AS failures_last_min
FROM agent_metrics
GROUP BY agent_name
HAVING COUNT(*) FILTER (WHERE NOT success AND recorded_at > NOW() - INTERVAL '1 minute') >= 3;
```

---

## Trin 6 — Auto-scaling (container-niveau)

Agenter deployes som individuelle containere. Scaling styres af queue-dybde og CPU.

### Docker Compose til lokal Stage 3

```yaml
# docker-compose.yml
services:
  routing_db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: routing_db
      POSTGRES_PASSWORD: ${ROUTING_DB_PASSWORD}
    volumes: [routing_data:/var/lib/postgresql/data]

  agent_db:
    image: postgres:16
    environment:
      POSTGRES_DB: agent_db
      POSTGRES_PASSWORD: ${AGENT_DB_PASSWORD}
    volumes: [agent_data:/var/lib/postgresql/data]

  user_db:
    image: postgres:16
    environment:
      POSTGRES_DB: user_db
      POSTGRES_PASSWORD: ${USER_DB_PASSWORD}
    volumes: [user_data:/var/lib/postgresql/data]

  audit_db:
    image: postgres:16
    environment:
      POSTGRES_DB: audit_db
      POSTGRES_PASSWORD: ${AUDIT_DB_PASSWORD}
    volumes: [audit_data:/var/lib/postgresql/data]

  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes
    volumes: [redis_data:/data]

  tdd_agent:
    build: ./agents/tdd_agent
    environment:
      ROUTING_DB_URL: postgresql://postgres:${ROUTING_DB_PASSWORD}@routing_db/routing_db
      AGENT_DB_URL:   postgresql://postgres:${AGENT_DB_PASSWORD}@agent_db/agent_db
      USER_DB_URL:    postgresql://postgres:${USER_DB_PASSWORD}@user_db/user_db
      AUDIT_DB_URL:   postgresql://postgres:${AUDIT_DB_PASSWORD}@audit_db/audit_db
      REDIS_URL:      redis://redis:6379
      LLM_API_KEY:    ${LLM_API_KEY}
    depends_on: [routing_db, agent_db, user_db, audit_db, redis]
    deploy:
      replicas: 2           # start med 2 — scale manuelt eller via Swarm/K8s
      restart_policy:
        condition: on-failure
        delay: 5s
        max_attempts: 3

volumes:
  routing_data:
  agent_data:
  user_data:
  audit_data:
  redis_data:
```

### Scaling-regler (Kubernetes / Docker Swarm)

| Metric | Grænse op | Grænse ned |
|--------|-----------|-----------|
| CPU per agent-container | > 70% | < 30% |
| Redis stream-dybde | > 100 ubehandlede events | < 10 |
| Inaktiv tid | — | > 30 min |
| SLA-brud rate | > 5% | < 1% |

---

## Trin 7 — Verificér Stage 3

```bash
# Er event bus aktiv og events flyder?
redis-cli XLEN agent_events

# Hvilke events er i køen?
redis-cli XRANGE agent_events - + COUNT 10

# Er consumer groups registreret?
redis-cli XINFO GROUPS agent_events

# Har en consumer group pending (uprocessede) events?
redis-cli XPENDING agent_events tdd_agent_group - + 10
```

```sql
-- Er opgaver fordelt på tværs af de fire databaser korrekt?
-- (kør i routing_db)
SELECT status, COUNT(*) FROM task_entries GROUP BY status;

-- (kør i agent_db)
SELECT agent_name, status, COUNT(*) FROM agent_output GROUP BY agent_name, status;

-- (kør i audit_db)
SELECT event_type, COUNT(*) FROM audit_log
WHERE occurred_at > NOW() - INTERVAL '1 hour'
GROUP BY event_type ORDER BY COUNT(*) DESC;
```

---

## Mappestruktur efter Stage 3

```
project/
├── .env
├── .env.example
├── docker-compose.yml          ← Trin 6
├── db/
│   ├── schema_routing.sql
│   ├── schema_agent.sql
│   ├── schema_user.sql
│   ├── schema_audit.sql
│   └── connections.py          ← Trin 2
├── bus/
│   ├── publisher.py            ← Trin 1
│   └── consumer.py             ← Trin 1
├── sync/
│   ├── task_sync.py
│   ├── router.py
│   └── embed_tasks.py
├── agents/
│   ├── shared/
│   │   ├── context.py
│   │   ├── retry.py
│   │   ├── notify.py
│   │   ├── circuit_breaker.py  ← Trin 3
│   │   ├── bulkhead.py         ← Trin 4
│   │   └── metrics.py          ← Trin 5
│   └── tdd_agent/
│       ├── SKILL.md
│       ├── agent.py
│       ├── run.py              ← event-driven (Trin 1)
│       └── prompts/
│           └── system.md
└── api/
    └── approve.py
```

---

## Stage 3 — Tjekliste

- [ ] Redis kører med `--appendonly yes` (events persisteres)
- [ ] `publisher.py` og `consumer.py` implementeret med consumer groups og `XACK`
- [ ] Agentens run-loop er event-driven — ingen polling
- [ ] Fire databaser oprettet: `routing_db`, `agent_db`, `user_db`, `audit_db`
- [ ] `audit_db` har `REVOKE DELETE/UPDATE` på `audit_log`
- [ ] `db/connections.py` bruges konsekvent — ingen hårdkodede connection strings
- [ ] Circuit Breaker wrapper alle LLM- og eksterne service-kald
- [ ] Bulkhead-limits defineret per prioritetsniveau
- [ ] `agent_metrics` gemmes per kørsel (varighed, tokens, success)
- [ ] Nøgle-queries bekræfter at events flyder og databaser er synkroniserede
- [ ] Docker Compose starter alle services reproducerbart

---

> **Næste skridt (Stage 4):** Tilføj perimeter-sikkerhed (WAF, API Gateway, TLS 1.3), Zero Trust mellem agenter via MCP, og en Shared Agent Protocol (SAP/A2A) der standardiserer kommunikation på tværs af agenter — inkl. structured handover af artefakter (test-rapporter, code drafts, PR-links).
