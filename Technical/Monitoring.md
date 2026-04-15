# Monitoring & Observability — Postgres Agent System

Komplet observability-setup for Postgres-løsningen. Alle fire databaser, MCP-serveren, event bussen og agenterne overvåges fra ét samlet sted — med Postgres som den primære kilde til metrics.

---

## Overblik

Postgres-løsningen har en unik fordel i forhold til observability: **alt er allerede i databasen**. Opgave-status, agent-output, eskaleringer og audit-logs er struktureret data i Postgres. Det betyder at størstedelen af monitoring kan bygges med SQL-queries mod eksisterende tabeller — suppleret med Prometheus for infrastruktur-metrics og Grafana for visualisering.

```mermaid
flowchart TD
    subgraph SYSTEM["System-komponenter"]
        MCP["MCP Server"]
        AGENTS["AI Agenter"]
        BUS["Event Bus\nRedis Streams"]
        ETL["ETL Scripts"]
    end

    subgraph POSTGRES["Postgres Databases"]
        RDB[("routing_db\nTASK_ENTRIES")]
        ADB[("agent_db\nAGENT_METRICS\nAGENT_OUTPUT")]
        AUDB[("audit_db\nAUDIT_LOG")]
    end

    subgraph OBSERVABILITY["Observability Stack"]
        PROM["Prometheus\nInfrastruktur-metrics"]
        PGEX["postgres_exporter\nDB-metrics"]
        LOKI["Loki\nLog-aggregering"]
        GRAF["Grafana\nDashboards + Alerting"]
    end

    subgraph ALERTS["Alerting"]
        SLACK["Slack\n#ops-alerts"]
        PD["PagerDuty\nOn-call"]
        EMAIL["Email\nEskalering"]
    end

    MCP -->|"metrics /metrics"| PROM
    AGENTS -->|"logs (JSON)"| LOKI
    BUS -->|"metrics"| PROM
    ETL -->|"logs (JSON)"| LOKI

    RDB --> PGEX
    ADB --> PGEX
    AUDB --> PGEX

    PGEX --> PROM
    PROM --> GRAF
    LOKI --> GRAF

    ADB -->|"agent_metrics\nSQL queries"| GRAF
    AUDB -->|"audit_log\nSQL queries"| GRAF

    GRAF -->|"Warning"| SLACK
    GRAF -->|"Critical"| PD
    GRAF -->|"Eskalering"| EMAIL

    classDef system fill:#1e3a5f,color:#ffffff,stroke:#3b82f6,stroke-width:2px
    classDef db fill:#1a3a2a,color:#ffffff,stroke:#22c55e,stroke-width:2px
    classDef obs fill:#4a1515,color:#ffffff,stroke:#ef4444,stroke-width:2px
    classDef alert fill:#374151,color:#ffffff,stroke:#6b7280,stroke-width:2px

    class MCP,AGENTS,BUS,ETL system
    class RDB,ADB,AUDB db
    class PROM,PGEX,LOKI,GRAF obs
    class SLACK,PD,EMAIL alert
```

### De tre observability-søjler

| Søjle | Kilde | Formål |
|-------|-------|--------|
| **Metrics** | Prometheus + Postgres SQL | Kvantitative målinger: latency, throughput, fejlrater |
| **Logs** | Loki + audit_db | Strukturerede hændelser: hvem gjorde hvad hvornår |
| **Traces** | audit_db event-kæder | Opgave-flow fra ingest til completion |

---

## 1. Database-skema til metrics

Metrics gemmes i `agent_db` og `audit_db` — de er allerede en del af Postgres-arkitekturen.

### agent_metrics tabellen

```sql
-- agent_db: agent_metrics
-- Gemmer performance-data for hvert agent-kald.
-- Bruges direkte i Grafana via PostgreSQL data source.

CREATE TABLE agent_metrics (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_name    TEXT        NOT NULL,
    task_entry_id UUID        NOT NULL,
    duration_ms   INTEGER     NOT NULL,
    llm_tokens_used INTEGER   NOT NULL DEFAULT 0,
    token_input   INTEGER     NOT NULL DEFAULT 0,
    token_output  INTEGER     NOT NULL DEFAULT 0,
    success       BOOLEAN     NOT NULL,
    error_type    TEXT,                              -- 'timeout', 'llm_error', 'validation', NULL
    retry_count   INTEGER     NOT NULL DEFAULT 0,
    recorded_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indekser til hurtige dashboard-queries
CREATE INDEX idx_metrics_agent_time   ON agent_metrics (agent_name, recorded_at DESC);
CREATE INDEX idx_metrics_success_time ON agent_metrics (success, recorded_at DESC);
CREATE INDEX idx_metrics_recorded     ON agent_metrics (recorded_at DESC);

-- Partitionering for langtidsdata (valgfrit, anbefalet ved >100k rækker/dag)
-- CREATE TABLE agent_metrics_partitioned (LIKE agent_metrics INCLUDING ALL)
--     PARTITION BY RANGE (recorded_at);
```

### mcp_access_log tabellen

