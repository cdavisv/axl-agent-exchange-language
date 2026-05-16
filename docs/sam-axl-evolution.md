---
name: sam-axl-evolution
description: "AXL protocol evolution for SAM: tracks token savings, proposes new shorthands for high-frequency patterns, validates ambiguity, maintains evolution log. Use when SAM is optimizing inter-agent communication efficiency. NOT for: modifying the shared AXL spec directly."
metadata:
  {
    "uniclaw":
      {
        "emoji": "🧬",
        "requires": { "bins": ["python3"] },
      },
  }
---

# SAM AXL Evolution Skill

Protocol optimization for SAM's Agent eXchange Language usage. Tracks token efficiency, identifies high-frequency patterns, proposes new shorthands, and validates that extensions introduce no ambiguity — all as a local extension layer that does not modify the shared AXL v2.0 spec.

## When to Use

✅ **USE this skill when:**

- Analyzing AXL message traffic for compression opportunities
- Proposing new shorthand prefixes or field abbreviations
- Validating that a proposed extension is unambiguous
- Measuring token savings of current AXL usage vs. natural language
- Reviewing SAM's AXL evolution log for adoption decisions
- Promoting a local extension to the core spec (with operator approval)

## When NOT to Use

❌ **DON'T use this skill when:**

- Modifying the shared AXL spec (`src/axl/models.py`) -> only local extensions
- Defining abbreviations that conflict with AXL v2.0 reserved fields
- Introducing Unicode-dependent syntax → ASCII-safe only per AXL spec
- The proposed extension has fewer than 10 observed occurrences of the pattern

## Design Principles

- **Local first:** Extensions live in `sam_axl_proposals` table, not the shared spec
- **Data-driven:** Only propose shorthands for patterns observed 10+ times
- **No ambiguity:** Every proposal must pass collision checks against existing AXL grammar
- **Measurable:** Track token savings per extension to justify adoption
- **Reversible:** Extensions can be deprecated without breaking existing messages

## Capabilities

### Traffic Analysis

```
Inputs:  AXL message log (from SAM sessions, agent workflows)
Process:
  1. Parse all AXL messages using existing parse_axl_message()
  2. Count frequency of field combinations, prefix patterns, value repetitions
  3. Identify verbose patterns that appear 10+ times
  4. Calculate token cost of each pattern vs. hypothetical shorthand
Output:  frequency report + compression opportunity rankings
```

### Shorthand Proposal

```
Inputs:  high-frequency pattern, proposed shorthand
Process:
  1. Define proposed shorthand (new field key, prefix modifier, or value alias)
  2. Check collision against AXL v2.0 reserved fields and enums
  3. Check collision against existing local extensions
  4. Estimate token savings across observed corpus
  5. Generate `SY: mode=registry` declaration message for the extension
Output:  proposal record with savings estimate and collision report
```

### Ambiguity Validation

```
Inputs:  proposed extension definition
Process:
  1. Parse proposed syntax against AXL grammar rules
  2. Test against corpus of existing messages for false matches
  3. Verify round-trip: generate → parse → normalize → compare
  4. Check that extension degrades gracefully (ignored by non-SAM agents)
Output:  validation result (pass/fail) with detailed collision analysis
```

### Token Savings Tracking

```
Inputs:  message pairs (AXL vs. natural language equivalent)
Process:
  1. Tokenize both versions (approximate with word/subword count)
  2. Compute per-message savings ratio
  3. Aggregate savings by prefix type, channel, and time period
  4. Track savings trend over time as extensions are adopted
Output:  savings dashboard with per-extension and aggregate metrics
```

### Evolution Log

```
Inputs:  proposal lifecycle events (proposed, tested, adopted, deprecated)
Process:
  1. Record all proposals with creation date, status, and metrics
  2. Track adoption rate (how often extensions are used after approval)
  3. Flag underperforming extensions for deprecation review
  4. Generate periodic evolution summary for operator review
Output:  evolution log with status, adoption metrics, and recommendations
```

## Promotion Workflow

When a local extension proves valuable (high adoption, measurable savings, no collisions):

1. SAM generates a promotion proposal with evidence
2. Operator reviews savings data and collision report
3. If approved, extension is added to the shared AXL spec
4. SAM updates local extension status to "promoted"
5. All agents begin using the promoted shorthand

**Promotion requires explicit operator approval** — SAM cannot modify the shared spec autonomously.

## Memory Integration

SAM stores AXL evolution data in its persistent memory:
- **Episodic:** Individual proposal outcomes, adoption events
- **Semantic:** AXL grammar rules, collision patterns, token economics
- **Procedural:** Successful extension patterns, validation workflows
- **User preferences:** Operator's tolerance for new syntax, review cadence

## Example Extensions

```text
# Proposing a new shorthand for frequent "status blocked by dependency" pattern
SY: id=s-ext-1; mode=registry; abbr=blkd; meaning="st=blk with &dep ref"

# Before extension (12 tokens):
ST: ref=t-fe-9; st=blk; why=api-contract; &t-api-7

# After extension (9 tokens):
ST: ref=t-fe-9; blkd=t-api-7; why=api-contract

# Savings: ~25% per message, observed 47 times in last 30 days
```
