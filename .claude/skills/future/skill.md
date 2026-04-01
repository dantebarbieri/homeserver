---
name: future
description: Pick off low-hanging fruit from FUTURE.md — analyzes incomplete tasks, drafts a fact-checked plan, implements on approval, guides validation, and marks done.
allowed-tools: Read, Edit, Write, Bash, Grep, Glob, Agent, WebFetch, WebSearch, Skill, EnterPlanMode, ExitPlanMode
---

Work through a task from FUTURE.md using the 5-phase workflow below. Each phase ends with a user checkpoint — do NOT proceed to the next phase until the user responds.

If `$ARGUMENTS` is provided, use it to filter or select a specific task (e.g., a priority number or keyword).

---

## Phase 1: Analyze & Select

1. Read `FUTURE.md` in full.
2. Identify all **incomplete** tasks — those whose headings are NOT struck through (`~~...~~`) and do NOT have a `✅ Done` marker.
3. Rank incomplete tasks by **low-hanging fruit score** (prefer low effort + low risk + additive-only changes). Use the Summary Table at the bottom of FUTURE.md for effort/risk metadata.
4. If `$ARGUMENTS` was provided, filter to matching tasks. Otherwise, present the **top 3 easiest** candidates with:
   - Task name and priority number
   - Why it's low-hanging fruit (effort, risk, dependencies)
   - Any blockers or prerequisites
5. Ask the user which task to tackle. **STOP and wait for the user to respond.**

---

## Phase 2: Draft Plan & Fact-Check

For the selected task, use **plan mode** to draft a detailed, well-structured implementation plan:

1. Call `EnterPlanMode` to enter plan mode. This gives you a structured plan file and restricts you to read-only exploration until the plan is approved.

2. **Read every file** referenced in the FUTURE.md task section (compose files, configuration.nix, sample.env, homepage configs, etc.) to understand the current state.

3. **Fact-check all claims** in the FUTURE.md description. This is critical — FUTURE.md may be outdated or wrong:
   - **Docker images**: Verify image names/tags exist by checking the registry (use WebFetch on Docker Hub API `https://hub.docker.com/v2/repositories/library/<image>/tags/<tag>` or GitHub Container Registry equivalent). Flag images that don't exist or have been renamed.
   - **NixOS options**: Use `/nixos-option <option.path>` for every NixOS option mentioned. Flag any that don't exist, are deprecated, or have wrong types.
   - **NixOS omissions**: When the plan omits an optional NixOS option (e.g., not setting `channel` in `system.autoUpgrade`), verify that omitting it is valid — check the option's default value and confirm the module doesn't require it. Nix attribute sets with `enable = true` may have other fields that look optional but are actually required.
   - **File paths**: Use Glob/Read to verify every file path mentioned in the task actually exists in the repo.
   - **Port numbers**: Cross-reference with existing compose files and configuration.nix firewall rules.
   - **URLs/endpoints**: Verify health check endpoints and API paths mentioned are accurate for the current image versions.
   - **Environment variables**: Check `docker/sample.env` for any env vars referenced.

4. **Write the plan** to the plan file with:
   - **Context**: Why this change is being made
   - **Fact-check results**: What checked out, what was wrong/corrected
   - **Implementation steps**: Exact files to create or modify (with paths), what changes to make in each file, order of operations
   - **Verification section**: How to test the changes

5. Call `ExitPlanMode` to present the plan for approval. **STOP and wait for the user to accept or revise the plan.**

---

## Phase 3: Implement, Commit, Push & Provide Validation Instructions

Once the user accepts the plan:

1. **Implement all changes** described in the accepted plan.
2. **Commit** with a descriptive message summarizing what was added/changed.
3. **Push** to the remote.
4. **Provide validation instructions** as a **single ZSH script block** the user can paste directly into their SSH session. Rules:
   - Every line must be valid ZSH — use `#` comments for informational messages, not plain text
   - Use `z` (zoxide) instead of `cd` for directory changes
   - Include expected output as comments (e.g., `# Expected: shows "active (running)"`)
   - Group related commands with comment headers
   - Use `&&` to chain dependent commands
   - Example format:
     ```zsh
     # === Pull changes ===
     z /srv/homeserver && git pull

     # === Apply NixOS config ===
     sudo nixos-rebuild switch

     # === Verify timer exists ===
     # Expected: nixos-upgrade.timer entry with next run ~04:30
     systemctl list-timers | grep -i upgrade

     # === Confirm Docker is unaffected ===
     # Expected: containers still running
     docker ps --format '{{.Names}}' | head -5
     ```
5. Ask the user to run the validation steps and paste the results. **STOP and wait.**

---

## Phase 4: Assess Validation Results

When the user pastes command output:

1. **Parse each result** against the expected output from Phase 3.
2. For each validation step, report:
   - **PASS** — output matches expectations, explain briefly
   - **FAIL** — output differs, explain what's wrong and what it means
   - **WARN** — output is acceptable but has something unexpected worth noting
3. Check for **side effects**: unexpected errors in other services, broken containers, failed health checks.
4. Give a clear **overall verdict**:
   - **All clear** — everything passed, safe to finalize
   - **Issues found** — describe problems, propose fixes, and offer to implement them (loop back to Phase 3)
5. If all clear, tell the user you'll now mark the task as done. **STOP and wait for confirmation to proceed.**

---

## Phase 5: Mark Done & Finalize

1. **Update FUTURE.md** to mark the task as complete. Follow the existing pattern:
   - In the **heading**: wrap with `~~` strikethrough and append ` ✅ Done` — e.g., `## ~~Priority 8: NixOS Auto-Upgrade~~ ✅ Done`
   - In the **Table of Contents**: same strikethrough + checkmark — e.g., `- [~~Priority 8: NixOS Auto-Upgrade~~](#priority-8-nixos-auto-upgrade) ✅ Done`
   - In the **Summary Table**: add `~~...~~ ✅` to the item name column
2. **Commit** with message like "Mark <task name> as done in FUTURE.md"
3. **Push** to the remote.
4. Report completion with a brief summary of what was accomplished.
