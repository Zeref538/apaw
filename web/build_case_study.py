"""Generate web/case-study.html from the committed results.

    uv run python web/build_case_study.py

Every number and chart on the page is read here, from eval/ and web/data/, at
build time. The pipeline re-runs this on every tick (pipeline/run.py), so the
live scores on the page move with the collector instead of freezing.

Prose lives in case-study.template.html. Measurements do not: the template
only holds {{PLACEHOLDERS}} and the /*%%DATA%%*/ slot the charts read.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
TEMPLATE = WEB / "case-study.template.html"
OUT = WEB / "case-study.html"
GATE = 200


def live() -> dict:
    e = pd.read_csv(ROOT / "eval" / "error_log.csv")
    out = {}
    for h, d in e.groupby("horizon"):
        m, p = float(d["abs_err_model"].mean()), float(d["abs_err_persistence"].mean())
        out[str(int(h))] = {"n": len(d), "model": round(m, 3), "persistence": round(p, 3),
                            "gain": round(100 * (1 - m / p), 1)}
    return out


def backtest() -> dict:
    m = json.loads((ROOT / "eval" / "metrics.json").read_text(encoding="utf-8"))
    return {h: {"n": v["n"], "model": round(v["mae_model"], 3),
                "persistence": round(v["mae_persistence"], 3),
                "gain": round(100 * (1 - v["mae_model"] / v["mae_persistence"]), 1)}
            for h, v in m["per_horizon"].items()}


def search() -> dict:
    log = (ROOT / "eval" / "experiment_log.txt").read_text(encoding="utf-8")
    sweeps = [int(n) for n in re.findall(r"--- .*?: (\d+) configurations ---", log)]
    ex = json.loads((ROOT / "eval" / "experiments.json").read_text(encoding="utf-8"))
    mean = lambda d: sum(v["ratio"] for k, v in d.items() if k.isdigit()) / 7
    return {"sweeps": sweeps, "total": sum(sweeps), "split": ex["split"],
            "dev": round(mean(ex["winner"]["dev"]), 3),
            "holdout": round(mean(ex["winner_holdout"]), 3),
            "hold_h": {h: v for h, v in ex["winner_holdout"].items() if h.isdigit()}}


def attempt() -> dict:
    a = json.loads((ROOT / "eval" / "attempt_next.json").read_text(encoding="utf-8"))
    return {"h1": a["dev_h1_mae"], "rule": a["dev_rule"], "ratio": a["dev_mean_ratio"],
            "chosen": a["chosen"], "seeds": a["seeds"]}


def dashboard() -> dict:
    f = json.loads((WEB / "data" / "forecasts.json").read_text(encoding="utf-8"))
    dams = [{"dam": d["dam"], "risk": d["risk"], "rwl": d["rwl_m"], "nhwl": d.get("nhwl_m"),
             "rule": d.get("rule_curve_m"),
             "obs": [[o["date"], o["rwl_m"]] for o in d["observed"][-30:]],
             "fc": [[x["target_date"], x["pred_rwl_m"]] for x in d["forecasts"]]}
            for d in f["dams"]]
    curve = [[c["target_date"], c.get("roll_abs_err_model"), c.get("roll_abs_err_persistence")]
             for c in f["learning_curve"]]
    return {"dams": dams, "curve": curve, "generated": f["generated_at"][:10]}


def build() -> str:
    L, B, S, A, D = live(), backtest(), search(), attempt(), dashboard()
    gains = [v["gain"] for v in L.values()]
    bgains = [v["gain"] for v in B.values()]
    n_obs = len(pd.read_csv(ROOT / "data" / "dam_levels.csv"))
    ahead = sum(v["model"] < v["persistence"] for v in L.values())
    ranked = sum(v["n"] >= GATE for v in L.values())
    inc, best = A["h1"]["incumbent"], min(A["rule"].items(), key=lambda kv: kv[1]["pct_vs_incumbent"])
    fill = {
        "LIVE_AHEAD": ahead, "LIVE_RANKED": ranked, "N_H": len(L),
        "LIVE_N": f"{sum(v['n'] for v in L.values()):,}",
        "LIVE_MIN": f"{min(gains):.0f}", "LIVE_MAX": f"{max(gains):.0f}",
        "BT_MIN": f"{min(bgains):.0f}", "BT_MAX": f"{max(bgains):.0f}",
        "H1_MODEL": f"{L['1']['model']:.3f}", "H1_PERS": f"{L['1']['persistence']:.3f}",
        "H1_GAIN": f"{L['1']['gain']:.0f}", "H1_N": L["1"]["n"],
        "N_OBS": f"{n_obs:,}", "N_DAMS": len(D["dams"]), "GENERATED": D["generated"],
        "SEARCH_TOTAL": f"{S['total']:,}", "SWEEPS": " + ".join(f"{n:,}" for n in S["sweeps"]),
        "SPLIT": S["split"], "DEV": f"{S['dev']:.3f}", "HOLD": f"{S['holdout']:.3f}",
        "INC_MEAN": f"{inc['mean']:.4f}", "INC_MIN": f"{inc['min']:.4f}", "INC_MAX": f"{inc['max']:.4f}",
        "BEST_NAME": best[0].split("_", 1)[1].replace("_", " "),
        "BEST_PCT": f"{-best[1]['pct_vs_incumbent']:.1f}",
        "SEED_RATIO_MIN": f"{A['ratio']['incumbent']['min']:.3f}",
        "SEED_RATIO_MAX": f"{A['ratio']['incumbent']['max']:.3f}",
    }
    html = TEMPLATE.read_text(encoding="utf-8")
    for k, v in fill.items():
        html = html.replace("{{" + k + "}}", str(v))
    left = re.findall(r"\{\{[A-Z0-9_]+\}\}", html)
    assert not left, f"unfilled placeholders: {left}"
    data = {"live": L, "backtest": B, "search": S, "attempt": A, "dams": D["dams"], "curve": D["curve"]}
    return html.replace("/*%%DATA%%*/", json.dumps(data, separators=(",", ":")))


if __name__ == "__main__":
    OUT.write_text(build(), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
