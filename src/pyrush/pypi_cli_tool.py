import os
import requests
import argparse
import re
from bs4 import BeautifulSoup
import concurrent.futures
import subprocess
import sys
import shutil
from pathlib import Path
import functools
import site # Added for determine_target_install_dir

"""
PyRush: PyPI Package Management Tool
(Description and ARM64 considerations as before)
"""

# --- Verbose Print Helper ---
def print_verbose(*args, **kwargs):
    # In future, this could check a verbosity flag from args
    print("VERBOSE:", *args, **kwargs, file=sys.stderr)
    sys.stderr.flush()

# --- Cache Directory Helper ---
def get_cache_dir(custom_cache_dir_str=None):
    if custom_cache_dir_str: cache_dir = Path(custom_cache_dir_str)
    else: cache_dir = Path.home() / ".cache" / "pyrush" / "downloads"
    try: os.makedirs(cache_dir, exist_ok=True)
    except OSError as e: print(f"Warning: Could not create cache directory {cache_dir}: {e}. Caching might be unreliable or disabled.")
    return cache_dir

# --- Target Install Directory Determination ---
def determine_target_install_dir():
    '''
    Determines a suitable default installation directory for packages.
    Priority:
    1. Active virtual environment's site-packages.
    2. User's site-packages directory.
    3. First writable system site-packages directory found in sys.path (use with caution).
    Returns the path as a string, or None if no suitable writable path is found.
    '''
    # --- Original logic restored ---
    print_verbose("Attempting to determine default installation directory...")

    # 1. Check for an active virtual environment
    if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
        print_verbose(f"Virtual environment detected at: {sys.prefix}")
        for path_item in sys.path:
            if isinstance(path_item, str) and sys.prefix in path_item and 'site-packages' in path_item.lower():
                if os.path.isdir(path_item) and os.access(path_item, os.W_OK):
                    print_verbose(f"Using virtual environment site-packages: {path_item}")
                    return path_item
                else:
                    print_verbose(f"Found venv site-packages '{path_item}' but it's not writable or not a directory.")
        print_verbose("Could not find a writable site-packages directory within the active virtual environment.")
    else:
        print_verbose("No active virtual environment detected.")

    # 2. Try user's site-packages directory
    if hasattr(site, 'getusersitepackages'):
        user_site_paths = site.getusersitepackages()
        if isinstance(user_site_paths, str): user_site_paths = [user_site_paths] # Ensure it's a list

        for user_site in user_site_paths:
            print_verbose(f"Checking user site-packages: {user_site}")
            try:
                if not os.path.exists(user_site):
                    print_verbose(f"User site-packages '{user_site}' does not exist. Attempting to create.")
                    os.makedirs(user_site, exist_ok=True)

                if os.path.isdir(user_site) and os.access(user_site, os.W_OK):
                    print_verbose(f"Using (potentially newly created) user site-packages: {user_site}")
                    return user_site
                else:
                    print_verbose(f"User site-packages '{user_site}' is not writable or could not be confirmed after creation attempt.")
            except Exception as e:
                print_verbose(f"Error creating or checking user site-packages '{user_site}': {e}")
    else:
        print_verbose("`site.getusersitepackages()` not available or returned unexpected type.")

    # 3. Fallback: First writable site-packages in sys.path (use with caution)
    print_verbose("Checking all paths in sys.path for a writable site-packages directory (fallback)...")
    for path_item in sys.path:
        if isinstance(path_item, str) and 'site-packages' in path_item.lower():
            if os.path.isdir(path_item) and os.access(path_item, os.W_OK):
                if (hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix)) and sys.prefix not in path_item:
                    print_verbose(f"Skipping site-packages '{path_item}' as it appears to be from a different environment.")
                    continue
                print_verbose(f"Warning: Using a globally visible site-packages directory: {path_item}. "
                              "Consider using a virtual environment or the --user scheme for safer installs.")
                return path_item

    print_verbose("Could not determine a suitable default writable installation directory from sys.path site-packages.")
    return None


