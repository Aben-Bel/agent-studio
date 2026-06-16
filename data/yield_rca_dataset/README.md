# Yield RCA — validation dataset + generator

A synthetic semiconductor wafer dataset built to **validate a root-cause-analysis tool**,
plus a marimo notebook that regenerates it with toggleable parameters, plus an honest
loader for the real SECOM dataset.

## Why synthetic (and why that is the honest choice here)

A root-cause tool can only be *proven correct* against data where the true cause is known.
Real fab data never ships with that answer key. So this dataset injects **known**
`process_step → defect` relationships and documents them, alongside lots where the
relationship is **provably absent**. The answer key is computed from the *realized*
statistics of the generated data, so it cannot claim an effect the data does not contain.

Grafting a fake `process_step` column onto real data (e.g. SECOM) is **not** done here:
that would manufacture false stage-level findings dressed in a real dataset's credibility.
The SECOM section analyses the real data as-is, with no invented columns.

## What is in `data/`

| File | Contents |
|---|---|
| `lot_a.csv` | Strong real cause: Etching at high `temperature_c`. Tool must flag it. |
| `lot_b.csv` | Pure null: defects independent of everything. Tool must report no cause. |
| `lot_c.csv` | Real cause (CMP at high `voltage_v`) + confounded decoy (`current_ma`). Tool must flag voltage and reject current. |
| `lot_d.csv` | Subtle near-noise cause (weak Lithography effect). Tool should report it as weak/uncertain, not a strong cause. |
| `all_lots.csv` | All four lots concatenated. |
| `answer_key.md` | Human-readable ground truth + realized statistics. |
| `answer_key.json` | Same, machine-readable, for automated test assertions. |

Columns (match the common Kaggle wafer schema): `lot_id, wafer_id, process_step,
temperature_c, pressure_torr, gas_flow_sccm, etch_rate_nm_min, voltage_v, current_ma,
defect_label` where `defect_label` is `1` = defective, `0` = good.

Default size is 10,000 wafers per lot (40,000 rows). Raise **Wafers per lot** in the
notebook for a much larger CSV.

## Expected tool behavior (the acceptance bar)

- **LOT_A:** identify Etching + high temperature; report the test statistic and a large effect size.
- **LOT_B:** report **no statistically significant association**; name **no** root cause.
- **LOT_C:** identify CMP + high voltage; report `current_ma` as **confounded / not independently predictive**.
- **LOT_D:** report a weak/borderline effect with a wide interval; do not present it as a strong cause.

The numbers behind each (chi-square, two-proportion test, Wilson CIs, BH-corrected step
scan, and for LOT_C a logistic confounder check) are in `answer_key.md`.

## Run / regenerate

```bash
python -m venv env && source env/bin/activate      # Windows: env\Scripts\activate
pip install -r requirements.txt
marimo edit generate_dataset.py                     # interactive: toggle params, Generate, Write files
# or headless:
marimo run generate_dataset.py
```

The notebook keeps all generation logic in `yield_gen_core.py` (same module used to build
the shipped `data/`), so the interactive output and the shipped files come from one source
of truth.

## Optional: real SECOM data (honest screen)

SECOM (Kaggle `paresh2047/uci-semcom`) is real fab data: ~1,567 wafers, ~591 anonymized
sensor features, pass/fail label, heavily imbalanced, with no `process_step`. Download
`uci-secom.csv` yourself (it cannot be bundled), set its path in the last notebook section,
and click **Run honest SECOM screen**. It cleans the data (drops zero-variance/all-NaN
columns, median-imputes), runs a per-feature test against the fail label, applies
**Benjamini-Hochberg FDR** across all ~590 tests, and reports how many features survive —
with no invented stage column. Confirm the dataset's license on its Kaggle page before any
commercial-context use.

## Dependencies

`numpy`, `pandas`, `scipy`, `marimo`. The shipped data was generated with numpy/pandas/scipy
only; `marimo` is needed only to run the notebook interactively.
