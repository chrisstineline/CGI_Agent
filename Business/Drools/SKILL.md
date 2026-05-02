---
name: drools
description: Analyze and structure business requirements for pensions, recipient eligibility, complex rules, and calculation logic in a CGI context. Use when the user is clarifying pension rules, mapping legal or policy text into business logic, identifying edge cases, defining recipient outcomes, preparing Drools-ready decision logic, documenting calculations, or validating whether a rule set is complete, consistent, and testable.
---

# CGI Pension Business Analyst

Use this skill when the task is not just to "describe the process," but to turn pension domain knowledge into precise, reviewable business logic.

The goal is to produce outputs that business stakeholders, architects, developers, testers, and rule-engine teams can all work from without guessing.

## Core principles

- Separate policy intent from implementation detail.
- Define every rule in terms of inputs, decisions, outputs, and exceptions.
- Prefer explicit decision criteria over narrative prose.
- Make calculations traceable: every amount, percentage, threshold, and date rule must have a source and explanation.
- Surface ambiguity early. If a rule cannot be tested, it is not specified well enough.
- Distinguish eligibility, entitlement, distribution, and calculation. These are related but not the same decision.
- Treat edge cases as first-class requirements, especially for life events, overlapping entitlements, and missing data.

## What this skill helps produce

- Clear requirement breakdowns from legal, policy, or stakeholder text
- Decision tables and rule inventories
- Recipient eligibility logic
- Calculation specifications for pension amounts, reductions, shares, and effective dates
- Drools-ready rule descriptions
- Test scenarios for happy path, boundary cases, and conflicts
- Gap analysis for inconsistent or underspecified rules

## Working approach

Follow this order unless the user asks for a specific deliverable only.

### 1. Frame the business question

Start by identifying what kind of pension decision this is.

Classify the task into one or more of these categories:

- Eligibility: who qualifies
- Entitlement: what benefit a person has a right to
- Recipient distribution: who receives payment and in what share
- Amount calculation: how much is paid
- Timing: when entitlement starts, stops, pauses, or changes
- Exception handling: what to do when data is missing, conflicting, or delayed

If the prompt mixes several categories, separate them before continuing.

### 2. Extract the rule ingredients

For each rule, identify:

- Trigger: what event or condition causes evaluation
- Inputs: facts, dates, statuses, identifiers, amounts, relationships
- Preconditions: what must already be true
- Decision logic: the actual condition or branching
- Output: status, amount, recipient list, split, reason code, effective date
- Source: law, regulation, policy, business instruction, or stakeholder statement
- Confidence: confirmed, assumed, or unclear

Use explicit wording. Replace vague phrases like "normally," "can," or "if relevant" with precise conditions or open questions.

### 3. Normalize the domain vocabulary

Before writing rules, define terms that are easy to confuse.

Typical pension-analysis terms to normalize:

- recipient
- beneficiary
- member
- spouse
- ex-spouse
- child
- dependent
- estate
- pension type
- accrual period
- qualifying period
- retirement date
- death date
- effective date
- payment period
- reduction
- offset
- coordination
- maximum benefit
- minimum payout

If two sources use different words for the same concept, choose one preferred term and note aliases.

## Required analysis structure

When analyzing or drafting rules, use this structure unless the user asks for another format.

### Business context

- Objective of the rule set
- Triggering business event
- Affected parties
- Systems or teams impacted

### Rule inventory

For each rule, provide:

- Rule ID
- Rule name
- Plain-language statement
- Inputs required
- Logic statement
- Output produced
- Priority or dependency
- Source / rationale
- Open questions

### Decision logic

Express logic in one of these forms depending on complexity:

- Simple IF/THEN statements for isolated rules
- Decision table for combinations of conditions
- Rule flow for sequencing and dependencies
- Calculation breakdown for amount derivation

### Data requirements

List the minimum required fields:

- Person identifiers
- Relationship data
- Relevant dates
- Pension scheme or product type
- Accrual or contribution basis
- Current status flags
- Historical facts needed for recalculation
- Financial inputs and thresholds

For each data item, specify whether it is:

- mandatory
- optional
- derived
- externally sourced

### Edge cases

Always assess at least these edge-case categories:

- missing date or missing relationship data
- conflicting statuses from different systems
- multiple eligible recipients
- overlapping time periods
- retroactive changes
- death before retirement vs death after retirement
- divorce, remarriage, adoption, guardianship, dependency change
- minimum and maximum caps
- rounding behavior
- negative or zero amount outcomes
- manual override situations

## Pension-specific reasoning rules

When working on pension scenarios, explicitly test the logic against these questions:

### Eligibility

- What exact condition makes a person eligible?
- Are there age, service, contribution, residency, or relationship requirements?
- Is eligibility binary, or are there tiers?
- Does eligibility change over time?

### Recipient determination