# --- Download Functions ---
def download_file(url, output_directory, filename_from_url, use_cache=True, cache_dir_path=None):
    os.makedirs(output_directory, exist_ok=True)
    local_filepath = Path(output_directory) / filename_from_url
    if use_cache and cache_dir_path and os.access(str(cache_dir_path), os.W_OK):
        cached_file_path = cache_dir_path / filename_from_url
        if cached_file_path.exists():
            try:
                shutil.copy2(cached_file_path, local_filepath)
                print(f"  Used cached file: {cached_file_path} -> {local_filepath}")
                return str(local_filepath)
            except Exception as e: print(f"  Warning: Error using cached file {cached_file_path}: {e}. Attempting fresh download.")
    elif use_cache and cache_dir_path and not os.access(str(cache_dir_path), os.W_OK):
        print(f"  Warning: Cache directory {cache_dir_path} is not writable. Proceeding without caching for this file.")
        use_cache = False
    print(f"  Downloading: {filename_from_url} to {output_directory}")
    try:
        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            with open(local_filepath, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192): f.write(chunk)
        if use_cache and cache_dir_path and os.access(str(cache_dir_path), os.W_OK):
            try:
                shutil.copy2(local_filepath, cached_file_path)
                print(f"  Cached: {filename_from_url} to {cached_file_path}")
            except Exception as e: print(f"  Warning: Could not cache downloaded file {local_filepath} to {cached_file_path}: {e}")
        return str(local_filepath)
    except requests.exceptions.RequestException as e: print(f"  Error downloading {url}: {e}"); return None

def query_pypi_simple_api(package_name):
    url = f"https://pypi.org/simple/{package_name}/"
    try:
        response = requests.get(url)
        response.raise_for_status(); return response.text
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404: print(f"Package '{package_name}' not found on PyPI (404 Error).")
        else: print(f"HTTP error querying PyPI for {package_name}: {e}")
    except requests.exceptions.RequestException as e: print(f"Network error querying PyPI for {package_name}: {e}")
    return None

def parse_simple_api_html(html_content, package_name):
    soup = BeautifulSoup(html_content, 'html.parser')
    files = []
    normalized_package_name = re.sub(r"[-_.]+", "-", package_name).lower()
    for a_tag in soup.find_all('a'):
        href = a_tag.get('href'); filename = a_tag.text.strip()
        if href and filename:
            version, file_type, parsed_pkg_name = "unknown", "unknown", "unknown"
            wheel_match = re.match(r"^(.*?)-(.*?)-(.*?)-(.*?)-(.*?)\.whl$", filename, re.IGNORECASE)
            sdist_gz = re.match(r"^(.*?)-(.*?)\.tar\.gz$", filename, re.IGNORECASE)
            sdist_zip = re.match(r"^(.*?)-(.*?)\.zip$", filename, re.IGNORECASE)
            if wheel_match: file_type, parsed_pkg_name, version = "wheel", wheel_match.group(1), wheel_match.group(2)
            elif sdist_gz: file_type, parsed_pkg_name, version = "sdist", sdist_gz.group(1), sdist_gz.group(2)
            elif sdist_zip: file_type, parsed_pkg_name, version = "sdist", sdist_zip.group(1), sdist_zip.group(2)
            normalized_parsed_pkg_name = re.sub(r"[-_.]+", "-", parsed_pkg_name).lower()
            if normalized_parsed_pkg_name == normalized_package_name:
                files.append({"filename": filename, "url": href, "version": version, "type": file_type, "package_name": parsed_pkg_name})
    return files

def select_distribution_file(files_info, package_name, target_version=None):
    if not files_info: return None
    eligible = [f for f in files_info if f['version'] == target_version] if target_version else files_info
    if not eligible and target_version: print(f"No files found for version {target_version} of {package_name}."); return None
    if not target_version:
        try: eligible.sort(key=lambda x: x['version'], reverse=True)
        except TypeError: print("Warning: Could not reliably sort versions.")
    wheels = [f for f in eligible if f['type'] == 'wheel']
    if wheels: print(f"Selected wheel: {wheels[0]['filename']} (version {wheels[0]['version']})"); return wheels[0]['url']
    sdists = [f for f in eligible if f['type'] == 'sdist']
    if sdists: print(f"Selected sdist: {sdists[0]['filename']} (version {sdists[0]['version']})"); return sdists[0]['url']
    if target_version: print(f"Found files for version {target_version}, but no wheel or sdist.")
    return None

# --- Dependency Resolution Functions ---
def get_package_metadata_json(package_name):
    url = f"https://pypi.org/pypi/{package_name}/json"
    try:
        response = requests.get(url)
        response.raise_for_status(); return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404: print(f"Package '{package_name}' not found on PyPI (JSON API - 404 Error).")
        else: print(f"HTTP error fetching JSON for {package_name}: {e}")
    except requests.exceptions.RequestException as e: print(f"Network error fetching JSON for {package_name}: {e}")
    except requests.exceptions.JSONDecodeError as e: print(f"Error decoding JSON for {package_name}: {e}")
    return None

