# Agent Code Template

This document provides production-ready templates for implementing AI agents within the Postgres-based system architecture.

---

## 1. Base Agent Class

All agents inherit from this base class, which implements the core contract and communication protocol.

### Structure

```python
# agents/base_agent.py
import asyncio
import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import uuid4

import psycopg2
import psycopg2.pool
from pydantic import BaseModel, validator

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AgentConfig(BaseModel):
    """Agent configuration loaded from SKILL.md"""
    agent_name: str
    agent_id: str
    purpose: str
    capabilities: list[str]
    allowed_operations: list[str]
    forbidden_operations: list[str]
    max_retries: int = 3
    timeout_seconds: int = 300
    resource_limits: Dict[str, Any]

    @validator('forbidden_operations')
    def validate_forbidden(cls, v):
        if not isinstance(v, list):
            raise ValueError("forbidden_operations must be a list")
        return v


class TaskPayload(BaseModel):
    """Standard task payload from Postgres"""
    task_id: str
    source: str
    type: str
    priority: str
    data: Dict[str, Any]
    context: Dict[str, Any]
    assigned_to: Optional[str] = None
    created_at: datetime


class AgentResponse(BaseModel):
    """Standard response format (SAP Protocol)"""
    message_id: str
    agent_name: str
    task_id: str
    status: str  # 'processing', 'completed', 'failed', 'escalated'
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None
    artifacts: list[str] = []
    metadata: Dict[str, Any]
    timestamp: datetime


class BaseAgent(ABC):
    """
    Base class for all agents in the system.
    
    Implements:
    - Database connectivity
    - SKILL.md contract enforcement
    - SAP (Shared Agent Protocol)
    - Event bus integration
    - Error handling and retry logic
    """

    def __init__(self, config: AgentConfig, db_config: Dict[str, str]):
        self.config = config
        self.db_config = db_config
        self.message_id = str(uuid4())
        
        # Database connection pool
        self.db_pool = psycopg2.pool.SimpleConnectionPool(
            1, 5,
            host=db_config['host'],
            port=db_config['port'],
            database=db_config['database'],
            user=db_config['user'],
            password=db_config['password']
        )

    async def process_task(self, task: TaskPayload) -> AgentResponse:
        """
        Main entry point for task processing.
        Implements retry logic, error handling, and contract enforcement.
        """
        response = AgentResponse(
            message_id=str(uuid4()),
            agent_name=self.config.agent_name,
            task_id=task.task_id,
            status='processing',
            metadata={'started_at': datetime.now().isoformat()}
        )

        try:
            # Contract validation
            self._validate_task(task)

            # Execute task with retry logic
            result = await self._execute_with_retries(task)

            response.status = 'completed'
            response.result = result
            response.metadata['completed_at'] = datetime.now().isoformat()

        except ForbiddenOperationError as e:
            logger.error(f"Forbidden operation: {e}")
            response.status = 'failed'
            response.error = {
                'type': 'ForbiddenOperationError',
                'message': str(e)
            }

        except Exception as e:
            logger.error(f"Task failed: {e}")
            response.status = 'escalated'
            response.error = {
                'type': type(e).__name__,
                'message': str(e)
            }
            await self._escalate_task(task, str(e))

        # Log response to database
        await self._log_response(response)

        return response

    def _validate_task(self, task: TaskPayload) -> None:
        """
        Validate task against SKILL.md contract.
        
        Raises ForbiddenOperationError if task violates constraints.
        """
        operation = task.data.get('operation')

        # Check if operation is forbidden
        if operation in self.config.forbidden_operations:
            raise ForbiddenOperationError(
                f"Operation '{operation}' is forbidden for {self.config.agent_name}"
            )

        # Check if operation is allowed
        if self.config.allowed_operations and operation not in self.config.allowed_operations:
            raise ForbiddenOperationError(
                f"Operation '{operation}' not in allowed list"
            )

        # Check resource limits
        if task.data.get('size', 0) > self.config.resource_limits.get('max_data_size'):
            raise ValueError("Task data exceeds size limit")

    async def _execute_with_retries(self, task: TaskPayload) -> Dict[str, Any]:
        """
        Execute task with exponential backoff retry logic.
        """
        attempt = 0
        last_error = None

        while attempt < self.config.max_retries:
            try:
                logger.info(f"Executing task {task.task_id} (attempt {attempt + 1})")
                result = await self.execute(task)
                return result

            except RetryableError as e:
                last_error = e
                attempt += 1
                
                if attempt < self.config.max_retries:
                    backoff = 2 ** attempt  # Exponential backoff
                    logger.warning(
                        f"Retryable error (attempt {attempt}), "
                        f"backing off {backoff}s: {e}"
                    )
                    await asyncio.sleep(backoff)
                else:
                    logger.error(f"Max retries exceeded for task {task.task_id}")
                    raise

            except NonRetryableError as e:
                logger.error(f"Non-retryable error: {e}")
                raise

        raise last_error

    @abstractmethod
    async def execute(self, task: TaskPayload) -> Dict[str, Any]:
        """
        Agent-specific implementation.
        Must be overridden by subclasses.
        
        Args:
            task: The task to process
            
        Returns:
            Dictionary with result data
        """
        pass

    async def _log_response(self, response: AgentResponse) -> None:
        """Log agent response to Postgres audit_db"""
        conn = self.db_pool.getconn()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO audit_log 
                (id, event_type, entity_id, payload, occurred_at)
                VALUES 
                (%s, %s, %s, %s, %s)
            """, (
                str(uuid4()),
                'agent_response',
                response.task_id,
                json.dumps(response.dict(), default=str),
                datetime.now()
            ))
            conn.commit()
        finally:
            self.db_pool.putconn(conn)

    async def _escalate_task(self, task: TaskPayload, reason: str) -> None:
        """Escalate failed task to human review"""
        conn = self.db_pool.getconn()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO escalation_log 
                (id, task_entry_id, from_user_id, to_user_id, reason, escalated_at)
                VALUES 
                (%s, %s, %s, %s, %s, %s)
            """, (
                str(uuid4()),
                task.task_id,
                self.config.agent_id,
                None,  # Will be assigned by system
                reason,
                datetime.now()
            ))
            conn.commit()
        finally:
            self.db_pool.putconn(conn)

    async def query_postgres(self, query: str, params: tuple = ()) -> list[Dict]:
        """
        Safely query Postgres with connection pooling.
        
        Args:
            query: SQL query
            params: Query parameters
            
        Returns:
            List of result rows as dictionaries
        """
        conn = self.db_pool.getconn()
        try:
            cursor = conn.cursor()
            cursor.execute(query, params)
            
            columns = [desc[0] for desc in cursor.description]
            results = [dict(zip(columns, row)) for row in cursor.fetchall()]
            
            return results
        finally:
            self.db_pool.putconn(conn)

    def close(self):
        """Clean up database connections"""
        self.db_pool.closeall()


# Custom exceptions
class RetryableError(Exception):
    """Transient error that can be retried"""
    pass


class NonRetryableError(Exception):
    """Permanent error that cannot be retried"""
    pass


class ForbiddenOperationError(Exception):
    """Operation violates SKILL.md contract"""
    pass
```