```sql
-- audit_db: mcp_access_log
-- Logning af alle MCP tool-kald — supplement til audit_log.
-- Giver finere granularitet for MCP-specifik monitoring.

CREATE TABLE mcp_access_log (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_name    TEXT        NOT NULL,
    tool_name     TEXT        NOT NULL,
    params_hash   TEXT,                              -- SHA-256 af params (ikke selve data)
    status        TEXT        NOT NULL,              -- 'success', 'denied', 'error', 'rate_limited'
    duration_ms   INTEGER     NOT NULL,
    db_name       TEXT,                              -- 'routing', 'agent', 'user', 'audit', NULL
    response_size INTEGER     DEFAULT 0,             -- bytes i respons
    ip_address    INET,
    occurred_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_mcp_agent_time ON mcp_access_log (agent_name, occurred_at DESC);
CREATE INDEX idx_mcp_tool_time  ON mcp_access_log (tool_name, occurred_at DESC);
CREATE INDEX idx_mcp_status     ON mcp_access_log (status, occurred_at DESC);
```

---

## 2. Instrumentering af kode

### 2a. Agent metrics-recording

```python
# agents/shared/metrics.py
"""
Gem performance-metrics i agent_db ved hvert agent-kald.
Bruges af alle agenter — TDD, review, PO, context.
"""
import time
import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Optional

from db.connections import db

logger = logging.getLogger("agent.metrics")


@dataclass
class MetricsContext:
    """Samler metrics under et agent-kald."""
    agent_name: str
    task_id: str
    start_time: float = field(default_factory=time.monotonic)
    token_input: int = 0
    token_output: int = 0
    retry_count: int = 0
    error_type: Optional[str] = None
    success: bool = True


@contextmanager
def track_agent_call(agent_name: str, task_id: str):
    """
    Context manager der automatisk tracker tid og gemmer metrics.

    Brug:
        with track_agent_call("tdd_agent", task_id) as ctx:
            response = client.messages.create(...)
            ctx.token_input = response.usage.input_tokens
            ctx.token_output = response.usage.output_tokens
    """
    ctx = MetricsContext(agent_name=agent_name, task_id=task_id)
    try:
        yield ctx
    except Exception as e:
        ctx.success = False
        ctx.error_type = type(e).__name__
        raise
    finally:
        duration_ms = int((time.monotonic() - ctx.start_time) * 1000)
        _save_metrics(ctx, duration_ms)


def _save_metrics(ctx: MetricsContext, duration_ms: int) -> None:
    """Gem metrics i agent_db.agent_metrics."""
    try:
        with db("agent") as (_, cur):
            cur.execute("""
                INSERT INTO agent_metrics
                    (agent_name, task_entry_id, duration_ms,
                     llm_tokens_used, token_input, token_output,
                     success, error_type, retry_count)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                ctx.agent_name,
                ctx.task_id,
                duration_ms,
                ctx.token_input + ctx.token_output,
                ctx.token_input,
                ctx.token_output,
                ctx.success,
                ctx.error_type,
                ctx.retry_count,
            ))
    except Exception as e:
        # Metrics-fejl må ALDRIG stoppe agent-arbejde
        logger.error(f"Metrics-lagring fejlede: {e}")
```

### 2b. Brug i en agent

```python
# agents/tdd_agent/agent.py
from agents.shared.metrics import track_agent_call
from agents.shared.mcp_client import MCPClient

mcp = MCPClient()

def run(task_id: str) -> dict:
    with track_agent_call("tdd_agent", task_id) as ctx:
        # Hent kontekst via MCP
        task_ctx = mcp.call("get_task_context", {"task_id": task_id})

        # Kald LLM
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            messages=[{"role": "user", "content": build_prompt(task_ctx)}],
        )

        # Registrér token-forbrug
        ctx.token_input = response.usage.input_tokens
        ctx.token_output = response.usage.output_tokens

        result = parse_response(response)

        # Gem output via MCP
        mcp.call("save_agent_output", {
            "task_id": task_id,
            "result": result,
            "status": "done",
        })

        return result
```

### 2c. MCP Server metrics-endpoint

```python
# mcp/metrics_endpoint.py
"""
Prometheus-kompatibelt /metrics endpoint for MCP-serveren.
Eksponerer counters, histogrammer og gauges til Prometheus scraping.
"""
from prometheus_client import (
    Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
)
from fastapi import Response

# ─── Counters ────────────────────────────────────────────────────
tool_calls_total = Counter(
    "mcp_tool_calls_total",
    "Antal MCP tool-kald",
    ["agent_name", "tool_name", "status"],
)

auth_failures_total = Counter(
    "mcp_auth_failures_total",
    "Antal fejlede authentication-forsøg",
    ["reason"],
)

# ─── Histogrammer ────────────────────────────────────────────────
tool_duration_seconds = Histogram(
    "mcp_tool_duration_seconds",
    "Varighed af MCP tool-kald i sekunder",
    ["agent_name", "tool_name"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

# ─── Gauges ──────────────────────────────────────────────────────
active_connections = Gauge(
    "mcp_db_active_connections",
    "Aktive database-forbindelser per pool",
    ["database"],
)

queue_depth = Gauge(
    "mcp_event_queue_depth",
    "Antal ubehandlede events i kø",
)


async def metrics_endpoint():
    """GET /metrics — Prometheus scrape-endpoint."""
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )
```

### 2d. Struktureret JSON-logging

```python
# agents/shared/logging_config.py
"""
JSON-formateret logging til stdout — opsamles af Loki/Fluentd.
Alle agenter og MCP-serveren bruger denne konfiguration.
"""
import json
import logging
import sys
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    """Formatér log-entries som JSON til maskinel parsing."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Tilføj ekstra felter hvis de findes
        for key in ("agent_name", "task_id", "tool_name", "duration_ms",
                     "tokens_used", "error_type", "request_id"):
            if hasattr(record, key):
                log_entry[key] = getattr(record, key)

        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry)


def setup_logging(service_name: str, level: str = "INFO") -> None:
    """Konfigurér JSON-logging for en service."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    root = logging.getLogger()
    root.setLevel(getattr(logging, level))
    root.addHandler(handler)

    # Dæmp noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
```

