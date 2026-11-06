# Prompt Log

This file records prompts actually used for this project. Entries are chronological. The project brief below is reproduced from the attached `pasted_content.txt`; it is not an invented summary.

## 2026-11-06 approximately 12:05 — Manus chat input (user attachment)

```text
I’m doing a solo 24-hour hackathon project called “Kill It and Prove It.” Read the project PDF in my Downloads folder and treat it as the requirements. I am a beginner.

Work only in my authorized local project folder. This must be a command-line key-value database, not a website or UI. Use Python 3 and its standard library unless the PDF or installed tools make that infeasible. Do not use external research, wide research, sub-agents, deployment, paid services, or third-party database/storage libraries.

CREDIT-AWARE WORK RULES
- I have 2,190 Manus credits total. There is no reliable fixed cost per phase, so do not claim you can enforce a hard credit cap.
- Keep work focused. Do not repeatedly re-read or restate the entire PDF; extract a concise checklist once and refer to it.
- Work in the phases below. At the end of each phase, stop and report files changed, commands run, real results, failures, and remaining work. Wait for me to say “continue” before starting the next phase.
- Before each phase, give me a brief estimate of what you intend to do. If the phase is likely to require a large rewrite or broad exploration, tell me first and propose a smaller step.
- Do not spend credits polishing prose, building visuals, researching technologies, or adding features outside the brief.
- Make changes directly in the local project folder. Before editing, inspect it and the Git state. Never overwrite unrelated files or an existing repository.
- Keep meaningful Git commits throughout, but only if the hackathon has started and the folder is a fresh repository. Never make one giant final commit.
- Explain each important design choice simply so I can explain to judges.
- Never claim code or a test works unless you actually ran it and saw it pass. Preserve and report failures honestly.
- The hackathon permits AI, but requires PROMPTS.md to log every actual prompt in chronological order, unedited, with tool name and approximate time. Remind me to record this prompt and each later prompt. Never invent log entries.
- Do not use AI during judging. Help me prepare explanations I can give without AI.

FIRST RESPONSE ONLY: PHASE 0 — PLAN
1. Confirm you can read the PDF and access the authorized local folder and terminal.
2. Check Python and Git versions. Inspect whether the folder already contains files or a Git repository.
3. Summarize the mandatory requirements in a short checklist.
4. Propose the simplest design you think can work. Explain the file format, checksums, batch commit rule, sync-before-ACK ordering, recovery after a torn write, and how compaction would swap files safely.
5. Give a short phase plan and identify any requirement that looks risky for a solo beginner.
6. Do not code yet. Stop and wait for “continue.”

PHASES — DO ONE AT A TIME, STOP AFTER EACH

PHASE 1 — Minimum engine
Implement and explain put, get, delete, batch, open/recovery, and close. Use a single authoritative data file, record framing/checksums, all-or-nothing batch recovery, durable sync before ACK, and a simple global lock. Add only the minimum tests needed to verify basic recovery. Make a meaningful commit if allowed. Stop and report.

PHASE 2 — CLI
Implement the required commands: open, put, get, del, batch, dump, check, and serve. ACK in serve mode only after the operation is durable. Document exact Windows commands. Run and report actual basic command checks. Commit. Stop and report.

PHASE 3 — Torture tool
Implement a separate tester with a reproducible seed and independent oracle of acknowledged operations. It must abruptly kill the child process during in-flight work, restart it, compare recovered state, and report the first mismatch. Add concurrency and batch coverage. Add targeted modes only as time permits. Never make the test pass by avoiding kills or trusting the database’s own dump as expected truth. Report exactly what was tested and any limitations of Windows process-kill testing. Commit. Stop and report.

PHASE 4 — Maintenance and size limit
Implement crash-safe compaction and configurable maximum file size. Test interruption before/during/after replacement, failed writes, failed batches, and recovery. Do not risk existing acknowledged data to force a feature through. If a requirement cannot be safely completed, explain why and mark it unverified. Commit. Stop and report.

PHASE 5 — Required documentation
Create README.md, BREAKING.md, ARCHITECTURE.md, and PROMPTS.md.
- README: one build command, every CLI command, exact file format, write ordering, and recovery process.
- BREAKING: crash-point table, ordering argument naming actual calls, at least three honest weaknesses, actual failed attempts, and three prioritized improvements.
- ARCHITECTURE: detailed diagram, recovery flow, durability/atomicity/recovery arguments, and all 32 Section 5 scenario rows from Groups A–F. Each row must name actual code and actual evidence or say “not verified.”
- PROMPTS: include only prompts actually used, unedited, chronological, with tool and approximate time. Do not fabricate this history.
Use evidence from code and test output. Do not claim untested scenarios pass. Commit. Stop and report.

PHASE 6 — Final verification
Follow README from a clean checkout if feasible. Run the required CLI and torture checks that are actually implemented. Measure recovery on a large dataset only if practical. Verify offline operation. Report actual timings and failures; do not invent results. Make a final meaningful commit if appropriate. Give me a short demo script and likely judge questions with answers based on the real code. Stop and report.

CORE REQUIREMENTS FROM THE PDF
- Single-process embedded key-value database, one authoritative file.
- put/get/delete/batch/open/close.
- Byte keys 1–1,024 bytes; values 0–1 MB; at least 1,000,000 keys; batches up to 10,000 operations.
- A successful write survives process death. Batches are fully applied or absent. A reader never sees half a batch.
- Concurrent callers do not corrupt data. One global lock is allowed.
- Recovery after a crash during write, batch, recovery, close, or compaction.
- Compaction can shrink the file and is crash-safe.
- Configurable file-size cap; errors must not corrupt acknowledged data.
- Recovery target under 2 seconds for 1,000,000 keys.
- Offline operation and a fresh Git history with meaningful commits.
- Torture tool has independent oracle, actual random in-flight kills, reproducible seed, restart/check/compare, and honest results.
- During judging, no AI or internet. I must understand and explain the implementation.
```

## 2026-11-06 approximately 12:07 — Manus chat input (user)

```text
continue
```

## 2026-11-06 approximately 12:12 — Manus chat input (user)

```text
continue
```

## 2026-11-06 approximately 12:14 — Manus chat input (user)

```text
continue
```

## 2026-11-06 approximately 12:16 — Manus chat input (user)

```text
contine
```

## 2026-11-06 approximately 12:19 — Manus chat input (user)

```text
continue
```

## 2026-11-06 approximately 12:22 — Manus chat input (user)

```text
continue
```

## 2026-11-06 approximately 12:24 — Manus chat input (user)

```text
bith paths
```
