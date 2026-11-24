"""The hardship-request workflow, with its deploy gate, decision gate and execution gate.

Receive -> extract (stand-in) -> retrieve policy and account snapshot -> recommend (stand-in)
-> rule checks -> route by role -> reviewer decision -> executor. Every step writes one event to
the audit log. Content goes to the content store; the provider requests go to outbound.jsonl;
spans without content go to traces.jsonl; one line per step goes to app.log.

The model is a scripted stand-in (data/stand_in_outputs.json). No model is called.
"""

import json
from pathlib import Path

from common import DATA, action_sha, canon, diff_components, load, manifest, manifest_sha, plus, sha
from evidence import AuditLog, ContentStore, append_jsonl, read_jsonl

REQUESTED_MODEL = "lender-recommender"
DEFAULT_RETURNED = "lender-recommender-2026-10-01"
EVIDENCE_VIEW = "card-v3"


class Refused(Exception):
    pass


class Workflow:
    def __init__(self, root: Path, data_dir: Path = DATA, returned_model: str = DEFAULT_RETURNED,
                 log_prompts: bool = False, cache: bool = False):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.data_dir = Path(data_dir)
        self.returned_model = returned_model
        self.log_prompts = log_prompts      # the misconfiguration E9's negative control uses
        self.cache = cache                  # a response cache keyed by prompt hash (E11's negative control)
        self.audit = AuditLog(self.root / "audit.jsonl")
        self.content = ContentStore(self.root)
        self.cases = {c["case_id"]: c for c in load("cases.json", DATA)["cases"]}
        self.outputs = load("stand_in_outputs.json", DATA)["cases"]
        self.policies = load("policies.json", DATA)["versions"]
        self.staff = load("staff.json", DATA)["staff"]
        self.evaluations = load("evaluations.json", DATA)["evaluations"]
        self.state_path = self.root / "state.json"   # the workflow's own state; the checker never reads it

    # --- state and side records ---------------------------------------------------------------
    def _state(self) -> dict:
        return json.loads(self.state_path.read_text()) if self.state_path.exists() else {"active": None, "decisions": {}}

    def _save(self, state: dict) -> None:
        self.state_path.write_text(json.dumps(state, indent=1))

    def _log(self, at: str, line: str, level: str = "INFO") -> None:
        with (self.root / "app.log").open("a", encoding="utf-8") as f:
            f.write(f"{at} {level} {line}\n")

    def _span(self, at: str, decision_id: str, name: str, attributes: dict) -> None:
        append_jsonl(self.root / "traces.jsonl", {"at": at, "decision_id": decision_id, "span": name,
                                                  "duration_ms": 1000, "attributes": attributes})

    # --- deploy gate --------------------------------------------------------------------------
    def activate(self, release: str, at: str) -> dict:
        candidate = manifest(release, self.data_dir)
        candidate_sha = manifest_sha(candidate)
        evaluated = [e for e in self.evaluations if e["release"] == release]
        match = [e for e in evaluated if e["manifest_sha256"] == candidate_sha and e["evaluated_at"] < at]
        if not match:
            # Diff against the manifest that was evaluated (rebuilt from the frozen data and checked by hash).
            reference = manifest(release, DATA)
            if evaluated and manifest_sha(reference) != evaluated[0]["manifest_sha256"]:
                raise RuntimeError("the frozen data no longer reproduces the evaluated manifest")
            changed = diff_components(candidate, reference)
            self.audit.append(at, "release_refused", "deploy-gate",
                              {"release": release, "manifest_sha256": candidate_sha, "changed_components": changed,
                               "reason": "no evaluation of this manifest"})
            self._log(at, f"deploy refused release={release} changed={','.join(changed)}")
            raise Refused(f"no evaluation of manifest {candidate_sha[:8]}; changed: {changed}")
        releases_dir = self.root / "releases"
        releases_dir.mkdir(exist_ok=True)
        (releases_dir / f"{release}.json").write_text(json.dumps(candidate, indent=1))
        policy_version = candidate["components"]["policy"]["version"]
        self.audit.append(at, "release_activated", "deploy-gate",
                          {"release": release, "manifest_sha256": candidate_sha,
                           "evaluation_id": match[0]["evaluation_id"], "policy_version": policy_version})
        state = self._state()
        state["active"] = {"release": release, "manifest_sha256": candidate_sha, "policy_version": policy_version}
        self._save(state)
        self._log(at, f"release activated {release}")
        return state["active"]

    # --- the workflow up to the review queue ----------------------------------------------------
    def _model_call(self, decision_id: str, subject: str, step: str, template: str, prompt: str,
                    raw_output: str, at: str, active: dict) -> None:
        prompt_ref, prompt_digest = self.content.put(subject, f"{decision_id}-{step}-prompt", prompt, at)
        output_ref, output_digest = self.content.put(subject, f"{decision_id}-{step}-output", raw_output, at)
        append_jsonl(self.root / "outbound.jsonl", {"at": at, "subject_id": subject, "decision_id": decision_id,
                                                    "step": step, "model": REQUESTED_MODEL, "prompt": prompt,
                                                    "returned_model": self.returned_model})
        if self.cache:
            append_jsonl(self.root / "cache.jsonl", {"key": sha(prompt.encode()), "prompt": prompt, "output": raw_output})
        spec = manifest(active["release"], self.data_dir)["components"][f"{step}_prompt"]
        self.audit.append(at, "model_call", "workflow", {
            "step": step, "release": active["release"],
            "prompt_template": {"name": f"{step}_prompt", "version": spec["version"], "sha256": spec["sha256"]},
            "model_requested": REQUESTED_MODEL, "model_returned": self.returned_model, "version_metadata": None,
            "prompt_ref": prompt_ref, "prompt_hmac": prompt_digest,
            "output_ref": output_ref, "output_hmac": output_digest}, decision_id)
        self._span(at, decision_id, f"model.{step}", {"model.requested": REQUESTED_MODEL,
                                                      "model.returned": self.returned_model,
                                                      "prompt.chars": len(prompt)})
        self._log(at, f"decision={decision_id} step={step} model={self.returned_model}")
        if self.log_prompts:
            self._log(at, f"decision={decision_id} prompt={prompt!r}", level="DEBUG")

    def process(self, case_id: str, decision_id: str | None = None, at: str | None = None) -> str:
        """Run one case up to the review queue. Returns the decision ID."""
        state = self._state()
        active = state["active"]
        if not active:
            raise Refused("no active release")
        case = self.cases[case_id]
        decision_id = decision_id or f"D-{case_id}"
        subject = case["subject_id"]
        t = at or case["received_at"]
        policy = self.policies[active["policy_version"]]

        letter_ref, letter_digest = self.content.put(subject, f"{decision_id}-letter", case["letter"], t)
        income_ref, income_digest = self.content.put(subject, f"{decision_id}-income",
                                                     json.dumps(case["income_statement"], sort_keys=True), t)
        self.audit.append(t, "received", "intake", {
            "case_id": case_id, "subject_id": subject, "exception_raised_by": case.get("exception_raised_by"),
            "letter_ref": letter_ref, "letter_hmac": letter_digest,
            "income_ref": income_ref, "income_hmac": income_digest}, decision_id)
        self._log(t, f"decision={decision_id} step=received")

        t = plus(t, minutes=0.25)
        snapshot = dict(case["account"], as_of=t)
        snapshot_text = json.dumps(snapshot, sort_keys=True)
        snap_ref, snap_digest = self.content.put(subject, f"{decision_id}-account", snapshot_text, t)
        self.audit.append(t, "context", "workflow", {
            "policy": {"doc_id": policy["doc_id"], "version": policy["version"], "sha256": sha(canon(policy))},
            "account_snapshot": {"ref": snap_ref, "hmac": snap_digest, "as_of": t}}, decision_id)

        # Extraction sees the letter and the income statement; nothing else.
        t = plus(t, minutes=0.25)
        template = (self.data_dir / "extraction_prompt.txt").read_text(encoding="utf-8")
        prompt = template.format(letter=case["letter"], income_statement=json.dumps(case["income_statement"]))
        extraction_raw = self.outputs[case_id]["extraction_raw"]
        self._model_call(decision_id, subject, "extraction", template, prompt, extraction_raw, t, active)

        # Recommendation sees the extracted facts, the policy, and only the account fields it needs:
        # no name, no letter, no loan ID.
        t = plus(t, minutes=0.25)
        template = (self.data_dir / "recommendation_prompt.txt").read_text(encoding="utf-8")
        account = {k: case["account"][k] for k in ("balance", "arrears_days", "fees_outstanding")}
        prompt = template.format(policy_version=policy["version"], policy_text=policy["text"], facts=extraction_raw,
                                 account=json.dumps(account, sort_keys=True),
                                 requested=json.dumps(case["requested"], sort_keys=True))
        recommendation_raw = self.outputs[case_id]["recommendation_raw"]
        self._model_call(decision_id, subject, "recommendation", template, prompt, recommendation_raw, t, active)

        recommendation = json.loads(recommendation_raw)
        action = {k: recommendation[k] for k in ("action", "amount", "months") if k in recommendation}
        t = plus(t, minutes=0.25)
        self.audit.append(t, "recommended", "workflow", {"action": action, "action_sha256": action_sha(action)},
                          decision_id)

        facts = json.loads(extraction_raw)
        rules = policy["rules"]
        surplus = facts["monthly_income"] - facts["monthly_expenses"]
        checks = [{"name": "surplus_below_threshold",
                   "passed": surplus < rules["surplus_decline_at"] or action["action"] == "decline",
                   "detail": f"surplus {surplus:.2f}, threshold {rules['surplus_decline_at']:.2f}"}]
        if action["action"] == "fee_waiver":
            checks.append({"name": "amount_within_fees",
                           "passed": action["amount"] <= case["account"]["fees_outstanding"],
                           "detail": f"{action['amount']:.2f} of {case['account']['fees_outstanding']:.2f}"})
        if action["action"] == "payment_plan":
            checks.append({"name": "plan_within_limit", "passed": action["months"] <= rules["max_plan_months"],
                           "detail": f"{action['months']} of {rules['max_plan_months']} months"})
        self.audit.append(t, "checked", "workflow", {"checks": checks}, decision_id)

        agent_limit = rules["role_waiver_limit"]["hardship-agent"]
        role = "hardship-lead" if action["action"] == "fee_waiver" and action["amount"] > agent_limit else "hardship-agent"
        self.audit.append(t, "routed", "workflow", {"required_role": role, "release": active["release"],
                                                    "policy_version": active["policy_version"]}, decision_id)
        self._log(t, f"decision={decision_id} step=routed role={role}")
        state["decisions"][decision_id] = {"case_id": case_id, "subject_id": subject, "action": action,
                                           "checks": checks, "release": active["release"],
                                           "policy_version": active["policy_version"],
                                           "exception_raised_by": case.get("exception_raised_by")}
        self._save(state)
        return decision_id

    # --- gates shared by the decision and the executor -----------------------------------------
    def _authority(self, reviewer: str, action: dict, policy_version: str, raised_by: str | None) -> str | None:
        role = self.staff[reviewer]["role"]
        rules = self.policies[policy_version]["rules"]
        if raised_by and reviewer == raised_by:
            return "separation of duties: the reviewer raised this exception"
        if action and action["action"] == "fee_waiver" and action["amount"] > rules["role_waiver_limit"][role]:
            return f"role limit: {role} may approve up to {rules['role_waiver_limit'][role]:.2f} under {policy_version}"
        if action and action["action"] == "payment_plan" and action["months"] > rules["max_plan_months"]:
            return "plan longer than the policy allows"
        return None

    def decide(self, decision_id: str, reviewer: str, decision: str, at: str, reason_code: str,
               modified_action: dict | None = None) -> dict:
        state = self._state()
        d = state["decisions"][decision_id]
        active = state["active"]
        approved = None
        if decision == "approve":
            approved = d["action"]
        elif decision == "modify":
            approved = modified_action
        problem = None
        if (d["release"], d["policy_version"]) != (active["release"], active["policy_version"]):
            problem = "stale: the release changed since the case was routed"
        else:
            problem = self._authority(reviewer, approved if decision != "reject" else None,
                                      active["policy_version"], d["exception_raised_by"])
        if problem:
            self.audit.append(at, "decision_refused", reviewer, {"decision": decision, "reason": problem}, decision_id)
            self._log(at, f"decision={decision_id} decision refused: {problem}")
            raise Refused(problem)
        shown = {"recommended": d["action"], "checks": d["checks"]}
        event = self.audit.append(at, "decided", reviewer, {
            "reviewer": reviewer, "role": self.staff[reviewer]["role"], "decision": decision, "reason_code": reason_code,
            "approved_action": approved, "approved_action_sha256": action_sha(approved) if approved else None,
            "release": active["release"], "policy_version": active["policy_version"],
            "evidence_view": {"version": EVIDENCE_VIEW, "shown_sha256": sha(canon(shown))}}, decision_id)
        self._log(at, f"decision={decision_id} decided={decision}")
        d["decided"] = {"reviewer": reviewer, "decision": decision, "approved": approved,
                        "release": active["release"], "policy_version": active["policy_version"]}
        self._save(state)
        if decision == "reject" or (approved and approved["action"] == "decline"):
            self.audit.append(at, "no_action", "workflow", {"reason": "rejected" if decision == "reject" else "decline approved"},
                              decision_id)
        return event

    # --- execution gate -----------------------------------------------------------------------
    def execute(self, decision_id: str, at: str, action: dict | None = None) -> dict:
        state = self._state()
        d = state["decisions"][decision_id]
        active = state["active"]
        decided = d.get("decided")
        action = action or (decided or {}).get("approved")
        problem = None
        if not decided or decided["decision"] not in ("approve", "modify"):
            problem = "no approval"
        elif action_sha(action) != action_sha(decided["approved"]):
            problem = "the action differs from the approved action"
        elif (decided["release"], decided["policy_version"]) != (active["release"], active["policy_version"]):
            problem = "stale: the release changed since the approval"
        else:
            problem = self._authority(decided["reviewer"], action, active["policy_version"], d["exception_raised_by"])
        if problem:
            self.audit.append(at, "execution_refused", "executor",
                              {"action": action, "action_sha256": action_sha(action) if action else None,
                               "reason": problem}, decision_id)
            self._log(at, f"decision={decision_id} execution refused: {problem}")
            raise Refused(problem)
        ledger = read_jsonl(self.root / "ledger.jsonl")
        ledger_id = f"ADJ-{len(ledger) + 1:04d}"
        case = self.cases[d["case_id"]]
        append_jsonl(self.root / "ledger.jsonl", {"ledger_id": ledger_id, "decision_id": decision_id,
                                                  "loan_id": case["account"]["loan_id"], "action": action, "at": at})
        event = self.audit.append(at, "executed", "executor",
                                  {"action": action, "action_sha256": action_sha(action), "ledger_id": ledger_id},
                                  decision_id)
        self._log(at, f"decision={decision_id} executed {ledger_id}")
        return event

    # --- a derived copy for E11 and E12 -------------------------------------------------------
    def add_to_eval_set(self, decision_id: str, at: str) -> None:
        d = self._state()["decisions"][decision_id]
        case = self.cases[d["case_id"]]
        append_jsonl(self.root / "eval_cases.jsonl", {"at": at, "subject_id": d["subject_id"], "case_id": d["case_id"],
                                                      "letter": case["letter"], "recommended": d["action"]})


def run_baseline(root: Path, **kwargs) -> Workflow:
    """All 12 cases under assistant-2026.11.1, decided as data/decisions.json says."""
    from evidence import write_anchor
    wf = Workflow(root, **kwargs)
    wf.activate("assistant-2026.11.1", "2026-11-03T08:00:00Z")
    decisions = load("decisions.json")["decisions"]
    last = None
    for case_id, case in wf.cases.items():
        decision_id = wf.process(case_id)
        spec = decisions[case_id]
        at = plus(case["received_at"], minutes=spec["after_minutes"])
        wf.decide(decision_id, spec["reviewer"], spec["decision"], at, spec["reason_code"], spec.get("modified_action"))
        approved = wf._state()["decisions"][decision_id]["decided"]["approved"]
        if spec["decision"] != "reject" and approved["action"] != "decline":
            wf.execute(decision_id, plus(at, minutes=1))
        last = plus(at, minutes=1)
    wf.add_to_eval_set("D-C03", last)
    wf.add_to_eval_set("D-C07", last)
    write_anchor(root, plus(last, minutes=5))
    return wf
