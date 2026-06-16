import marimo

__generated_with = "0.9.0"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    import numpy as np
    import pandas as pd
    import json
    from pathlib import Path

    import yield_gen_core as core
    return Path, core, json, mo, np, pd


@app.cell
def _(mo):
    mo.md(
        r"""
        # Yield RCA — synthetic dataset generator (with ground truth)

        This notebook builds semiconductor wafer lots where the `process_step → defect`
        relationship is **real by construction and documented**, so a root-cause tool can be
        *validated*: it must find the cause where one exists and report **no cause** where none
        does. Real fab data cannot do this — it has no answer key.

        - **LOT_A** — strong real cause (Etching at high temperature)
        - **LOT_B** — pure null (defects independent of everything)
        - **LOT_C** — real cause (CMP at high voltage) **plus a confounded decoy** (`current_ma`)
        - **LOT_D** — subtle near-noise cause (weak Lithography effect)

        Move the sliders, click **Generate**, then **Write files**. The answer key is built from
        the *realized* statistics, so it can never claim an effect the data does not contain.
        """
    )
    return


@app.cell
def _(mo):
    mo.md("## Global parameters")
    return


@app.cell
def _(mo):
    seed = mo.ui.number(value=42, start=0, stop=10_000_000, label="Random seed")
    n_per_lot = mo.ui.slider(2000, 50000, step=1000, value=10000, label="Wafers per lot")
    base_rate = mo.ui.slider(0.01, 0.10, step=0.005, value=0.03, label="Baseline defect rate p0")
    mo.vstack([seed, n_per_lot, base_rate])
    return base_rate, n_per_lot, seed


@app.cell
def _(core, mo):
    mo.md("## LOT_A — strong real cause")
    a_step = mo.ui.dropdown(options=core.STEPS, value="Etching", label="Trigger step")
    a_param = mo.ui.dropdown(options=core.NUMERIC_COLS, value="temperature_c", label="Trigger parameter")
    a_quantile = mo.ui.slider(0.50, 0.95, step=0.05, value=0.75, label="'High' quantile (within step)")
    a_lifted = mo.ui.slider(0.05, 0.40, step=0.01, value=0.22, label="Lifted defect rate")
    mo.vstack([a_step, a_param, a_quantile, a_lifted])
    return a_lifted, a_param, a_quantile, a_step


@app.cell
def _(mo):
    mo.md("## LOT_B — pure null")
    b_rate = mo.ui.slider(0.01, 0.10, step=0.005, value=0.05, label="Flat defect rate (independent of all features)")
    b_rate
    return (b_rate,)


@app.cell
def _(core, mo):
    mo.md("## LOT_C — real cause + confounded decoy")
    c_step = mo.ui.dropdown(options=core.STEPS, value="CMP", label="Trigger step")
    c_param = mo.ui.dropdown(options=core.NUMERIC_COLS, value="voltage_v", label="Trigger parameter")
    c_quantile = mo.ui.slider(0.50, 0.95, step=0.05, value=0.75, label="'High' quantile (within step)")
    c_lifted = mo.ui.slider(0.05, 0.40, step=0.01, value=0.17, label="Lifted defect rate")
    c_decoy_corr = mo.ui.slider(0.0, 0.99, step=0.05, value=0.90,
                                label="Decoy: corr(current_ma, voltage_v) within step")
    mo.vstack([c_step, c_param, c_quantile, c_lifted, c_decoy_corr])
    return c_decoy_corr, c_lifted, c_param, c_quantile, c_step


@app.cell
def _(core, mo):
    mo.md("## LOT_D — subtle near-noise cause")
    d_step = mo.ui.dropdown(options=core.STEPS, value="Lithography", label="Trigger step")
    d_param = mo.ui.dropdown(options=core.NUMERIC_COLS, value="pressure_torr", label="Trigger parameter")
    d_quantile = mo.ui.slider(0.50, 0.95, step=0.05, value=0.75, label="'High' quantile (within step)")
    d_lifted = mo.ui.slider(0.04, 0.12, step=0.005, value=0.06, label="Lifted defect rate (keep small)")
    mo.vstack([d_step, d_param, d_quantile, d_lifted])
    return d_lifted, d_param, d_quantile, d_step


@app.cell
def _(mo):
    mo.md("## Decision rule (used by the validators and answer key)")
    alpha = mo.ui.slider(0.01, 0.10, step=0.01, value=0.05, label="Significance level alpha")
    min_lift = mo.ui.slider(0.0, 0.10, step=0.005, value=0.03, label="Minimum practical lift to flag")
    mo.vstack([alpha, min_lift])
    return alpha, min_lift


