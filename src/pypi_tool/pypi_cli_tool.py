import os
import requests
import argparse
import re
from bs4 import BeautifulSoup
import concurrent.futures
import subprocess
import sys

"""
PyPI Downloader and Installer

This script provides functionalities to:
1. Download single packages from PyPI (specific version or latest).
2. Resolve all dependencies for a given package.
3. Download a package and all its resolved dependencies.
4. Install a package, its dependencies, and the main package itself into a target directory.

ARM64/Cross-Platform Considerations:
- This script, being Python, is generally portable and should run on ARM64 systems
  if a Python interpreter is available.
- Successful installation and execution of downloaded packages on ARM64 depend on:
  a) Availability of pre-built ARM64 wheels for the packages and their dependencies.
     Many popular packages provide these (e.g., *_aarch64.whl, *_arm64.whl).
  b) If ARM64 wheels are not available, installation would require building from source
     distributions (sdists). This script currently DOES NOT SUPPORT sdist compilation.
     Building from source on an ARM64 host would require appropriate build tools
     (compilers, development headers for libraries, etc.).
- The `select_distribution_file` function prefers any wheel over sdists. If multiple
  wheels are available for the same package version (e.g., for different architectures
  like x86_64 and aarch64), the current selection logic might not explicitly prioritize
  the ARM64 wheel if the Simple API hasn't already filtered for the host architecture.
  However, PyPI's Simple API usually provides links that are compatible with the requesting
  architecture when available. See comments in `select_distribution_file` for more details.
- The `package_installer.py` script (called by this script's --install function)
  currently only handles the installation of .whl files.
"""

# --- Download Functions ---

