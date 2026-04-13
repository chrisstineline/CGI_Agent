# Security Architecture — Fortress Layers

This document outlines the multi-layered security architecture designed as a "fortress" to protect the Postgres-based agent system against various threats and attacks.

---

## Fortress Concept Overview

The fortress architecture implements **defense in depth** with multiple independent security layers. Each layer provides protection against different types of threats, ensuring that if one layer is breached, subsequent layers continue to protect critical assets.

```mermaid
flowchart TD
    THREATS["External Threats<br>• DDoS Attacks<br>• Malware<br>• Unauthorized Access<br>• Data Breaches"]

    LAYER1["Layer 1: Perimeter<br>• WAF<br>• DDoS Protection<br>• API Gateway"]
    LAYER2["Layer 2: Network<br>• VPC Isolation<br>• Network Segmentation<br>• TLS Encryption"]
    LAYER3["Layer 3: Application<br>• Authentication<br>• Authorization<br>• Input Validation"]
    LAYER4["Layer 4: Data<br>• Encryption at Rest<br>• Access Controls<br>• Audit Logging"]
    LAYER5["Layer 5: Monitoring<br>• SIEM<br>• Threat Detection<br>• Incident Response"]

    ASSETS["Critical Assets<br>• Agent Code<br>• Task Data<br>• User Credentials<br>• Audit Logs"]

    THREATS --> LAYER1
    LAYER1 --> LAYER2
    LAYER2 --> LAYER3
    LAYER3 --> LAYER4
    LAYER4 --> LAYER5
    LAYER5 --> ASSETS

    classDef threat fill:#4a1515,color:#ffffff,stroke:#ef4444,stroke-width:3px
    classDef layer fill:#1e3a5f,color:#ffffff,stroke:#3b82f6,stroke-width:2px
    classDef asset fill:#1a3a2a,color:#ffffff,stroke:#22c55e,stroke-width:2px

    class THREATS threat
    class LAYER1,LAYER2,LAYER3,LAYER4,LAYER5 layer
    class ASSETS asset
```

### Key Principles

- **No Single Point of Failure**: Each layer operates independently
- **Fail-Safe Defaults**: Security controls default to "deny" when in doubt
- **Zero Trust**: Every request is verified regardless of origin
- **Continuous Monitoring**: All layers generate security events for analysis
- **Automated Response**: Security incidents trigger automated remediation

---

## Layer 1: Perimeter Security

The outermost layer protects against external threats before they reach internal systems.

### Architecture

```mermaid
flowchart LR
    INTERNET["Internet"]
    CDN["Content Delivery Network<br>• Global Distribution<br>• Basic Filtering"]
    WAF["Web Application Firewall<br>• SQL Injection Protection<br>• XSS Prevention<br>• Rate Limiting"]
    DDoS["DDoS Protection<br>• Traffic Scrubbing<br>• Bot Detection<br>• Auto-Mitigation"]
    API_GW["API Gateway<br>• Request Routing<br>• Authentication<br>• Throttling"]

    INTERNET --> CDN
    CDN --> WAF
    WAF --> DDoS
    DDoS --> API_GW

    subgraph "Perimeter Controls"
        CDN
        WAF
        DDoS
        API_GW
    end

    classDef perimeter fill:#6b7280,color:#ffffff,stroke:#374151,stroke-width:2px
    classDef internet fill:#4a1515,color:#ffffff,stroke:#ef4444,stroke-width:2px

    class INTERNET internet
    class CDN,WAF,DDoS,API_GW perimeter
```

### Components

| Component | Purpose | Technologies | Threat Protection |
|-----------|---------|--------------|-------------------|
| **CDN** | Global content distribution and basic filtering | Cloudflare, Akamai | Basic DDoS, geographic blocking |
| **WAF** | Application-layer attack prevention | ModSecurity, AWS WAF | SQL injection, XSS, CSRF |
| **DDoS Protection** | Volumetric attack mitigation | Cloudflare Spectrum, AWS Shield | SYN floods, UDP amplification |
| **API Gateway** | Request orchestration and basic auth | Kong, AWS API Gateway | Unauthorized access, request flooding |

### Configuration Example

```yaml
# WAF Rules Configuration
waf_rules:
  - name: "SQL Injection Protection"
    pattern: "(\\b(union|select|insert|update|delete|drop|create)\\b)"
    action: "block"
    severity: "high"

  - name: "Rate Limiting"
    requests_per_minute: 100
    burst_limit: 20
    action: "throttle"

# DDoS Protection Settings
ddos_protection:
  enabled: true
  scrubbing_centers: ["us-east-1", "eu-west-1", "ap-southeast-1"]
  mitigation_mode: "always_on"
  alert_threshold: 1000000  # requests per second
```

