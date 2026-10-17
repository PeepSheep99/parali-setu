"""Benchmark: the deployed service, over the internet, as a judge would use it.

- Read endpoints (public pages' data): 20 requests each, p50/p95.
- The farmer agent over HTTP: short chats that stop before an offer, so no
  booking is created and no crew time is held on the live demo. Their
  conversations are tagged farmer_id "bench_live_*" and deleted afterwards.

    python -m bench.bench_live                  # writes bench/results/live.json
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

API = "https://parali-setu-api-866617346749.asia-southeast1.run.app"
OUT = ROOT / "bench" / "results" / "live.json"
READS = ["/health", "/prices/today", "/impact", "/ops/summary", "/forecast", "/depots", "/fire-detections",
         "/inventory", "/costs"]
CHATS = [
    ["I have 8 acres of paddy straw in Bahadurpur, Sangrur.", "How and when do I get paid?"],
    ["ਮੇਰੇ ਕੋਲ 10 ਕਿੱਲੇ ਝੋਨੇ ਦੀ ਪਰਾਲੀ ਹੈ, ਪਿੰਡ ਭੁੱਚੋ, ਬਠਿੰਡਾ।", "ਤੁਸੀਂ ਪਰਾਲੀ ਕਿਵੇਂ ਤੋਲਦੇ ਹੋ?"],
    ["मेरे पास 6 एकड़ धान की पराली है, गाँव नीलोखेड़ी, करनाल।", "आज का भाव क्या है?"],
    ["mere kol 12 kille jhona hai, pind Rakhra, Patiala", "paise kado milange ji"],
    ["I have 5 acres in Pehowa, Kurukshetra.", "What do you take care of for me?"],
]


def pct(values, q):
    values = sorted(values)
    k = (len(values) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    return round(values[lo] + (values[hi] - values[lo]) * (k - lo))


def bench_reads(client: httpx.Client) -> dict:
    out = {}
    for path in READS:
        ms, codes = [], set()
        for _ in range(20):
            t = time.perf_counter()
            r = client.get(API + path)
            ms.append((time.perf_counter() - t) * 1000)
            codes.add(r.status_code)
        out[path] = {"p50": pct(ms, .5), "p95": pct(ms, .95), "status": sorted(codes)}
        print(path, out[path], flush=True)
    return out


def bench_agent(client: httpx.Client) -> dict:
    turns, conv_ids = [], []
    for i, chat in enumerate(CHATS):
        conv = None
        for words in chat:
            data = {"farmer_id": f"bench_live_{i}", "text": words, "speak": "true"}
            if conv:
                data["conversation_id"] = conv
            t = time.perf_counter()
            r = client.post(API + "/agent/turn", data=data, timeout=60)
            ms = (time.perf_counter() - t) * 1000
            body = r.json() if r.status_code == 200 else {}
            conv = body.get("conversation_id") or conv
            calls = (body.get("guardrails") or {}).get("model_calls") or []
            turns.append({"status": r.status_code, "ms": round(ms), "language": body.get("language"),
                          "audio": bool((body.get("reply") or {}).get("audio_base64")),
                          "offer": any(c.get("type") == "offer" for c in body.get("cards", []))})
            print(f"chat {i} turn {len(turns)}: {r.status_code} {round(ms)} ms", flush=True)
        if conv:
            conv_ids.append(conv)
    ok = [t for t in turns if t["status"] == 200]
    return {"turns": turns, "conversation_ids": conv_ids,
            "turn_with_voice_ms": {"p50": pct([t["ms"] for t in ok], .5), "p95": pct([t["ms"] for t in ok], .95)},
            "ok": f"{len(ok)}/{len(turns)}", "offers_created": sum(t["offer"] for t in turns)}


def cleanup(conv_ids: list[str]) -> int:
    import firestore_store as store
    db = store.get_firestore_client()
    n = 0
    for cid in conv_ids:
        doc = store.get_conversation(db, cid)
        if doc and str(doc.get("farmer_id", "")).startswith("bench_live_"):
            db.collection("conversations").document(cid).delete()
            n += 1
    return n


if __name__ == "__main__":
    with httpx.Client(timeout=30) as client:
        reads = bench_reads(client)
        agent = bench_agent(client)
    agent["deleted_conversations"] = cleanup(agent["conversation_ids"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"api": API, "reads": reads, "agent": agent, "ran_at": time.strftime("%Y-%m-%d %H:%M")},
                              indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"agent": {k: v for k, v in agent.items() if k != "turns"}}, indent=1))