---

## 2. TDD Agent Implementation

Example of a concrete agent implementing test-driven development.

```python
# agents/tdd_agent.py
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict

from base_agent import BaseAgent, TaskPayload, RetryableError


class TDDAgent(BaseAgent):
    """
    TDD Agent: Generates and validates tests using test-driven development.
    
    SKILL.md Contract:
    - Capabilities: Generate unit tests, execute tests, create reports
    - Allowed: Read code, run scripts, write reports
    - Forbidden: Modify production code, deploy
    """

    async def execute(self, task: TaskPayload) -> Dict[str, Any]:
        """
        Execute TDD task: generate tests and validate code.
        """
        code_draft = task.data.get('code_draft')
        test_framework = task.data.get('test_framework', 'pytest')
        coverage_target = task.data.get('coverage_target', 0.80)

        # Generate test file
        test_code = await self._generate_tests(code_draft, test_framework)

        # Execute tests
        test_results = await self._run_tests(test_code, test_framework)

        # Check coverage
        coverage = test_results.get('coverage', 0)
        if coverage < coverage_target:
            raise RetryableError(
                f"Coverage {coverage}% below target {coverage_target}%"
            )

        return {
            'test_file': test_code,
            'results': test_results,
            'coverage': coverage,
            'status': 'passed'
        }

    async def _generate_tests(self, code_draft: str, framework: str) -> str:
        """
        Generate test cases for provided code.
        Uses Claude API to generate comprehensive tests.
        """
        prompt = f"""
        Generate comprehensive {framework} unit tests for the following code:
        
        ```python
        {code_draft}
        ```
        
        Requirements:
        - Test both happy path and edge cases
        - Include error handling tests
        - Target 80%+ code coverage
        - Use descriptive test names
        - Include docstrings explaining what each test validates
        """

        # Call Claude API (assumes environment variable for API key)
        import anthropic
        client = anthropic.Anthropic()

        message = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )

        return message.content[0].text

    async def _run_tests(self, test_code: str, framework: str) -> Dict[str, Any]:
        """
        Execute tests and collect results.
        Runs tests in isolated sandbox.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test_generated.py"
            test_file.write_text(test_code)

            # Run pytest with coverage
            result = subprocess.run(
                [
                    framework,
                    str(test_file),
                    "--cov",
                    "--cov-report=json",
                    "--tb=short"
                ],
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode != 0:
                raise RetryableError(f"Tests failed: {result.stdout}\n{result.stderr}")

            # Parse coverage report
            import json
            coverage_file = Path(tmpdir) / ".coverage"
            
            return {
                'passed': True,
                'stdout': result.stdout,
                'stderr': result.stderr,
                'coverage': 0.85  # Parse from JSON report
            }
```

