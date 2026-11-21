# Agent runtime

`src.agents` is a small standard-library-only ReAct loop. Agents receive a
closed tool registry, validate JSON arguments before execution, and stop on
step, wall-clock, or cost budgets. Tools marked `needs_approval=True` create a
pending row rather than executing. `Team` provides SQLite blackboard state and
delegation mailboxes.

Set `SOONY_AGENT_MODE=replay` to use cassettes from `store/agent_cassettes`;
`record` stores live request/response pairs there. `SOONY_LLM_URL` selects an
OpenAI-compatible endpoint, otherwise `ANTHROPIC_API_KEY` selects Anthropic.
Tests use `FakeLLM` and never access the network.
