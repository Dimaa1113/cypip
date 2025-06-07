# ARM64 Testing Strategy for PyPI Tooling

This document outlines a conceptual testing strategy for ensuring `pypi_downloader.py` and `package_installer.py` work effectively in ARM64 environments.

## 1. Environment Setup

Testing should ideally cover various ARM64 environments:

*   **Real ARM64 Hardware:**
    *   Linux-based ARM64 SBCs (e.g., Raspberry Pi 4/5 - 64-bit OS).
    *   ARM64 servers (e.g., AWS Graviton instances, Oracle Cloud ARM Ampere instances).
    *   Macbooks with Apple Silicon (M1/M2/M3) running macOS (as macOS is also ARM64-based, though Python packaging can have macOS specifics).
*   **Emulation (QEMU):**
    *   Full system emulation of an ARM64 Linux environment on x86_64 hardware. This can be slower but useful for CI/automation if dedicated hardware is limited.
*   **Containerization (Docker):**
    *   Using Docker images built for `linux/arm64` on ARM64 hardware or on x86_64 systems with QEMU-based Docker Desktop support. This is excellent for reproducible test environments.
*   **Continuous Integration (CI):**
    *   Utilize CI services that offer ARM64 runners (e.g., GitHub Actions with third-party ARM runners or self-hosted ARM runners, AWS CodeBuild with Graviton).

For all environments, ensure a compatible Python version (e.g., 3.8+) is installed, along with any necessary build tools if sdist compilation (future feature) were to be tested.

## 2. Key Test Cases

### 2.1. `pypi_downloader.py`

*   **Pure Python Packages:**
    *   **Test:** Download and install a simple, pure Python package (e.g., `blinker`, `six`).
    *   **Verification:**
        *   Script completes without errors.
        *   Correct wheel (usually `*-py3-none-any.whl`) is selected and downloaded.
        *   Package is installed to the target directory.
        *   Basic import and functionality check in Python (e.g., `python -c "import blinker; print(blinker.__version__)"`).
*   **Packages with Pre-built ARM64 Wheels:**
    *   **Test:** Download and install packages known to have ARM64 wheels (e.g., `numpy`, `pandas`, `cryptography` for relevant Python versions).
    *   **Verification:**
        *   Script selects the ARM64-specific wheel (e.g., `*_aarch64.whl`, `*_arm64.whl`, or a `manylinux*_aarch64.whl`). This might require inspecting PyPI directly or the script's selection output if it's made more verbose for architectures.
        *   Package is downloaded and installed.
        *   Core functionality check (e.g., for `numpy`, perform a simple array operation).
*   **Dependency Resolution on ARM64:**
    *   **Test:** Use `--resolve` and `--install` for a package with dependencies (e.g., `flask`, `requests`) where some dependencies might have architecture-specific versions.
    *   **Verification:**
        *   All dependencies are correctly identified.
        *   The appropriate wheel (ARM64 or platform-agnostic) is chosen for each dependency.
        *   All packages are downloaded and installed.
*   **Error Handling - No ARM64 Wheel:**
    *   **Test:** (If such a package is found) Attempt to download a package version that has wheels for other architectures but not ARM64, and only an sdist is available.
    *   **Verification:**
        *   The script should download the sdist (as per current `select_distribution_file` fallback).
        *   The `--install` command (using `package_installer.py`) would then currently fail for this sdist, which is expected behavior as `package_installer.py` only handles wheels. This would highlight the need for sdist installation support.

### 2.2. `package_installer.py` (Direct Testing)

*   **Valid ARM64 Wheel:**
    *   **Test:** Manually provide a path to a known-good ARM64 wheel file.
    *   **Verification:** Package installs correctly into the target directory. Contents match wheel structure.
*   **Corrupted Wheel:**
    *   **Test:** Use a truncated or modified ARM64 wheel file.
    *   **Verification:** `package_installer.py` reports an error (e.g., "BadZipFile").
*   **Non-Wheel File:**
    *   **Test:** Provide a `.tar.gz` sdist or a random file.
    *   **Verification:** `package_installer.py` reports an error about invalid file type.

### 2.3. (Future) Sdist Installation (Not currently supported)

*   **Test:** For a package with no ARM64 wheel, attempt to download the sdist and (once sdist installation is implemented) build and install it.
*   **Verification:**
    *   Requires appropriate ARM64 build toolchain (C/C++ compilers, Fortran for some scientific packages, library development headers).
    *   Installation succeeds.
    *   Package works correctly.

## 3. Verification Methods

*   **Script Exit Codes:** Ensure scripts exit with 0 on success and non-zero on failure.
*   **Stdout/Stderr Analysis:** Check for expected success messages and absence of unexpected errors. Parse error messages for known failure conditions.
*   **File System Checks:**
    *   Verify that downloaded files appear in the `./downloads` directory.
    *   Verify that installed packages appear in the specified target directory with the correct file structure (`package_name/`, `*.dist-info/`).
*   **Basic Functionality Tests (Smoke Tests):**
    *   For installed packages, run a simple Python import: `python -c "import package_name"`.
    *   For key packages, run a minimal piece of code that uses its core functionality (e.g., `numpy.array([1,2,3])`).

## 4. Automation

*   Where possible, automate these tests using shell scripts or a Python testing framework (like `pytest`).
*   Integrate into CI pipelines with ARM64 runners/emulators.

This testing strategy provides a roadmap for ensuring the tools are robust and functional for ARM64 users, acknowledging current limitations and pointing towards future enhancements.
