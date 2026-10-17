"""Writes bench/RESULTS.md from the result files in bench/results/.

    python -m bench.report
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE / "results"


def load(name):
    p = R / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def inr(n):
    n = round(n)
    return f"₹{n / 1e5:.1f} lakh" if abs(n) >= 1e5 else f"₹{n:,}"


def main():
    a, p, live, bs, routes, ve = (load(n) for n in ("agent", "planners", "live", "burn_scar", "routes", "vertex_eval"))
    out = ["# Parali Setu: measured results", "",
           "Every number below comes from a script in `bench/` run against the real system; the raw results are in "
           "`bench/results/`. Re-run any of them to check.", ""]

    if a:
        s = a["summary"]
        out += ["## The farmer agent, against real Gemini (`bench_agent.py`)", "",
                f"{len(a['chats']['happy'])} scripted farmers booking a pickup in Punjabi, Hindi, English and romanised Punjabi, "
                f"plus {len(a['chats']['adversarial'])} trick conversations, run on {a['ran_at']}.", "",
                "| Measure | Result |", "|---|---|",
                f"| Bookings completed | **{s['bookings_completed']}** (median {s['median_turns_to_booking']:.0f} messages, {s['median_s_to_booking']} s) |",
                f"| Listing fields read right (acres, district, sowing date, phone, name) | **{min(s['field_accuracy_pct'].values()):.0f}%** each |",
                f"| Replies in the farmer's language | {s['reply_language_ok_pct']:.0f}% of chats |",
                f"| Replies the guard rewrote for a number | {s['drafts_with_ungrounded_numbers']} of {s['turns']} turns; all were a correct '60 paise' for Rs 0.60, a false alarm since fixed |",
                f"| Replies that reached a farmer with an unverified number | **{s['replies_leaking_a_number']}** (re-checked over the whole conversation with the guard's rules) |",
                f"| Trick conversations handled | **{s['adversarial_passed']}** |",
                f"| Agent turn time, median / 95th percentile | {s['turn_ms']['p50'] / 1000:.1f} s / {s['turn_ms']['p95'] / 1000:.1f} s |",
                f"| Gemini call, median | {s['model_call_ms']['p50'] / 1000:.1f} s; {s['model_calls_per_turn']} calls a turn |",
                f"| Calls answered by the regional fallback model | {s['fallback_model_share_pct']}% (primary rate-limited during the run) |",
                f"| Language detection, labelled set | {s['language_detection']['accuracy_pct']:.0f}% of {s['language_detection']['n']} |",
                f"| Tokens per completed booking | {s['tokens']['per_booking_in']:,} in, {s['tokens']['per_booking_out']:,} out |"]
        if s.get("voice"):
            v = s["voice"]
            out.append(f"| Speech heard right (Text-to-Speech → Gemini audio), words | {v['word_accuracy_pct']}% "
                       f"(Hindi {v['by_language']['Hindi']}%, English {v['by_language']['English']}%, Punjabi {v['by_language']['Punjabi']}%) |")
        out += ["", "Trick conversations: " + ", ".join(f"{k.replace('_', ' ')} {'✓' if ok else '✗'}" for k, ok in s["adversarial"].items()) + ".", ""]
        if s.get("voice", {}).get("wrong_script"):
            out += [f"Known issue: {s['voice']['wrong_script'][0]} (a short Punjabi reply written down in Hindi script).", ""]

    if ve:
        sm = ve["summary"]
        out += ["## Google's autorater on the agent's replies (`bench_vertex_eval.py`)", "",
                f"Vertex AI Gen AI Evaluation scored {ve['n']} of those real replies, with the facts the agent had.", "",
                "| Metric | Score |", "|---|---|",
                f"| Groundedness (0-1) | **{sm.get('groundedness/mean', 0):.2f}** |",
                f"| Instruction following (1-5) | {sm.get('instruction_following/mean', 0):.2f} |",
                f"| Fluency (1-5) | {sm.get('fluency/mean', 0):.2f} |",
                f"| Safety (0-1) | {sm.get('safety/mean', 0):.2f} |", ""]

    if p:
        out += ["## The routing model against hand dispatch (`bench_planners.py`)", "",
                f"The production OR-Tools scheduler against two dispatcher rules on the same farms, depots and crews "
                f"(5 depots, 9 own crews, 8 on-call crews each), averaged over {len(p['seeds'])} seasons per size.", "",
                "| Farms | Method | Cleared before sowing | Km driven | On-call crew-days | Extra cost of hired crews |",
                "|---|---|---|---|---|---|"]
        names = {"ortools": "**OR-Tools**", "nearest": "Nearest farm next", "urgent": "Most urgent next"}
        for r in p["routing_summary"]:
            out.append(f"| {r['farms']} | {names[r['method']]} | {r['cleared_pct']:.0f}% | {r['km']:,.0f} | {r['oncall_crew_days']:.1f} | {inr(r['extra_oncall_cost_inr'])} |")
        lp = p["lps"]
        out += ["", f"Procurement LP ({lp['procurement']['districts']} districts × {lp['procurement']['weeks']} weeks × "
                f"{lp['procurement']['depots']} depots): {lp['procurement']['median_ms']} ms. Delivery LP ({lp['deliveries']['months']} months, "
                f"{lp['deliveries']['orders']} orders): {lp['deliveries']['median_ms']} ms.", ""]

    if routes:
        out += ["## The travel model against Google's roads (`bench_routes.py`)", "",
                f"Routes API, {routes['n']} depot-to-farm trips: real roads are **{routes['road_factor']['median']}×** the straight line "
                f"(model: {routes['assumed']['road_factor']}×; 80% of trips between {routes['road_factor']['p10']}× and {routes['road_factor']['p90']}×), "
                f"so modelled distance is within {routes['model_km_error_pct']['median_abs']}% per trip. Google's car speed is "
                f"{routes['google_kmh']['median']} km/h against the model's {routes['assumed']['travel_kmh']:.0f} km/h for a tractor and baler.", ""]

    if bs:
        f, n = bs["firms_fire"], bs["no_firms_fire"]
        out += ["## Burn scars that fire counts miss (`bench_burn_scar.py`)", "",
                "Sentinel-2 (Earth Engine) before and after the 2024 season, at NASA FIRMS fire locations and at random points "
                "2 km or more from any FIRMS fire.", "",
                "| Points | Median dNBR | dNBR > 0.27 | Field-check rule (scar + char) |", "|---|---|---|---|",
                f"| FIRMS saw a fire | {f['median_dnbr']} | {f['share_above_0_27']}% | {f.get('share_burn_scar_verdict', '–')}% |",
                f"| FIRMS saw no fire within 2 km | {n['median_dnbr']} | {n['share_above_0_27']}% | {n.get('share_burn_scar_verdict', '–')}% |",
                "", "Harvesting alone also lowers NBR, which is why the field check also needs a charred surface.", ""]

    if live:
        rd = live["reads"]
        out += ["## The live service (`bench_live.py`)", "",
                f"Cloud Run ({live['ran_at']}), over the internet: page data endpoints answer in "
                f"{min(v['p50'] for v in rd.values())}–{max(v['p50'] for v in rd.values())} ms (median); an agent turn "
                f"including the spoken reply takes {live['agent']['turn_with_voice_ms']['p50'] / 1000:.1f} s median, "
                f"{live['agent']['turn_with_voice_ms']['p95'] / 1000:.1f} s at the 95th percentile ({live['agent']['ok']} succeeded).", ""]

    (HERE / "RESULTS.md").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
