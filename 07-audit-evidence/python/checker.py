"""The independent checker: does the evidence show that the controls operated?

It reads only the stores (audit log, anchor, ledger, the staff directory, the policy store, the
evaluation records), never the workflow's state or code paths. Each finding names a check (K1-K8
in PROTOCOL.md), a decision ID where there is one, and what it found.

What it can't do: see anything that left no record in the stores it reads. That's what E6's
negative control shows.
"""

from pathlib import Path

from common import action_sha, load
from evidence import AuditLog, chain_start, check_anchor, read_jsonl, verify_chain

REQUIRED = ["received", "context", "model_call", "model_call", "recommended", "checked", "routed", "decided"]
IGNORED = {"decision_refused", "execution_refused", "erased"}


def check(root: Path, k2: bool = True, k5: bool = True) -> list[dict]:
    root = Path(root)
    events = AuditLog(root / "audit.jsonl").events()
    staff = load("staff.json")["staff"]
    policies = load("policies.json")["versions"]
    evaluations = {e["release"]: e for e in load("evaluations.json")["evaluations"]}
    findings = []

    def find(k, decision_id, what):
        findings.append({"check": k, "decision_id": decision_id, "finding": what})

    # K1: the chain.
    broken = verify_chain(events, chain_start(root))
    if broken is not None:
        find("K1", None, f"chain broken at event {broken}")

    # K2: the external anchor.
    if k2:
        problem = check_anchor(root)
        if problem:
            find("K2", None, problem)

    # The release active at each point in the log, by sequence order.
    active = None
    active_at = {}
    for e in events:
        if e["kind"] == "release_activated":
            active = e["data"]
        active_at[e["seq"]] = active

    by_decision = {}
    for e in events:
        if e["decision_id"]:
            by_decision.setdefault(e["decision_id"], []).append(e)

    for decision_id, evs in by_decision.items():
        received = next((e for e in evs if e["kind"] == "received"), None)
        recommended = next((e for e in evs if e["kind"] == "recommended"), None)
        raised_by = received["data"]["exception_raised_by"] if received else None

        for ex in (e for e in evs if e["kind"] == "executed"):
            # K3: an approval that operated: before, same action, still current, allowed, separate.
            decided = [e for e in evs if e["kind"] == "decided" and e["seq"] < ex["seq"]
                       and e["data"]["decision"] in ("approve", "modify")]
            if not decided:
                find("K3", decision_id, "executed with no approval")
                continue
            dec = decided[-1]["data"]
            if dec["approved_action_sha256"] != ex["data"]["action_sha256"]:
                find("K3", decision_id, "executed action differs from the approved action")
            now = active_at[ex["seq"]]
            if now is None:
                # The release record aged out with the oldest events (deviation D3): the evidence for
                # this check is gone, which is itself a finding, not a reason to crash.
                find("K3", decision_id, "no release activation in the retained log; can't check the approval")
                continue
            if (dec["release"], dec["policy_version"]) != (now["release"], now["policy_version"]):
                find("K3", decision_id, f"stale approval: approved under {dec['release']}, executed under {now['release']}")
            reviewer = dec["reviewer"]
            role = staff.get(reviewer, {}).get("role")
            if role != dec["role"]:
                find("K3", decision_id, f"recorded role {dec['role']} differs from the directory ({role})")
            action = ex["data"]["action"]
            rules = policies[now["policy_version"]]["rules"]
            if action["action"] == "fee_waiver" and role and action["amount"] > rules["role_waiver_limit"][role]:
                find("K3", decision_id, f"role limit: {role} approved {action['amount']:.2f} under {now['policy_version']}")
            if raised_by and reviewer == raised_by:
                find("K3", decision_id, "separation of duties: approved by the person who raised the exception")

            # K7: a difference from the recommendation needs a recorded modification.
            if recommended and ex["data"]["action_sha256"] != recommended["data"]["action_sha256"] and dec["decision"] != "modify":
                find("K7", decision_id, "executed action differs from the recommendation without a modify decision")

        # K6: the model identifier that was evaluated.
        for mc in (e for e in evs if e["kind"] == "model_call"):
            evaluated = evaluations.get(mc["data"]["release"], {}).get("returned_model_observed")
            if mc["data"]["model_returned"] != evaluated:
                find("K6", decision_id, f"returned model {mc['data']['model_returned']} differs from the evaluated {evaluated}")

        # K8: completeness.
        kinds = [e["kind"] for e in evs if e["kind"] not in IGNORED]
        if kinds[:len(REQUIRED)] != REQUIRED:
            find("K8", decision_id, f"incomplete: steps {kinds}")
        else:
            decided = next(e for e in evs if e["kind"] == "decided")["data"]
            approved = decided["approved_action"]
            needs_execution = decided["decision"] in ("approve", "modify") and approved and approved["action"] != "decline"
            closing = "executed" if needs_execution else "no_action"
            if closing not in kinds[len(REQUIRED):]:
                find("K8", decision_id, f"incomplete: no {closing} event")

    # K5: reconciliation with the system of record.
    if k5:
        ledger = read_jsonl(root / "ledger.jsonl")
        executed = [e for e in events if e["kind"] == "executed"]
        for entry in ledger:
            matching = [e for e in executed if e["data"]["ledger_id"] == entry["ledger_id"]]
            if len(matching) != 1:
                find("K5", entry["decision_id"], f"ledger entry {entry['ledger_id']} has {len(matching)} executed events")
            elif matching[0]["data"]["action_sha256"] != action_sha(entry["action"]):
                find("K5", entry["decision_id"], f"ledger entry {entry['ledger_id']} differs from its executed event")
        ids = {entry["ledger_id"] for entry in ledger}
        for e in executed:
            if e["data"]["ledger_id"] not in ids:
                find("K5", e["decision_id"], f"executed event names {e['data']['ledger_id']}, missing from the ledger")
    return findings