def download_file(url, directory="."):
    """Downloads a file from a URL to a specified directory."""
    if not os.path.exists(directory):
        os.makedirs(directory)

    filename_from_url = url.split('/')[-1].split('#')[0]
    local_filename = os.path.join(directory, filename_from_url)

    try:
        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            with open(local_filename, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        print(f"Downloaded: {local_filename}")
        return local_filename
    except requests.exceptions.RequestException as e:
        print(f"Error downloading {url}: {e}")
        return None

def query_pypi_simple_api(package_name):
    """Queries the PyPI simple API for a package and returns the HTML content."""
    url = f"https://pypi.org/simple/{package_name}/"
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.text
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            print(f"Package '{package_name}' not found on PyPI (404 Error).")
        else:
            print(f"HTTP error querying PyPI for {package_name}: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Network error querying PyPI for {package_name}: {e}")
        return None

def parse_simple_api_html(html_content, package_name):
    """Parses the HTML from the PyPI simple API page to find distribution files."""
    soup = BeautifulSoup(html_content, 'html.parser')
    files = []
    normalized_package_name = re.sub(r"[-_.]+", "-", package_name).lower()
    for a_tag in soup.find_all('a'):
        href = a_tag.get('href')
        filename = a_tag.text.strip()
        if href and filename:
            version, file_type, parsed_package_name = "unknown", "unknown", "unknown"
            wheel_match = re.match(r"^(.*?)-(.*?)-(.*?)-(.*?)-(.*?)\.whl$", filename, re.IGNORECASE)
            sdist_tar_gz_match = re.match(r"^(.*?)-(.*?)\.tar\.gz$", filename, re.IGNORECASE)
            sdist_zip_match = re.match(r"^(.*?)-(.*?)\.zip$", filename, re.IGNORECASE)

            if wheel_match:
                file_type, parsed_package_name, version = "wheel", wheel_match.group(1), wheel_match.group(2)
            elif sdist_tar_gz_match:
                file_type, parsed_package_name, version = "sdist", sdist_tar_gz_match.group(1), sdist_tar_gz_match.group(2)
            elif sdist_zip_match:
                file_type, parsed_package_name, version = "sdist", sdist_zip_match.group(1), sdist_zip_match.group(2)

            normalized_parsed_name = re.sub(r"[-_.]+", "-", parsed_package_name).lower()
            if normalized_parsed_name == normalized_package_name:
                files.append({"filename": filename, "url": href, "version": version, "type": file_type, "package_name": parsed_package_name})
    return files

def select_distribution_file(files_info, package_name, target_version=None):
    """Selects the best distribution file based on version and type (wheel preferred)."""
    if not files_info: return None
    eligible_files = [f for f in files_info if f['version'] == target_version] if target_version else files_info
    if not eligible_files and target_version:
        print(f"No files found for version {target_version} of {package_name}.")
        return None

    if not target_version: # Try to sort by version if no specific version is targeted
        try:
            eligible_files.sort(key=lambda x: x['version'], reverse=True) # Not robust: packaging.version is better
        except TypeError:
            print("Warning: Could not reliably sort versions. Selection might not be latest.")
            pass # Continue with unsorted or partially sorted if error

    wheels = [f for f in eligible_files if f['type'] == 'wheel']
    if wheels:
        print(f"Selected wheel: {wheels[0]['filename']} (version {wheels[0]['version']})")
        return wheels[0]['url']
    sdists = [f for f in eligible_files if f['type'] == 'sdist']
    if sdists:
        print(f"Selected sdist: {sdists[0]['filename']} (version {sdists[0]['version']})")
        return sdists[0]['url']
    if target_version:
         print(f"Found files for version {target_version}, but no wheel or sdist among them.")
    return None

# --- Dependency Resolution Functions ---

def get_package_metadata_json(package_name):
    """Queries the PyPI JSON API for a package and returns the parsed JSON."""
    url = f"https://pypi.org/pypi/{package_name}/json"
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            print(f"Package '{package_name}' not found on PyPI (JSON API - 404 Error).")
        else:
            print(f"HTTP error fetching JSON for {package_name}: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Network error fetching JSON for {package_name}: {e}")
        return None
    except requests.exceptions.JSONDecodeError as e: # Changed from requests.JSONDecodeError
        print(f"Error decoding JSON for {package_name}: {e}")
        return None

def parse_dependency_string(dep_string):
    """Parses a requirement string to get the package name."""
    dep_string = re.sub(r"\[.*?\]", "", dep_string) # Remove extras
    match = re.match(r"^\s*([a-zA-Z0-9._-]+)", dep_string)
    return match.group(1) if match else None

def resolve_dependencies_recursive(current_package_name, already_processed_packages, all_discovered_dependencies_set):
    """Recursively resolves dependencies."""
    if current_package_name in already_processed_packages:
        return

    print(f"Processing: {current_package_name}")
    already_processed_packages.add(current_package_name)
    all_discovered_dependencies_set.add(current_package_name)

    metadata = get_package_metadata_json(current_package_name)
    if not metadata:
        print(f"Could not fetch metadata for {current_package_name}. Skipping its dependencies.")
        return

    requires_dist = metadata.get("info", {}).get("requires_dist")
    if requires_dist:
        for dep_string in requires_dist:
            if ";" in dep_string: # Basic marker handling
                dep_spec, marker = dep_string.split(";", 1)
                # Simplified marker logic: ignore if it's for a different python_version or an extra
                if "python_version" in marker and ("<" in marker or ">" in marker or "==" in marker or "!=" in marker):
                    # print(f"  Marker for {dep_spec.strip()}: {marker.strip()} - basic check, might not be accurate.")
                    pass # Attempt to parse name, but acknowledge limitations
                elif "extra ==" in marker:
                    print(f"  Skipping extra dependency: {dep_string}")
                    continue

            parsed_name = parse_dependency_string(dep_string)
            if parsed_name:
                resolve_dependencies_recursive(parsed_name, already_processed_packages, all_discovered_dependencies_set)
    else:
        print(f"No 'requires_dist' found for {current_package_name} or it's empty.")

# --- Combined Download Logic for a Single Package (for parallel execution) ---

def download_package_simple_latest(package_name, download_directory):
    """
    Resolves and downloads the latest suitable version of a single package.
    Returns a tuple: (package_name, downloaded_file_path_or_None, error_message_or_None)
    """
    print(f"Starting download for: {package_name}")
    package_html_content = query_pypi_simple_api(package_name)
    if not package_html_content:
        error_msg = f"Could not retrieve package information (simple API) for {package_name}."
        print(f"  ERROR: {error_msg}")
        return package_name, None, error_msg

    files_info = parse_simple_api_html(package_html_content, package_name)
    if not files_info:
        error_msg = f"No files found for {package_name} after parsing simple API page."
        print(f"  ERROR: {error_msg}")
        return package_name, None, error_msg

    selected_file_url = select_distribution_file(files_info, package_name, None) # None for latest version
    if not selected_file_url:
        error_msg = f"Could not find a suitable file to download for {package_name}."
        print(f"  ERROR: {error_msg}")
        return package_name, None, error_msg

    # print(f"  Selected file for {package_name}: {selected_file_url.split('/')[-1].split('#')[0]}")
    downloaded_path = download_file(selected_file_url, directory=download_directory)
    if downloaded_path:
        # print(f"  Successfully downloaded {package_name} to {downloaded_path}")
        return package_name, downloaded_path, None
    else:
        error_msg = f"Failed to download file for {package_name} from {selected_file_url}."
        # Error is already printed by download_file, but good to have a status here.
        return package_name, None, error_msg


# --- Command Handler Functions ---

def handle_resolve_command(args):
    """Handles the 'resolve' command."""
    print(f"--- Resolving dependencies for {args.package_name} ---")
    all_dependencies_set = set()
    processed_packages_set = set()

    resolve_dependencies_recursive(args.package_name, processed_packages_set, all_dependencies_set)

    print("\nAll unique dependencies (including the initial package):")
    if not all_dependencies_set:
            print(f"No dependencies could be resolved for {args.package_name}")
    for dep in sorted(list(all_dependencies_set)):
        print(f"- {dep}")
    print("--- Resolution finished ---")

def handle_download_command(args):
    """Handles the 'download' command for single or multiple packages (if extended)."""
    # This handler currently focuses on downloading a single package, potentially a specific version.
    # The parallel download of multiple packages is handled by `handle_install_command`.
    # If we want `pypi_cli_tool.py download <pkg1> <pkg2> ...`, this function would need a loop
    # and potentially parallel execution similar to the download phase of `handle_install_command`.
    # For now, it mirrors the old default behavior for one package.

    # Note: The original simple download mode implicitly downloaded a single package (args.package_name and optional args.version).
    # The `download_package_simple_latest` is for *latest* version.
    # To support specific version with `download` command, we need to use the older logic.

    print(f"--- Downloading single package: {args.package_name}{f' (version {args.version})' if args.version else ''} ---")
    print(f"--- Output directory: {os.path.abspath(args.output_dir)} ---")

    package_html_content = query_pypi_simple_api(args.package_name)
    if not package_html_content:
        print(f"Could not retrieve package information for {args.package_name}.")
        print("--- Download finished ---")
        return

    files_info = parse_simple_api_html(package_html_content, args.package_name)
    if not files_info:
        print(f"No files found for {args.package_name} after parsing.")
        print("--- Download finished ---")
        return

    # If version is specified for download command, use it. Otherwise, None (latest).
    selected_file_url = select_distribution_file(files_info, args.package_name, args.version)
    if selected_file_url:
        print(f"Selected file for download: {selected_file_url.split('/')[-1].split('#')[0]}")
        download_file(selected_file_url, directory=args.output_dir)
    else:
        version_msg = f" version {args.version}" if args.version else " (latest)"
        print(f"Could not find a suitable file for {args.package_name}{version_msg}.")
    print("--- Download finished ---")


def handle_install_command(args):
    """Handles the 'install' command."""
    print(f"--- Starting full install process for {args.package_name} ---")
    print(f"--- Target environment directory: {os.path.abspath(args.target_dir)} ---")
    all_dependencies_set = set()
    processed_packages_set = set()

    # Step 1: Dependency Resolution
    print(f"\nStep 1: Resolving dependencies for {args.package_name}...")
    resolve_dependencies_recursive(args.package_name, processed_packages_set, all_dependencies_set)

    if not all_dependencies_set:
        print("No dependencies found or resolution failed. Aborting install.")
        print("\n--- Full install process finished ---")
        return

    # Step 2: Parallel Downloading
    # Using a temporary/default download dir for the wheels before installation
    download_wheels_dir = "./downloads"
    os.makedirs(download_wheels_dir, exist_ok=True)
    print(f"\nStep 2: Downloading resolved packages ({len(all_dependencies_set)} total) to '{download_wheels_dir}' using up to {args.max_workers} workers...")
    sorted_deps = sorted(list(all_dependencies_set))
    download_results = []
    successfully_downloaded_wheels = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        future_to_package = {executor.submit(download_package_simple_latest, dep_name, download_wheels_dir): dep_name for dep_name in sorted_deps}

        for i, future in enumerate(concurrent.futures.as_completed(future_to_package)):
            package_name_done = future_to_package[future]
            try:
                name, path, error = future.result()
                download_results.append({"name": name, "path": path, "error": error, "status": "Success" if path else "Failed"})
                if path:
                    print(f"  SUCCESS (Download): [{i+1}/{len(sorted_deps)}] Downloaded {name} to {path}")
                    successfully_downloaded_wheels.append(path)
                else:
                    print(f"  FAILURE (Download): [{i+1}/{len(sorted_deps)}] Failed to download {name}. Reason: {error}")
            except Exception as exc:
                print(f"  EXCEPTION (Download): [{i+1}/{len(sorted_deps)}] {package_name_done} generated an exception: {exc}")
                download_results.append({"name": package_name_done, "path": None, "error": str(exc), "status": "Exception"})

    print("\nDownload Summary:")
    successful_downloads_count = len(successfully_downloaded_wheels)
    total_attempted_downloads = len(download_results)
    print(f"  {successful_downloads_count} out of {total_attempted_downloads} packages downloaded successfully.")

    if successful_downloads_count < total_attempted_downloads:
        print("  Failed/Skipped downloads:")
        for res in download_results:
            if res["status"] != "Success":
                print(f"    - {res['name']}: {res['error']}")

    # Step 3: Parallel Installation
    if successfully_downloaded_wheels:
        print(f"\nStep 3: Installing {len(successfully_downloaded_wheels)} downloaded packages into {args.target_dir} using up to {args.max_workers} workers...")
        installation_results = []
        # Assuming package_installer.py is in the same directory as this script
        installer_script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "package_installer.py")

        if not os.path.exists(installer_script_path):
            print(f"  ERROR: package_installer.py not found at {installer_script_path}. Cannot proceed with installation.")
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=args.max_workers) as executor:
                future_to_wheel = {
                    executor.submit(subprocess.run, [sys.executable, installer_script_path, wheel_path, args.target_dir], capture_output=True, text=True): wheel_path
                    for wheel_path in successfully_downloaded_wheels
                }
                for i, future in enumerate(concurrent.futures.as_completed(future_to_wheel)):
                    wheel_path_done = future_to_wheel[future]
                    package_name_from_wheel = os.path.basename(wheel_path_done).split('-', 1)[0]
                    try:
                        completed_process = future.result()
                        if completed_process.returncode == 0:
                            print(f"  SUCCESS (Install): [{i+1}/{len(successfully_downloaded_wheels)}] Installed {package_name_from_wheel}")
                            installation_results.append({"name": package_name_from_wheel, "status": "Success", "output": completed_process.stdout})
                        else:
                            print(f"  FAILURE (Install): [{i+1}/{len(successfully_downloaded_wheels)}] Failed to install {package_name_from_wheel}.")
                            print(f"    Installer Output (stdout):\n{completed_process.stdout.strip()}")
                            print(f"    Installer Error Output (stderr):\n{completed_process.stderr.strip()}")
                            installation_results.append({"name": package_name_from_wheel, "status": "Failed", "error": completed_process.stderr, "output": completed_process.stdout})
                    except Exception as exc:
                        print(f"  EXCEPTION (Install): [{i+1}/{len(successfully_downloaded_wheels)}] Installation of {package_name_from_wheel} generated an exception: {exc}")
                        installation_results.append({"name": package_name_from_wheel, "status": "Exception", "error": str(exc)})

            print("\nInstallation Summary:")
            successful_installs_count = sum(1 for res in installation_results if res["status"] == "Success")
            total_attempted_installs = len(installation_results)
            print(f"  {successful_installs_count} out of {total_attempted_installs} packages installed successfully.")
            if successful_installs_count < total_attempted_installs:
                print("  Failed/Skipped installations:")
                for res in installation_results:
                    if res["status"] != "Success":
                        print(f"    - {res['name']}: {res.get('error', 'No specific error output.')}")
    else:
        print("\nStep 3: Installation skipped as no packages were successfully downloaded.")

    print("\n--- Full install process finished ---")