---

## 3. Prometheus-konfiguration

### prometheus.yml

```yaml
# prometheus/prometheus.yml
global:
  scrape_interval: 15s
  evaluation_interval: 15s
  external_labels:
    environment: "production"
    system: "cgi-agent"

# ─── Scrape-konfiguration ───────────────────────────────────────
scrape_configs:

  # MCP Server — applikations-metrics
  - job_name: "mcp-server"
    static_configs:
      - targets: ["mcp-server:8000"]
    metrics_path: "/metrics"
    scrape_interval: 10s

  # Postgres — database-metrics via postgres_exporter
  - job_name: "postgres-routing"
    static_configs:
      - targets: ["postgres-exporter-routing:9187"]
    params:
      target: ["routing-db:5432"]

  - job_name: "postgres-agent"
    static_configs:
      - targets: ["postgres-exporter-agent:9187"]
    params:
      target: ["agent-db:5432"]

  - job_name: "postgres-audit"
    static_configs:
      - targets: ["postgres-exporter-audit:9187"]
    params:
      target: ["audit-db:5432"]

  - job_name: "postgres-user"
    static_configs:
      - targets: ["postgres-exporter-user:9187"]
    params:
      target: ["user-db:5432"]

  # Redis — event bus metrics
  - job_name: "redis"
    static_configs:
      - targets: ["redis-exporter:9121"]

  # Node Exporter — host-level metrics (CPU, RAM, disk)
  - job_name: "node"
    static_configs:
      - targets: ["node-exporter:9100"]

# ─── Alert-regler ────────────────────────────────────────────────
rule_files:
  - "/etc/prometheus/rules/*.yml"

# ─── Alertmanager ────────────────────────────────────────────────
alerting:
  alertmanagers:
    - static_configs:
        - targets: ["alertmanager:9093"]
```

### postgres_exporter custom queries

```yaml
# postgres-exporter/queries.yml
# Custom queries der eksponerer Postgres-løsningens egne tabeller som metrics.
# Disse supplerer standard pg_stat-metrics med domænespecifikke data.

pg_task_status:
  query: |
    SELECT
      status,
      priority,
      COUNT(*) AS count
    FROM task_entries
    GROUP BY status, priority
  metrics:
    - status:
        usage: "LABEL"
    - priority:
        usage: "LABEL"
    - count:
        usage: "GAUGE"
        description: "Antal opgaver per status og prioritet"

pg_agent_performance:
  query: |
    SELECT
      agent_name,
      ROUND(AVG(duration_ms))::int AS avg_duration_ms,
      ROUND(AVG(llm_tokens_used))::int AS avg_tokens,
      ROUND(100.0 * COUNT(*) FILTER (WHERE NOT success) / NULLIF(COUNT(*), 0), 1) AS error_pct,
      COUNT(*) AS total_runs
    FROM agent_metrics
    WHERE recorded_at > NOW() - INTERVAL '5 minutes'
    GROUP BY agent_name
  metrics:
    - agent_name:
        usage: "LABEL"
    - avg_duration_ms:
        usage: "GAUGE"
        description: "Gennemsnitlig agent-varighed i ms (5 min vindue)"
    - avg_tokens:
        usage: "GAUGE"
        description: "Gennemsnitligt token-forbrug (5 min vindue)"
    - error_pct:
        usage: "GAUGE"
        description: "Fejlrate i procent (5 min vindue)"
    - total_runs:
        usage: "GAUGE"
        description: "Antal kørsler i vindue"

pg_sla_breaches:
  query: |
    SELECT
      te.priority,
      COUNT(*) AS breach_count
    FROM task_entries te
    JOIN user_chain uc ON uc.id = te.assigned_to
    WHERE te.status NOT IN ('done', 'blocked')
      AND EXTRACT(EPOCH FROM (NOW() - te.created_at)) / 3600 > uc.sla_hours
    GROUP BY te.priority
  metrics:
    - priority:
        usage: "LABEL"
    - breach_count:
        usage: "GAUGE"
        description: "Antal opgaver der overskrider SLA"

pg_mcp_tool_usage:
  query: |
    SELECT
      tool_name,
      status,
      COUNT(*) AS call_count,
      ROUND(AVG(duration_ms))::int AS avg_ms
    FROM mcp_access_log
    WHERE occurred_at > NOW() - INTERVAL '5 minutes'
    GROUP BY tool_name, status
  metrics:
    - tool_name:
        usage: "LABEL"
    - status:
        usage: "LABEL"
    - call_count:
        usage: "GAUGE"
        description: "MCP tool-kald (5 min vindue)"
    - avg_ms:
        usage: "GAUGE"
        description: "Gennemsnitlig MCP tool-latens i ms"

pg_escalation_rate:
  query: |
    SELECT
      COUNT(*) FILTER (WHERE escalated_at > NOW() - INTERVAL '1 hour') AS last_hour,
      COUNT(*) FILTER (WHERE escalated_at > NOW() - INTERVAL '24 hours') AS last_24h
    FROM escalation_log
  metrics:
    - last_hour:
        usage: "GAUGE"
        description: "Eskaleringer seneste time"
    - last_24h:
        usage: "GAUGE"
        description: "Eskaleringer seneste 24 timer"

pg_token_usage:
  query: |
    SELECT
      agent_name,
      SUM(token_input) AS total_input_tokens,
      SUM(token_output) AS total_output_tokens,
      SUM(llm_tokens_used) AS total_tokens
    FROM agent_metrics
    WHERE recorded_at > NOW() - INTERVAL '1 hour'
    GROUP BY agent_name
  metrics:
    - agent_name:
        usage: "LABEL"
    - total_input_tokens:
        usage: "GAUGE"
        description: "Input-tokens seneste time"
    - total_output_tokens:
        usage: "GAUGE"
        description: "Output-tokens seneste time"
    - total_tokens:
        usage: "GAUGE"
        description: "Samlede tokens seneste time"
```

