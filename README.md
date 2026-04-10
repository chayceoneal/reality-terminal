# Reality Terminal

Point your OpenClaw agent at this repo.

It contains the instructions and starter files needed to build a private, local-first Sreality property radar with personalized ranking, a bilingual terminal-style dashboard, and daily summaries.

Your agent should review this repo, ask you the questions it needs about region, filters, ranking preferences, dashboard style, and delivery method, then build the system for your environment.

## What this repo is

This is an agent-first build kit, not a one-size-fits-all finished deployment.

A capable OpenClaw agent should be able to:
- read this repo
- understand the product goal
- ask the human for missing preferences
- adapt the included starter code
- wire automation for the target environment
- keep the result private unless explicitly told otherwise

## Example dashboard

A sample Reality Terminal dashboard view, showing the terminal-style layout, bilingual labels, and ranked listing sections.

![Reality Terminal example dashboard](/example-dashboard.jpeg)

## How to use

1. Give this repo to your OpenClaw agent.
2. Ask it to build Reality Terminal for your environment.
3. Answer its questions about region, preferences, and delivery.
4. Let it create the final local version.

## Expected agent workflow

A good agent should:
1. Read `REALITY_TERMINAL_HANDOFF.md`
2. Review `config.example.json`
3. Ask the human for:
   - target region
   - property categories
   - size/layout preferences
   - price ranges
   - location boosts or exclusions
   - rental restriction handling
   - delivery channel and schedule
   - dashboard styling preferences
4. Create a local working `config.json`
5. Adapt `run.py` as needed
6. Test the collector and generated dashboard
7. Set up automation in OpenClaw
8. Keep the dashboard private by default

## Included files

- `REALITY_TERMINAL_HANDOFF.md` — detailed agent instructions
- `config.example.json` — public-safe example config
- `run.py` — starter implementation for scraping, scoring, dashboard generation, and summary output
- `example-latest-summary.txt` — example summary output format
- `.gitignore` — keeps local data and private config out of git

## Human setup

If you are a human operator, the shortest version is:

- give this repo to your OpenClaw agent
- ask it to build Reality Terminal for you
- answer its questions
- let it implement the final local version

## Privacy model

This project is intended to be private/local-first by default.

Recommended defaults:
- local files for snapshots/history
- static HTML dashboard generation
- private access via Tailscale or equivalent
- no public exposure unless explicitly requested
- no committing live snapshot data or personal config into git

## Notes

The example config uses Prague purely as a public-safe demonstration. It is not intended to imply a preferred user location.