# --- Main Execution Block ---

def main():
    parser = argparse.ArgumentParser(description="PyPI Package Management Tool (Download, Resolve, Install).")

    # Common arguments
    # Ensure os.cpu_count() is handled for potential None return
    cpu_cores = os.cpu_count()
    default_max_workers = min(5, cpu_cores + 4 if cpu_cores else 5)

    subparsers = parser.add_subparsers(title="Commands", dest="command", required=True,
                                       help="Available commands")

    # --- 'download' command ---
    parser_download = subparsers.add_parser("download", help="Download a specific package (latest or specific version).")
    parser_download.add_argument("package_name", help="Name of the package to download.")
    parser_download.add_argument("--version", help="Version of the package to download (optional, default is latest).")
    parser_download.add_argument("--output-dir", default="./downloads/",
                                 help="Directory to save downloaded files (default: ./downloads/).")
    parser_download.add_argument("--max-workers", type=int, default=default_max_workers,
                                 help=f"Max number of parallel workers (default: {default_max_workers}). Currently mainly for internal ops if any.")
    parser_download.set_defaults(func=handle_download_command)

    # --- 'install' command ---
    parser_install = subparsers.add_parser("install", help="Resolve dependencies, download all, and install all into a target directory.")
    parser_install.add_argument("package_name", help="Name of the root package to install.")
    parser_install.add_argument("--target-dir", default="./installed_packages/",
                                help="Target directory for installation (e.g., ./my_env/site-packages/, default: ./installed_packages/).")
    parser_install.add_argument("--max-workers", type=int, default=default_max_workers,
                                help=f"Max number of parallel workers for download/install phases (default: {default_max_workers}).")
    parser_install.set_defaults(func=handle_install_command)

    # --- 'resolve' command ---
    parser_resolve = subparsers.add_parser("resolve", help="Resolve and list all dependencies for a package.")
    parser_resolve.add_argument("package_name", help="Name of the package to resolve.")
    parser_resolve.set_defaults(func=handle_resolve_command)

    args = parser.parse_args()
    args.func(args) # Call the appropriate handler function

if __name__ == "__main__":
    main()


# Future steps for downloader:
# 1. Test thoroughly with various packages and versions for download.
# 2. Consider adding support for more robust version sorting (e.g., using 'packaging' library for download).
# 3. Add more specific wheel selection logic (e.g., Python version, ABI, platform for download).

# Future steps for resolver:
# 1. Implement more robust parsing of requires_dist strings, especially handling markers and extras (e.g., using 'packaging' library).
# 2. Handle version specifiers for dependencies if we need to install specific versions of dependencies.
# 3. Potentially integrate with the downloader to fetch resolved dependencies.