@app.cell
def _(
    a_lifted, a_param, a_quantile, a_step, alpha, b_rate, base_rate,
    c_decoy_corr, c_lifted, c_param, c_quantile, c_step, core,
    d_lifted, d_param, d_quantile, d_step, min_lift, n_per_lot, seed,
):
    # Assemble a GenParams from the live controls. Cheap; updates reactively.
    params = core.GenParams(
        seed=int(seed.value), n_per_lot=int(n_per_lot.value), base_rate=float(base_rate.value),
        a_step=a_step.value, a_param=a_param.value, a_quantile=float(a_quantile.value), a_lifted=float(a_lifted.value),
        b_rate=float(b_rate.value),
        c_step=c_step.value, c_param=c_param.value, c_quantile=float(c_quantile.value),
        c_lifted=float(c_lifted.value), c_decoy_corr=float(c_decoy_corr.value),
        d_step=d_step.value, d_param=d_param.value, d_quantile=float(d_quantile.value), d_lifted=float(d_lifted.value),
        alpha=float(alpha.value), min_lift=float(min_lift.value),
    )
    return (params,)


@app.cell
def _(mo):
    gen_button = mo.ui.run_button(label="Generate / regenerate dataset")
    gen_button
    return (gen_button,)


@app.cell
def _(core, gen_button, mo, params, pd):
    mo.stop(not gen_button.value, mo.md("> Adjust parameters above, then click **Generate**."))

    lots = core.generate_all(params)                 # {lot_id: (df, meta)}
    frames = [df for (df, _meta) in lots.values()]
    all_lots = pd.concat(frames, ignore_index=True)
    results = [core.validate_lot(df, meta, params) for (df, meta) in lots.values()]
    mo.md(f"Generated **{len(all_lots):,} rows** across {len(lots)} lots.")
    return all_lots, lots, results


@app.cell
def _(mo, pd, results):
    # Compact validation summary: did each lot behave as its ground truth requires?
    rows = []
    for r in results:
        flagged = [s["step"] for s in r["step_scan"] if s["flagged"]]
        mt = r["mechanism_test"]
        rows.append({
            "lot": r["lot_id"],
            "kind": r["kind"],
            "overall_rate": round(r["overall_defect_rate"], 4),
            "chi2_p (step~defect)": f"{r['chi2_step_vs_defect']['p_value']:.2e}",
            "steps_flagged": ", ".join(flagged) if flagged else "none",
            "mechanism_p": (f"{mt['p_value']:.2e}" if mt else "—"),
            "mechanism_lift": (round(mt["abs_lift"], 3) if mt else "—"),
        })
    summary = pd.DataFrame(rows)
    mo.vstack([mo.md("### Validation summary (built from realized stats)"), summary])
    return (summary,)


@app.cell
def _(mo, results):
    # LOT_C confounder detail: naive view flags the decoy; honest logistic rejects it.
    c = next((r for r in results if r["lot_id"] == "LOT_C"), None)
    if c and "confounder_test" in c:
        ct = c["confounder_test"]
        lg = ct["logistic_conditional"]
        msg = mo.md(
            f"""
            ### LOT_C confounder check (the decoy trap)

            - corr(`current_ma`, `voltage_v`) within {ct['scope']}: **{ct['current_voltage_corr']:.2f}**
            - naive marginal `current_ma` vs defect: p = **{ct['naive_marginal_current_p']:.2e}**
              — looks predictive, a naive tool is fooled.
            - logistic `defect ~ voltage_v + current_ma`:
              `voltage_v` coef {lg['voltage_v']['coef']:+.3f} (p={lg['voltage_v']['p_value']:.2e}),
              `current_ma` coef {lg['current_ma']['coef']:+.3f} (p={lg['current_ma']['p_value']:.2e}).
            - **Verdict:** {ct['verdict']}
            """
        )
    else:
        msg = mo.md("")
    msg
    return


@app.cell
def _(mo):
    mo.md("## Write files to disk")
    out_dir = mo.ui.text(value="data_out", label="Output folder")
    write_button = mo.ui.run_button(label="Write CSVs + answer key")
    mo.vstack([out_dir, write_button])
    return out_dir, write_button