---

## 4. Alert-regler

### Prometheus alerting rules

```yaml
# prometheus/rules/agent_alerts.yml
groups:

  # ─── Agent Health ────────────────────────────────────────────────
  - name: agent_health
    rules:

      - alert: AgentHighErrorRate
        expr: pg_agent_performance_error_pct > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Agent {{ $labels.agent_name }} har >10% fejlrate"
          description: "Fejlrate er {{ $value }}% over de seneste 5 minutter."
          runbook: "https://wiki.intern/runbooks/agent-error-rate"

      - alert: AgentCriticalErrorRate
        expr: pg_agent_performance_error_pct > 50
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Agent {{ $labels.agent_name }} har >50% fejlrate — mulig circuit breaker"
          description: "Fejlrate er {{ $value }}%. Kontrollér LLM-forbindelse og database."

      - alert: AgentSlowResponse
        expr: pg_agent_performance_avg_duration_ms > 30000
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Agent {{ $labels.agent_name }} er langsom (>30s gennemsnit)"
          description: "Gennemsnitlig varighed er {{ $value }}ms."

      - alert: AgentNotRunning
        expr: pg_agent_performance_total_runs == 0
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Agent {{ $labels.agent_name }} har ikke kørt i 15 minutter"
          description: "Tjek om agenten er oppe og modtager events fra bussen."

  # ─── SLA Compliance ─────────────────────────────────────────────
  - name: sla_compliance
    rules:

      - alert: SLABreachCritical
        expr: pg_sla_breaches_breach_count{priority="critical"} > 0
        for: 0m
        labels:
          severity: critical
        annotations:
          summary: "{{ $value }} kritiske opgaver overskrider SLA"
          description: "Kritiske opgaver SKAL eskaleres øjeblikkeligt."

      - alert: SLABreachHigh
        expr: pg_sla_breaches_breach_count{priority="high"} > 3
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "{{ $value }} høj-prioritet opgaver overskrider SLA"

  # ─── Token Usage ─────────────────────────────────────────────────
  - name: token_usage
    rules:

      - alert: TokenBudgetWarning
        expr: sum(pg_token_usage_total_tokens) > 500000
        for: 0m
        labels:
          severity: warning
        annotations:
          summary: "Token-forbrug over 500k seneste time"
          description: "Samlet forbrug: {{ $value }} tokens. Tjek om en agent looper."

      - alert: TokenBudgetCritical
        expr: sum(pg_token_usage_total_tokens) > 2000000
        for: 0m
        labels:
          severity: critical
        annotations:
          summary: "Token-forbrug over 2M seneste time — muligt loop"
          description: "Samlet forbrug: {{ $value }}. Stop berørte agenter omgående."

      - alert: SingleAgentTokenSpike
        expr: pg_token_usage_total_tokens > 300000
        for: 0m
        labels:
          severity: warning
        annotations:
          summary: "Agent {{ $labels.agent_name }} har brugt >300k tokens seneste time"

  # ─── MCP Server ──────────────────────────────────────────────────
  - name: mcp_health
    rules:

      - alert: MCPHighLatency
        expr: pg_mcp_tool_usage_avg_ms > 5000
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "MCP tool {{ $labels.tool_name }} har >5s gennemsnitlig latens"

      - alert: MCPAuthFailures
        expr: rate(mcp_auth_failures_total[5m]) > 1
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Gentagne MCP auth-fejl — mulig angrebsvektor"
          description: "{{ $value }} fejl/sekund. Tjek audit_db for detaljer."

      - alert: MCPRateLimited
        expr: pg_mcp_tool_usage_call_count{status="rate_limited"} > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Agent {{ $labels.agent_name }} bliver rate limited"

  # ─── Database Health ─────────────────────────────────────────────
  - name: database_health
    rules:

      - alert: DatabaseConnectionPoolExhausted
        expr: pg_stat_activity_count > pg_settings_max_connections * 0.9
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Database {{ $labels.datname }} connection pool >90% brugt"

      - alert: DatabaseSlowQueries
        expr: pg_stat_activity_max_tx_duration > 60
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Langsom query i {{ $labels.datname }} (>60s)"

      - alert: DiskSpaceRunningLow
        expr: pg_database_size_bytes / 1024 / 1024 / 1024 > 50
        for: 0m
        labels:
          severity: warning
        annotations:
          summary: "Database {{ $labels.datname }} er over 50GB"

  # ─── Event Bus ───────────────────────────────────────────────────
  - name: event_bus
    rules:

      - alert: EventQueueBacklog
        expr: mcp_event_queue_depth > 500
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Event-kø har >500 ubehandlede beskeder"

      - alert: EventQueueCritical
        expr: mcp_event_queue_depth > 2000
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Event-kø har >2000 ubehandlede beskeder — scale agenter op"
```

