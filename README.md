# responsibility

A small GitHub-ready toolbox for **excited-state analysis workflows**.

At the moment, this repository contains one working utility:

- **Multiwfn state-to-state spectrum tool**
  - batch-runs Multiwfn on paired `.fchk + .log` files
  - extracts transition dipole information from `transdipmom.txt`
  - builds **state-resolved SS / TT spectra**
  - groups transitions by initial-state family such as `S1->Sn`, `T2->Tn`
  - exports figures, transition tables, family-resolved spectrum data, and logs

This repository is designed as a **collection repo** rather than a single-purpose repo. That means you can continue adding future tools here, for example:

- QM/MM cluster analysis wrappers
- post-processing scripts for excited-state workflows
- plotting utilities for state-resolved spectra or transition statistics

---

## Current repository structure

```text
responsibility/
├── README.md
├── requirements.txt
└── scripts/
    └── multiwfn_state_spectrum_tool.py
```

---

## Current tool: Multiwfn state-to-state spectrum tool

### What it does

This script automates the following workflow:

1. Run **Multiwfn** on each matched `*.fchk + *.log` pair.
2. Export `transdipmom.txt`.
3. Parse transition data from Multiwfn output.
4. Assign each job as `SS`, `TT`, or infer it when running in `BOTH` mode.
5. Keep only the transitions intended for plotting.
6. Build family-resolved spectra with Gaussian broadening in energy space.
7. Export figures, Excel files, and logs.

### Supported modes

- `SS`: singlet-to-singlet excited-state transitions
- `TT`: triplet-to-triplet excited-state transitions
- `BOTH`: process both kinds together, with job type inferred from file name or `JOB_KIND_MAP`

### Input requirements

Each job must have a matched pair in the same work directory:

```text
molecule_1.fchk
molecule_1.log
molecule_2.fchk
molecule_2.log
...
```

The stem must match exactly.

### Output content

By default, the script writes a dedicated output folder under the work directory:

```text
state_spectra_output/
├── excel/
│   └── <molecule>_<kind>_spectrum_data.xlsx
├── figures/
│   └── <molecule>_<kind>_spectrum.png
├── logs/
│   ├── run.log
│   ├── run_summary.csv
│   ├── run_summary.xlsx
│   └── multiwfn/
├── raw_transdip_txt/
│   └── <molecule>_transdipmom.txt
└── transitions/
    └── <molecule>_transitions.xlsx
```

### Excel sheets that are actually exported

#### `transitions/<molecule>_transitions.xlsx`

- `raw_transitions`
- `annotated_transitions`
- `plot_transitions`

#### `excel/<molecule>_<kind>_spectrum_data.xlsx`

- `stick_data`
- `curve_data`
- `family_summary`

---

## Important interpretation note

This tool does **not** infer spin labels directly from the raw Multiwfn table itself. It uses the selected job type (`SS` or `TT`) to label indices.

In the current implementation:

- for `SS`: index `0 -> S0`, index `n -> Sn`
- for `TT`: index `0 -> REF`, index `n -> Tn`

And only **true excited-to-excited** transitions are plotted.

That means the plotted spectrum is intended for transitions such as:

- `S1 -> S2/S3/...`
- `S2 -> S3/S4/...`
- `T1 -> T2/T3/...`
- `T2 -> T3/T4/...`

It does **not** plot:

- `S0 -> Sn`
- `REF -> Tn`
- inter-multiplicity transitions such as `S -> T` or `T -> S`

This point is worth stating clearly in GitHub documentation, because it is exactly the kind of detail that later users will otherwise misunderstand.

---

## Installation

### 1. Python environment

Recommended: **Python 3.9+**

Install dependencies:

```bash
pip install -r requirements.txt
```

### 2. Multiwfn

Install Multiwfn separately and make sure you know the path to `Multiwfn.exe`.

You can either:

- pass it explicitly with `--multiwfn`, or
- set an environment variable named `MULTIWFN_EXE`

Example on Windows PowerShell:

```powershell
$env:MULTIWFN_EXE = "C:\\Path\\To\\Multiwfn.exe"
```

---

## Usage

### Recommended command-line usage

From the repository root:

```bash
python scripts/multiwfn_state_spectrum_tool.py \
  --work-dir "D:\\your\\job_folder" \
  --multiwfn "C:\\Path\\To\\Multiwfn.exe" \
  --mode BOTH \
  --wl-min 300 \
  --wl-max 4200 \
  --wl-step 1 \
  --sigma-ev 0.10 \
  --keep-raw-txt
```

### Useful options

- `--mode SS|TT|BOTH`
- `--show-multiwfn`
- `--keep-raw-txt`
- `--output-to-workdir-root`
- `--output-root-name state_spectra_output`

### Example: keep outputs inside a named folder

```bash
python scripts/multiwfn_state_spectrum_tool.py \
  --work-dir "D:\\calc\\spectra_jobs" \
  --multiwfn "C:\\Path\\To\\Multiwfn.exe" \
  --mode TT \
  --output-root-name "state_spectra_output"
```

---

## How `BOTH` mode decides whether a file is SS or TT

When `--mode BOTH` is used, the script tries to infer job type from the file stem.

It looks for patterns such as:

- TT-like: `t1`, `tt`, `triplet`
- SS-like: `s0`, `ss`, `singlet`

If this is not reliable for your files, edit `JOB_KIND_MAP` in the script and define the mapping manually.

Example:

```python
JOB_KIND_MAP = {
    "mol1_s0": "SS",
    "mol1_t1": "TT",
}
```

This is the safest choice when your naming convention is fixed and you want reproducible behavior.

---

## What is already good about this tool

Compared with a one-off local plotting script, this version is already suitable for a GitHub repo because it has:

- command-line arguments
- structured output folders
- log files and run summaries
- batch processing of many jobs
- clear separation between raw transitions, plotting transitions, and spectrum data

That makes it a decent first module in a larger excited-state analysis toolbox.

---

## Recommended future additions

When you add more tools to this repository later, a clean direction would be:

1. keep each workflow as an independent script under `scripts/`
2. keep one top-level README for the whole repository
3. add one short usage section for each tool
4. only split into subpackages when the repo becomes clearly multi-module

For your next planned feature, a natural next addition would be something like:

```text
scripts/qmmm_cluster_analysis.py
```

That will fit very naturally into the current repository layout.

---

## Citation / acknowledgement

If you use this repository in a paper or internal workflow note, please cite the underlying computational tools appropriately, especially **Multiwfn**.