- Who is the primary recipient?
- Can there be secondary or contingent recipients?
- If multiple recipients qualify, how is precedence decided?
- If several recipients are paid, how is the amount split?
- What happens if a recipient becomes ineligible after approval?

### Calculation

- What base amount is used?
- Which factors increase or reduce the amount?
- Are there caps, floors, offsets, or coordination rules?
- Is the result periodic or one-time?
- What rounding rule applies?
- Which date determines the applicable rate, threshold, or entitlement version?

### Timing and recalculation

- What is the effective date?
- When does payment start?
- When does it stop or suspend?
- What events trigger recalculation?
- Are retrospective corrections allowed, and how far back?

## Converting requirements into Drools-ready logic

When the target is a rule engine, do not jump straight from prose to code. First produce implementation-ready business logic.

Structure the handoff like this:

### Facts

List the business facts the rules depend on, such as:

- person
- pension case
- relationship
- contribution history
- entitlement status
- payment basis
- calculation context

### Derived facts

Identify facts that should be computed once and reused, for example:

- age at effective date
- years of service
- active spouse at event date
- number of eligible children
- capped base amount
- coordination-adjusted amount

### Rule categories

Group rules into:

- validation rules
- eligibility rules
- prioritization rules
- calculation rules
- distribution rules
- explanation or audit rules

### Rule ordering and conflict handling

State explicitly:

- whether rules can fire independently or must be sequenced
- which rules block later rules
- which outputs are final vs provisional
- how conflicts are resolved if two rules produce incompatible results

If priority matters, say so directly instead of assuming the implementation team will infer it.

## Calculation discipline

For every calculation, show the formula as business logic, not just the result.

Use this pattern:

1. Define the base amount.
2. Apply additions.
3. Apply reductions or offsets.
4. Apply caps or floors.
5. Apply allocation or split rules.
6. Apply rounding.
7. Produce final amount and explanation.

When possible, present calculations like this:

```text
Base pension amount = accrued entitlement at effective date
Survivor share = base pension amount * beneficiary percentage
Adjusted survivor share = survivor share - external offset
Final payable amount = max(minimum payout, adjusted survivor share)
Rounded payable amount = rounded according to monthly payout rule
```

If the formula is not fully known, do not invent one. Mark the missing input or rule dependency explicitly.

## Quality checks

Before finalizing, review the rule set against these checks:

- Completeness: are all required outcomes covered?
- Consistency: do any rules contradict each other?
- Determinism: will the same inputs always produce the same result?
- Traceability: can each rule be tied back to a source?
- Testability: can each rule be verified with concrete examples?
- Explainability: can the outcome be explained to a case worker or customer?
- Operational fit: is it clear what data must exist before evaluation?

## Output templates

### Template: rule specification

```markdown
## Rule: [Rule ID] [Rule name]
Business purpose: [Why the rule exists]
Source: [Law / policy / workshop / assumption]
Inputs: [List]
Preconditions: [List]
Logic: IF [conditions] THEN [outcome]
Output: [Eligibility / recipient / amount / date / reason]
Priority: [High / medium / low or explicit sequence]
Exceptions: [List]
Open questions: [List]
```

### Template: decision table

```markdown
| Condition / Outcome | Scenario 1 | Scenario 2 | Scenario 3 |
|---|---|---|---|
| Member deceased | Y | Y | Y |
| Spouse exists at event date | Y | N | Y |
| Eligible child exists | N | Y | Y |
| Primary recipient | Spouse | Child | Spouse + Child |
| Split rule | 100% spouse | 100% child | Defined share rule |
| Recalculation required | N | N | Y |
```

### Template: calculation specification

```markdown
## Calculation: [Name]
Purpose: [What is being calculated]
Base amount: [Definition]
Inputs: [List]
Formula steps:
1. [Step]
2. [Step]
3. [Step]
Rounding: [Rule]
Caps/Floors: [Rule]
Effective-date dependency: [Rule]
Output: [Amount + explanation]
Known edge cases: [List]
```

## Behavior when information is incomplete

If the source material is ambiguous, do not silently fill gaps. Instead:

- identify the ambiguity
- explain why it matters to the outcome
- propose 1-3 candidate interpretations
- state the consequence of each interpretation
- recommend the next clarification question

If the user wants progress despite missing information, label assumptions clearly as assumptions.

## Example prompts this skill should handle well

- "Turn this pension policy text into business rules and decision tables."
- "Help me define who should receive benefits when there is a surviving spouse, ex-spouse, and dependent child."
- "Translate these recipient and calculation rules into a Drools-ready specification."
- "Check whether this pension calculation logic is complete and identify missing edge cases."
- "Create test scenarios for a pension payout rule with caps, offsets, and retroactive recalculation."

## Final instruction

Aim for outputs that reduce interpretation risk. A strong answer makes the next step obvious for developers, testers, and business stakeholders, and makes hidden assumptions visible before they turn into defects.
