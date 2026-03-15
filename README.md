# responsibility

A lightweight and extensible toolbox for **excited-state analysis workflows**.

This repository is intended as a **collection of practical utilities** for post-processing and analysis in excited-state calculations, rather than a single-purpose project. It is designed to grow over time as new workflow wrappers and analysis scripts are added.

At present, the repository includes one working utility:

- **Multiwfn state-to-state spectrum tool**
  - batch-runs Multiwfn on matched `.fchk` and `.log` files
  - extracts transition dipole data from `transdipmom.txt`
  - builds **state-resolved SS / TT spectra**
  - groups transitions by initial-state family such as `S1→Sn` and `T2→Tn`
  - exports figures, transition tables, spectrum data, and logs

Planned future additions may include:

- QM/MM cluster analysis wrappers
- post-processing tools for excited-state workflows
- plotting utilities for transition statistics and state-resolved spectra
- HOMO–LUMO and excited-state charge-transfer analysis helpers

---

## Scope of the repository

This repository is structured as a **collection repository** for excited-state analysis utilities.

Rather than focusing on only one script, it is intended to host multiple reusable tools that support practical post-processing workflows in computational excited-state studies. The current Multiwfn-based spectrum tool serves as the first working module, while future modules may extend the repository toward a broader analysis environment covering orbital analysis, charge-transfer characterization, and QM/MM-based post-processing.

This organization is intentional: keeping each workflow as an independent script under `scripts/` makes the repository easier to maintain, extend, and document as new tools are added.

---

## Repository layout

```text
responsibility/
├── README.md
├── requirements.txt
└── scripts/
    └── multiwfn_state_spectrum_tool.py
```

---

## Current tool

### Multiwfn state-to-state spectrum tool

This script automates a Multiwfn-based workflow for building **excited-state-to-excited-state spectra** from paired Gaussian-style outputs.

### Main features

- batch processing of multiple jobs
- automatic matching of `.fchk` and `.log` files
- Multiwfn execution from Python
- parsing of `transdipmom.txt`
- support for **SS**, **TT**, or mixed processing
- family-resolved spectral construction with Gaussian broadening
- structured export of tables, plots, and logs

---

## What the tool does

For each matched `*.fchk + *.log` pair, the script performs the following steps:

1. Run **Multiwfn**
2. Export `transdipmom.txt`
3. Parse transition information from the Multiwfn output
4. Assign the job type as `SS`, `TT`, or infer it in `BOTH` mode
5. Filter transitions according to the plotting rules
6. Construct family-resolved spectra in energy space using Gaussian broadening
7. Export figures, Excel files, raw text outputs, and run logs

---

## Supported modes

- `SS` — singlet excited-state to singlet excited-state transitions
- `TT` — triplet excited-state to triplet excited-state transitions
- `BOTH` — process both types together, with job type inferred from file names or from a manual mapping

---

## Input requirements

Each calculation must provide a matched pair of files in the same working directory:

```text
molecule_1.fchk
molecule_1.log
molecule_2.fchk
molecule_2.log
...
```

The filename stem must match exactly.

---

## Output structure

By default, the script writes results to a dedicated output directory under the working directory:

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

### Exported Excel sheets

#### `transitions/<molecule>_transitions.xlsx`

- `raw_transitions`
- `annotated_transitions`
- `plot_transitions`

#### `excel/<molecule>_<kind>_spectrum_data.xlsx`

- `stick_data`
- `curve_data`
- `family_summary`

---

## Important note on state labeling and plotting rules

This tool does **not** infer spin labels directly from the raw Multiwfn transition table. Instead, it assigns state labels based on the selected job type (`SS` or `TT`).

In the current implementation:

- for `SS`: index `0 → S0`, index `n → Sn`
- for `TT`: index `0 → REF`, index `n → Tn`

Only **true excited-to-excited** transitions are retained for spectral plotting.

That means the plotted spectra are intended for transitions such as:

- `S1 → S2/S3/...`
- `S2 → S3/S4/...`
- `T1 → T2/T3/...`
- `T2 → T3/T4/...`

The following transitions are **not** plotted:

- `S0 → Sn`
- `REF → Tn`
- inter-multiplicity transitions such as `S → T` or `T → S`

This behavior is intentional and should be kept in mind when interpreting the generated spectra.

---

## Installation

### 1. Python environment

Recommended: **Python 3.9+**

Install dependencies:

```bash
pip install -r requirements.txt
```

### 2. Multiwfn

Install **Multiwfn** separately and make sure the path to `Multiwfn.exe` is available.

You can either:

- pass it explicitly with `--multiwfn`, or
- define an environment variable named `MULTIWFN_EXE`

Example on Windows PowerShell:

```powershell
$env:MULTIWFN_EXE = "C:\\Path\\To\\Multiwfn.exe"
```

---

## Usage

### Basic example

Run from the repository root:

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

### Example: custom output folder name

```bash
python scripts/multiwfn_state_spectrum_tool.py \
  --work-dir "D:\\calc\\spectra_jobs" \
  --multiwfn "C:\\Path\\To\\Multiwfn.exe" \
  --mode TT \
  --output-root-name "state_spectra_output"
```

---

## How `BOTH` mode determines SS vs TT jobs

When `--mode BOTH` is used, the script attempts to infer the job type from the filename stem.

Patterns currently checked include:

- TT-like: `t1`, `tt`, `triplet`
- SS-like: `s0`, `ss`, `singlet`

If this is not reliable for your naming scheme, define the mapping manually in `JOB_KIND_MAP` inside the script.

Example:

```python
JOB_KIND_MAP = {
    "mol1_s0": "SS",
    "mol1_t1": "TT",
}
```

For fixed naming conventions, a manual mapping is the safest and most reproducible choice.

---

## Design considerations

The current implementation is designed to be more reusable than a one-off local plotting script. It provides:

- command-line execution
- batch processing for multiple jobs
- structured output directories
- run logs and summary files
- explicit separation between raw transitions, annotated transitions, and plotted transitions
- reproducible export of spectrum figures and data tables

These design choices make the tool easier to maintain and extend as part of a broader excited-state analysis toolbox.

---

## Future directions

This repository is expected to grow gradually as additional workflow modules become available.

Likely future additions include:

- QM/MM cluster analysis wrappers
- HOMO–LUMO analysis helpers
- excited-state charge-transfer and IFCT analysis tools
- additional plotting and reporting utilities for excited-state calculations

A natural example of a future addition would be:

```text
scripts/qmmm_cluster_analysis.py
```

As more tools are added, the repository can remain organized by keeping each workflow self-contained under `scripts/`, while documenting them centrally through the top-level `README.md`.

---

## Acknowledgement

If you use this repository in academic work or internal workflow documentation, please make sure to properly acknowledge the underlying computational software, especially **Multiwfn**.

---

## Status

This repository is under active development.

The current version is already usable for Multiwfn-based SS/TT state-resolved spectrum analysis, and additional workflow tools will be added over time.
