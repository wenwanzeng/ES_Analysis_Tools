
"""
================================================================================
      MULTIWFN STATE-RESOLVED SPECTRUM TOOL (SS / TT / BOTH)
================================================================================

What this tool does
-------------------
1. Calls Multiwfn to export transition dipole information (transdipmom.txt)
2. Saves raw intermediate files and detailed logs
3. Parses the transition table from Multiwfn
4. Assigns SS / TT state labels based on the job type
5. Builds family-resolved spectra:
      SS: S1->Sn, S2->Sn, ...
      TT: T1->Tn, T2->Tn, ...
6. Outputs:
      - spectrum figures (curve + stick lines)
      - Excel files with raw transitions, annotated transitions, plot transitions
      - Excel files with family-resolved curve data and stick data
      - Multiwfn stdout/stderr logs
      - optional raw transdipmom.txt copies

Important note
--------------
This script does NOT infer singlet/triplet labels from transdipmom.txt itself.
Instead:
- SS jobs are interpreted as:
      index 0 -> S0
      index n -> Sn
- TT jobs are interpreted as:
      index 0 -> REF (reference state)
      index n -> Tn

Therefore, if MODE="BOTH", file naming must allow the script to infer whether
each job is SS or TT. You can customize JOB_KIND_MAP or infer_job_kind().
================================================================================
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import subprocess
import traceback
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Literal

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


# ============================= USER CONFIGURATION =============================
WORK_DIR = Path.cwd()
MWFN_EXE = Path(os.environ.get("MULTIWFN_EXE", "Multiwfn.exe"))

# SS / TT / BOTH
MODE: Literal["SS", "TT", "BOTH"] = "BOTH"

# Plot range
WAVELENGTH_MIN_NM = 500.0
WAVELENGTH_MAX_NM = 4200.0
WAVELENGTH_STEP_NM = 1.0

# Gaussian width in eV
GAUSSIAN_WIDTH_EV = 0.10

# Multiwfn / output options
QUIET = True
SAVE_RAW_TRANSDIP_TXT = True
OUTPUT_TO_WORKDIR_ROOT = False   # True -> output directly under WORK_DIR
OUTPUT_ROOT_NAME = "state_spectra_output"  # only used if OUTPUT_TO_WORKDIR_ROOT=False

# If MODE="BOTH", you can explicitly map file stem -> SS/TT here
# Example:
# JOB_KIND_MAP = {
#     "s0_job1": "SS",
#     "t1_job2": "TT",
# }
JOB_KIND_MAP: dict[str, Literal["SS", "TT"]] = {}
# ============================================================================


VALID_MODES = {"SS", "TT", "BOTH"}
H2EV = 27.211386245988
EV2NM = 1239.84193


@dataclass
class MultiwfnJob:
    name: str
    fchk: Path
    log: Path
    kind: Literal["SS", "TT"]


@dataclass
class JobResult:
    molecule: str
    kind: str
    status: str = "FAILED"
    total_raw_transitions: int = 0
    total_plot_transitions: int = 0
    family_count: int = 0
    multiwfn_returncode: int | None = None
    multiwfn_log_file: str = ""
    error_message: str = ""


def build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract SS/TT transitions via Multiwfn and build state-resolved spectra."
    )
    parser.add_argument("--work-dir", type=Path, default=WORK_DIR, help="Directory containing .fchk/.log pairs")
    parser.add_argument("--multiwfn", type=Path, default=MWFN_EXE, help="Path to Multiwfn executable")
    parser.add_argument("--mode", type=str, default=MODE, choices=sorted(VALID_MODES), help="SS / TT / BOTH")
    parser.add_argument("--wl-min", type=float, default=WAVELENGTH_MIN_NM, help="Minimum wavelength (nm)")
    parser.add_argument("--wl-max", type=float, default=WAVELENGTH_MAX_NM, help="Maximum wavelength (nm)")
    parser.add_argument("--wl-step", type=float, default=WAVELENGTH_STEP_NM, help="Wavelength step (nm)")
    parser.add_argument("--sigma-ev", type=float, default=GAUSSIAN_WIDTH_EV, help="Gaussian width in eV")
    parser.add_argument("--show-multiwfn", action="store_true", help="Show Multiwfn stdout/stderr in terminal")
    parser.add_argument("--keep-raw-txt", action="store_true", help="Keep raw transdipmom.txt copies")
    parser.add_argument("--output-to-workdir-root", action="store_true", help="Write output folders directly under the work directory")
    parser.add_argument("--output-root-name", type=str, default=OUTPUT_ROOT_NAME, help="Name of the output root folder when not writing directly into the work directory")
    return parser


def safe_name(text: str, maxlen: int = 120) -> str:
    text = re.sub(r'[<>:"/\\|?*]+', "_", str(text)).strip()
    return text[:maxlen] if text else "NONAME"


def make_multiwfn_transdip_input(fchk_path: str, log_path: str) -> str:
    # IMPORTANT:
    # This menu sequence matches the workflow you were using:
    #   load fchk -> electron excitation analysis -> transition dipole output -> load log -> export
    return f"{fchk_path}\n18\n5\n{log_path}\n2\n0\n"


def infer_job_kind(name: str, global_mode: str) -> Literal["SS", "TT"]:
    if name in JOB_KIND_MAP:
        return JOB_KIND_MAP[name]

    if global_mode in {"SS", "TT"}:
        return global_mode  # type: ignore[return-value]

    n = name.lower()

    tt_patterns = [
        r"(^|[_\-])t1([_\-]|$)",
        r"(^|[_\-])tt([_\-]|$)",
        r"triplet",
    ]
    ss_patterns = [
        r"(^|[_\-])s0([_\-]|$)",
        r"(^|[_\-])ss([_\-]|$)",
        r"singlet",
    ]

    for pat in tt_patterns:
        if re.search(pat, n):
            return "TT"
    for pat in ss_patterns:
        if re.search(pat, n):
            return "SS"

    raise ValueError(
        f"Cannot infer job kind for file '{name}'. "
        f"Please set MODE='SS' or MODE='TT', or add the file stem to JOB_KIND_MAP."
    )


class SpectrumTool:
    def __init__(
        self,
        work_dir: Path,
        multiwfn_exe: Path,
        mode: Literal["SS", "TT", "BOTH"],
        wl_min_nm: float,
        wl_max_nm: float,
        wl_step_nm: float,
        sigma_ev: float,
        quiet: bool,
        keep_raw_txt: bool,
        output_to_workdir_root: bool,
        output_root_name: str,
    ):
        self.work_dir = Path(work_dir)
        self.multiwfn_exe = Path(multiwfn_exe)
        self.mode = mode
        self.wl_min_nm = wl_min_nm
        self.wl_max_nm = wl_max_nm
        self.wl_step_nm = wl_step_nm
        self.sigma_ev = sigma_ev
        self.quiet = quiet
        self.keep_raw_txt = keep_raw_txt
        self.output_to_workdir_root = output_to_workdir_root
        self.output_root_name = output_root_name

        self.output_root = self.work_dir if self.output_to_workdir_root else (self.work_dir / self.output_root_name)

        self.raw_txt_dir = self.output_root / "raw_transdip_txt"
        self.transition_dir = self.output_root / "transitions"
        self.figure_dir = self.output_root / "figures"
        self.data_dir = self.output_root / "excel"
        self.log_dir = self.output_root / "logs"
        self.multiwfn_log_dir = self.log_dir / "multiwfn"

        self.logger = logging.getLogger("spectrum_tool")

    def validate(self) -> None:
        if self.mode not in VALID_MODES:
            raise SystemExit(f"[ERROR] Invalid mode: {self.mode}")
        if not self.work_dir.exists() or not self.work_dir.is_dir():
            raise SystemExit(f"[ERROR] WORK_DIR not found: {self.work_dir}")
        if not self.multiwfn_exe.exists() or not self.multiwfn_exe.is_file():
            raise SystemExit(f"[ERROR] Multiwfn executable not found: {self.multiwfn_exe}")
        if self.wl_min_nm <= 0 or self.wl_max_nm <= self.wl_min_nm:
            raise SystemExit("[ERROR] Invalid wavelength range")
        if self.wl_step_nm <= 0:
            raise SystemExit("[ERROR] Wavelength step must be positive")
        if self.sigma_ev <= 0:
            raise SystemExit("[ERROR] Gaussian width must be positive")
        if not self.output_to_workdir_root and not str(self.output_root_name).strip():
            raise SystemExit("[ERROR] output_root_name cannot be empty")

    def prepare_output_dirs(self) -> None:
        for path in [
            self.output_root,
            self.raw_txt_dir,
            self.transition_dir,
            self.figure_dir,
            self.data_dir,
            self.log_dir,
            self.multiwfn_log_dir,
        ]:
            path.mkdir(parents=True, exist_ok=True)

    def setup_logging(self) -> None:
        self.logger.setLevel(logging.INFO)
        self.logger.handlers.clear()

        fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

        file_handler = logging.FileHandler(self.log_dir / "run.log", encoding="utf-8")
        file_handler.setFormatter(fmt)
        self.logger.addHandler(file_handler)

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(fmt)
        self.logger.addHandler(console_handler)

    def collect_jobs(self) -> list[MultiwfnJob]:
        jobs: list[MultiwfnJob] = []
        for fchk in sorted(self.work_dir.glob("*.fchk")):
            name = fchk.stem
            log = self.work_dir / f"{name}.log"
            if not log.exists():
                self.logger.warning("[SKIP] Missing .log for %s", name)
                continue

            kind = infer_job_kind(name, self.mode)
            jobs.append(MultiwfnJob(name=name, fchk=fchk, log=log, kind=kind))

        return jobs

    def run_multiwfn_transdip(self, job: MultiwfnJob) -> tuple[Path, int, Path]:
        """
        Run Multiwfn and return:
            (transdip_path, returncode, multiwfn_log_path)
        """
        input_text = make_multiwfn_transdip_input(
            str(job.fchk.resolve()),
            str(job.log.resolve()),
        )

        # Ensure settings.ini can be found, so Multiwfn won't insert the
        # unexpected "Press ENTER to continue" step.
        env = os.environ.copy()
        env["Multiwfnpath"] = str(self.multiwfn_exe.parent)

        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

        # Remove stale transdip file first
        transdip = self.work_dir / "transdipmom.txt"
        transdip.unlink(missing_ok=True)

        completed = subprocess.run(
            [str(self.multiwfn_exe)],
            input=input_text,
            text=True,
            cwd=self.work_dir,
            capture_output=True,
            check=False,
            env=env,
            creationflags=creationflags,
        )

        multiwfn_log_path = self.multiwfn_log_dir / f"{safe_name(job.name)}_multiwfn_stdout_stderr.txt"
        multiwfn_log_text = (
            f"# Return code: {completed.returncode}\n\n"
            f"# STDOUT\n{completed.stdout}\n\n"
            f"# STDERR\n{completed.stderr}\n"
        )
        multiwfn_log_path.write_text(multiwfn_log_text, encoding="utf-8", errors="ignore")

        if not self.quiet:
            if completed.stdout:
                print(completed.stdout)
            if completed.stderr:
                print(completed.stderr)

        if not transdip.exists():
            raise RuntimeError(
                f"Multiwfn did not generate transdipmom.txt for {job.name}. "
                f"See log: {multiwfn_log_path}"
            )

        if self.keep_raw_txt:
            saved = self.raw_txt_dir / f"{safe_name(job.name)}_transdipmom.txt"
            saved.write_bytes(transdip.read_bytes())

        return transdip, completed.returncode, multiwfn_log_path

    @staticmethod
    def parse_transdip(path: Path) -> pd.DataFrame:
        """
        Parse Multiwfn transdipmom.txt into a raw transition table.

        This function does NOT try to infer singlet/triplet labels from the file.
        """
        if not path.exists():
            return pd.DataFrame()

        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        records: list[dict[str, object]] = []

        section = None
        for line in lines:
            if "Transition electric dipole moment between ground state (0) and excited states" in line:
                section = "ground_to_excited"
                continue

            if "Transition electric dipole moment between excited states" in line:
                section = "excited_to_excited"
                continue

            if section and re.match(r"\s*\d+\s+\d+", line):
                parts = line.split()
                try:
                    i_idx = int(parts[0])
                    j_idx = int(parts[1])
                    x = float(parts[2])
                    y = float(parts[3])
                    z = float(parts[4])
                    delta_e_ev = float(parts[5])
                    osc_strength = float(parts[6])
                except (IndexError, ValueError):
                    continue

                records.append(
                    {
                        "section": section,
                        "i_index": i_idx,
                        "j_index": j_idx,
                        "mu_x_au": x,
                        "mu_y_au": y,
                        "mu_z_au": z,
                        "delta_e_ev": delta_e_ev,
                        "delta_e_hartree": delta_e_ev / H2EV,
                        "wavelength_nm": (EV2NM / delta_e_ev) if delta_e_ev > 0 else np.nan,
                        "oscillator_strength": osc_strength,
                    }
                )

        return pd.DataFrame(records)

    @staticmethod
    def state_label_from_index(idx: int, kind: Literal["SS", "TT"]) -> str:
        if kind == "SS":
            return "S0" if idx == 0 else f"S{idx}"
        return "REF" if idx == 0 else f"T{idx}"

    def annotate_transitions(self, df: pd.DataFrame, kind: Literal["SS", "TT"]) -> pd.DataFrame:
        if df.empty:
            return df.copy()

        out = df.copy()
        out["job_kind"] = kind
        out["initial_state"] = out["i_index"].map(lambda x: self.state_label_from_index(int(x), kind))
        out["final_state"] = out["j_index"].map(lambda x: self.state_label_from_index(int(x), kind))
        out["kind"] = kind
        spin_symbol = "S" if kind == "SS" else "T"
        out["family"] = out["initial_state"] + f"-{spin_symbol}n"
        return out

    def select_plot_transitions(self, df: pd.DataFrame, kind: Literal["SS", "TT"]) -> pd.DataFrame:
        """
        SS:
            only keep true excited-state-to-excited-state transitions:
            S1->Sn, S2->Sn, ...

        TT:
            only keep true excited-state-to-excited-state transitions:
            T2->Tn, T3->Tn, ...
            (do NOT include section == ground_to_excited)
        """
        if df.empty:
            return df.copy()

        mask = (
            (df["section"] == "excited_to_excited") &
            (df["j_index"] > df["i_index"]) &
            (df["i_index"] >= 1)
        )

        out = df.loc[mask].copy()
        out = out[out["delta_e_ev"] > 0].copy()
        out = out[out["oscillator_strength"] >= 0].copy()
        return out

    def build_wavelength_grid(self) -> np.ndarray:
        return np.arange(self.wl_min_nm, self.wl_max_nm + 1e-12, self.wl_step_nm)

    def gaussian_spectrum_from_lines(
        self,
        transitions: pd.DataFrame,
        wavelengths_nm: np.ndarray,
    ) -> np.ndarray:
        """
        Build spectrum using Gaussian broadening in energy space
        and evaluate it on the user-requested wavelength grid.
        """
        if transitions.empty:
            return np.zeros_like(wavelengths_nm, dtype=float)

        line_E = transitions["delta_e_ev"].to_numpy(dtype=float)
        line_f = transitions["oscillator_strength"].to_numpy(dtype=float)

        eval_E = EV2NM / wavelengths_nm
        # shape: (n_wavelength, n_lines)
        diff = eval_E[:, None] - line_E[None, :]
        intensity = np.sum(line_f[None, :] * np.exp(-0.5 * (diff / self.sigma_ev) ** 2), axis=1)
        return intensity

    def build_family_spectra(self, plot_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
        """
        Returns:
            curve_df: wavelength + family columns
            summary_df: one-row-per-family summary
        """
        wavelengths_nm = self.build_wavelength_grid()
        family_names = sorted(plot_df["family"].unique(), key=self.family_sort_key)

        curve_df = pd.DataFrame({"wavelength_nm": wavelengths_nm})
        summary_records = []

        for family in family_names:
            family_transitions = plot_df[plot_df["family"] == family].copy()
            family_curve = self.gaussian_spectrum_from_lines(family_transitions, wavelengths_nm)
            curve_df[family] = family_curve

            summary_records.append(
                {
                    "family": family,
                    "transition_count": len(family_transitions),
                    "max_oscillator_strength": float(family_transitions["oscillator_strength"].max()) if not family_transitions.empty else 0.0,
                    "max_curve_intensity": float(np.max(family_curve)) if len(family_curve) else 0.0,
                }
            )

        return curve_df, pd.DataFrame(summary_records)

    @staticmethod
    def family_sort_key(text: str) -> tuple[int, str]:
        # S1-Sn, S2-Sn, ... or T1-Tn, T2-Tn, ...
        m = re.fullmatch(r"\s*([ST])(\d+)-[ST]n\s*", str(text))
        if m:
            return (int(m.group(2)), str(text))
        return (999999, str(text))

    def export_transition_workbook(
        self,
        molecule: str,
        raw_df: pd.DataFrame,
        annotated_df: pd.DataFrame,
        plot_df: pd.DataFrame,
    ) -> Path:
        out_xlsx = self.transition_dir / f"{safe_name(molecule)}_transitions.xlsx"
        with pd.ExcelWriter(out_xlsx, engine="openpyxl") as writer:
            raw_df.to_excel(writer, sheet_name="raw_transitions", index=False)
            annotated_df.to_excel(writer, sheet_name="annotated_transitions", index=False)
            plot_df.to_excel(writer, sheet_name="plot_transitions", index=False)
        return out_xlsx

    def export_spectrum_data(
        self,
        molecule: str,
        kind: Literal["SS", "TT"],
        plot_df: pd.DataFrame,
        curve_df: pd.DataFrame,
        family_summary_df: pd.DataFrame,
    ) -> Path:
        out_xlsx = self.data_dir / f"{safe_name(molecule)}_{kind}_spectrum_data.xlsx"
        stick_df = plot_df[[
            "family",
            "initial_state",
            "final_state",
            "delta_e_ev",
            "wavelength_nm",
            "oscillator_strength",
            "section",
            "i_index",
            "j_index",
        ]].copy()

        with pd.ExcelWriter(out_xlsx, engine="openpyxl") as writer:
            stick_df.to_excel(writer, sheet_name="stick_data", index=False)
            curve_df.to_excel(writer, sheet_name="curve_data", index=False)
            family_summary_df.to_excel(writer, sheet_name="family_summary", index=False)
        return out_xlsx

    def plot_spectrum(
        self,
        molecule: str,
        kind: Literal["SS", "TT"],
        plot_df: pd.DataFrame,
        curve_df: pd.DataFrame,
        ) -> Path:
        family_names = [c for c in curve_df.columns if c != "wavelength_nm"]
        n_family = len(family_names)
        colors = plt.cm.rainbow(np.linspace(0, 1, max(n_family, 1)))

        fig, (ax_curve, ax_stick) = plt.subplots(
            2, 1, figsize=(16, 8), sharex=True,
            gridspec_kw={"height_ratios": [3.0, 1.3], "hspace": 0.08}
        )

        max_curve = 0.0
        max_f = 0.0
        if not plot_df.empty:
            max_f = float(plot_df["oscillator_strength"].max())

        # ===== label settings =====
        label_threshold = 0.05   # 只标 f >= 0.05 的峰，可自行改小/改大
        y_offset = max(0.02, max_f * 0.05)

        for idx, family in enumerate(family_names):
            color = colors[idx]
            family_curve = curve_df[family].to_numpy(dtype=float)
            family_sticks = plot_df[plot_df["family"] == family].copy()

            ax_curve.plot(
                curve_df["wavelength_nm"],
                family_curve,
                lw=2.0,
                color=color,
                label=family,
            )

            ax_stick.vlines(
                family_sticks["wavelength_nm"],
                0,
                family_sticks["oscillator_strength"],
                colors=[color],
                lw=1.3,
                alpha=0.95,
            )

                # ===== annotate specific transitions, e.g. T1-T2, T1-T3 =====
            label_rows = family_sticks[family_sticks["oscillator_strength"] >= label_threshold].copy()
            label_rows = label_rows.sort_values("wavelength_nm").reset_index(drop=True)

            for k, (_, row) in enumerate(label_rows.iterrows()):
                wl = float(row["wavelength_nm"])
                fval = float(row["oscillator_strength"])

                init_state = str(row["initial_state"])
                final_state = str(row["final_state"])
                label = f"{init_state}-{final_state}"

                # 交错三层，减少重叠
                extra_offset = y_offset * (1 + (k % 3) * 0.9)

                ax_stick.text(
                    wl,
                    fval + extra_offset,
                    label,
                    color=color,
                    fontsize=8,
                    rotation=90,
                    ha="center",
                    va="bottom",
                    clip_on=True,
                )

            max_curve = max(max_curve, float(np.max(family_curve)) if len(family_curve) else 0.0)

        ax_curve.set_xlim(self.wl_min_nm, self.wl_max_nm)
        ax_curve.set_ylabel("Broadened intensity (a.u.)")
        ax_stick.set_ylabel("Osc. strength (f)")
        ax_stick.set_xlabel("Wavelength (nm)")
        ax_curve.set_title(f"{molecule} | {kind} state-resolved spectrum")
        ax_curve.grid(alpha=0.25, linestyle="--")

        if max_curve > 0:
            ax_curve.set_ylim(0, max_curve * 2)
        if max_f > 0:
            ax_stick.set_ylim(0, max_f * 2)

        ax_curve.legend(frameon=False, ncol=2)
        fig.tight_layout()

        out_png = self.figure_dir / f"{safe_name(molecule)}_{kind}_spectrum.png"
        fig.savefig(out_png, dpi=300, bbox_inches="tight")
        plt.close(fig)
        return out_png

    def process_job(self, job: MultiwfnJob) -> JobResult:
        result = JobResult(molecule=job.name, kind=job.kind)

        transdip_path, returncode, multiwfn_log_path = self.run_multiwfn_transdip(job)
        result.multiwfn_returncode = returncode
        result.multiwfn_log_file = str(multiwfn_log_path)

        try:
            raw_df = self.parse_transdip(transdip_path)
        finally:
            transdip_path.unlink(missing_ok=True)

        if raw_df.empty:
            raise RuntimeError(f"No transitions parsed from transdipmom.txt. See log: {multiwfn_log_path}")

        annotated_df = self.annotate_transitions(raw_df, job.kind)
        plot_df = self.select_plot_transitions(annotated_df, job.kind)

        self.export_transition_workbook(job.name, raw_df, annotated_df, plot_df)

        result.total_raw_transitions = len(raw_df)
        result.total_plot_transitions = len(plot_df)

        if plot_df.empty:
            self.logger.info("[%s] No plottable %s transitions found", job.name, job.kind)
            result.status = "DONE"
            return result

        curve_df, family_summary_df = self.build_family_spectra(plot_df)
        result.family_count = len(family_summary_df)

        self.export_spectrum_data(job.name, job.kind, plot_df, curve_df, family_summary_df)
        self.plot_spectrum(job.name, job.kind, plot_df, curve_df)

        result.status = "DONE"
        return result

    def export_run_summary(self, results: list[JobResult]) -> None:
        df = pd.DataFrame([asdict(r) for r in results])
        csv_path = self.log_dir / "run_summary.csv"
        xlsx_path = self.log_dir / "run_summary.xlsx"
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="run_summary", index=False)

    def run(self) -> None:
        self.validate()
        self.prepare_output_dirs()
        self.setup_logging()

        self.logger.info("[GLOBAL] WORK_DIR: %s", self.work_dir)
        self.logger.info("[GLOBAL] Multiwfn: %s", self.multiwfn_exe)
        self.logger.info("[GLOBAL] MODE: %s", self.mode)
        self.logger.info("[GLOBAL] Output root: %s", self.output_root)

        jobs = self.collect_jobs()
        if not jobs:
            raise SystemExit("[ERROR] No valid .fchk/.log job pairs found.")

        self.logger.info("[GLOBAL] Collected %d jobs", len(jobs))
        results: list[JobResult] = []
        failure_count = 0

        for idx, job in enumerate(jobs, 1):
            self.logger.info("[%d/%d] Start %s (%s)", idx, len(jobs), job.name, job.kind)
            try:
                result = self.process_job(job)
            except Exception as exc:
                failure_count += 1
                tb = traceback.format_exc()
                self.logger.error("[%s] FAILED: %s", job.name, exc)
                self.logger.error(tb)

                result = JobResult(
                    molecule=job.name,
                    kind=job.kind,
                    status="FAILED",
                    error_message=str(exc),
                )
            results.append(result)

        self.export_run_summary(results)

        if failure_count:
            self.logger.warning("[GLOBAL] Completed with %d failure(s). See %s", failure_count, self.log_dir / "run.log")
        else:
            self.logger.info("[GLOBAL] Completed successfully with no failures.")

        self.logger.info("[GLOBAL] Results saved to: %s", self.output_root)


def main() -> None:
    args = build_cli().parse_args()
    tool = SpectrumTool(
        work_dir=args.work_dir,
        multiwfn_exe=args.multiwfn,
        mode=args.mode,
        wl_min_nm=args.wl_min,
        wl_max_nm=args.wl_max,
        wl_step_nm=args.wl_step,
        sigma_ev=args.sigma_ev,
        quiet=not args.show_multiwfn,
        keep_raw_txt=args.keep_raw_txt,
        output_to_workdir_root=args.output_to_workdir_root,
        output_root_name=args.output_root_name,
    )
    tool.run()


if __name__ == "__main__":
    main()
