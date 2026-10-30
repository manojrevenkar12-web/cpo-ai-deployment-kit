# 1. Models read, code decides

Status: accepted

Inbound text (eMSP emails, drivers' tickets, exports, bid documents) is read by a model; everything that
moves money or publishes data is decided by code over system data and `config/policy.yaml`. A model's
answer must parse into its task's schema or it is not used. Consequence: an injected instruction that a
model obeys still moves no money (tested with the quarantine switched off); the cost is that each new
kind of decision needs rules written with the business, which is also what makes it reviewable.