@app.cell
def _(Path, all_lots, core, json, lots, mo, out_dir, params, results, write_button):
    mo.stop(not write_button.value, mo.md("> Generate first, then click **Write CSVs + answer key**."))

    out = Path(out_dir.value)
    out.mkdir(parents=True, exist_ok=True)
    for lot_id, (df, _m) in lots.items():
        df.to_csv(out / f"{lot_id.lower()}.csv", index=False)
    all_lots.to_csv(out / "all_lots.csv", index=False)

    key = {
        "generator_params": {f: getattr(params, f) for f in params.__dataclass_fields__},
        "decision_rule": f"flag a group only if BH-adjusted p < {params.alpha} AND |lift| >= {params.min_lift}",
        "lots": results,
    }
    (out / "answer_key.json").write_text(json.dumps(key, indent=2, default=str))
    written = [str(p) for p in sorted(out.glob("*"))]
    mo.md("Wrote:\n\n" + "\n".join(f"- `{w}`" for w in written))
    return


@app.cell
def _(mo):
    mo.md(
        r"""
        ---
        ## Optional: honest analysis of REAL data (SECOM)

        This section loads the real SECOM dataset (Kaggle `paresh2047/uci-semcom`) **as-is**.
        SECOM has 591 anonymized sensor features and a pass/fail label — and **no process_step**.
        This notebook will **not** invent one: grafting a fake `process_step` onto real rows would
        manufacture false stage-level findings. Instead it screens every real feature against the
        fail label with **Benjamini-Hochberg FDR correction** — the honest way to handle 590+
        simultaneous tests — and reports how many survive.

        Download `uci-secom.csv` from Kaggle yourself, then point the path below at it.
        """
    )
    return


@app.cell
def _(mo):
    secom_path = mo.ui.text(value="uci-secom.csv", label="Path to downloaded SECOM csv")
    secom_button = mo.ui.run_button(label="Run honest SECOM screen")
    mo.vstack([secom_path, secom_button])
    return secom_button, secom_path


@app.cell
def _(Path, core, mo, np, pd, secom_button, secom_path):
    mo.stop(not secom_button.value, mo.md("> Set the SECOM path, then click **Run honest SECOM screen**."))
    mo.stop(not Path(secom_path.value).exists(),
            mo.md(f"> File not found: `{secom_path.value}` — download `uci-secom.csv` from Kaggle first."))

    raw = pd.read_csv(secom_path.value)

    # locate target: a Pass/Fail column, else the last column
    target_col = next((c for c in raw.columns if str(c).strip().lower() in
                       ("pass/fail", "pass_fail", "passfail", "target", "label")), raw.columns[-1])
    y_raw = raw[target_col]
    # SECOM labels are typically -1 (pass) / 1 (fail); map fail -> 1
    y = (y_raw == y_raw.max()).astype(int).to_numpy()

    # features: numeric columns only, drop obvious id/time columns and the target
    drop = {target_col}
    for c in raw.columns:
        if str(c).strip().lower() in ("time", "timestamp", "id", "wafer_id"):
            drop.add(c)
    feats = raw.drop(columns=list(drop), errors="ignore").apply(pd.to_numeric, errors="coerce")

    # clean: drop all-NaN / zero-variance columns, median-impute the rest
    feats = feats.dropna(axis=1, how="all")
    nunique = feats.nunique(dropna=True)
    feats = feats.loc[:, nunique > 1]
    feats = feats.fillna(feats.median(numeric_only=True))

    # per-feature Welch t-test: fail group vs pass group
    from scipy import stats as _st
    fail = feats[y == 1]
    passg = feats[y == 0]
    pvals = []
    for col in feats.columns:
        a = fail[col].to_numpy()
        b = passg[col].to_numpy()
        if a.std() == 0 and b.std() == 0:
            pvals.append(1.0)
        else:
            pvals.append(float(_st.ttest_ind(a, b, equal_var=False, nan_policy="omit").pvalue))
    pvals = np.array(pvals)
    padj = core.benjamini_hochberg(pvals)

    n_fail = int(y.sum())
    n_total = len(y)
    survivors = int((padj < 0.05).sum())
    table = (pd.DataFrame({"feature": feats.columns, "p_raw": pvals, "p_adj_BH": padj})
             .sort_values("p_adj_BH").head(15).reset_index(drop=True))

    note = mo.md(
        f"""
        ### SECOM honest screen

        - rows: **{n_total}**, failures: **{n_fail}** ({n_fail/n_total:.1%}) — note the class imbalance
        - features tested: **{feats.shape[1]}** (after dropping all-NaN / zero-variance columns)
        - features surviving **BH FDR < 0.05**: **{survivors}**
        - target column detected: `{target_col}`; **no `process_step` was invented**

        Top features by adjusted p-value (these are *associations*, not proven causes):
        """
    )
    mo.vstack([note, table])
    return
