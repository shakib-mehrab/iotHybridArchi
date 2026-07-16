# HybridGuard Build Agent — Setup

This folder is a drop-in agent kit for building the HybridGuard project with
Claude Code (or any agent that reads `CLAUDE.md`) across multiple sessions.

## Setup (one time)

1. Copy your original build prompt document into this project's root as
   `HYBRIDGUARD_MASTER_PROMPT.md`. That file is the spec: exact phases,
   exact code, directory layout, dataset mapping. Don't edit it unless you're
   changing the actual plan.
2. Copy `CLAUDE.md` from this kit into the project root too. Claude Code
   reads `CLAUDE.md` automatically at the start of every session — this is
   what makes the multi-session behavior work without you re-explaining the
   rules each time.
3. Copy `state/hybridguard_build_state.json` into the project's `state/`
   folder. This is the fresh starting point (Phase 0, nothing done yet).

Resulting layout at your project root:
```
F:\4 1 Research\hybrid-architecture\iotHybridArchi\
├── CLAUDE.md                        ← process rules (this kit)
├── HYBRIDGUARD_MASTER_PROMPT.md      ← your original spec (paste it in)
├── state\
│     └── hybridguard_build_state.json
└── ...                               ← everything else gets built by the agent
```

## Starting a session

Open Claude Code in the project root and just say what you want to work on,
e.g. "let's start Phase 0" or "continue the build." `CLAUDE.md` tells the
agent to check `state/hybridguard_build_state.json` first and pick up from
there automatically — you don't need to re-paste anything unless the agent
asks for it.

## Resuming after a dropped session

If a session ends mid-phase, just start a new one and say:

> Resume build — here is my current state:

then paste the contents of `state/hybridguard_build_state.json`. The agent
will re-verify the last completed phase before moving on, per `CLAUDE.md`
section 1.

## What's different from the original document

`CLAUDE.md` doesn't repeat your phase-by-phase spec — it wraps it with:
- session-start / session-end protocol
- stricter one-step-at-a-time gating for the Fabric/WSL/Docker parts
- RAM safety checks before Phase 2 and Phase 3
- three concrete bug fixes applied automatically during the build (see
  CLAUDE.md section 5): the on-chain gas-limit query/write mismatch, the WSL
  env-var propagation issue in `fabric_client.py`, and the likely
  `ipfshttpclient` / Kubo 0.28 version incompatibility.

If you disagree with any of those three fixes (e.g. you want gas-limit
tracking to stay fully on-chain rather than move to the gateway), just say so
at the relevant point in Phase 3 — CLAUDE.md tells the agent to confirm with
you before applying that particular one, since it changes the chaincode
signature.