---

## Layer 2: Network Security

Network-level isolation and encryption protect data in transit and prevent lateral movement.

### Architecture

```mermaid
flowchart TD
    EXTERNAL["External Network"]
    FIREWALL["Next-Gen Firewall<br>• Stateful Inspection<br>• Application Awareness<br>• Threat Intelligence"]
    VPN["VPN Gateway<br>• Remote Access<br>• Site-to-Site<br>• Client Certificates"]
    VPC["Virtual Private Cloud<br>• Network Segmentation<br>• Security Groups<br>• NACLs"]
    SUBNETS["Subnets<br>• Public<br>• Private<br>• Isolated"]

    EXTERNAL --> FIREWALL
    FIREWALL --> VPN
    VPN --> VPC
    VPC --> SUBNETS

    subgraph "Network Zones"
        DMZ["DMZ<br>Web Servers<br>Load Balancers"]
        APP["Application<br>Agent Services<br>API Servers"]
        DATA["Data<br>Databases<br>Storage"]
    end

    SUBNETS --> DMZ
    SUBNETS --> APP
    SUBNETS --> DATA

    classDef network fill:#1e3a5f,color:#ffffff,stroke:#3b82f6,stroke-width:2px
    classDef zone fill:#1a3a2a,color:#ffffff,stroke:#22c55e,stroke-width:2px

    class EXTERNAL,FIREWALL,VPN,VPC,SUBNETS network
    class DMZ,APP,DATA zone
```

### Network Segmentation

```mermaid
erDiagram
    INTERNET ||--|| FIREWALL : "filters"
    FIREWALL ||--|| LOAD_BALANCER : "routes"
    LOAD_BALANCER ||--|| WEB_SERVERS : "forwards"
    WEB_SERVERS ||--|| APP_SERVERS : "api_calls"
    APP_SERVERS ||--|| DATABASES : "queries"

    WEB_SERVERS {
        string security_group "sg-web-001"
        string subnet "subnet-public"
        boolean public_ip "true"
    }

    APP_SERVERS {
        string security_group "sg-app-001"
        string subnet "subnet-private"
        boolean public_ip "false"
    }

    DATABASES {
        string security_group "sg-db-001"
        string subnet "subnet-isolated"
        boolean public_ip "false"
    }
```

### Encryption Implementation

```json
{
  "tls_configuration": {
    "version": "TLS 1.3",
    "cipher_suites": [
      "TLS_AES_256_GCM_SHA384",
      "TLS_CHACHA20_POLY1305_SHA256"
    ],
    "certificate_authority": "Let's Encrypt",
    "hsts": {
      "enabled": true,
      "max_age": 31536000,
      "include_subdomains": true
    },
    "certificate_pinning": {
      "enabled": true,
      "pins": ["sha256-hash1", "sha256-hash2"]
    }
  },
  "mutual_tls": {
    "client_certificates": {
      "required": true,
      "ca_certificate": "internal-ca.pem",
      "revocation_check": "OCSP"
    }
  }
}
```

---

## Layer 3: Application Security

Application-level controls protect against code-level vulnerabilities and unauthorized access.

### Authentication & Authorization

```mermaid
flowchart TD
    USER["User Request"]
    AUTH["Authentication<br>• JWT Validation<br>• MFA Check<br>• Session Management"]
    AUTHZ["Authorization<br>• Role-Based Access<br>• Attribute-Based<br>• Policy Engine"]
    AUDIT["Audit Logging<br>• Access Attempts<br>• Permission Changes<br>• Security Events"]

    USER --> AUTH
    AUTH -->|"valid"| AUTHZ
    AUTH -->|"invalid"| DENY["Access Denied"]
    AUTHZ -->|"allowed"| ALLOW["Access Granted"]
    AUTHZ -->|"denied"| DENY

    AUTH --> AUDIT
    AUTHZ --> AUDIT
    ALLOW --> AUDIT
    DENY --> AUDIT

    classDef flow fill:#1e3a5f,color:#ffffff,stroke:#3b82f6,stroke-width:2px
    classDef security fill:#1a3a2a,color:#ffffff,stroke:#22c55e,stroke-width:2px
    classDef deny fill:#4a1515,color:#ffffff,stroke:#ef4444,stroke-width:2px

    class USER,AUTH,AUTHZ,AUDIT,ALLOW flow
    class DENY deny
```

