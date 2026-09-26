"""Agentic generation — two agents that share a directory and nothing else.

Session 4's Actor-Critic-Boss (``boss.py`` orchestrates iterative refinement,
``critic.py`` is the read-only auditor) runs a FIXED choreography over the
conversational path.

Session 12's estimation agent (``agent_schemas.py``, ``agent_tools.py``,
``agent_loop.py``) is the other shape: a manual tool loop over the raw Responses
API where the MODEL decides how many searches to run and in what order.

This layer MAY import ``app.generation.conversation`` (the multi-turn substrate it
runs on); the reverse is forbidden, and so is importing any other ``generation``
sibling — which is why the estimation agent takes its retrieval backend injected.
"""