### Alertmanager-konfiguration

```yaml
# alertmanager/alertmanager.yml
global:
  resolve_timeout: 5m
  slack_api_url: "${SLACK_WEBHOOK_URL}"

route:
  receiver: "default-slack"
  group_by: ["alertname", "severity"]
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h

  routes:
    # Critical → PagerDuty + Slack
    - match:
        severity: critical
      receiver: "pagerduty-critical"
      repeat_interval: 15m

    # Warning → Slack
    - match:
        severity: warning
      receiver: "slack-warnings"
      repeat_interval: 4h

receivers:
  - name: "default-slack"
    slack_configs:
      - channel: "#ops-alerts"
        title: "{{ .GroupLabels.alertname }}"
        text: "{{ range .Alerts }}{{ .Annotations.summary }}\n{{ end }}"

  - name: "pagerduty-critical"
    pagerduty_configs:
      - service_key: "${PAGERDUTY_SERVICE_KEY}"
        severity: critical
    slack_configs:
      - channel: "#ops-critical"
        title: "🔴 CRITICAL: {{ .GroupLabels.alertname }}"
        text: "{{ range .Alerts }}{{ .Annotations.description }}\n{{ end }}"

  - name: "slack-warnings"
    slack_configs:
      - channel: "#ops-alerts"
        title: "⚠️ WARNING: {{ .GroupLabels.alertname }}"
        text: "{{ range .Alerts }}{{ .Annotations.summary }}\n{{ end }}"
```

---

## 5. Grafana Dashboards

### 5a. Agent Performance Dashboard

```sql
-- Panel: Agent-gennemsnitsvarighed (time series)
SELECT
    recorded_at AS time,
    agent_name,
    AVG(duration_ms) OVER (
        PARTITION BY agent_name
        ORDER BY recorded_at
        ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
    ) AS avg_duration_ms
FROM agent_metrics
WHERE recorded_at > NOW() - INTERVAL '${__range}'
ORDER BY recorded_at;

-- Panel: Fejlrate per agent (gauge)
SELECT
    agent_name,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE NOT success) /
        NULLIF(COUNT(*), 0), 1
    ) AS error_pct
FROM agent_metrics
WHERE recorded_at > NOW() - INTERVAL '1 hour'
GROUP BY agent_name;

-- Panel: Opgaver per status (pie chart)
SELECT status, COUNT(*) AS count
FROM task_entries
GROUP BY status;

-- Panel: Top 10 langsomste opgaver (tabel)
SELECT
    am.agent_name,
    te.source_ref,
    te.priority,
    am.duration_ms,
    am.llm_tokens_used,
    am.recorded_at
FROM agent_metrics am
JOIN task_entries te ON te.id = am.task_entry_id
WHERE am.recorded_at > NOW() - INTERVAL '24 hours'
ORDER BY am.duration_ms DESC
LIMIT 10;
```

### 5b. Token-forbrug Dashboard

```sql
-- Panel: Token-forbrug per time (time series)
SELECT
    date_trunc('hour', recorded_at) AS time,
    agent_name,
    SUM(token_input) AS input_tokens,
    SUM(token_output) AS output_tokens,
    SUM(llm_tokens_used) AS total_tokens
FROM agent_metrics
WHERE recorded_at > NOW() - INTERVAL '${__range}'
GROUP BY date_trunc('hour', recorded_at), agent_name
ORDER BY time;

-- Panel: Estimeret LLM-omkostning per dag (stat)
SELECT
    ROUND(
        (SUM(token_input) * 0.000003 +
         SUM(token_output) * 0.000015)::numeric, 2
    ) AS estimated_cost_usd
FROM agent_metrics
WHERE recorded_at > NOW() - INTERVAL '24 hours';

-- Panel: Token-effektivitet per agent (bar chart)
SELECT
    agent_name,
    ROUND(AVG(token_input)) AS avg_input,
    ROUND(AVG(token_output)) AS avg_output,
    ROUND(AVG(llm_tokens_used)) AS avg_total,
    COUNT(*) AS total_calls
FROM agent_metrics
WHERE recorded_at > NOW() - INTERVAL '24 hours'
    AND success = true
GROUP BY agent_name
ORDER BY avg_total DESC;

-- Panel: Token-budget forbrug (gauge)
-- Månedligt budget: 10M tokens
SELECT
    ROUND(
        100.0 * SUM(llm_tokens_used) /
        10000000.0, 1
    ) AS budget_usage_pct
FROM agent_metrics
WHERE recorded_at > date_trunc('month', NOW());
```

### 5c. MCP & Database Health Dashboard