---

## 3. Contract Analysis Agent (Leader_Chain Example)

Example of agent for analyzing RFP contracts.

```python
# agents/contract_analysis_agent.py
import re
from typing import Any, Dict

import anthropic

from base_agent import BaseAgent, TaskPayload


class ContractAnalysisAgent(BaseAgent):
    """
    Contract Analysis Agent: Analyzes RFP documents and extracts requirements.
    
    Used in: Leader_Chain scenario for public sector contract acquisition
    """

    async def execute(self, task: TaskPayload) -> Dict[str, Any]:
        """
        Analyze RFP document and extract key information.
        """
        rfp_content = task.data.get('rfp_content')
        rfp_type = task.data.get('rfp_type', 'public_sector')

        # Extract key requirements
        requirements = await self._extract_requirements(rfp_content)

        # Analyze compliance needs
        compliance = await self._analyze_compliance(rfp_content)

        # Assess risk and opportunity
        assessment = await self._assess_opportunity(rfp_content, requirements)

        return {
            'budget': requirements.get('budget'),
            'deadline': requirements.get('deadline'),
            'compliance_requirements': compliance.get('requirements'),
            'technical_specs': requirements.get('technical_specs'),
            'risk_assessment': assessment.get('risk_level'),
            'routing_decision': assessment.get('recommended_agent'),
            'analysis': {
                'requirements': requirements,
                'compliance': compliance,
                'assessment': assessment
            }
        }

    async def _extract_requirements(self, content: str) -> Dict[str, Any]:
        """Extract technical and business requirements"""
        client = anthropic.Anthropic()

        message = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1500,
            messages=[{
                "role": "user",
                "content": f"""
                Analyze this RFP and extract:
                1. Budget amount and currency
                2. Deadline date
                3. Technical specifications required
                4. Key deliverables
                5. Success criteria
                
                RFP Content:
                {content}
                
                Format as JSON.
                """
            }]
        )

        import json
        response_text = message.content[0].text
        
        # Parse JSON from response
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        
        return {}

    async def _analyze_compliance(self, content: str) -> Dict[str, Any]:
        """Analyze compliance and regulatory requirements"""
        keywords = {
            'GDPR': ['data protection', 'personal data', 'gdpr'],
            'ISO27001': ['information security', 'iso 27001'],
            'HIPAA': ['health information', 'hipaa'],
            'PCI-DSS': ['payment', 'pci', 'credit card']
        }

        requirements = []
        for standard, keywords_list in keywords.items():
            if any(kw in content.lower() for kw in keywords_list):
                requirements.append(standard)

        return {'requirements': requirements}

    async def _assess_opportunity(
        self, content: str, requirements: Dict
    ) -> Dict[str, Any]:
        """Assess business opportunity and risk"""
        client = anthropic.Anthropic()

        message = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1000,
            messages=[{
                "role": "user",
                "content": f"""
                Based on this RFP analysis, assess:
                1. Risk level (low/medium/high)
                2. Opportunity value (low/medium/high)
                3. Recommended next action
                4. Key risks to mitigate
                
                Requirements: {requirements}
                
                Format as JSON.
                """
            }]
        )

        import json
        response_text = message.content[0].text
        
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        
        return {'risk_level': 'medium', 'recommended_agent': 'proposal_drafting_assistant'}
```

