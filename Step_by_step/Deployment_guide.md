# Deployment Guide — Postgres-based Agent System

Complete step-by-step guide for deploying the Postgres-based AI agent system to development, staging, and production environments.

---

## Table of Contents

1. [Prerequisites & Requirements](#prerequisites--requirements)
2. [Pre-Deployment Checklist](#pre-deployment-checklist)
3. [Database Setup](#database-setup)
4. [Application Deployment](#application-deployment)
5. [Configuration & Secrets Management](#configuration--secrets-management)
6. [Security Hardening](#security-hardening)
7. [Monitoring & Observability Setup](#monitoring--observability-setup)
8. [Testing & Validation](#testing--validation)
9. [Rollback Procedures](#rollback-procedures)
10. [Troubleshooting](#troubleshooting)

---

## Prerequisites & Requirements

### System Requirements

| Component | Development | Staging | Production |
|-----------|-------------|---------|-----------|
| **OS** | Linux (Ubuntu 20.04+) | Linux (Ubuntu 20.04+) | Linux (Ubuntu 20.04+) |
| **CPU** | 4 cores | 8 cores | 16+ cores |
| **RAM** | 8 GB | 16 GB | 32+ GB |
| **Storage** | 50 GB | 200 GB | 1 TB+ |
| **Network** | 1 Gbps | 10 Gbps | 10 Gbps |

### Software Dependencies

```bash
# Required packages
- Docker 20.10+
- Docker Compose 1.29+
- PostgreSQL 14+
- Python 3.11+
- Node.js 18+ (for API gateway)
- Kafka 3.0+ (for event bus)
- Redis 7.0+ (for caching)

# Optional but recommended
- Kubernetes 1.24+ (for production orchestration)
- Terraform 1.0+ (for IaC)
- Prometheus 2.30+ (for metrics)
- Grafana 8.0+ (for dashboards)
```

### Installation Commands

```bash
# Update system packages
sudo apt-get update && sudo apt-get upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER

# Install Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/download/1.29.2/docker-compose-$(uname -s)-$(uname -m)" \
  -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Install Python 3.11
sudo apt-get install -y python3.11 python3.11-venv python3.11-dev

# Install PostgreSQL client
sudo apt-get install -y postgresql-client-14
```

### Required Accounts & Access

- [ ] GitHub repository access
- [ ] Docker registry credentials
- [ ] Cloud provider account (AWS/Azure/GCP)
- [ ] PostgreSQL database hosting or local instance
- [ ] Kafka cluster access or managed service
- [ ] API keys for third-party services (Claude API, etc.)
- [ ] SSH keys for server access

---

## Pre-Deployment Checklist

### Code Readiness

```bash
# Clone repository
git clone https://github.com/cgi/agent-system.git
cd agent-system

# Verify branch
git branch -v

# Check for uncommitted changes
git status

# Review recent commits
git log --oneline -10
```

Checklist:
- [ ] Code reviewed and approved
- [ ] All tests passing
- [ ] Security scanning complete
- [ ] Documentation updated
- [ ] Dependencies pinned in requirements.txt
- [ ] Environment-specific configs prepared

### Database Readiness

```bash
# Test database connection
psql -h DATABASE_HOST -U DATABASE_USER -d postgres -c "SELECT 1"

# Verify database exists or prepare for creation
psql -h DATABASE_HOST -U DATABASE_USER -d postgres -l | grep agent_db
```

Checklist:
- [ ] Database server accessible
- [ ] Database user credentials secured
- [ ] Backup strategy tested
- [ ] Replication configured (if applicable)
- [ ] Monitoring setup verified

### Infrastructure Readiness

Checklist:
- [ ] Network configured (VPC, security groups)
- [ ] Load balancer configured
- [ ] SSL certificates provisioned
- [ ] Logging infrastructure ready
- [ ] Monitoring dashboards prepared
- [ ] On-call rotation established

---

## Database Setup

### Step 1: Create Databases

```bash
# Connect to PostgreSQL
PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -U $DB_USER -d postgres

# Create main database
CREATE DATABASE agent_db
  WITH ENCODING 'UTF8'
  LC_COLLATE 'C'
  LC_CTYPE 'C'
  TEMPLATE template0;

# Create separate databases for isolation
CREATE DATABASE routing_db;
CREATE DATABASE agent_output_db;
CREATE DATABASE user_db;
CREATE DATABASE audit_db;

# Create agent user
CREATE USER agent_app WITH PASSWORD 'secure_password_here';

# Grant permissions
GRANT CONNECT ON DATABASE agent_db TO agent_app;
GRANT CONNECT ON DATABASE routing_db TO agent_app;
GRANT CONNECT ON DATABASE agent_output_db TO agent_app;
GRANT CONNECT ON DATABASE user_db TO agent_app;
GRANT CONNECT ON DATABASE audit_db TO agent_app;

# Exit
\q
```

### Step 2: Apply Schema

```bash
# Download migration scripts
cd database/migrations

# List migrations
ls -la *.sql | sort

# Apply migrations in order
for file in 000*.sql 001*.sql 002*.sql; do
  echo "Applying $file..."
  PGPASSWORD=$DB_PASSWORD psql \
    -h $DB_HOST \
    -U agent_app \
    -d agent_db \
    -f "$file"
done

# Verify schema
PGPASSWORD=$DB_PASSWORD psql \
  -h $DB_HOST \
  -U agent_app \
  -d agent_db \
  -c "\dt"
```

### Step 3: Initialize Data

```bash
# Load initial data
PGPASSWORD=$DB_PASSWORD psql \
  -h $DB_HOST \
  -U agent_app \
  -d agent_db \
  -f database/seed_data.sql

# Verify data
PGPASSWORD=$DB_PASSWORD psql \
  -h $DB_HOST \
  -U agent_app \
  -d agent_db \
  -c "SELECT COUNT(*) FROM agent_registry;"
```

### Step 4: Enable Extensions

```bash
# Connect as admin user
PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -U $DB_USER -d agent_db

-- Enable pgvector for semantic search
CREATE EXTENSION IF NOT EXISTS vector;

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Enable JSON functions
CREATE EXTENSION IF NOT EXISTS "json";

-- Enable full-text search
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- Verify extensions
\dx
\q
```

### Step 5: Test Database Connection

```bash
# Test connection from application server
python -c "
import psycopg2
try:
  conn = psycopg2.connect(
    host='$DB_HOST',
    user='agent_app',
    password='$DB_PASSWORD',
    database='agent_db'
  )
  cursor = conn.cursor()
  cursor.execute('SELECT version()')
  print(cursor.fetchone())
  conn.close()
  print('✓ Database connection successful')
except Exception as e:
  print(f'✗ Connection failed: {e}')
"
```

---

## Application Deployment

### Step 1: Prepare Environment

```bash
# Create application directory
sudo mkdir -p /opt/cgi-agent-system
sudo chown $USER:$USER /opt/cgi-agent-system
cd /opt/cgi-agent-system

# Clone repository
git clone https://github.com/cgi/agent-system.git .

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt  # for development

# Verify installation
python --version
pip list | head -20
```

### Step 2: Build Docker Images

```bash
# Build agent images
docker build -f docker/Dockerfile.agent \
  -t cgi-agent:latest \
  -t cgi-agent:$VERSION .

# Build API gateway image
docker build -f docker/Dockerfile.api \
  -t cgi-api-gateway:latest \
  -t cgi-api-gateway:$VERSION .

# Build sync scripts image
docker build -f docker/Dockerfile.sync \
  -t cgi-sync-scripts:latest \
  -t cgi-sync-scripts:$VERSION .

# Verify images
docker images | grep cgi-
```

### Step 3: Push to Registry

```bash
# Login to Docker registry
echo $DOCKER_REGISTRY_PASSWORD | docker login -u $DOCKER_REGISTRY_USER --password-stdin $DOCKER_REGISTRY

# Tag images
docker tag cgi-agent:latest $DOCKER_REGISTRY/cgi-agent:$VERSION
docker tag cgi-api-gateway:latest $DOCKER_REGISTRY/cgi-api-gateway:$VERSION
docker tag cgi-sync-scripts:latest $DOCKER_REGISTRY/cgi-sync-scripts:$VERSION

# Push images
docker push $DOCKER_REGISTRY/cgi-agent:$VERSION
docker push $DOCKER_REGISTRY/cgi-api-gateway:$VERSION
docker push $DOCKER_REGISTRY/cgi-sync-scripts:$VERSION

# Verify push
docker images --digests | grep cgi-
```

### Step 4: Deploy with Docker Compose

```yaml
# docker-compose.yml
version: '3.8'

services:
  # PostgreSQL Database
  postgres:
    image: postgres:14-alpine
    container_name: cgi-postgres
    environment:
      POSTGRES_USER: ${DB_USER}
      POSTGRES_PASSWORD: ${DB_PASSWORD}
      POSTGRES_DB: agent_db
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./database/migrations:/docker-entrypoint-initdb.d
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DB_USER}"]
      interval: 10s
      timeout: 5s
      retries: 5

  # Redis Cache
  redis:
    image: redis:7-alpine
    container_name: cgi-redis
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  # Kafka Event Bus
  kafka:
    image: confluentinc/cp-kafka:7.0.0
    container_name: cgi-kafka
    depends_on:
      - zookeeper
    environment:
      KAFKA_BROKER_ID: 1
      KAFKA_ZOOKEEPER_CONNECT: zookeeper:2181
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://kafka:29092,PLAINTEXT_HOST://localhost:9092
      KAFKA_LISTENER_SECURITY_PROTOCOL_MAP: PLAINTEXT:PLAINTEXT,PLAINTEXT_HOST:PLAINTEXT
      KAFKA_INTER_BROKER_LISTENER_NAME: PLAINTEXT
    ports:
      - "9092:9092"

  zookeeper:
    image: confluentinc/cp-zookeeper:7.0.0
    container_name: cgi-zookeeper
    environment:
      ZOOKEEPER_CLIENT_PORT: 2181

  # API Gateway
  api-gateway:
    image: ${DOCKER_REGISTRY}/cgi-api-gateway:${VERSION}
    container_name: cgi-api-gateway
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      DB_HOST: postgres
      DB_USER: ${DB_USER}
      DB_PASSWORD: ${DB_PASSWORD}
      REDIS_URL: redis://redis:6379
      KAFKA_BROKERS: kafka:29092
    ports:
      - "8000:8000"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 10s
      timeout: 5s
      retries: 5

  # Agent Service
  agent-service:
    image: ${DOCKER_REGISTRY}/cgi-agent:${VERSION}
    container_name: cgi-agent
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      DB_HOST: postgres
      DB_USER: ${DB_USER}
      DB_PASSWORD: ${DB_PASSWORD}
      REDIS_URL: redis://redis:6379
      KAFKA_BROKERS: kafka:29092
      CLAUDE_API_KEY: ${CLAUDE_API_KEY}
    deploy:
      replicas: 3
      resources:
        limits:
          cpus: '0.5'
          memory: 512M

volumes:
  postgres_data:
```

Deploy:

```bash
# Set environment variables
export DB_USER=agent_app
export DB_PASSWORD=$(openssl rand -base64 32)
export VERSION=1.0.0
export DOCKER_REGISTRY=registry.example.com
export CLAUDE_API_KEY=sk-xxx

# Deploy
docker-compose up -d

# Verify deployment
docker-compose ps
docker-compose logs -f api-gateway

# Wait for health checks
sleep 30
curl http://localhost:8000/health
```

### Step 5: Verify Deployment

```bash
# Check container status
docker-compose ps

# Check logs
docker-compose logs agent-service | head -50

# Test API
curl -X GET http://localhost:8000/api/v1/health

# Test database
docker exec cgi-postgres \
  psql -U agent_app -d agent_db -c "SELECT count(*) FROM task_entries;"

# Test message queue
docker exec cgi-kafka \
  kafka-broker-api-versions.sh --bootstrap-server localhost:9092
```

---

## Configuration & Secrets Management

### Step 1: Create .env File

```bash
# Create environment file
cat > .env.production << 'EOF'
# Database
DB_HOST=prod-postgres.example.com
DB_PORT=5432
DB_USER=agent_app
DB_PASSWORD=${DB_PASSWORD}
DB_NAME=agent_db

# Redis
REDIS_URL=redis://:password@redis.example.com:6379

# Kafka
KAFKA_BROKERS=kafka1.example.com:9092,kafka2.example.com:9092

# API
API_HOST=0.0.0.0
API_PORT=8000
API_WORKERS=4

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json

# Security
JWT_SECRET=${JWT_SECRET}
ENCRYPTION_KEY=${ENCRYPTION_KEY}

# Third-party APIs
CLAUDE_API_KEY=${CLAUDE_API_KEY}
JIRA_API_KEY=${JIRA_API_KEY}

# Monitoring
SENTRY_DSN=${SENTRY_DSN}
PROMETHEUS_ENABLED=true

# Feature flags
ENABLE_SELF_HEALING=true
ENABLE_AUTO_SCALING=false
EOF

# Restrict permissions
chmod 600 .env.production
```

### Step 2: Use AWS Secrets Manager (Production)

```bash
# Store secrets
aws secretsmanager create-secret \
  --name cgi-agent/production/db-password \
  --secret-string "$DB_PASSWORD"

aws secretsmanager create-secret \
  --name cgi-agent/production/jwt-secret \
  --secret-string "$JWT_SECRET"

# Retrieve secrets
aws secretsmanager get-secret-value \
  --secret-id cgi-agent/production/db-password \
  --query SecretString --output text
```

### Step 3: Configure with Environment Variables

```python
# config.py
import os
from dotenv import load_dotenv

load_dotenv('.env.production')

class Config:
    # Database
    DB_HOST = os.getenv('DB_HOST')
    DB_PORT = int(os.getenv('DB_PORT', 5432))
    DB_USER = os.getenv('DB_USER')
    DB_PASSWORD = os.getenv('DB_PASSWORD')
    DB_NAME = os.getenv('DB_NAME')
    
    # Redis
    REDIS_URL = os.getenv('REDIS_URL')
    
    # Kafka
    KAFKA_BROKERS = os.getenv('KAFKA_BROKERS').split(',')
    
    # Security
    JWT_SECRET = os.getenv('JWT_SECRET')
    ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY')
    
    # Logging
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
```

---

## Security Hardening

### Step 1: Enable HTTPS

```bash
# Generate SSL certificate
sudo certbot certonly --standalone -d agent-api.example.com

# Configure nginx as reverse proxy
sudo apt-get install -y nginx

# Create nginx config
sudo tee /etc/nginx/sites-available/cgi-agent << 'EOF'
upstream api_backend {
    server localhost:8000;
}

server {
    listen 80;
    server_name agent-api.example.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name agent-api.example.com;
    
    ssl_certificate /etc/letsencrypt/live/agent-api.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/agent-api.example.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    
    location / {
        proxy_pass http://api_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

# Enable site
sudo ln -s /etc/nginx/sites-available/cgi-agent /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

### Step 2: Configure Firewall

```bash
# Enable UFW
sudo ufw enable

# Allow SSH
sudo ufw allow 22/tcp

# Allow HTTP/HTTPS
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# Allow internal services
sudo ufw allow from 10.0.0.0/8 to any port 5432  # PostgreSQL
sudo ufw allow from 10.0.0.0/8 to any port 6379  # Redis
sudo ufw allow from 10.0.0.0/8 to any port 9092  # Kafka

# Verify rules
sudo ufw status verbose
```

### Step 3: Enable Database Encryption

```sql
-- Enable SSL for PostgreSQL connections
-- In postgresql.conf:
-- ssl = on
-- ssl_cert_file = '/path/to/cert.pem'
-- ssl_key_file = '/path/to/key.pem'

-- Restart PostgreSQL
sudo systemctl restart postgresql

-- Verify
psql -h DATABASE_HOST -U agent_app -d agent_db -c "SHOW ssl;"
```

### Step 4: Set File Permissions

```bash
# Application files
sudo chown -R nobody:nogroup /opt/cgi-agent-system
sudo chmod 755 /opt/cgi-agent-system

# Config files
sudo chmod 600 /opt/cgi-agent-system/.env.production

# Logs
sudo mkdir -p /var/log/cgi-agent
sudo chown nobody:nogroup /var/log/cgi-agent
sudo chmod 755 /var/log/cgi-agent
```

---

## Monitoring & Observability Setup

### Step 1: Install Prometheus

```yaml
# prometheus.yml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'cgi-agent'
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/metrics'

  - job_name: 'postgres'
    static_configs:
      - targets: ['localhost:9187']

  - job_name: 'redis'
    static_configs:
      - targets: ['localhost:9121']
```

Deploy:

```bash
docker run -d \
  -p 9090:9090 \
  -v $(pwd)/prometheus.yml:/etc/prometheus/prometheus.yml \
  --name prometheus \
  prom/prometheus
```

### Step 2: Install Grafana

```bash
docker run -d \
  -p 3000:3000 \
  -e GF_SECURITY_ADMIN_PASSWORD=admin \
  --name grafana \
  grafana/grafana
```

Access: http://localhost:3000

### Step 3: Set Up Alerting

```yaml
# alerting_rules.yml
groups:
  - name: cgi-agent
    rules:
      - alert: HighErrorRate
        expr: rate(http_requests_total{status=~"5.."}[5m]) > 0.05
        for: 5m
        annotations:
          summary: "High error rate detected"

      - alert: DatabaseConnectionFailed
        expr: pg_connections_failed > 0
        for: 2m
        annotations:
          summary: "Database connection failed"

      - alert: QueueBacklog
        expr: kafka_queue_depth > 1000
        for: 10m
        annotations:
          summary: "Message queue backlog too high"
```

### Step 4: Configure Logging

```python
# logging_config.py
import logging
import logging.handlers
import json

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_data = {
            'timestamp': self.formatTime(record),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module
        }
        return json.dumps(log_data)

# Setup logging
logger = logging.getLogger('cgi-agent')
handler = logging.handlers.RotatingFileHandler(
    '/var/log/cgi-agent/app.log',
    maxBytes=100000000,  # 100 MB
    backupCount=10
)
formatter = JSONFormatter()
handler.setFormatter(formatter)
logger.addHandler(handler)
```

---

## Testing & Validation

### Step 1: Pre-Deployment Tests

```bash
# Unit tests
pytest tests/unit/ -v --cov=agents

# Integration tests
pytest tests/integration/ -v

# Security tests
safety check
bandit -r agents/

# Code quality
flake8 agents/
black --check agents/
```

### Step 2: Smoke Tests

```bash
# Health check
curl -X GET https://agent-api.example.com/health

# Create test task
curl -X POST https://agent-api.example.com/api/v1/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "source": "test",
    "type": "test",
    "priority": "low",
    "data": {"test": true}
  }'

# Query task status
curl -X GET https://agent-api.example.com/api/v1/tasks/TASK_ID
```

### Step 3: Load Testing

```bash
# Using locust
locust -f tests/load/locustfile.py \
  --host https://agent-api.example.com \
  --users 100 \
  --spawn-rate 10 \
  --run-time 10m
```

### Step 4: Validation Checklist

- [ ] All services running (docker-compose ps)
- [ ] Database accessible and populated
- [ ] API responding to requests
- [ ] Metrics being collected
- [ ] Logs being generated
- [ ] Alerts configured
- [ ] HTTPS working
- [ ] Database backups functioning
- [ ] Event bus connected
- [ ] External APIs working

---

## Rollback Procedures

### Automatic Rollback (Blue-Green Deployment)

```bash
# Deploy new version to green environment
docker-compose -f docker-compose.green.yml up -d

# Run tests
pytest tests/smoke/

# If successful, switch traffic
# If failed, revert
docker-compose -f docker-compose.blue.yml up -d
```

### Manual Rollback

```bash
# Stop current deployment
docker-compose down

# Switch to previous version
export VERSION=0.9.0
docker-compose up -d

# Verify
docker-compose ps
curl https://agent-api.example.com/health

# Run validation tests
pytest tests/smoke/
```

### Database Rollback

```bash
# Stop application
docker-compose stop

# Restore from backup
pg_restore -h DB_HOST -U DB_USER -d agent_db \
  /backups/agent_db_backup_20260415.sql

# Start application
docker-compose up -d

# Verify data integrity
psql -h DB_HOST -U DB_USER -d agent_db -c \
  "SELECT COUNT(*) FROM task_entries;"
```

---

## Troubleshooting

### Common Issues & Solutions

#### Issue: Database Connection Failed

```bash
# Check database is running
docker-compose ps postgres

# Check credentials
echo "DB_USER=$DB_USER DB_PASSWORD=$DB_PASSWORD"

# Test connection manually
PGPASSWORD=$DB_PASSWORD psql -h localhost -U $DB_USER -d agent_db -c "SELECT 1"

# Check logs
docker-compose logs postgres | tail -50
```

#### Issue: High Memory Usage

```bash
# Check container resource usage
docker stats cgi-agent

# Set memory limits
docker-compose down
# Edit docker-compose.yml to add:
# deploy:
#   resources:
#     limits:
#       memory: 512M

docker-compose up -d

# Monitor
docker stats --no-stream
```

#### Issue: Slow Queries

```bash
# Enable query logging
psql -h DB_HOST -U DB_USER -d agent_db

-- Enable slow query log
ALTER SYSTEM SET log_min_duration_statement = 1000;  -- log queries > 1s

-- Reload config
SELECT pg_reload_conf();

-- View logs
SELECT * FROM pg_read_file('/var/log/postgresql/postgresql.log', 0, 10000);
```

#### Issue: Message Queue Backlog

```bash
# Check queue depth
docker exec cgi-kafka \
  kafka-topics.sh --bootstrap-server localhost:9092 \
  --describe --topic task.created

# Scale up consumers
docker-compose down
# Edit docker-compose.yml to increase replicas
docker-compose up -d

# Monitor queue
watch -n 5 'docker exec cgi-kafka kafka-topics.sh \
  --bootstrap-server localhost:9092 --describe'
```

### Debug Commands

```bash
# View all logs
docker-compose logs -f

# Execute command in container
docker exec cgi-agent bash -c "python debug_script.py"

# Database shell
docker exec cgi-postgres psql -U agent_app -d agent_db

# Check network connectivity
docker exec cgi-agent curl -v http://postgres:5432

# View metrics
curl http://localhost:8000/metrics

# Check configuration
docker inspect cgi-agent | grep -A 20 "Env"
```

---

## Post-Deployment Steps

### Step 1: Verify Monitoring

- [ ] Prometheus collecting metrics
- [ ] Grafana dashboards displaying data
- [ ] Alerts triggering correctly

### Step 2: Document Deployment

- [ ] Document actual versions deployed
- [ ] Record configuration details
- [ ] Update runbook with any changes
- [ ] Notify team of deployment

### Step 3: Schedule Backups

```bash
# Daily backup
0 2 * * * /opt/cgi-agent-system/backup.sh
```

### Step 4: Create Runbooks

Document:
- How to restart services
- How to scale up/down
- How to add new agents
- How to rotate secrets
- Emergency contacts

---

## Deployment Checklist Summary

- [ ] Prerequisites installed
- [ ] Database configured
- [ ] Application deployed
- [ ] Secrets configured
- [ ] Security hardened
- [ ] Monitoring enabled
- [ ] Tests passing
- [ ] Health checks verified
- [ ] Logging functional
- [ ] Alerts configured
- [ ] Documentation updated
- [ ] Team notified
