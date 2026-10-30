# 4. Enterprise systems behind MCP servers with the caller's identity

Status: accepted

Each system (CSMS, roaming, payments, ERP, documents) and the kit itself is an MCP server (Streamable HTTP,
Entra ID tokens). Tools run with the caller's functions and countries; read tools are marked read-only,
write tools destructive and token-gated. Copilot Studio, the kit's own Agent Framework copilot, Claude and
n8n's AI agent node can then use the same governed access instead of each integration getting its own
service account.