### Input Validation & Sanitization

```python
class InputValidator:
    def __init__(self):
        self.sanitizers = {
            'sql': self._sanitize_sql,
            'html': self._sanitize_html,
            'json': self._sanitize_json,
            'file_path': self._sanitize_path
        }

    def validate_request(self, request_data):
        """Comprehensive input validation"""
        validated = {}

        for field, value in request_data.items():
            field_type = self._get_field_type(field)

            # Type checking
            if not self._validate_type(value, field_type):
                raise ValidationError(f"Invalid type for {field}")

            # Length limits
            if len(str(value)) > self._get_max_length(field):
                raise ValidationError(f"Value too long for {field}")

            # Sanitization
            if field_type in self.sanitizers:
                value = self.sanitizers[field_type](value)

            # Business rule validation
            self._validate_business_rules(field, value)

            validated[field] = value

        return validated

    def _sanitize_sql(self, value):
        """Prevent SQL injection"""
        # Remove dangerous characters and patterns
        dangerous_patterns = [
            r';\s*--',  # SQL comments
            r';\s*/\*',  # Block comments
            r'union\s+select',  # Union attacks
            r'exec\s*\(',  # Dynamic SQL
        ]
        for pattern in dangerous_patterns:
            value = re.sub(pattern, '', value, flags=re.IGNORECASE)
        return value

    def _sanitize_html(self, value):
        """Prevent XSS attacks"""
        return bleach.clean(value, tags=[], strip=True)

    def _sanitize_path(self, value):
        """Prevent path traversal"""
        # Remove .. and absolute paths
        value = re.sub(r'\.\.', '', value)
        if value.startswith('/'):
            raise ValidationError("Absolute paths not allowed")
        return value
```

### Session Management

```json
{
  "session_security": {
    "session_timeout": 3600,
    "absolute_timeout": 28800,
    "idle_timeout": 1800,
    "regenerate_on_login": true,
    "secure_cookie": {
      "http_only": true,
      "secure": true,
      "same_site": "strict"
    },
    "csrf_protection": {
      "enabled": true,
      "token_length": 32,
      "regenerate_per_request": false
    }
  }
}
```

---

## Layer 4: Data Security

Protects data at rest, in use, and during transmission.

### Data Protection Architecture

```mermaid
flowchart TD
    DATA["Data Sources"]
    ENCRYPT["Encryption<br>• AES-256<br>• Key Management<br>• Envelope Encryption"]
    ACCESS["Access Control<br>• Row-Level Security<br>• Column Masking<br>• Dynamic Views"]
    AUDIT["Audit Logging<br>• Data Access<br>• Changes<br>• Compliance"]
    BACKUP["Secure Backup<br>• Encrypted<br>• Access Controls<br>• Retention Policies"]

    DATA --> ENCRYPT
    ENCRYPT --> ACCESS
    ACCESS --> AUDIT
    AUDIT --> BACKUP

    subgraph "Data States"
        REST["At Rest<br>Database Files<br>Backups"]
        TRANSIT["In Transit<br>Network Traffic<br>API Calls"]
        USE["In Use<br>Application Memory<br>Processing"]
    end

    ENCRYPT --> REST
    ENCRYPT --> TRANSIT
    ENCRYPT --> USE

    classDef data fill:#1e3a5f,color:#ffffff,stroke:#3b82f6,stroke-width:2px
    classDef security fill:#1a3a2a,color:#ffffff,stroke:#22c55e,stroke-width:2px

    class DATA,ENCRYPT,ACCESS,AUDIT,BACKUP,REST,TRANSIT,USE data
```

### Encryption Implementation