def parse_dependency_string(dep_string):
    match = re.match(r"^\s*([a-zA-Z0-9._-]+)", dep_string)
    if match:
        name = match.group(1)
        return name.strip()
    return None

MAX_RECURSION_DEPTH = 20
def resolve_dependencies_recursive(current_package_name, already_processed_packages, all_discovered_dependencies_set, depth=0):
    indent = "  " * depth
    normalized_current_package_name = current_package_name.lower().replace("_", "-")
    if depth > MAX_RECURSION_DEPTH:
        print(f"{indent}ERROR: Max recursion depth ({MAX_RECURSION_DEPTH}) exceeded for {normalized_current_package_name}. Stopping this path.", file=sys.stderr)
        return
    if normalized_current_package_name in already_processed_packages: return
    print(f"Processing: {normalized_current_package_name}")
    already_processed_packages.add(normalized_current_package_name)
    all_discovered_dependencies_set.add(normalized_current_package_name)
    metadata = get_package_metadata_json(normalized_current_package_name)
    if not metadata and current_package_name != normalized_current_package_name:
        metadata = get_package_metadata_json(current_package_name)
    if not metadata:
        print(f"Could not fetch metadata for {current_package_name} (tried as {normalized_current_package_name}). Skipping its dependencies.")
        return
    requires_dist_list = metadata.get("info", {}).get("requires_dist")
    if requires_dist_list:
        for dep_string in requires_dist_list:
            package_name_to_resolve = parse_dependency_string(dep_string)
            if package_name_to_resolve:
                if ";" in dep_string:
                    parts = dep_string.split(";",1); marker_str = parts[1].strip()
                    if "extra ==" in marker_str: pass
                    elif "python_version" in marker_str: pass
                resolve_dependencies_recursive(package_name_to_resolve, already_processed_packages, all_discovered_dependencies_set, depth + 1)
            else:
                print(f"Warning: Could not parse package name from dependency string: '{dep_string}' for package '{current_package_name}'", file=sys.stderr)
    else:
        print(f"No 'requires_dist' found for {current_package_name} or it's empty.")

# --- Combined Download Logic ---
def download_package_simple_latest(package_name, download_output_directory, use_cache=True, cache_dir_path=None):
    normalized_query_name = package_name.lower().replace("_", "-")
    print(f"Processing package for download: {normalized_query_name} (original: {package_name})")
    package_html_content = query_pypi_simple_api(normalized_query_name)
    if not package_html_content: error_msg = f"Could not retrieve Simple API page for {normalized_query_name}."; print(f"  ERROR: {error_msg}"); return package_name, None, error_msg
    files_info = parse_simple_api_html(package_html_content, normalized_query_name)
    if not files_info: error_msg = f"No files found on Simple API page for {normalized_query_name}."; print(f"  ERROR: {error_msg}"); return package_name, None, error_msg
    selected_file_url = select_distribution_file(files_info, normalized_query_name, None)
    if not selected_file_url: error_msg = f"Could not select a suitable file to download for {normalized_query_name}."; print(f"  ERROR: {error_msg}"); return package_name, None, error_msg
    filename = selected_file_url.split('/')[-1].split('#')[0]
    downloaded_path = download_file(selected_file_url, output_directory=download_output_directory, filename_from_url=filename, use_cache=use_cache, cache_dir_path=cache_dir_path)
    if downloaded_path: return package_name, downloaded_path, None
    else: error_msg = f"Download failed for {normalized_query_name} from {selected_file_url}."; return package_name, None, error_msg

# --- Command Handler Functions ---
def handle_resolve_command(args):
    print(f"--- Resolving dependencies for {args.package_name} ---")
    all_deps = set(); processed_pkgs = set()
    resolve_dependencies_recursive(args.package_name, processed_pkgs, all_deps, depth=0)
    print("\nAll unique dependencies (including the initial package):")
    if not all_deps: print(f"No dependencies could be resolved for {args.package_name}")
    for dep in sorted(list(all_deps)): print(f"- {dep}")
    print("--- Resolution finished ---")

