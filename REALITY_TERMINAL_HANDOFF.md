# Reality Terminal — Agent Handoff

This repository is an agent-first build kit for creating a private, local-first Sreality property monitoring system.

Your job as the agent is not merely to run the included files as-is. Your job is to review this repo, understand the intended product, ask the human the missing questions, and build an adapted version for their preferences and environment.

## Product goal

Build a private property radar for Sreality that:
- searches one or more target regions
- monitors selected property categories
- ranks listings using human-specific heuristics
- stores snapshots/history locally
- generates a dashboard the human can review privately
- sends concise periodic summaries through OpenClaw

The intended product name is **Reality Terminal**.

## Default architecture

Prefer this architecture unless the human asks for something else:
- Python collector/scoring pipeline
- local JSON snapshot storage
- static HTML dashboard output
- OpenClaw cron for periodic runs and summary delivery
- private dashboard access via Tailscale or another private network path

Prefer the simplest implementation that works.

## Privacy expectations

Default to private/local-first behavior.

Unless explicitly asked otherwise:
- do not expose the dashboard publicly
- do not publish live snapshot data
- do not publish personal config values
- do not assume the example region in this repo is the human's real search region

If preparing a public GitHub repo, keep only public-safe template files.

## What to ask the human

Before finalizing the build, ask for the items needed to personalize ranking and automation.

At minimum, confirm:
- target region name
- Sreality region parameters if needed (`region`, `region-id`, `region-type`, radius)
- categories to monitor:
  - apartments for sale
  - apartments for rent
  - family homes for sale
  - family homes for rent
  - land for sale
- apartment layouts to include
- minimum area targets
- soft budget bands for sale/rent/land
- location boosts or penalties
- acceptable renovation level
- rental restrictions to exclude entirely
- dashboard language/styling preferences
- summary channel and schedule
- whether private dashboard access should use Tailscale

## Implementation guidance

Use `run.py` as a starter, not a sacred artifact.

Adapt it as needed to:
- support the requested categories
- support the requested scoring logic
- support bilingual or single-language dashboard labels
- keep displayed titles/region labels config-driven rather than hardcoded
- exclude listings based on explicit human rules
- generate concise summary text for automated delivery

Keep the implementation understandable. Favor fewer moving parts over framework-heavy designs.

## Config guidance

The repo includes `config.example.json`.

Use it as a template only.

Recommended pattern:
1. copy `config.example.json` to `config.json`
2. customize `config.json` for the human's real preferences
3. keep `config.json` out of git

## Dashboard guidance

The dashboard should:
- be easy to skim
- show top candidates first
- show newly discovered listings clearly
- preserve source links
- make score rationale visible but compact
- work well on desktop and mobile

A dark terminal-style visual theme is a good default but should remain customizable.

## Summary guidance

Periodic summaries should be brief and useful.

Suggested pattern:
- say whether anything new was found
- group by category
- include only the top few items per category
- include price and score
- avoid wall-of-text output

See `example-latest-summary.txt` for shape, not canon.

## OpenClaw automation guidance

If OpenClaw is available, prefer:
- cron for scheduled execution
- internal messaging for summary delivery
- private network access for dashboard viewing

When possible, the agent should perform the setup rather than merely describing it.

## Definition of done

The build is complete when:
- the collector runs successfully
- the dashboard is generated successfully
- summaries are generated successfully
- the configuration reflects the human's preferences
- automation is wired or clearly ready to wire
- privacy expectations are respected
- the human can access the result in the intended way

## If publishing a public repo

Keep the repo clean and reusable:
- include `README.md`
- include this handoff file
- include `config.example.json`
- include starter code
- include example output only
- exclude live data, generated dashboard output, caches, and private config

## Human-facing one-line summary

If the human wants a simple explanation of this repo, use:

> Point your OpenClaw agent at this repo. It contains the instructions and starter files needed to build Reality Terminal. The agent should review it, ask the questions it needs, and create the system for your environment.
