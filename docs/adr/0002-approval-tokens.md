# 2. Approval tokens bound to the action

Status: accepted

Writes (ERP credit notes and refunds, location publishing) accept only an HMAC token over the action id,
the hash of its payload, the approver and an expiry, issued when a person with the action's role approves
it and never to the person who prepared it. The token is single-use. The same check runs in the API, the
MCP write tools and the Teams card. Agents, flows and people therefore all reach the systems the same way,
and an agent that is tricked can at most prepare a proposal.