def handle_download_command(args):
    print(f"--- Downloading package: {args.package_name}{f' (version {args.version})' if args.version else ' (latest)'} ---")
    print(f"--- Output directory: {os.path.abspath(args.output_dir)} ---")
    use_cache = not args.no_cache
    actual_cache_dir = get_cache_dir(args.cache_dir) if use_cache else None
    if use_cache: print(f"--- Cache enabled. Cache directory: {actual_cache_dir} ---")
    else: print("--- Cache disabled ---")
    package_to_download = args.package_name
    package_html_content = query_pypi_simple_api(package_to_download)
    if not package_html_content: print(f"Could not retrieve Simple API page for {package_to_download}."); print("--- Download finished ---"); return
    files_info = parse_simple_api_html(package_html_content, package_to_download)
    if not files_info: print(f"No files found on Simple API page for {package_to_download}."); print("--- Download finished ---"); return
    selected_file_url = select_distribution_file(files_info, package_to_download, args.version)
    if selected_file_url:
        filename = selected_file_url.split('/')[-1].split('#')[0]
        print(f"Selected file for download: {filename}")
        download_file(selected_file_url, output_directory=args.output_dir, filename_from_url=filename, use_cache=use_cache, cache_dir_path=actual_cache_dir)
    else:
        version_msg = f" version {args.version}" if args.version else " (any suitable latest)"
        print(f"Could not find/select a suitable file for {package_to_download}{version_msg}.")
    print("--- Download finished ---")

def handle_install_command(args):
    # Determine target directory
    if args.target_dir:
        target_directory = args.target_dir
        print_verbose(f"User specified target directory: {target_directory}")
    else:
        print_verbose("No target directory specified by user. Attempting to determine a default.")
        target_directory = determine_target_install_dir()
        if target_directory:
            # Use a more prominent print for auto-determined paths for user awareness
            print(f"PyRush will install packages to the automatically determined directory: {target_directory}")
            print("Use the --target-dir option to specify a different location if this is not suitable.")
        else:
            print("Error: Could not automatically determine a suitable installation directory.", file=sys.stderr)
            print("Please specify an installation directory using the --target-dir option.", file=sys.stderr)
            sys.exit(1) # Exit if no target directory can be used

    print(f"--- Starting full install process for {args.package_name} ---")
    # Use the 'target_directory' variable determined above
    print(f"--- Target environment directory: {os.path.abspath(target_directory)} ---")

    use_cache = not args.no_cache
    actual_cache_dir = get_cache_dir(args.cache_dir) if use_cache else None
    if use_cache: print(f"--- Cache enabled. Cache directory: {actual_cache_dir} ---")
    else: print("--- Cache disabled ---")

    all_deps = set(); processed_pkgs = set()
    print(f"\nStep 1: Resolving dependencies for {args.package_name}...")
    initial_package_name = args.package_name
    resolve_dependencies_recursive(initial_package_name, processed_pkgs, all_deps, depth=0)
    if not all_deps: print("No dependencies found. Aborting install."); print("\n--- Full install process finished ---"); return

    dl_dir = "./downloads"; os.makedirs(dl_dir, exist_ok=True)
    print(f"\nStep 2: Downloading {len(all_deps)} packages to '{dl_dir}' using up to {args.max_workers} workers...")
    sorted_deps = sorted(list(all_deps)); dl_results = []; good_wheels = []
    worker_func = functools.partial(download_package_simple_latest, download_output_directory=dl_dir, use_cache=use_cache, cache_dir_path=actual_cache_dir)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        future_map = {executor.submit(worker_func, name): name for name in sorted_deps}
        for i, future in enumerate(concurrent.futures.as_completed(future_map)):
            pkg_name_done = future_map[future]
            try:
                name_returned_by_worker, path, error = future.result()
                dl_results.append({"name": name_returned_by_worker, "path": path, "error": error, "status": "Success" if path else "Failed"})
                if path: print(f"  SUCCESS (Download): [{i+1}/{len(sorted_deps)}] {name_returned_by_worker} to {path}"); good_wheels.append(path)
                else: print(f"  FAILURE (Download): [{i+1}/{len(sorted_deps)}] {name_returned_by_worker}. Reason: {error}")
            except Exception as exc:
                print(f"  EXCEPTION (Download): [{i+1}/{len(sorted_deps)}] {pkg_name_done} generated: {exc}")
                dl_results.append({"name": pkg_name_done, "path": None, "error": str(exc), "status": "Exception"})
    print("\nDownload Summary:")
    dl_ok_count = len(good_wheels); print(f"  {dl_ok_count} of {len(dl_results)} downloaded successfully.")
    if dl_ok_count < len(dl_results): print("  Failed/Skipped downloads:"); [print(f"    - {r['name']}: {r['error']}") for r in dl_results if r["status"] != "Success"]

    if good_wheels:
        # Use the 'target_directory' variable here
        print(f"\nStep 3: Installing {len(good_wheels)} packages into {target_directory} using up to {args.max_workers} workers...")
        install_results = []
        installer_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "package_installer.py")
        if not os.path.exists(installer_path): print(f"  ERROR: package_installer.py not found at {installer_path}. Cannot install.");
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=args.max_workers) as executor:
                # Pass 'target_directory' to subprocess
                future_map_install = {executor.submit(subprocess.run, [sys.executable, installer_path, p, target_directory], capture_output=True, text=True): p for p in good_wheels}
                for i, future in enumerate(concurrent.futures.as_completed(future_map_install)):
                    wheel_path_done = future_map_install[future]; pkg_name_wheel = os.path.basename(wheel_path_done).split('-',1)[0]
                    try:
                        res = future.result()
                        if res.returncode == 0: print(f"  SUCCESS (Install): [{i+1}/{len(good_wheels)}] {pkg_name_wheel}"); install_results.append({"name":pkg_name_wheel, "status":"Success"})
                        else: print(f"  FAILURE (Install): [{i+1}/{len(good_wheels)}] {pkg_name_wheel}.\n    Stdout:\n{res.stdout.strip()}\n    Stderr:\n{res.stderr.strip()}"); install_results.append({"name":pkg_name_wheel, "status":"Failed", "error":res.stderr})
                    except Exception as exc: print(f"  EXCEPTION (Install): [{i+1}/{len(good_wheels)}] {pkg_name_wheel} generated: {exc}"); install_results.append({"name":pkg_name_wheel, "status":"Exception", "error":str(exc)})
            print("\nInstallation Summary:")
            install_ok_count = sum(1 for r in install_results if r["status"] == "Success"); print(f"  {install_ok_count} of {len(install_results)} installed successfully.")
            if install_ok_count < len(install_results): print("  Failed/Skipped installs:"); [print(f"    - {r['name']}: {r.get('error','N/A')}") for r in install_results if r["status"] != "Success"]
    else: print("\nStep 3: Installation skipped as no packages were downloaded.")
    print("\n--- Full install process finished ---")

