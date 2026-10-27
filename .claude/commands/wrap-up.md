---
description: End-of-session capture into the vault. Finds this session's decisions, analyses and platform quirks that titan-vault doesn't have yet, drafts them, and writes the ones Albert approves to main-vault.
---

Capture this session into Titan's second brain, the `albertngo/titan-vault` Obsidian vault.

The procedure is the vault's `CONVENTIONS.md`, section **Capture from work sessions**. That
section is canonical. This command only points at it, so there is no copy here to fall
behind. The same file sits in titan-agents, titan-desk, titan-website and titan-bookkeeper.

1. **Load the vault.** If a `titan-vault` checkout is already in this session, use it and
   `git pull` on `main-vault`. Otherwise `add_repo` (`albertngo/titan-vault`,
   `access: "push"`), `git clone --depth 1 <clone_url> /workspace/titan-vault`, then
   `register_repo_root`.
2. **Read `CONVENTIONS.md` in full**, then run the `/wrap-up` steps in its **Capture from
   work sessions** section against this session.
3. If that section is missing, stop and say so. Do not make up a procedure.
