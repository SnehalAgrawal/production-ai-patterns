"""
Reads the saved runs, joins the client's, the application's and the services' records by request id, and prints the
breakdown, the variant comparisons, and the expectations of PROTOCOL.md (E1-E12) with PASS or FAIL.

  python report.py            print the report
  python report.py --write    also save ../results/report.txt and ../results/summary.json

Every number is derived from the saved records. Delays inside the stand-ins are configured (data/settings.json);
see PROTOCOL.md for what is simulated, configured and measured.
"""
import argparse
import io
import json
import sys
from contextlib import redirect_stdout

from breakdown import attribute, durations_by_name, median, nearest_rank, segments, span_sums
from common import DATA, HERE, NS_PER_MS, ROOT, RUNS, load_settings, read_jsonl, sha256

PERCENTILES = [50, 90, 95, 99]
COMPARED = ["V0-baseline", "V1-faster-decode", "V2-parallel-lookups", "V3-stream-per-sentence",
            "V5-rare-slow-billing", "NC-uninstrumented-step"]
SLICES = {"all": lambda r: True, "tool": lambda r: r["needs_tool"], "no tool": lambda r: not r["needs_tool"]}


def ms(ns: float) -> float:
    return ns / NS_PER_MS


# ---------------------------------------------------------------------------------------------- loading


def load_run(path) -> dict:
    clients = {r["request_id"]: r for r in read_jsonl(path / "client.jsonl") if not r["warmup"]}
    apps = {r.get("request_id"): r for r in read_jsonl(path / "app.jsonl")}
    services = read_jsonl(path / "services.jsonl")
    slow = {s["index"] for s in services if s.get("service") == "invoices" and s.get("slow")}
    requests, errors = [], []
    for rid, c in sorted(clients.items(), key=lambda kv: kv[1]["index"]):
        a = apps.get(rid)
        if "error" in c or a is None or "error" in a:
            errors.append(rid)
            continue
        times = {**{k: c[k] for k in ("intended_ns", "started_ns", "connected_ns", "first_byte_ns", "last_byte_ns")},
                 **{k: a[k] for k in ("accepted_ns", "dequeued_ns", "first_write_ns", "last_write_ns")}}
        seg = segments(times)
        attributed, unattributed = attribute(a["dequeued_ns"], a["last_write_ns"], a["spans"])
        naive, leaves = span_sums(a["spans"])
        answer = a["model"]["answer"]
        requests.append({
            "request_id": rid, "index": c["index"], "needs_tool": c["needs_tool"], "slow_billing": c["index"] in slow,
            "e2e": ms(c["last_byte_ns"] - c["intended_ns"]), "ttfb": ms(c["first_byte_ns"] - c["intended_ns"]),
            "first_read_has_text": c["first_read_has_text"],
            "segments": {k: ms(v) for k, v in seg.items()},
            "telescopes": sum(seg.values()) == c["last_byte_ns"] - c["intended_ns"],
            "attributed": {k: ms(v) for k, v in attributed.items()}, "unattributed": ms(unattributed),
            "handler": ms(seg["handler"]), "naive_sum": ms(naive), "leaf_sum": ms(leaves),
            "durations": {k: ms(v) for k, v in durations_by_name(a["spans"]).items()},
            "server_ttfb": ms(a["first_write_ns"] - a["dequeued_ns"]),
            "answer_app_ttft": ms(answer["first_chunk_ns"] - answer["start_ns"]),
            "answer_app_total": ms(answer["last_chunk_ns"] - answer["start_ns"]),
            "answer_reported": answer["reported"],
            "spans": a["spans"], "dequeued_ns": a["dequeued_ns"], "times": times,
        })
    env = json.loads((path / "env.json").read_text())
    return {"requests": requests, "errors": errors, "env": env}


def load_all(base=RUNS) -> dict:
    settings = load_settings()
    runs = {}
    for variant in settings["variants"]:
        for repeat in range(1, settings["repeats"] + 1):
            path = base / variant / f"r{repeat}"
            if (path / "env.json").exists():
                runs.setdefault(variant, {})[repeat] = load_run(path)
    return runs


