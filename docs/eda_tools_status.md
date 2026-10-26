# Open-source EDA tool status (checked 2026-10-26)

Scope: tools for a small accelerator prototype. Verilator is used for RTL simulation, Yosys for synthesis, and OpenROAD for place-and-route plus PPA estimates. Every statement below was read on a page fetched on the date above. "Not verified" means the page could not be fetched or did not say.

## Verilator

| Item | Status | Source |
|---|---|---|
| Latest release | **5.052, 2026-09-05**. Earlier releases: 5.050 (2026-07-01), 5.048 (2026-04-26). | https://veripool.org/guide/latest/changes.html |
| License | LGPL-3.0 **or** Artistic-2.0, at the user's choice. Examples and test files in the docs are CC0. Copyright 2003–2026 Wilson Snyder. | https://veripool.org/guide/latest/copyright.html |
| What it does | Compiles Verilog/SystemVerilog into a C++ or SystemC model. The model is cycle-accurate and 2-state, and processes are statically scheduled when the model is built. Version 5 (2022) added an IEEE-compliant scheduler and delay semantics. | https://en.wikipedia.org/wiki/Verilator |
| Recent features (5.052) | UVM 2020-3.2 support (with noted limitations), the Unigen2 constrained-randomization algorithm, `default clocking`, `soft foreach`, and `weak`/`strong` in property expressions. | https://veripool.org/guide/latest/changes.html |
| Limitations relevant to an accelerator prototype | It is 2-state, so it does not model X/Z propagation the way 4-state event-driven simulators do. It is cycle-based, so it cannot show behavior inside a clock cycle. SystemVerilog assertion support is partial ("some SystemVerilog assertions"). It has no built-in power estimation, so switching activity has to be exported and fed to other tools (an export path was not verified here). | https://en.wikipedia.org/wiki/Verilator |
| Python-installable build | There is **no official PyPI package.** An unofficial wrapper, `verilator` 5.48.0 (2026-05-16, Apache-2.0 for the wrapper, repository dau-dev/verilator-python), ships platform wheels for Windows x86-64, Linux x86-64, and macOS ARM64. Whether those wheels bundle a full toolchain is not verified, and its version trails upstream (5.48 vs 5.052). YoWASP does **not** package Verilator; its PyPI organization lists no Verilator package. | https://www.pypi.org/project/verilator/ ; https://pypi.org/org/YoWASP |

## Yosys

| Item | Status | Source |
|---|---|---|
| Latest release | **0.70**, inferred from the YoWASP package `yowasp-yosys` 0.70.0.0.post1259 (released 2026-10-13), which PyPI says corresponds to upstream Yosys 0.70. The GitHub releases page could not be fetched, so the exact upstream tag date is not verified. For comparison, the Arch Linux package was 0.66 (built 2026-06-21). | https://pypi.org/project/yowasp-yosys ; https://www.archlinux.de/packages/extra/x86_64/yosys |
| License | ISC (GPL-compatible, similar to MIT or 2-clause BSD). Third-party code in `abc/` and `libs/` keeps its own licenses. | https://github.com/YosysHQ/yosys |
| What it does | A framework for RTL synthesis. It provides synthesis passes that can be combined in scripts and extended in C++, and it is the synthesis front end for the OpenROAD and OpenLane flows. | https://github.com/YosysHQ/yosys ; https://en.wikipedia.org/wiki/OpenROAD_Project |
| Limitations relevant to an accelerator prototype | Verilog-2005 support is extensive. SystemVerilog support (through sv-elab and slang) covers an "informally defined synthesizable subset" of IEEE 1800-2017/2023. `read_verilog` does no syntax checking, so lint the RTL first; the README suggests Verilator for this. Industry-grade SystemVerilog and VHDL parsers require the commercial Tabby CAD Suite. | https://github.com/YosysHQ/yosys |
| Python-installable build | **Yes.** `pip install yowasp-yosys` installs a WebAssembly build. It ships as a universal wheel (`py3-none-any`), needs Python ≥3.9, and runs on any OS, Windows included. It is licensed ISC. A newer pre-release (0.70.0.188…dev0, 2026-10-22) exists, but pip ignores pre-releases by default. YoWASP also packages nextpnr (FPGA place-and-route) and Boolector. | https://pypi.org/project/yowasp-yosys ; https://pypi.org/org/YoWASP |