```python
class DataEncryption:
    def __init__(self, kms_client):
        self.kms = kms_client
        self.algorithm = 'AES-256-GCM'

    async def encrypt_data(self, plaintext, context=None):
        """Envelope encryption with KMS"""
        # Generate data key
        data_key = await self.kms.generate_data_key(
            key_id=self.master_key_id,
            key_spec='AES_256'
        )

        # Encrypt data with data key
        encrypted_data = await self._encrypt_with_data_key(
            plaintext, data_key['Plaintext']
        )

        # Encrypt data key with master key
        encrypted_key = await self.kms.encrypt(
            key_id=self.master_key_id,
            plaintext=data_key['CiphertextBlob']
        )

        return {
            'encrypted_data': encrypted_data,
            'encrypted_key': encrypted_key['CiphertextBlob'],
            'algorithm': self.algorithm,
            'context': context
        }

    async def decrypt_data(self, encrypted_package):
        """Decrypt envelope-encrypted data"""
        # Decrypt data key
        decrypted_key = await self.kms.decrypt(
            ciphertext_blob=encrypted_package['encrypted_key']
        )

        # Decrypt data
        plaintext = await self._decrypt_with_data_key(
            encrypted_package['encrypted_data'],
            decrypted_key['Plaintext']
        )

        return plaintext

    async def rotate_keys(self, old_key_id, new_key_id):
        """Key rotation for enhanced security"""
        # Find all data encrypted with old key
        affected_records = await self._find_records_by_key(old_key_id)

        # Re-encrypt with new key
        for record in affected_records:
            decrypted = await self.decrypt_data(record['encrypted_package'])
            new_encrypted = await self.encrypt_data(decrypted, record['context'])

            await self._update_record(record['id'], new_encrypted)

        # Mark old key for deletion
        await self.kms.schedule_key_deletion(old_key_id, 30)
```

### Row-Level Security (RLS)

```sql
-- Implement RLS in PostgreSQL
CREATE POLICY user_data_policy ON task_entries
    FOR ALL
    USING (user_id = current_user_id() OR role = 'admin');

CREATE POLICY agent_data_policy ON agent_output
    FOR SELECT
    USING (agent_name IN (
        SELECT agent_name FROM user_agent_permissions
        WHERE user_id = current_user_id()
    ));

-- Dynamic data masking
CREATE FUNCTION mask_sensitive_data(column_value text, user_role text)
RETURNS text AS $$
BEGIN
    IF user_role IN ('admin', 'auditor') THEN
        RETURN column_value;
    ELSIF user_role = 'user' THEN
        RETURN overlay(column_value placing '****' from 1 for length(column_value) - 4);
    ELSE
        RETURN '****';
    END IF;
END;
$$ LANGUAGE plpgsql;
```

---

## Layer 5: Monitoring & Response

Continuous monitoring and automated response complete the fortress.

### Security Information and Event Management (SIEM)

```mermaid
flowchart LR
    SOURCES["Security Sources<br>• System Logs<br>• Network Traffic<br>• Application Events<br>• User Activity"]
    COLLECTION["Log Collection<br>• Agents<br>• API Calls<br>• Database Triggers"]
    PROCESSING["Event Processing<br>• Normalization<br>• Correlation<br>• Enrichment"]
    ANALYSIS["Security Analysis<br>• Pattern Detection<br>• Anomaly Detection<br>• Threat Intelligence"]
    ALERTS["Alert Generation<br>• Severity Scoring<br>• Escalation Rules<br>• Automated Response"]
    RESPONSE["Incident Response<br>• Automated Actions<br>• Human Investigation<br>• Remediation"]

    SOURCES --> COLLECTION
    COLLECTION --> PROCESSING
    PROCESSING --> ANALYSIS
    ANALYSIS --> ALERTS
    ALERTS --> RESPONSE

    classDef process fill:#1e3a5f,color:#ffffff,stroke:#3b82f6,stroke-width:2px
    classDef analysis fill:#4a1515,color:#ffffff,stroke:#ef4444,stroke-width:2px
    classDef response fill:#1a3a2a,color:#ffffff,stroke:#22c55e,stroke-width:2px

    class SOURCES,COLLECTION,PROCESSING process
    class ANALYSIS,ALERTS analysis
    class RESPONSE response
```

### Threat Detection Rules

```json
{
  "threat_detection_rules": [
    {
      "name": "Brute Force Attack",
      "condition": "failed_login_attempts > 5 AND time_window = 300",
      "severity": "high",
      "actions": ["block_ip", "notify_security_team", "require_mfa"]
    },
    {
      "name": "Data Exfiltration",
      "condition": "large_data_download AND unusual_time AND external_ip",
      "severity": "critical",
      "actions": ["block_user", "isolate_system", "alert_executive"]
    },
    {
      "name": "Privilege Escalation",
      "condition": "role_change AND no_approval AND high_privilege_role",
      "severity": "high",
      "actions": ["revoke_access", "audit_investigation", "password_reset"]
    },
    {
      "name": "Anomalous API Usage",
      "condition": "api_calls_per_minute > baseline * 3 AND unusual_endpoints",
      "severity": "medium",
      "actions": ["throttle_requests", "require_additional_auth"]
    }
  ]
}
```

### Automated Response System