```sql
-- Panel: MCP tool-kald per minut (time series)
SELECT
    date_trunc('minute', occurred_at) AS time,
    tool_name,
    COUNT(*) AS calls
FROM mcp_access_log
WHERE occurred_at > NOW() - INTERVAL '${__range}'
GROUP BY time, tool_name
ORDER BY time;

-- Panel: MCP adgangsnægtelser (tabel)
SELECT
    agent_name,
    tool_name,
    status,
    COUNT(*) AS count,
    MAX(occurred_at) AS last_seen
FROM mcp_access_log
WHERE status IN ('denied', 'rate_limited')
    AND occurred_at > NOW() - INTERVAL '24 hours'
GROUP BY agent_name, tool_name, status
ORDER BY count DESC;

-- Panel: Database-størrelse (bar chart)
SELECT
    datname,
    pg_database_size(datname) / 1024 / 1024 AS size_mb
FROM pg_database
WHERE datname IN ('routing_db', 'agent_db', 'user_db', 'audit_db');

-- Panel: Aktive forbindelser per database (gauge)
SELECT
    datname,
    COUNT(*) AS active_connections
FROM pg_stat_activity
WHERE datname IN ('routing_db', 'agent_db', 'user_db', 'audit_db')
GROUP BY datname;
```

### 5d. SLA & Eskalerings Dashboard

```sql
-- Panel: SLA-overholdelse (gauge, mål: >95%)
SELECT
    ROUND(
        100.0 * COUNT(*) FILTER (
            WHERE status = 'done'
            AND EXTRACT(EPOCH FROM (routed_at - created_at)) / 3600 <=
                COALESCE((SELECT sla_hours FROM user_chain WHERE id = te.assigned_to), 24)
        ) / NULLIF(COUNT(*) FILTER (WHERE status = 'done'), 0), 1
    ) AS sla_compliance_pct
FROM task_entries te
WHERE created_at > NOW() - INTERVAL '30 days';

-- Panel: Eskaleringer over tid (time series)
SELECT
    date_trunc('day', escalated_at) AS time,
    reason,
    COUNT(*) AS escalations
FROM escalation_log
WHERE escalated_at > NOW() - INTERVAL '30 days'
GROUP BY time, reason
ORDER BY time;

-- Panel: Gennemsnitlig tid til løsning per prioritet (bar chart)
SELECT
    priority,
    ROUND(AVG(
        EXTRACT(EPOCH FROM (routed_at - created_at)) / 3600
    )::numeric, 1) AS avg_hours_to_resolve
FROM task_entries
WHERE status = 'done'
    AND created_at > NOW() - INTERVAL '30 days'
GROUP BY priority
ORDER BY
    CASE priority
        WHEN 'critical' THEN 1
        WHEN 'high' THEN 2
        WHEN 'normal' THEN 3
        WHEN 'low' THEN 4
    END;
```

---

## 6. Audit Trail som Tracing

I Postgres-løsningen erstatter `audit_db.audit_log` traditionel distributed tracing. Hvert event i systemet logges med entity_id, der gør det muligt at rekonstruere hele flowet for en opgave.

### Opgave-trace query

```sql
-- Fuld trace for en specifik opgave — alle events kronologisk
SELECT
    al.occurred_at,
    al.event_type,
    al.actor,
    al.payload->>'tool_name'      AS tool,
    al.payload->>'result_status'   AS status,
    al.payload->>'duration_ms'     AS duration,
    al.payload->>'error'           AS error
FROM audit_log al
WHERE al.entity_id = (
    SELECT id FROM task_entries WHERE source_ref = 'PROJ-421'
)
ORDER BY al.occurred_at;
```

**Eksempel output:**

```
occurred_at              | event_type        | actor         | tool              | status  | duration | error
─────────────────────────┼───────────────────┼───────────────┼───────────────────┼─────────┼──────────┼──────
2026-04-15 10:00:01.234  | task.created      | etl_jira      | NULL              | NULL    | NULL     | NULL
2026-04-15 10:00:01.567  | task.routed       | router        | NULL              | NULL    | NULL     | NULL
2026-04-15 10:00:02.012  | mcp.tool_call     | tdd_agent     | get_task_context  | success | 45       | NULL
2026-04-15 10:00:08.890  | mcp.tool_call     | tdd_agent     | run_tests         | success | 6200     | NULL
2026-04-15 10:00:09.123  | mcp.tool_call     | tdd_agent     | save_agent_output | success | 12       | NULL
2026-04-15 10:00:09.234  | agent.done        | tdd_agent     | NULL              | done    | 8000     | NULL
2026-04-15 10:00:09.345  | notification.sent | notifier      | NULL              | success | NULL     | NULL
```

### Trace-visualisering i Grafana

Grafana understøtter `Traces`-paneler direkte fra PostgreSQL data source. Byg en trace-visualisering med denne query:

```sql
-- Grafana Trace panel — konvertér audit_log til trace-format
SELECT
    al.id::text                                  AS "traceID",
    al.id::text                                  AS "spanID",
    al.actor                                     AS "operationName",
    al.event_type                                AS "serviceName",
    EXTRACT(EPOCH FROM al.occurred_at) * 1000    AS "startTime",
    COALESCE((al.payload->>'duration_ms')::float, 1) AS "duration",
    jsonb_build_object(
        'tool', al.payload->>'tool_name',
        'status', al.payload->>'result_status',
        'error', al.payload->>'error'
    )                                            AS "tags"
FROM audit_log al
WHERE al.entity_id = $task_id
ORDER BY al.occurred_at;
```

---

## 7. Nøgle-queries til drift-overvågning

Queries der kan køres manuelt eller integreres i dashboards og alerts.

### System-sundhed