def main():
    parser = argparse.ArgumentParser(description="PyRush: PyPI Package Management Tool (Download, Resolve, Install).")
    cpu_cores = os.cpu_count(); default_max_workers = min(5, cpu_cores + 4 if cpu_cores else 5)
    subparsers = parser.add_subparsers(title="Commands", dest="command", required=True, help="Available commands. Use <command> -h for more details.")

    p_dl = subparsers.add_parser("download", help="Download a specific package.")
    p_dl.add_argument("package_name", help="Name of the package.")
    p_dl.add_argument("--version", help="Version to download (default: latest).")
    p_dl.add_argument("--output-dir", default="./downloads/", help="Output directory (default: ./downloads/).")
    p_dl.add_argument("--max-workers", type=int, default=default_max_workers, help=f"Max parallel workers (default: {default_max_workers}).")
    p_dl.add_argument("--no-cache", action="store_true", help="Disable download cache.")
    p_dl.add_argument("--cache-dir", default=None, type=str, help="Custom cache directory.")
    p_dl.set_defaults(func=handle_download_command)

    p_in = subparsers.add_parser("install", help="Resolve, download, and install a package and its dependencies.")
    p_in.add_argument("package_name", help="Name of the root package.")
    # --target-dir default is now handled by the logic in handle_install_command if not provided
    p_in.add_argument("--target-dir", default=None,
                        help="Target installation directory (e.g., ./my_env/site-packages/). Auto-detected if not provided.")
    p_in.add_argument("--max-workers", type=int, default=default_max_workers, help=f"Max parallel workers (default: {default_max_workers}).")
    p_in.add_argument("--no-cache", action="store_true", help="Disable download cache.")
    p_in.add_argument("--cache-dir", default=None, type=str, help="Custom cache directory.")
    p_in.set_defaults(func=handle_install_command)

    p_res = subparsers.add_parser("resolve", help="Resolve and list dependencies for a package.")
    p_res.add_argument("package_name", help="Name of the package.")
    p_res.set_defaults(func=handle_resolve_command)

    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
