"""Application-level sandboxing for the multi-agent system (Session 14).

Three layers, in the order an action passes through them:

1. **Least privilege** (``grants``) — which agent may call which tool, declared
   as DATA and verified at startup. A grant nobody checks is a comment.
2. **Argument validation** (``guard``) — deterministic business rules over the
   arguments an agent wants to send. The model is the caller here, and a caller
   does not validate itself.
3. **Audit** (``audit``) — every action with its agent, tool, arguments and
   outcome, denied ones included, through one chokepoint.

This is the APPLICATION half of sandboxing. The runtime half — process
isolation, network policy, CPU/memory limits, secret handling — lives in the
deployment layer and is not in this package.
"""
