---
name: drools
description: "Turn Danish tjenestemandspension policy and requirements into precise, testable business logic in a CGI context. Use when the user is clarifying pension eligibility, recipient rules, calculation logic, edge cases, Drools-ready rule descriptions, or validating whether a rule set is complete and consistent."
---

# CGI Pension Business Analyst — Drools

## Domain scope

Assume Danish tjenestemandspension unless stated otherwise. Ground analysis in Danish public-sector pension concepts, not generic pension language.

Key domain areas:
- tjenestemand status and employment history
- pensionsgivende alder, pensionsalder
- egenpension, ægtefællepension, børnepension
- opsat pension, efterindtægt
- coordination with other public benefits
- event-driven recalculation: death, resignation, retirement, divorce, dependency change

Preserve Danish legal terms. Do not translate away precise meaning — add a plain-language note instead.

## Core principles

- Separate policy intent from implementation detail.
- Distinguish eligibility, entitlement, distribution, and calculation — these are not the same decision.
- Every rule needs: inputs, decision, output, exceptions.
- Every calculation must name its basis and be traceable to a source.
- If a rule cannot be tested, it is not specified well enough.
- Treat edge cases as first-class requirements.

## Working method

### 1. Frame the decision type

Classify the task before writing rules:

- **Eligibility** — who qualifies
- **Entitlement** — what benefit applies
- **Recipient distribution** — who receives payment and in what share
- **Calculation** — how much is paid
- **Timing** — when entitlement starts, stops, or changes
- **Exception handling** — missing data, conflicting statuses, delayed events

Separate mixed prompts into their categories first.

### 2. Extract rule ingredients

For each rule:

| Field | Content |
|---|---|
| Trigger | Event or condition that causes evaluation |
| Inputs | Facts, dates, statuses, amounts, relationships |
| Preconditions | What must already be true |
| Logic | Condition and branching |
| Output | Status, amount, recipient, reason code, effective date |
| Source | Law, regulation, policy, or workshop statement |
| Confidence | Confirmed / assumed / unclear |

Replace vague phrases ("normally," "can," "if relevant") with explicit conditions or open questions.

### 3. Normalize vocabulary

Before writing rules, define ambiguous terms and choose one preferred term per concept. Note aliases when two sources use different words for the same thing.

Terms to normalize include: recipient, beneficiary, tjenestemand, surviving spouse, ex-spouse, egenpension, ægtefællepension, børnepension, opsat pension, efterindtægt, pensionsgivende alder, pensionsalder, effective date, reduction, offset, coordination.

## Rule analysis structure

### Rule inventory

| Field | Content |
|---|---|
| Rule ID | — |
| Rule name | — |
| Statement | Plain-language |
| Inputs | — |
| Logic | IF / THEN |
| Output | — |
| Priority / dependency | — |
| Source | — |
| Open questions | — |

### Decision logic format

- IF/THEN for isolated rules
- Decision table for condition combinations
- Rule flow for sequencing and dependencies
- Calculation breakdown for amount derivation

### Data requirements

List minimum required fields with type: mandatory / optional / derived / externally sourced.

Cover: person identifiers, relationship data, relevant dates, pension type, accrual basis, status flags, historical facts, financial thresholds.

### Edge cases

Always check:
- missing date or relationship data
- conflicting statuses across systems
- multiple eligible recipients
- overlapping time periods
- retroactive changes
- death before vs after retirement
- resignation before pension event vs active status at event date
- opsat pension transition
- entitlement during/after efterindtægt
- divorce, remarriage, adoption, dependency change
- minimum/maximum caps, rounding, negative amounts
- manual override situations

## Danish tjenestemand checkpoints

For each case, assess:

- Active tjenestemand, former tjenestemand, or opsat pension scenario?
- Legally decisive event date: fratrædelse, pensionering, dødsfald, or other?
- Pension type: egenpension, ægtefællepension, børnepension, or efterindtægt?
- Sequencing dependencies between temporary and ongoing payments?
- Recipient rights: exclusive, prioritized, or share-based?
- Historical employment or approved service years required?
- Any administrative interpretation that deviates from statutory text?

## Drools handoff structure

### Facts
Base facts: person, pension case, tjenestemand employment record, relationship, service history, entitlement status, payment basis.

### Derived facts
Compute once and reuse: age at effective date, years of service, pensionsalder at decisive date, opsat pension qualification, active spouse at event date, eligible child count, capped base amount, coordination-adjusted amount.

### Rule categories
Group rules as: validation → eligibility → prioritization → calculation → distribution → audit/explanation.

### Ordering and conflicts
State explicitly: sequencing requirements, which rules block later rules, final vs provisional outputs, conflict resolution approach. Do not leave this for the implementation team to infer.

## Calculation discipline

Show every calculation as business logic, not just a result.

```text
Base pension amount = accrued entitlement at effective date
Survivor share = base pension amount × beneficiary percentage
Adjusted survivor share = survivor share − external offset
Final payable amount = max(minimum payout, adjusted survivor share)
Rounded payable amount = rounded per monthly payout rule
```

Steps: define base → apply additions → apply reductions/offsets → apply caps/floors → apply split → apply rounding → produce final amount with explanation.

Name the legal basis explicitly (pensionsalder, approved service years, statutory fraction, recipient share). If the formula is unknown, mark the gap — do not invent it.

## Quality checks

Before finalizing:

| Check | Question |
|---|---|
| Completeness | Are all required outcomes covered? |
| Consistency | Do rules contradict each other? |
| Determinism | Do same inputs always produce same result? |
| Traceability | Can each rule be tied to a source? |
| Testability | Can each rule be verified with examples? |
| Explainability | Can the outcome be explained to a case worker? |
| Operational fit | Is required data available before evaluation? |

## Output templates

### Rule specification
```
Rule ID / Name:
Business purpose:
Source:
Inputs:
Preconditions:
Logic: IF [conditions] THEN [outcome]
Output:
Priority:
Exceptions:
Open questions:
```

### Decision table
```
| Condition / Outcome       | Scenario 1   | Scenario 2   | Scenario 3          |
|---------------------------|--------------|--------------|---------------------|
| Member deceased           | Y            | Y            | Y                   |
| Spouse at event date      | Y            | N            | Y                   |
| Eligible child            | N            | Y            | Y                   |
| Primary recipient         | Spouse       | Child        | Spouse + Child      |
| Split rule                | 100% spouse  | 100% child   | Defined share rule  |
| Recalculation required    | N            | N            | Y                   |
```

### Calculation specification
```
Calculation name:
Purpose:
Base amount:
Inputs:
Formula steps: 1. / 2. / 3.
Rounding:
Caps / Floors:
Effective-date dependency:
Output:
Edge cases:
```

## When information is incomplete

Do not silently fill gaps. Instead:
1. Identify the ambiguity and why it affects the outcome.
2. Propose 1–3 candidate interpretations with consequences.
3. State the clarification question needed.

If the user wants progress despite gaps, label every assumption explicitly.