## OpenROAD

| Item | Status | Source |
|---|---|---|
| Latest release / versioning | **No tagged version verified.** The docs list two distributions: the standalone *Application* binary and the integrated *Flow* (OpenROAD-flow-scripts, ORFS). Prebuilt binaries come from "OpenROAD VaultLink", and Docker images are also available. Bazel is now the supported build system. The CMake build is deprecated and "will be removed on Nov. 1, 2026". Historical milestones were v1.0 (2020) and v2.0 (2021). | https://openroad.readthedocs.io/en/latest/main/README.html ; https://openroad.readthedocs.io/ ; https://en.wikipedia.org/wiki/OpenROAD_Project |
| License | BSD 3-Clause | https://openroad.readthedocs.io/en/latest/main/README.html |
| What it does | An autonomous RTL-to-GDSII digital flow. It covers floorplanning, pin and macro placement, PDN generation, global and detailed placement, timing analysis and gate resizing, clock tree synthesis, global and detailed routing, antenna checks, metal fill, parasitic extraction, and IR-drop analysis. It has Tcl and Python bindings. It began in 2018 under DARPA IDEA and is led by UC San Diego. | https://openroad.readthedocs.io/ ; https://en.wikipedia.org/wiki/OpenROAD_Project |
| Open PDKs / platforms | ORFS ships ASAP7 (7 nm, **predictive, not manufacturable**), Nangate45/FreePDK45, SKY130, GF180, and IHP SG13G2. Proprietary platforms (GF55, GF12, Intel22, Intel16, TSMC65) need user-supplied files because of NDAs. The README reports more than 600 silicon-ready tapeouts, mainly SKY130 and GF180. | https://openroad-flow-scripts.readthedocs.io/en/latest/index2.html ; https://openroad.readthedocs.io/en/latest/main/README.html |
| Limitations relevant to an accelerator prototype | (1) It has no synthesizer of its own and depends on Yosys. (2) The `-python` interpreter mode is "limited to db operations". (3) Native Windows is not supported; use Docker or WSL on Windows 10+, and prebuilt binaries exist only for Debian 12/13 and Ubuntu 24.04/26.04. (4) ORFS needs at least 1 core and 8 GB RAM, with 4 cores and 16 GB recommended; larger designs need more. (5) Final DRC/LVS signoff is usually done with external tools. (6) Results on ASAP7 are predictive only. Area, timing, and power from these open PDKs are not representative of a commercial 4–5 nm GPU process, so any extrapolation is class E. | https://openroad.readthedocs.io/en/latest/main/README.html ; https://openroad-flow-scripts.readthedocs.io/en/latest/index2.html ; https://en.wikipedia.org/wiki/OpenROAD_Project |
| Python-installable build | **No pip-installable OpenROAD binary was found**, and YoWASP does not package OpenROAD. The nearest option is **OpenLane 2** (`pip install openlane`), version 2.3.10 (2025-02-21), Apache-2.0. It is a Python flow infrastructure built on OpenROAD, Yosys, Magic, and KLayout. The PyPI page says the Python-only install expects you to supply the compiled tools yourself, and it recommends Nix or Docker. | https://pypi.org/org/YoWASP ; https://pypi.org/project/openlane/2.0.0 |

## Practical recommendation (engineering judgment, not a verified claim)

- **Fastest portable start:** `pip install yowasp-yosys` for synthesis and area/cell-count estimates, plus a system-installed Verilator 5.05x for simulation and linting.
- **Place-and-route and PPA:** run OpenROAD/ORFS in Docker (or WSL on Windows) with SKY130, GF180, or Nangate45. Use ASAP7 only for predictive what-if studies, and label those results as class E.