```sql
-- Samlet systemstatus — ét blik
SELECT
    (SELECT COUNT(*) FROM task_entries WHERE status = 'new')        AS pending_tasks,
    (SELECT COUNT(*) FROM task_entries WHERE status = 'in_progress') AS active_tasks,
    (SELECT COUNT(*) FROM task_entries WHERE status = 'done'
        AND created_at > NOW() - INTERVAL '24 hours')              AS completed_today,
    (SELECT COUNT(*) FROM agent_metrics
        WHERE NOT success AND recorded_at > NOW() - INTERVAL '1 hour') AS errors_last_hour,
    (SELECT ROUND(AVG(duration_ms)) FROM agent_metrics
        WHERE recorded_at > NOW() - INTERVAL '1 hour')             AS avg_latency_ms,
    (SELECT SUM(llm_tokens_used) FROM agent_metrics
        WHERE recorded_at > NOW() - INTERVAL '1 hour')             AS tokens_last_hour;
```

### Circuit breaker-status

```sql
-- Agenter der nærmer sig circuit breaker-grænsen (3 fejl/minut)
SELECT
    agent_name,
    COUNT(*) FILTER (
        WHERE NOT success
        AND recorded_at > NOW() - INTERVAL '1 minute'
    ) AS failures_last_min,
    CASE
        WHEN COUNT(*) FILTER (
            WHERE NOT success AND recorded_at > NOW() - INTERVAL '1 minute'
        ) >= 3 THEN '🔴 OPEN'
        WHEN COUNT(*) FILTER (
            WHERE NOT success AND recorded_at > NOW() - INTERVAL '1 minute'
        ) >= 2 THEN '🟡 HALF-OPEN'
        ELSE '🟢 CLOSED'
    END AS breaker_status
FROM agent_metrics
WHERE recorded_at > NOW() - INTERVAL '5 minutes'
GROUP BY agent_name;
```

### Token-anomali-detektion

```sql
-- Find agenter med unormalt højt token-forbrug
-- (mere end 3× standardafvigelse over gennemsnittet)
WITH agent_stats AS (
    SELECT
        agent_name,
        AVG(llm_tokens_used) AS avg_tokens,
        STDDEV(llm_tokens_used) AS stddev_tokens
    FROM agent_metrics
    WHERE recorded_at > NOW() - INTERVAL '7 days'
        AND success = true
    GROUP BY agent_name
)
SELECT
    am.agent_name,
    am.task_entry_id,
    am.llm_tokens_used,
    ast.avg_tokens,
    ROUND((am.llm_tokens_used - ast.avg_tokens) / NULLIF(ast.stddev_tokens, 0), 1) AS z_score
FROM agent_metrics am
JOIN agent_stats ast ON ast.agent_name = am.agent_name
WHERE am.recorded_at > NOW() - INTERVAL '1 hour'
    AND am.llm_tokens_used > ast.avg_tokens + (3 * ast.stddev_tokens)
ORDER BY z_score DESC;
```

### Audit-anomalier

```sql
-- Uventede event-mønstre de seneste 24 timer
SELECT
    event_type,
    actor,
    COUNT(*) AS count,
    MIN(occurred_at) AS first_seen,
    MAX(occurred_at) AS last_seen
FROM audit_log
WHERE occurred_at > NOW() - INTERVAL '24 hours'
    AND event_type LIKE 'mcp.auth_failure%'
GROUP BY event_type, actor
HAVING COUNT(*) > 5
ORDER BY count DESC;
```

---

## 8. Docker Compose — komplet observability stack

```yaml
# docker-compose.observability.yml
# Tilføj til hoved docker-compose.yml med:
#   docker compose -f docker-compose.yml -f docker-compose.observability.yml up

services:

  prometheus:
    image: prom/prometheus:v2.51.0
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - ./prometheus/rules:/etc/prometheus/rules:ro
      - prometheus_data:/prometheus
    command:
      - "--config.file=/etc/prometheus/prometheus.yml"
      - "--storage.tsdb.retention.time=30d"
      - "--web.enable-lifecycle"
    networks:
      - internal
    restart: unless-stopped

  alertmanager:
    image: prom/alertmanager:v0.27.0
    ports:
      - "9093:9093"
    volumes:
      - ./alertmanager/alertmanager.yml:/etc/alertmanager/alertmanager.yml:ro
    networks:
      - internal
    restart: unless-stopped

  grafana:
    image: grafana/grafana:10.4.0
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_PASSWORD}
      - GF_INSTALL_PLUGINS=grafana-piechart-panel
    volumes:
      - grafana_data:/var/lib/grafana
      - ./grafana/provisioning:/etc/grafana/provisioning:ro
      - ./grafana/dashboards:/var/lib/grafana/dashboards:ro
    networks:
      - internal
    restart: unless-stopped

  loki:
    image: grafana/loki:2.9.6
    ports:
      - "3100:3100"
    volumes:
      - loki_data:/loki
    networks:
      - internal
    restart: unless-stopped

  promtail:
    image: grafana/promtail:2.9.6
    volumes:
      - ./promtail/config.yml:/etc/promtail/config.yml:ro
      - /var/log:/var/log:ro
      - /var/lib/docker/containers:/var/lib/docker/containers:ro
    networks:
      - internal
    restart: unless-stopped

  # Postgres exporters — én per database
  postgres-exporter-routing:
    image: prometheuscommunity/postgres-exporter:v0.15.0
    environment:
      DATA_SOURCE_NAME: "postgresql://mcp_routing_rw:${ROUTING_DB_PASSWORD}@routing-db:5432/routing_db?sslmode=require"
      PG_EXPORTER_EXTEND_QUERY_PATH: "/etc/queries.yml"
    volumes:
      - ./postgres-exporter/queries.yml:/etc/queries.yml:ro
    networks:
      - internal

  postgres-exporter-agent:
    image: prometheuscommunity/postgres-exporter:v0.15.0
    environment:
      DATA_SOURCE_NAME: "postgresql://mcp_agent_rw:${AGENT_DB_PASSWORD}@agent-db:5432/agent_db?sslmode=require"
      PG_EXPORTER_EXTEND_QUERY_PATH: "/etc/queries.yml"
    volumes:
      - ./postgres-exporter/queries.yml:/etc/queries.yml:ro
    networks:
      - internal

  postgres-exporter-audit:
    image: prometheuscommunity/postgres-exporter:v0.15.0
    environment:
      DATA_SOURCE_NAME: "postgresql://mcp_audit_append:${AUDIT_DB_PASSWORD}@audit-db:5432/audit_db?sslmode=require"
    networks:
      - internal

  postgres-exporter-user:
    image: prometheuscommunity/postgres-exporter:v0.15.0
    environment:
      DATA_SOURCE_NAME: "postgresql://mcp_user_ro:${USER_DB_PASSWORD}@user-db:5432/user_db?sslmode=require"
    networks:
      - internal

  redis-exporter:
    image: oliver006/redis_exporter:v1.58.0
    environment:
      REDIS_ADDR: "redis://redis:6379"
    networks:
      - internal

  node-exporter:
    image: prom/node-exporter:v1.7.0
    ports:
      - "9100:9100"
    networks:
      - internal

volumes:
  prometheus_data:
  grafana_data:
  loki_data:

networks:
  internal:
    external: true
```