```python
class AutomatedResponse:
    def __init__(self, security_orchestrator):
        self.orchestrator = security_orchestrator
        self.response_actions = {
            'block_ip': self._block_ip,
            'revoke_access': self._revoke_access,
            'isolate_system': self._isolate_system,
            'throttle_requests': self._throttle_requests,
            'notify_team': self._notify_team
        }

    async def handle_alert(self, alert):
        """Execute automated response based on alert severity and type"""
        severity = alert.get('severity', 'low')
        actions = alert.get('actions', [])

        # High and critical alerts get immediate automated response
        if severity in ['high', 'critical']:
            for action in actions:
                if action in self.response_actions:
                    try:
                        await self.response_actions[action](alert)
                        logger.info(f"Executed automated response: {action}")
                    except Exception as e:
                        logger.error(f"Failed to execute {action}: {e}")

        # All alerts get logged and potentially escalated
        await self._log_incident(alert)
        await self._escalate_if_needed(alert)

    async def _block_ip(self, alert):
        """Block suspicious IP address"""
        ip = alert.get('source_ip')
        if ip:
            await self.orchestrator.block_ip(ip, duration=3600)  # 1 hour

    async def _revoke_access(self, alert):
        """Revoke user access temporarily"""
        user_id = alert.get('user_id')
        if user_id:
            await self.orchestrator.revoke_user_sessions(user_id)
            await self.orchestrator.require_password_reset(user_id)

    async def _isolate_system(self, alert):
        """Isolate compromised system"""
        system_id = alert.get('system_id')
        if system_id:
            await self.orchestrator.quarantine_system(system_id)
            await self.orchestrator.disable_outbound_traffic(system_id)

    async def _throttle_requests(self, alert):
        """Throttle API requests from suspicious source"""
        client_id = alert.get('client_id')
        if client_id:
            await self.orchestrator.set_rate_limit(client_id, requests_per_minute=10)

    async def _notify_team(self, alert):
        """Notify security team"""
        await self.orchestrator.send_alert_notification(
            team='security',
            alert=alert,
            priority=alert.get('severity', 'medium')
        )
```

---

## Security Metrics & Compliance

### Key Security Metrics

```mermaid
gauge title Security Health Score
%% Overall security posture
95

pie title Threat Distribution
    "Blocked Attacks" : 85
    "Investigated Incidents" : 12
    "Successful Breaches" : 3

pie title Response Times
    "< 5 minutes" : 60
    "5-30 minutes" : 30
    "> 30 minutes" : 10
```

### Compliance Frameworks

| Framework | Coverage | Implementation |
|-----------|----------|----------------|
| **GDPR** | Data protection, consent, breach notification | Data encryption, audit logging, consent management |
| **ISO 27001** | Information security management | Risk assessments, security controls, continuous improvement |
| **SOC 2** | Security, availability, confidentiality | Access controls, monitoring, incident response |
| **NIST CSF** | Cybersecurity framework | Identify, protect, detect, respond, recover |

### Regular Security Assessments

- **Vulnerability Scanning**: Weekly automated scans
- **Penetration Testing**: Quarterly external assessments
- **Code Reviews**: All changes require security review
- **Compliance Audits**: Annual third-party audits
- **Security Training**: Mandatory annual training for all personnel

---

## Incident Response Plan

### Phases

```mermaid
stateDiagram-v2
    [*] --> Detection
    Detection --> Assessment : Alert Triggered
    Assessment --> Containment : Breach Confirmed
    Containment --> Eradication : Threat Isolated
    Eradication --> Recovery : Threat Removed
    Recovery --> LessonsLearned : System Restored
    LessonsLearned --> [*] : Process Improved

    Assessment --> FalsePositive : Benign
    FalsePositive --> [*]

    Containment --> Communication : Stakeholders Notified
    Communication --> Eradication
```

### Response Timeline

| Phase | Timeframe | Responsible | Actions |
|-------|-----------|-------------|---------|
| **Detection** | Immediate | Monitoring System | Alert generation, initial triage |
| **Assessment** | < 30 minutes | Security Team | Threat analysis, impact evaluation |
| **Containment** | < 1 hour | Security + IT | Isolate affected systems, stop bleeding |
| **Eradication** | < 4 hours | Security Team | Remove malware, close vulnerabilities |
| **Recovery** | < 24 hours | IT + Business | Restore systems, validate integrity |
| **Lessons Learned** | < 1 week | All Teams | Post-mortem, process improvements |

---

This fortress-layered security architecture provides comprehensive protection against modern cyber threats while maintaining system availability and performance. Each layer builds upon the previous one, creating multiple barriers that must be breached for an attack to succeed.
