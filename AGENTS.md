## 2026.11.26: Background

This repo is a fork of a CLI tool, built initially by the Weaviate QA team to help them with their processes. It's been forked so that we can work on it as a prototype without affecting the parent repo.

In this day and age of AI tooling and coding agents, however, we see great potential for it to become an agentic surface. In particular, we at Weaviate see this tool as being the perfect surface for cluster lifecycle management, and administration.

In conjunction with this, we envisage the following:
- The Weaviate server MCP would be the tool for users engaging with Weaviate through coding agents, or web-based agents
- The SDKs would remain the main surface for building anything persistent, such as user-facing applications, or robust data ingestion pipelines.
- A set of agent skills would be updated (https://github.com/weaviate/agent-skills) to help users work holistically with these surfaces.

But, first, we should:

- [ ] Conduct research on how best to manage these agentic surfaces, then confirm or revise the current plan, including the draft first PoC steps below.

## 2026.11.26: weaviate-cli PoC

- The original CLI (https://github.com/weaviate/weaviate-cli) includes more functionalities (e.g. data plane) than what we would like to include in the future release as an admin tool. So, we should:
  - [ ] Identify a set of features to be removed from the CLI
  - [ ] Identify a set of features to be added to the CLI

- The CLI currently does not include any cluster lifecycle tooling at the moment. The Cloud has been working on a weaviate cloud CLI (https://github.com/weaviate/weaviate-cloud) which can provision clusters (for now, limited to cloud only)
  - [ ] Add a command to this CLI that would essentially download the `wcloud` CLI if not present, and use it to provision a cloud cluster

- Then, we should use the PoC fork with agents to evaluate the DX of using this tool.