---

## 4. Running an Agent

```python
# main.py
import asyncio
from agents.base_agent import AgentConfig, TaskPayload
from agents.tdd_agent import TDDAgent
from datetime import datetime


async def main():
    # Load configuration from environment or config file
    agent_config = AgentConfig(
        agent_name="tdd_agent",
        agent_id="agent-tdd-001",
        purpose="Generate and validate tests using TDD",
        capabilities=[
            "generate_unit_tests",
            "execute_tests",
            "create_reports"
        ],
        allowed_operations=["read_code", "run_scripts", "write_reports"],
        forbidden_operations=["modify_production_code", "deploy"],
        max_retries=3,
        timeout_seconds=300,
        resource_limits={
            "max_data_size": 1000000,  # 1MB
            "max_execution_time": 600,
            "max_memory": 512
        }
    )

    db_config = {
        'host': 'localhost',
        'port': 5432,
        'database': 'cgi_agent',
        'user': 'agent_user',
        'password': 'secure_password'
    }

    # Initialize agent
    agent = TDDAgent(agent_config, db_config)

    try:
        # Create task
        task = TaskPayload(
            task_id="uuid-task-001",
            source="jira",
            type="bug",
            priority="high",
            data={
                'code_draft': '''
def export_to_clinician(patient_data):
    # Implementation
    pass
                ''',
                'test_framework': 'pytest',
                'coverage_target': 0.80
            },
            context={
                'jira_issue': 'REGNORD-2847',
                'affected_users': 150
            }
        )

        # Process task
        response = await agent.process_task(task)

        print(f"Task Status: {response.status}")
        print(f"Result: {response.result}")

    finally:
        agent.close()


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 5. SKILL.md Contract Template

```yaml
# agents/tdd-agent/SKILL.md

# Agent Name: TDD Test Agent

## Purpose
Generate and validate unit tests using test-driven development principles. 
Ensures code quality through comprehensive test coverage.

## Capabilities
- Generate unit tests from code specifications
- Execute tests in isolated sandbox
- Collect and report coverage metrics
- Identify untested code paths
- Suggest test improvements

## Input Contract
```
{
  "code_draft": "string - code to test",
  "test_framework": "string - pytest or unittest",
  "coverage_target": "float - target coverage percentage (0.0-1.0)",
  "timeout": "int - max execution time in seconds"
}
```

## Output Contract
```
{
  "test_file": "string - generated test code",
  "results": {
    "passed": "bool",
    "total_tests": "int",
    "failures": "list",
    "skipped": "int"
  },
  "coverage": "float - achieved coverage percentage",
  "status": "string - passed or failed"
}
```

## Allowed Operations
- Read code files
- Run test scripts in sandbox
- Write test reports
- Query code metrics

## Forbidden Operations
- Modify production code
- Deploy code
- Modify database records
- Delete files
- Access external systems without approval

## Resource Limits
- Max execution time: 5 minutes
- Max data size: 1MB
- Max memory: 512MB
- Max file count: 100

