# PyRush

## Description

PyRush is a prototype Python package management tool designed to demonstrate core package handling functionalities. It supports dependency resolution, parallel downloading of package files from PyPI, and parallel installation of `.whl` (wheel) packages into a specified target environment.

This tool is intended as an educational example and a proof-of-concept for certain package management operations.

## Features

*   **Dependency Resolution:** Identifies and lists all direct and indirect dependencies for a given package.
*   **Parallel Downloads:** Downloads required packages from PyPI concurrently to speed up the acquisition process.
*   **Parallel Installation:** Installs downloaded `.whl` packages into a target directory in parallel.
*   **Command-Line Interface:** Provides a `pyrush` command with sub-commands for different actions (`resolve`, `download`, `install`).
*   **Automatic Target Directory Detection:** For the `install` command, PyRush can automatically detect suitable installation directories (e.g., active virtual environment, user site-packages).

## Requirements

*   Python 3.7+
*   External Dependencies (handled by the package):
    *   `requests>=2.20.0`
    *   `beautifulsoup4>=4.9.0`
*   For installing from source:
    *   `pip`
    *   `build` (install with `pip install build`)

## Installation from Source

To install PyRush from the source code:

1.  **Ensure you have the `build` tool:**
    ```bash
    pip install build
    ```

2.  **Navigate to the project root directory** (where `pyproject.toml` is located).

3.  **Build the package:**
    ```bash
    python -m build
    ```
    This will create a `.whl` file in the `dist/` directory (e.g., `dist/pyrush-0.1.0-py3-none-any.whl`).

4.  **Install the built package using pip:**
    ```bash
    pip install dist/pyrush-0.1.0-py3-none-any.whl
    ```
    *(Adjust the filename in the command above if the package name or version changes. The name will now be `pyrush`.)*

    Alternatively, you can often build and install in one step from the project root (if you have `setuptools` and `wheel` available, which are part of the `build-system` requires):
    ```bash
    pip install .
    ```

## Usage

The tool is accessed via the `pyrush` command-line interface.

**Basic Structure:**
```bash
pyrush <command> [options] <package_name>
```

**Available Commands:**

*   `pyrush resolve <package_name>`
    *   Resolves and lists all unique dependencies for the specified `<package_name>`.

*   `pyrush download <package_name> [--version <version>] [--output-dir <dir>] [--max-workers <N>] [--no-cache] [--cache-dir <cache_dir>]`
    *   Downloads the specified `<package_name>`.
    *   `--version`: Download a specific version. Defaults to the latest suitable if not provided.
    *   `--output-dir`: Directory to save the downloaded file(s) (default: `./downloads/`).
    *   `--max-workers`: Number of parallel workers.
    *   `--no-cache`: Disable download caching.
    *   `--cache-dir`: Specify a custom cache directory.

*   `pyrush install <package_name> [--target-dir <dir>] [--max-workers <N>] [--no-cache] [--cache-dir <cache_dir>]`
    *   Resolves all dependencies for `<package_name>`, downloads them, and then installs them all.
    *   `--target-dir <dir>`: Optional. Directory where packages will be installed. If not provided, PyRush attempts to auto-detect a suitable `site-packages` directory (see "Automatic Target Directory Detection" below).
    *   `--max-workers <N>`: Number of parallel workers for download and install phases.
    *   `--no-cache`: Disable download caching for the download phase.
    *   `--cache-dir <cache_dir>`: Specify a custom cache directory for the download phase.

**Automatic Target Directory Detection (for `install` command):**

If `--target-dir` is not specified for the `install` command, PyRush will attempt to find a suitable default `site-packages` directory in the following order of priority:
1.  The `site-packages` directory of an active Python virtual environment.
2.  The user-specific `site-packages` directory (e.g., `~/.local/lib/pythonX.Y/site-packages` on Linux). PyRush will attempt to create this directory if it doesn't exist.
3.  As a last resort, the first writable system-level `site-packages` directory found in Python's search path (a warning will be issued if this fallback is used).

It is generally recommended to use virtual environments or explicitly specify `--target-dir` for clarity and to avoid unintended installations, especially if you have multiple Python installations or complex setups. If PyRush cannot determine a suitable default directory, it will exit with an error, requiring you to use the `--target-dir` option.

**Example for `install` command:**
To install `flask` and its dependencies into a specific directory:
```bash
pyrush install flask --target-dir ./my_custom_env/site-packages --max-workers 4
```
To let PyRush attempt to auto-detect the installation directory:
```bash
pyrush install flask --max-workers 4
```

**Getting Help:**
To see all available commands:
```bash
pyrush -h
```
For help with a specific command:
```bash
pyrush <command> -h
```
Example: `pyrush install -h`

## Current Limitations & Disclaimer

*   **Prototype Status:** This tool is a prototype and should **not** be considered a replacement for established Python package managers like `pip` or `conda`. It lacks many of their advanced features, error handling, and safety checks.
*   **Wheel (.whl) Files Only:** The installation mechanism currently only supports `.whl` files. It cannot install packages from source distributions (`.tar.gz`, `.zip`).
*   **Basic Dependency Resolution:** Dependency resolution is basic. It identifies required packages but does not perform complex conflict resolution between different package version requirements.
*   **ARM64/Platform Support:** While the tool itself is Python-based and should run on ARM64, successful installation of packages depends on the availability of ARM64-compatible wheels on PyPI. The tool does not yet explicitly prioritize architecture-specific wheels if multiple options are available (though PyPI's simple API often filters by default).

## License

This project is assumed to be under the MIT License (please verify or update if a `LICENSE` file with different terms is added).
The `pyproject.toml` includes a classifier for "License :: OSI Approved :: MIT License".