# ---------------------------------------------------------------------------------------------- statistics


def med(requests, key, where=lambda r: True):
    values = [key(r) for r in requests if where(r)]
    return median(values) if values else None


def stats(requests: list[dict]) -> dict:
    out = {}
    for name, where in SLICES.items():
        chosen = [r for r in requests if where(r)]
        if not chosen:
            continue
        e2e = [r["e2e"] for r in chosen]
        out[f"{name}: N"] = len(chosen)
        out[f"{name}: mean e2e"] = sum(e2e) / len(e2e)
        for p in PERCENTILES:
            out[f"{name}: p{p} e2e"] = nearest_rank(e2e, p)
        out[f"{name}: max e2e"] = max(e2e)
        out[f"{name}: p50 ttfb"] = median([r["ttfb"] for r in chosen])
        out[f"{name}: p50 handler"] = median([r["handler"] for r in chosen])
    return out


def spread(values: list[float]) -> str:
    ordered = sorted(values)
    middle = ordered[len(ordered) // 2] if len(ordered) % 2 else median(ordered)
    return f"{middle:8.1f} [{ordered[0]:.1f}-{ordered[-1]:.1f}]"


# ---------------------------------------------------------------------------------------------- printing


def print_setup(runs: dict) -> dict:
    settings = load_settings()
    files = [ROOT / "PROTOCOL.md", DATA / "settings.json", DATA / "answer.txt", *sorted(HERE.glob("*.py"))]
    hashes = {str(f.relative_to(ROOT)): sha256(f) for f in files}
    print("# 03-latency-breakdown: report\n")
    print(f"Stand-in services with configured delays (data/settings.json, seed {settings['seed']}); "
          "measured on this machine.")
    print("Percentiles: nearest rank. Medians: nearest-rank p50. Times in ms. Ranges: [min-max] over repeats.\n")
    envs = [run["env"] for variant in runs.values() for run in variant.values()]
    first = envs[0]
    print(f"python {first['python']} ({first['implementation']}), {first['platform']}, {first['cpu_count']} CPUs")
    loads = [e[s]["loadavg"][0] for e in envs for s in ("before", "after")]
    ollama = [e[s]["ollama_established_connections"] for e in envs for s in ("before", "after")]
    times = sorted(e["before"]["time"] for e in envs)
    print(f"runs: {len(envs)}, {times[0]} to {times[-1]}; 1-minute load average {min(loads):.2f}-{max(loads):.2f}; "
          f"established connections to Ollama's port: {sorted(set(ollama))}")
    print("\nSHA-256:")
    for name, digest in hashes.items():
        print(f"  {digest[:16]}  {name}")
    return {"hashes": hashes, "environment": envs}


def print_overview(runs: dict) -> dict:
    print("\n## End-to-end latency per variant (median over repeats [range])\n")
    keys = ["N", "mean e2e", "p50 e2e", "p90 e2e", "p95 e2e", "p99 e2e", "max e2e", "p50 ttfb", "p50 handler"]
    summary = {}
    for variant, reps in runs.items():
        per_repeat = [stats(run["requests"]) for run in reps.values()]
        errors = sum(len(run["errors"]) for run in reps.values())
        summary[variant] = {k: [s[k] for s in per_repeat] for k in per_repeat[0]}
        print(f"{variant}  (repeats: {len(reps)}, failed requests: {errors})")
        for name in SLICES:
            if f"{name}: N" not in summary[variant]:
                continue
            row = "  ".join(f"{k.replace(' e2e', '')} {spread(summary[variant][f'{name}: {k}'])}" for k in keys[1:])
            n = summary[variant][f"{name}: N"]
            print(f"  {name:8s} N={'/'.join(str(x) for x in n):12s} {row}")
    return summary


def print_breakdown(runs: dict) -> None:
    print("\n## Where the handler's time goes (median per request, repeat 1)\n")
    print("critical-path attribution of the handler window; sums of span durations for comparison\n")
    names = ["read_request", "load_state", "rewrite", "retrieval", "tool", "answer", "check", "check.sentence", "send"]
    for variant in COMPARED + ["V4a-burst-app-queue", "V4b-burst-kernel-queue"]:
        if variant not in runs:
            continue
        rs = runs[variant][1]["requests"]
        for name, where in (("tool", SLICES["tool"]), ("no tool", SLICES["no tool"])):
            chosen = [r for r in rs if where(r)]
            if not chosen:
                continue
            parts = []
            for n in names:
                if any(n in r["durations"] for r in chosen):
                    parts.append(f"{n} {med(chosen, lambda r, n=n: r['attributed'].get(n, 0.0)):.1f}")
            print(f"{variant:24s} {name:7s} N={len(chosen):3d}  handler {med(chosen, lambda r: r['handler']):.1f} = "
                  + ", ".join(parts) + f", unattributed {med(chosen, lambda r: r['unattributed']):.1f}")
            print(f"{'':24s} {'':7s}        leaf sum {med(chosen, lambda r: r['leaf_sum']):.1f}, naive sum (parents"
                  f" too) {med(chosen, lambda r: r['naive_sum']):.1f}; e2e {med(chosen, lambda r: r['e2e']):.1f}, "
                  f"TTFB {med(chosen, lambda r: r['ttfb']):.1f}")


def print_segments(runs: dict) -> None:
    print("\n## Outside the handler: segments of the end-to-end time (repeat 1)\n")
    keys = ["schedule_lag", "connect", "kernel_accept_queue", "app_worker_queue", "handler", "delivery"]
    print(f"{'variant':24s} " + " ".join(f"{k:>22s}" for k in keys))
    for variant, reps in runs.items():
        rs = reps[1]["requests"]
        cells = [f"{med(rs, lambda r, k=k: r['segments'][k]):9.2f} max {max(r['segments'][k] for r in rs):8.1f}"
                 for k in keys]
        print(f"{variant:24s} " + " ".join(f"{c:>22s}" for c in cells))
    print("\n(median and max per segment; every request's segments add up to its end-to-end time)")


def print_waterfall(runs: dict) -> None:
    print("\n## One request, three ways (repeat 1)\n")
    base = runs["V0-baseline"][1]["requests"]
    tool = [r for r in base if r["needs_tool"]]
    target = med(tool, lambda r: r["e2e"])
    chosen = min(tool, key=lambda r: (abs(r["e2e"] - target), r["index"]))
    print(f"request index {chosen['index']}: the tool request whose V0 end-to-end time is closest to the tool "
          "slice's median\n")
    for variant in ("V0-baseline", "V2-parallel-lookups", "V3-stream-per-sentence"):
        r = next(x for x in runs[variant][1]["requests"] if x["index"] == chosen["index"])
        t0 = r["times"]["intended_ns"]
        print(f"{variant}: end-to-end {r['e2e']:.1f}, TTFB {r['ttfb']:.1f}, handler {r['handler']:.1f}, "
              f"leaf sum {r['leaf_sum']:.1f}, unattributed {r['unattributed']:.1f}")
        rows = [("app worker queue", r["times"]["accepted_ns"], r["times"]["dequeued_ns"])]
        merged = []
        for s in sorted(r["spans"], key=lambda s: s["start_ns"]):
            if s["parent"]:
                continue
            if merged and s["name"] in ("check.sentence", "send") and merged[-1][0] == "check.sentence + send":
                merged[-1] = (merged[-1][0], merged[-1][1], s["end_ns"], merged[-1][3] + 1)
            elif s["name"] in ("check.sentence", "send") and variant.startswith("V3"):
                merged.append(("check.sentence + send", s["start_ns"], s["end_ns"], 1))
            else:
                merged.append((s["name"], s["start_ns"], s["end_ns"], 1))
        for name, start, end, count in merged:
            label = name if count == 1 else f"{name} (x{count // 2}, interleaved with answer)"
            rows.append((label, start, end))
        for label, start, end in rows:
            print(f"   {ms(start - t0):7.1f} -> {ms(end - t0):7.1f}  {ms(end - start):6.1f}  {label}")
        print(f"   first byte received at {r['ttfb']:.1f}, last byte at {r['e2e']:.1f}\n")


def print_queues(runs: dict) -> None:
    print("## A burst of 12 requests, 2 workers: where the wait is (repeat 1, in order of arrival at the app)\n")
    for variant in ("V4a-burst-app-queue", "V4b-burst-kernel-queue"):
        rs = sorted(runs[variant][1]["requests"], key=lambda r: r["times"]["accepted_ns"])
        print(f"{variant}")
        print(f"   {'#':>2s} {'kernel accept queue':>20s} {'app worker queue':>17s} {'handler':>8s} "
              f"{'e2e':>8s} {'server-side view':>17s}")
        for i, r in enumerate(rs):
            s = r["segments"]
            server_view = s["app_worker_queue"] + s["handler"]
            print(f"   {i + 1:2d} {s['kernel_accept_queue']:20.1f} {s['app_worker_queue']:17.1f} "
                  f"{s['handler']:8.1f} {r['e2e']:8.1f} {server_view:17.1f}")
        print("   (server-side view: what the application can time, from accept() to its last write)\n")


def print_tail(runs: dict) -> None:
    print("## A rare slow dependency (V5, 400 requests)\n")
    for repeat, run in runs["V5-rare-slow-billing"].items():
        rs = run["requests"]
        e2e = sorted(r["e2e"] for r in rs)
        top = sorted(rs, key=lambda r: -r["e2e"])[:7]
        print(f"repeat {repeat}: N={len(rs)}, mean {sum(e2e) / len(e2e):.1f}, p50 {nearest_rank(e2e, 50):.1f}, "
              f"p90 {nearest_rank(e2e, 90):.1f}, p95 {nearest_rank(e2e, 95):.1f}, p99 {nearest_rank(e2e, 99):.1f} "
              f"(rank {-(-99 * len(e2e) // 100)} of {len(e2e)}), max {e2e[-1]:.1f}")
        print("   slowest 7: " + ", ".join(f"#{r['index']} {r['e2e']:.0f}{' (slow billing)' if r['slow_billing'] else ''}"
                                         for r in top))
    print()


def print_two_views(runs: dict) -> None:
    print("## The answer call seen from both sides (V0, every repeat)\n")
    for repeat, run in runs["V0-baseline"].items():
        rs = run["requests"]
        gap_total = [r["answer_app_total"] - r["answer_reported"]["total_ms"] for r in rs]
        gap_first = [r["answer_app_ttft"] - r["answer_reported"]["prompt_eval_ms"] for r in rs]
        print(f"repeat {repeat}: application saw first chunk at a median {med(rs, lambda r: r['answer_app_ttft']):.1f}"
              f" (stand-in reported {med(rs, lambda r: r['answer_reported']['prompt_eval_ms']):.1f}), last at "
              f"{med(rs, lambda r: r['answer_app_total']):.1f} (reported {med(rs, lambda r: r['answer_reported']['total_ms']):.1f});"
              f" gap median {median(gap_total):.2f}, max {max(gap_total):.2f}; first-chunk gap median {median(gap_first):.2f}")
    print()


# ---------------------------------------------------------------------------------------------- expectations


def expectations(runs: dict) -> list[tuple[str, bool, str]]:
    results = []

    def check(name, ok, detail):
        results.append((name, bool(ok), detail))

    v = {k: runs.get(k, {}) for k in load_settings()["variants"]}
    repeats = sorted(v["V0-baseline"])

    def mm(rs, key, where=lambda r: True):
        return med(rs, key, where)

    tool, notool = SLICES["tool"], SLICES["no tool"]
    for rep in repeats:
        b = v["V0-baseline"][rep]["requests"]
        names = {n for r in b for n in r["attributed"]}
        meds = {n: mm(b, lambda r, n=n: r["attributed"].get(n, 0.0)) for n in names}
        share = mm(b, lambda r: r["attributed"].get("answer", 0.0) / r["handler"])
        unatt = mm(b, lambda r: r["unattributed"])
        check(f"E1 r{rep}", max(meds, key=meds.get) == "answer" and 0.60 <= share <= 0.75 and unatt < 5,
              f"largest {max(meds, key=meds.get)}, answer share {share:.1%}, unattributed {unatt:.2f} ms")

        kq, aq = mm(b, lambda r: r["segments"]["kernel_accept_queue"]), mm(b, lambda r: r["segments"]["app_worker_queue"])
        tele = all(r["telescopes"] for r in b)
        naive_over = all(r["naive_sum"] > r["handler"] for r in b)
        leaf_over = max(r["leaf_sum"] - r["handler"] for r in b)
        check(f"E2 r{rep}", tele and kq < 2 and aq < 2 and naive_over and leaf_over <= 1,
              f"segments add up: {tele}; kernel queue {kq:.2f}, app queue {aq:.2f}; naive > handler for all: "
              f"{naive_over}; leaf sum - handler max {leaf_over:.2f}")

        f = v["V1-faster-decode"][rep]["requests"]
        drops = {s: mm(b, lambda r: r["e2e"], w) - mm(f, lambda r: r["e2e"], w) for s, w in (("tool", tool), ("no tool", notool))}
        others = {n: abs(mm(f, lambda r, n=n: r["durations"].get(n, 0.0)) - mm(b, lambda r, n=n: r["durations"].get(n, 0.0)))
                  for n in ("read_request", "load_state", "rewrite", "retrieval", "check", "send")}
        others["tool"] = abs(mm(f, lambda r: r["durations"]["tool"], tool) - mm(b, lambda r: r["durations"]["tool"], tool))
        check(f"E3 r{rep}", all(150 <= d <= 200 for d in drops.values()) and max(others.values()) < 5,
              f"e2e drop tool {drops['tool']:.1f}, no tool {drops['no tool']:.1f}; largest other span change "
              f"{max(others.values()):.2f} ({max(others, key=others.get)})")

        p = v["V2-parallel-lookups"][rep]["requests"]
        overlap = mm(p, lambda r: r["leaf_sum"] - r["handler"], tool)
        d_tool = mm(b, lambda r: r["e2e"], tool) - mm(p, lambda r: r["e2e"], tool)
        d_no = mm(b, lambda r: r["e2e"], notool) - mm(p, lambda r: r["e2e"], notool)
        check(f"E4 r{rep}", 20 <= overlap <= 40 and 20 <= d_tool <= 40 and abs(d_no) < 5,
              f"tool: leaf sum - handler {overlap:.1f}, e2e drop {d_tool:.1f}; no tool: e2e change {-d_no:+.1f}")

        s3 = v["V3-stream-per-sentence"][rep]["requests"]
        d_ttfb = mm(b, lambda r: r["ttfb"]) - mm(s3, lambda r: r["ttfb"])
        d_e2e = mm(b, lambda r: r["e2e"]) - mm(s3, lambda r: r["e2e"])
        check(f"E5 r{rep}", d_ttfb > 250 and 0 <= d_e2e <= 50, f"TTFB drop {d_ttfb:.1f}, e2e drop {d_e2e:.1f}")

        base_handler = mm(b, lambda r: r["handler"])
        a4 = v["V4a-burst-app-queue"][rep]["requests"]
        b4 = v["V4b-burst-kernel-queue"][rep]["requests"]
        aq_max = max(r["segments"]["app_worker_queue"] for r in a4)
        kq_max_a = max(r["segments"]["kernel_accept_queue"] for r in a4)
        h_a = mm(a4, lambda r: r["handler"])
        check(f"E6 r{rep}", aq_max >= 3000 and kq_max_a < 10 and abs(h_a / base_handler - 1) <= 0.10,
              f"app queue max {aq_max:.1f}, kernel queue max {kq_max_a:.2f}, handler median {h_a:.1f} vs V0 "
              f"{base_handler:.1f}")
        kq_max_b = max(r["segments"]["kernel_accept_queue"] for r in b4)
        h_b = mm(b4, lambda r: r["handler"])
        e_a, e_b = max(r["e2e"] for r in a4), max(r["e2e"] for r in b4)
        check(f"E7 r{rep}", kq_max_b >= 3000 and abs(h_b / base_handler - 1) <= 0.10 and abs(e_b / e_a - 1) <= 0.10,
              f"kernel queue max {kq_max_b:.1f}, app queue max {max(r['segments']['app_worker_queue'] for r in b4):.2f}"
              f", handler median {h_b:.1f}, max e2e {e_b:.1f} vs V4a {e_a:.1f}")

        t5 = v["V5-rare-slow-billing"][rep]["requests"]
        e2e = [r["e2e"] for r in t5]
        top5 = {r["index"] for r in sorted(t5, key=lambda r: -r["e2e"])[:5]}
        check(f"E8 r{rep}", top5 == {34, 137, 172, 249, 269} and nearest_rank(e2e, 95) < 900 and nearest_rank(e2e, 99) >= 1200,
              f"slowest 5 {sorted(top5)}; p95 {nearest_rank(e2e, 95):.1f}, p99 {nearest_rank(e2e, 99):.1f}")

        nc = v["NC-uninstrumented-step"][rep]["requests"]
        rise = mm(nc, lambda r: r["unattributed"]) - mm(b, lambda r: r["unattributed"])
        changes = {n: abs(mm(nc, lambda r, n=n: r["durations"].get(n, 0.0)) - mm(b, lambda r, n=n: r["durations"].get(n, 0.0)))
                   for n in ("read_request", "load_state", "rewrite", "retrieval", "answer", "check", "send")}
        check(f"E9 r{rep}", 17 <= rise <= 23 and max(changes.values()) < 5,
              f"unattributed rise {rise:.2f}; largest span change {max(changes.values()):.2f} ({max(changes, key=changes.get)})")

        two = all(r["answer_app_total"] >= r["answer_reported"]["total_ms"] and
                  r["answer_app_ttft"] >= r["answer_reported"]["prompt_eval_ms"] for r in b)
        gap = median([r["answer_app_total"] - r["answer_reported"]["total_ms"] for r in b])
        check(f"E11 r{rep}", two and gap < 5, f"app-observed >= reported for every call: {two}; median gap {gap:.2f}")

    for variant in COMPARED:
        reps = v[variant]
        for name, where in (("tool", tool), ("no tool", notool)):
            meds = [mm(run["requests"], lambda r: r["e2e"], where) for run in reps.values()]
            check(f"E10 {variant} {name}", max(meds) - min(meds) <= 10,
                  f"medians {', '.join(f'{m:.1f}' for m in meds)}; range {max(meds) - min(meds):.1f}")

    every = [r for reps in v.values() for run in reps.values() for r in run["requests"]]
    check("E12", all(r["first_read_has_text"] for r in every),
          f"{sum(r['first_read_has_text'] for r in every)} of {len(every)} first reads carried answer text")
    return results


def print_expectations(runs: dict) -> list:
    print("## Expectations (PROTOCOL.md)\n")
    results = expectations(runs)
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:28s} {detail}")
    print(f"\n{sum(ok for _, ok, _ in results)} of {len(results)} passed")
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--smoke", action="store_true", help="read runs/smoke/ (to test this script; never reported)")
    args = parser.parse_args()
    runs = load_all(RUNS / "smoke" if args.smoke else RUNS)
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        setup = print_setup(runs)
        summary = print_overview(runs)
        print_breakdown(runs)
        print_segments(runs)
        print_waterfall(runs)
        print_queues(runs)
        print_tail(runs)
        print_two_views(runs)
        results = print_expectations(runs)
    sys.stdout.write(buffer.getvalue())
    if args.write:
        out = ROOT / "results"
        out.mkdir(exist_ok=True)
        (out / "report.txt").write_text(buffer.getvalue())
        (out / "summary.json").write_text(json.dumps(
            {**setup, "per_repeat": summary, "expectations": [{"name": n, "pass": ok, "detail": d} for n, ok, d in results]},
            indent=1))


if __name__ == "__main__":
    main()