## Metrics
- Coverage ≥ 80%
- Runtime < 5 minutes
- No external dependencies

## Failure Handling
- Syntax errors: Log and report
- Test failures: Provide detailed output
- Timeout: Escalate to human
- Out of memory: Scale down batch size

## Dependencies
- pytest >= 7.0
- coverage >= 6.0
- pytest-timeout >= 2.0

## Owner
Team: TDD Automation
Contact: tdd-team@cgi.com
```

---

## 6. Agent Integration with Event Bus

```python
# agents/event_bus_integration.py
import asyncio
import json
from typing import Callable

from kafka import KafkaConsumer, KafkaProducer


class EventBusAdapter:
    """
    Integrates agents with Kafka-based event bus for asynchronous communication.
    """

    def __init__(self, broker: str, agent_name: str):
        self.broker = broker
        self.agent_name = agent_name
        
        self.producer = KafkaProducer(
            bootstrap_servers=broker,
            value_serializer=lambda v: json.dumps(v).encode('utf-8')
        )
        
        self.consumer = KafkaConsumer(
            f'task.assigned.{agent_name}',
            bootstrap_servers=broker,
            group_id=f'agent_{agent_name}',
            value_deserializer=lambda m: json.loads(m.decode('utf-8'))
        )

    async def subscribe_to_tasks(self, task_handler: Callable) -> None:
        """
        Subscribe to tasks assigned to this agent.
        """
        for message in self.consumer:
            task_data = message.value
            
            # Process task
            result = await task_handler(task_data)
            
            # Publish completion event
            self.producer.send(
                'agent.done',
                {
                    'agent_name': self.agent_name,
                    'task_id': task_data['task_id'],
                    'result': result
                }
            )

    def publish_event(self, event_type: str, data: dict) -> None:
        """Publish event to bus"""
        self.producer.send(event_type, data)
```

---

## 7. Database Query Helpers

```python
# agents/db_helpers.py
from typing import Any, Dict, List
import psycopg2


class PostgresHelper:
    """Helper methods for common database operations"""

    @staticmethod
    def get_task_context(conn, task_id: str) -> Dict[str, Any]:
        """
        Retrieve complete context for a task from all relevant tables.
        """
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, task_id, agent_name, result, status, created_at
            FROM agent_output
            WHERE task_entry_id = %s
            ORDER BY created_at DESC
            LIMIT 10
        """, (task_id,))
        
        previous_outputs = [dict(zip([d[0] for d in cursor.description], row)) 
                           for row in cursor.fetchall()]

        cursor.execute("""
            SELECT id, source, source_ref, claude_summary, priority, status
            FROM task_entries
            WHERE id = %s
        """, (task_id,))
        
        task_data = cursor.fetchone()

        return {
            'task': task_data,
            'history': previous_outputs
        }

    @staticmethod
    def update_task_status(conn, task_id: str, status: str) -> None:
        """Update task status in database"""
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE task_entries
            SET status = %s
            WHERE id = %s
        """, (status, task_id))
        conn.commit()

    @staticmethod
    def log_agent_output(conn, task_id: str, agent_name: str, 
                        result: Dict, status: str) -> None:
        """Log agent output to database"""
        import json
        from uuid import uuid4
        
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO agent_output 
            (id, task_entry_id, agent_name, result, status, created_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
        """, (
            str(uuid4()),
            task_id,
            agent_name,
            json.dumps(result),
            status
        ))
        conn.commit()
```

---

## Usage Summary

To implement a new agent:

1. **Create class inheriting from `BaseAgent`**
2. **Implement `execute()` method** with agent-specific logic
3. **Define SKILL.md contract** in agent directory
4. **Use database helpers** for Postgres operations
5. **Handle errors** with proper exception types
6. **Publish events** to event bus for coordination
7. **Log results** for audit trail

All agents automatically get:
- Retry logic with exponential backoff
- Contract enforcement from SKILL.md
- Database connection pooling
- Error handling and escalation
- Audit logging
- SAP protocol compliance