---

## 9. Grafana Data Source Provisioning

```yaml
# grafana/provisioning/datasources/datasources.yml
apiVersion: 1

datasources:
  # Prometheus — infrastruktur og applikations-metrics
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
    editable: false

  # Loki — log-aggregering
  - name: Loki
    type: loki
    access: proxy
    url: http://loki:3100
    editable: false

  # Postgres routing_db — direkte SQL queries
  - name: routing_db
    type: postgres
    url: routing-db:5432
    database: routing_db
    user: grafana_reader
    secureJsonData:
      password: "${GRAFANA_ROUTING_DB_PASSWORD}"
    jsonData:
      sslmode: require
      postgresVersion: 1600
    editable: false

  # Postgres agent_db — metrics og output
  - name: agent_db
    type: postgres
    url: agent-db:5432
    database: agent_db
    user: grafana_reader
    secureJsonData:
      password: "${GRAFANA_AGENT_DB_PASSWORD}"
    jsonData:
      sslmode: require
      postgresVersion: 1600
    editable: false

  # Postgres audit_db — audit trail og traces
  - name: audit_db
    type: postgres
    url: audit-db:5432
    database: audit_db
    user: grafana_reader
    secureJsonData:
      password: "${GRAFANA_AUDIT_DB_PASSWORD}"
    jsonData:
      sslmode: require
      postgresVersion: 1600
    editable: false
```

```sql
-- Opret read-only Grafana-bruger i alle databaser
-- Kør i routing_db, agent_db og audit_db

CREATE ROLE grafana_reader LOGIN PASSWORD '...';
GRANT SELECT ON ALL TABLES IN SCHEMA public TO grafana_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON TABLES TO grafana_reader;

-- Grafana-brugeren kan IKKE skrive, slette eller ændre
```

---

## 10. Opsummering

### Observability i Postgres-løsningen er enklere end i en AI-swarm

I en traditionel AI-swarm er observability svært fordi agenter er autonome, stateless og kommunikerer via ustrukturerede beskeder. I Postgres-løsningen er al state i databasen — monitoring er bare SQL.

```mermaid
flowchart LR
    subgraph TRAD["Traditionel (svært)"]
        T1["Agent-logs\n(ustruktureret)"]
        T2["Inter-agent messages\n(ingen central log)"]
        T3["Custom instrumentation\n(per agent)"]
    end

    subgraph PG["Postgres-løsning (let)"]
        P1["agent_metrics\n(struktureret SQL)"]
        P2["audit_log\n(central, immutable)"]
        P3["mcp_access_log\n(automatisk)"]
    end

    style TRAD fill:#4a1515,color:#ffffff,stroke:#ef4444
    style PG fill:#1a3a2a,color:#ffffff,stroke:#22c55e
```

| Aspekt | Traditionel | Postgres-løsning |
|--------|------------|------------------|
| **Metrics-kilde** | Custom per agent | `agent_metrics` tabel (standard SQL) |
| **Tracing** | Distributed tracing (Jaeger/Zipkin) | `audit_log` event-kæder (SQL) |
| **Log-format** | Varierer per agent | JSON, standardiseret |
| **Token-monitoring** | Manuel LLM API-kald | Automatisk i `agent_metrics` |
| **SLA-tracking** | Custom implementering | SQL join med `user_chain.sla_hours` |
| **Anomali-detektion** | ML-baseret (tokens) | SQL z-score analyse (0 tokens) |
| **Audit trail** | Rekonstruer fra logs | `SELECT * FROM audit_log` |
| **Opsætningstid** | Dage/uger | Timer (SQL + Grafana) |

**Kernepointe:** Postgres-løsningen gør observability til en forlængelse af det eksisterende database-lag, ikke et separat system. Det sparer implementeringstid, reducerer kompleksitet og sikrer at metrics aldrig forsvinder — de er i den samme database der driver resten af systemet.
