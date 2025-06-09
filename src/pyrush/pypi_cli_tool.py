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
import site
# CRITICAL REVERT: Ensure no packaging imports are present

"""
PyRush: PyPI Package Management Tool
"""

# --- Verbose Print Helper ---
def print_verbose(*args, **kwargs):
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
    print_verbose("Attempting to determine default installation directory...")
    if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
        print_verbose(f"Virtual environment detected at: {sys.prefix}")
        for path_item in sys.path:
            if isinstance(path_item, str) and sys.prefix in path_item and 'site-packages' in path_item.lower():
                if os.path.isdir(path_item) and os.access(path_item, os.W_OK):
                    print_verbose(f"Using virtual environment site-packages: {path_item}")
                    return path_item
        print_verbose("Could not find a writable site-packages directory within the active virtual environment.")
    else: print_verbose("No active virtual environment detected.")
    if hasattr(site, 'getusersitepackages'):
        user_site_paths = site.getusersitepackages()
        if isinstance(user_site_paths, str): user_site_paths = [user_site_paths]
        for user_site in user_site_paths:
            print_verbose(f"Checking user site-packages: {user_site}")
            try:
                if not os.path.exists(user_site):
                    print_verbose(f"User site-packages '{user_site}' does not exist. Attempting to create.")
                    os.makedirs(user_site, exist_ok=True)
                if os.path.isdir(user_site) and os.access(user_site, os.W_OK):
                    print_verbose(f"Using (potentially newly created) user site-packages: {user_site}")
                    return user_site
            except Exception as e: print_verbose(f"Error creating or checking user site-packages '{user_site}': {e}")
    else: print_verbose("`site.getusersitepackages()` not available or returned unexpected type.")
    print_verbose("Checking all paths in sys.path for a writable site-packages directory (fallback)...")
    for path_item in sys.path:
        if isinstance(path_item, str) and 'site-packages' in path_item.lower():
            if os.path.isdir(path_item) and os.access(path_item, os.W_OK):
                if (hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix)) and sys.prefix not in path_item:
                    continue
                print_verbose(f"Warning: Using a globally visible site-packages directory: {path_item}.")
                return path_item
    print_verbose("Could not determine a suitable default writable installation directory.")
    return None

# --- Download Functions ---
def download_file(url, output_directory, filename_from_url, use_cache=True, cache_dir_path=None):
    os.makedirs(output_directory, exist_ok=True)
    local_filepath = Path(output_directory) / filename_from_url
    if use_cache and cache_dir_path and os.access(str(cache_dir_path), os.W_OK):
        cached_file_path = cache_dir_path / filename_from_url
        if cached_file_path.exists():
            try: shutil.copy2(cached_file_path, local_filepath); print(f"  Used cached file: {cached_file_path} -> {local_filepath}"); return str(local_filepath)
            except Exception as e: print(f"  Warning: Error using cached file {cached_file_path}: {e}. Attempting fresh download.")
    elif use_cache and cache_dir_path and not os.access(str(cache_dir_path), os.W_OK):
        print(f"  Warning: Cache directory {cache_dir_path} is not writable. Proceeding without caching."); use_cache = False
    print(f"  Downloading: {filename_from_url} to {output_directory}")
    try:
        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            with open(local_filepath, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192): f.write(chunk)
        if use_cache and cache_dir_path and os.access(str(cache_dir_path), os.W_OK):
            try: shutil.copy2(local_filepath, cached_file_path); print(f"  Cached: {filename_from_url} to {cached_file_path}")
            except Exception as e: print(f"  Warning: Could not cache downloaded file {local_filepath} to {cached_file_path}: {e}")
        return str(local_filepath)
    except requests.exceptions.RequestException as e: print(f"  Error downloading {url}: {e}"); return None

def _simple_normalize_pypi_name(name):
    if not isinstance(name, str): name = str(name)
    return re.sub(r"[-_.]+", "-", name).lower()

def query_pypi_simple_api(package_name):
    normalized_name = _simple_normalize_pypi_name(package_name)
    url = f"https://pypi.org/simple/{normalized_name}/"
    try: response = requests.get(url); response.raise_for_status(); return response.text
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404: print(f"Package '{normalized_name}' (from '{package_name}') not found on PyPI Simple API (404 Error).")
        else: print(f"HTTP error querying Simple API for {normalized_name}: {e}")
    except requests.exceptions.RequestException as e: print(f"Network error querying Simple API for {normalized_name}: {e}")
    return None

def parse_simple_api_html(html_content, package_name):
    soup = BeautifulSoup(html_content, 'html.parser'); files = []
    query_normalized_name = _simple_normalize_pypi_name(package_name)
    for a in soup.find_all('a'):
        href = a.get('href'); fname = a.text.strip()
        if href and fname:
            v_str, ftype, parsed_pkg_name_from_file = "unknown", "unknown", "unknown"
            match = re.match(r"^([a-zA-Z0-9._-]+?)-([a-zA-Z0-9_.!+]+)", fname)
            if match:
                parsed_pkg_name_from_file = match.group(1)
                v_str = match.group(2)
            if fname.endswith(".whl"): ftype = "wheel"
            elif fname.endswith(".tar.gz"): ftype = "sdist"
            elif fname.endswith(".zip"): ftype = "sdist"
            if _simple_normalize_pypi_name(parsed_pkg_name_from_file) == query_normalized_name:
                files.append({"filename":fname,"url":href,"version_str":v_str, "type":ftype,"package_name":parsed_pkg_name_from_file})
    return files

def select_distribution_file(files_info, package_name, target_version_str=None):
    if not files_info: return None
    eligible_files = []
    if target_version_str:
        eligible_files = [f for f in files_info if f['version_str'] == target_version_str]
        if not eligible_files: print(f"No files for version {target_version_str} of {package_name}."); return None
    else:
        try: eligible_files = sorted(files_info, key=lambda x: x['version_str'], reverse=True)
        except Exception: print_verbose(f"Warning: Naive version string sort failed for {package_name}. Using original file order."); eligible_files = files_info
    wheels = [f for f in eligible_files if f['type'] == 'wheel']
    if wheels: print(f"Selected wheel: {wheels[0]['filename']} (v {wheels[0]['version_str']}) for {package_name}"); return wheels[0]['url']
    sdists = [f for f in eligible_files if f['type'] == 'sdist']
    if sdists: print(f"Selected sdist: {sdists[0]['filename']} (v {sdists[0]['version_str']}) for {package_name}"); return sdists[0]['url']
    if target_version_str and eligible_files: print(f"Files for version {target_version_str} found, but no wheel/sdist.")
    elif not eligible_files: print(f"No suitable files found for {package_name} {target_version_str or '(latest)'}.")
    return None

# --- Dependency Resolution ---
def get_package_metadata_json(package_name):
    normalized_name = _simple_normalize_pypi_name(package_name)
    url = f"https://pypi.org/pypi/{normalized_name}/json"
    try: response = requests.get(url); response.raise_for_status(); return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404: print(f"Package '{normalized_name}' (from '{package_name}') not on PyPI (JSON API).")
        else: print(f"HTTP error (JSON API) for {normalized_name}: {e}")
    except requests.exceptions.RequestException as e: print(f"Network error (JSON API) for {normalized_name}: {e}")
    except requests.exceptions.JSONDecodeError as e: print(f"JSON decode error for {normalized_name}: {e}")
    return None

def parse_dependency_string(dep_string):
    match = re.match(r"^\s*([a-zA-Z0-9._-]+)", dep_string)
    return match.group(1).strip() if match else None

MAX_RECURSION_DEPTH_EQUIVALENT = 1000
def resolve_dependencies_iterative(initial_pkg_name, processed_names, all_deps_names):
    initial_pkg_name_norm = _simple_normalize_pypi_name(initial_pkg_name)
    queue = {initial_pkg_name_norm}
    processed_count = 0
    while queue and processed_count < MAX_RECURSION_DEPTH_EQUIVALENT :
        pkg_name_to_check_norm = queue.pop()
        if pkg_name_to_check_norm in processed_names:
            print_verbose(f"Already processed '{pkg_name_to_check_norm}'. Skipping.")
            continue
        print(f"Processing: {pkg_name_to_check_norm}")
        processed_names.add(pkg_name_to_check_norm)
        all_deps_names.add(pkg_name_to_check_norm)
        processed_count +=1
        meta = get_package_metadata_json(pkg_name_to_check_norm)
        original_name_for_retry = initial_pkg_name if pkg_name_to_check_norm == initial_pkg_name_norm else pkg_name_to_check_norm
        if not meta and _simple_normalize_pypi_name(original_name_for_retry) != original_name_for_retry:
             print_verbose(f"Retrying metadata fetch for '{original_name_for_retry}' (original case) as '{pkg_name_to_check_norm}' failed.")
             meta = get_package_metadata_json(original_name_for_retry)
        if not meta:
            print_verbose(f"No metadata for {pkg_name_to_check_norm} (original name for retry context: {original_name_for_retry}). Skip deps.")
            continue
        reqs_list = meta.get("info", {}).get("requires_dist")
        if reqs_list:
            for dep_string in reqs_list:
                dep_name_parsed = parse_dependency_string(dep_string)
                if dep_name_parsed:
                    dep_name_norm = _simple_normalize_pypi_name(dep_name_parsed)
                    print_verbose(f"  Found requirement: '{dep_string}' -> Parsed name: '{dep_name_norm}'")
                    if ";" in dep_string:
                        marker_str = dep_string.split(";",1)[1].strip()
                        if "extra ==" in marker_str: print_verbose(f"  Info: Dependency '{dep_name_norm}' is an extra. PyRush will add base name to queue.")
                        elif "python_version" in marker_str: print_verbose(f"  Info: Dependency '{dep_name_norm}' has python_version marker: '{marker_str}'. PyRush will add base name to queue.")
                    if dep_name_norm not in processed_names: queue.add(dep_name_norm)
                else: print_verbose(f"Warning: Skipping invalid/unparsable requirement string for '{pkg_name_to_check_norm}': '{dep_string}'")
        else: print_verbose(f"No 'requires_dist' for {pkg_name_to_check_norm}.")
    if processed_count >= MAX_RECURSION_DEPTH_EQUIVALENT: print("Warning: Reached maximum processing iterations. Resulting list might be incomplete.", file=sys.stderr)

# --- Combined Download Logic ---
def download_package_simple_latest(pkg_name, dl_dir, use_cache=True, cache_path=None):
    norm_q_name = _simple_normalize_pypi_name(pkg_name)
    print(f"Processing package for download: {norm_q_name} (original input: {pkg_name})")
    html = query_pypi_simple_api(norm_q_name)
    if not html: err=f"Simple API query failed for {norm_q_name}."; print(f"  ERR: {err}"); return pkg_name,None,err
    files = parse_simple_api_html(html, norm_q_name)
    if not files: err=f"No files on Simple API for {norm_q_name}."; print(f"  ERR: {err}"); return pkg_name,None,err
    url = select_distribution_file(files, norm_q_name, None)
    if not url: err=f"No suitable file selected for {norm_q_name}."; print(f"  ERR: {err}"); return pkg_name,None,err
    fname = url.split('/')[-1].split('#')[0]
    dl_path = download_file(url,dl_dir,fname,use_cache,cache_path)
    if dl_path: return pkg_name, dl_path, None
    else: err=f"Download failed for {norm_q_name} from {url}."; return pkg_name,None,err

# --- Command Handlers ---
def handle_resolve_command(args):
    print(f"--- Resolving dependencies for {args.package_name} ---")
    all_deps_names=set(); processed_names=set()
    initial_name_norm = _simple_normalize_pypi_name(args.package_name)
    resolve_dependencies_iterative(initial_name_norm, processed_names, all_deps_names)
    print("\nAll unique dependencies (normalized names):"); [print(f"- {d}") for d in sorted(list(all_deps_names))]
    print("--- Resolution finished ---")

def handle_download_command(args):
    print(f"--- Downloading: {args.package_name} {args.version or '(latest)'} to {os.path.abspath(args.output_dir)} ---")
    use_cache=not args.no_cache; cache_dir_obj=get_cache_dir(args.cache_dir) if use_cache else None
    if use_cache: print(f"--- Cache enabled. Cache directory: {cache_dir_obj} ---")
    else: print("--- Cache disabled ---")
    pkg_to_dl_norm = _simple_normalize_pypi_name(args.package_name)
    html = query_pypi_simple_api(pkg_to_dl_norm)
    if not html: print(f"No Simple API page for {pkg_to_dl_norm}."); print("--- Download finished ---"); return
    files = parse_simple_api_html(html, pkg_to_dl_norm)
    if not files: print(f"No files for {pkg_to_dl_norm}."); print("--- Download finished ---"); return
    url = select_distribution_file(files, pkg_to_dl_norm, args.version)
    if url: fname=url.split('/')[-1].split('#')[0]; print(f"Selected: {fname}"); download_file(url,args.output_dir,fname,use_cache,cache_dir_obj)
    else: print(f"No suitable file for {pkg_to_dl_norm} {args.version or '(latest)'}.")
    print("--- Download finished ---")

def handle_install_command(args):
    target_dir_path = args.target_dir
    if not target_dir_path:
        print_verbose("No target directory specified. Auto-determining...")
        target_dir_path = determine_target_install_dir()
        if target_dir_path: print(f"Using auto-determined target: {target_dir_path}\nUse --target-dir to override.")
        else: print("ERR: No suitable target dir. Use --target-dir.", file=sys.stderr); sys.exit(1)
    print(f"--- Full install: {args.package_name} to {os.path.abspath(target_dir_path)} ---")
    use_cache=not args.no_cache; cache_dir_obj=get_cache_dir(args.cache_dir) if use_cache else None
    if use_cache: print(f"--- Cache enabled. Cache directory: {cache_dir_obj} ---")
    else: print("--- Cache disabled ---")
    all_deps_names=set(); processed_names=set()
    print(f"\nStep 1: Resolving {args.package_name}...")
    initial_name_norm = _simple_normalize_pypi_name(args.package_name)
    resolve_dependencies_iterative(initial_name_norm, processed_names, all_deps_names)
    if not all_deps_names: print("No deps. Abort."); print("--- Install finished ---"); return
    dl_intermed_dir="./downloads"; os.makedirs(dl_intermed_dir, exist_ok=True)
    print(f"\nStep 2: Download {len(all_deps_names)} pkgs to '{dl_intermed_dir}' (max {args.max_workers} workers)...")
    sorted_deps_names=sorted(list(all_deps_names)); dl_results=[]; good_wheels=[]
    worker = functools.partial(download_package_simple_latest, dl_dir=dl_intermed_dir, use_cache=use_cache, cache_path=cache_dir_obj)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        fm = {executor.submit(worker, n): n for n in sorted_deps_names}
        for i, f in enumerate(concurrent.futures.as_completed(fm)):
            pkg_n_done_norm=fm[f]
            try:
                name_returned_by_worker, path, error = f.result()
                dl_results.append({"name":name_returned_by_worker,"path":path,"error":error,"status":"OK" if path else "FAIL"})
                if path: print(f"  OK DL [{i+1}/{len(sorted_deps_names)}] {name_returned_by_worker} to {path}"); good_wheels.append(path)
                else: print(f"  FAIL DL [{i+1}/{len(sorted_deps_names)}] {name_returned_by_worker}. Err: {error}")
            except Exception as exc: print(f"  EXC DL [{i+1}/{len(sorted_deps_names)}] {pkg_n_done_norm} generated: {exc}"); dl_results.append({"name":pkg_n_done_norm,"path":None,"error":str(exc),"status":"EXC"})
    print("\nDL Summary:"); dl_ok=len(good_wheels); print(f"  {dl_ok}/{len(dl_results)} DLed OK.")
    if dl_ok < len(dl_results): print("  Failed/Skipped DLs:"); [print(f"    - {r['name']}: {r['error']}") for r in dl_results if r["status"] != "OK"]
    if good_wheels:
        print(f"\nStep 3: Install {len(good_wheels)} pkgs to {target_dir_path} (max {args.max_workers} workers)...")
        install_results=[]
        inst_script=os.path.join(os.path.dirname(os.path.abspath(__file__)),"package_installer.py")
        if not os.path.exists(inst_script): print(f"  ERR: {inst_script} not found. No install.");
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=args.max_workers) as executor:
                fm_inst = {executor.submit(subprocess.run, [sys.executable,inst_script,wheel,target_dir_path],capture_output=True,text=True): wheel for wheel in good_wheels}
                for i,f in enumerate(concurrent.futures.as_completed(fm_inst)):
                    whl_done=fm_inst[f]; pkg_whl_name=os.path.basename(whl_done).split('-',1)[0]
                    try:
                        res=f.result()
                        if res.returncode==0: print(f"  OK Inst [{i+1}/{len(good_wheels)}] {pkg_whl_name}"); inst_results.append({"name":pkg_whl_name,"status":"OK"})
                        else: print(f"  FAIL Inst [{i+1}/{len(good_wheels)}] {pkg_whl_name}.\n    Stdout:\n{res.stdout.strip()}\n    Stderr:\n{res.stderr.strip()}"); inst_results.append({"name":pkg_whl_name,"status":"FAIL","error":res.stderr})
                    except Exception as exc: print(f"  EXC Inst [{i+1}/{len(good_wheels)}] {pkg_whl_name} generated: {exc}"); inst_results.append({"name":pkg_whl_name,"status":"EXC","error":str(exc)})
            print("\nInstall Summary:"); inst_ok_cnt=sum(1 for r in inst_results if r["status"]=="OK"); print(f"  {inst_ok_cnt}/{len(inst_results)} installed OK.")
            if inst_ok_cnt < len(inst_results): print("  Failed/Skipped Installs:"); [print(f"    - {r['name']}: {r.get('error','N/A')}") for r in inst_results if r["status"] != "OK"]
    else: print("\nStep 3: Install skipped, no pkgs DLed.")
    print("--- Full install process finished ---")

def main():
    # print("DEBUG: main() started.", file=sys.stderr) # Debug prints removed
    # sys.stderr.flush()
    parser = argparse.ArgumentParser(description="PyRush: PyPI Package Management Tool")
    cpu_cores = os.cpu_count(); def_mw = min(5, cpu_cores + 4 if cpu_cores else 5)
    subs = parser.add_subparsers(title="Commands", dest="command", required=True, help="Use <cmd> -h for details.")

    p_dl = subs.add_parser("download", help="Download a package.")
    p_dl.add_argument("package_name", help="Package name.")
    p_dl.add_argument("--version", help="Version (default: latest).")
    p_dl.add_argument("--output-dir", default="./downloads/", help="Output dir (default: ./downloads/).")
    p_dl.add_argument("--max-workers", type=int, default=def_mw, help=f"Max workers (default: {def_mw}).")
    p_dl.add_argument("--no-cache", action="store_true", help="Disable cache.")
    p_dl.add_argument("--cache-dir", default=None, type=str, help="Custom cache dir.")
    p_dl.set_defaults(func=handle_download_command)

    p_in = subs.add_parser("install", help="Resolve, download, & install package + deps.")
    p_in.add_argument("package_name", help="Root package name.")
    p_in.add_argument("--target-dir", default=None, help="Target install dir (auto-detected if None).")
    p_in.add_argument("--max-workers", type=int, default=def_mw, help=f"Max workers (default: {def_mw}).")
    p_in.add_argument("--no-cache", action="store_true", help="Disable cache.")
    p_in.add_argument("--cache-dir", default=None, type=str, help="Custom cache dir.")
    p_in.set_defaults(func=handle_install_command)

    p_res = subs.add_parser("resolve", help="Resolve and list dependencies.")
    p_res.add_argument("package_name", help="Package name.")
    p_res.set_defaults(func=handle_resolve_command)

    args = parser.parse_args()
    # print(f"DEBUG: Parsed args: {args}", file=sys.stderr) # Debug prints removed
    # sys.stderr.flush()
    if hasattr(args, 'func'):
        # print(f"DEBUG: Calling func for command {args.command}", file=sys.stderr) # Debug prints removed
        # sys.stderr.flush()
        args.func(args)
    else:
        # print("DEBUG: No func attribute on args object. Dumping help.", file=sys.stderr) # Debug prints removed
        # sys.stderr.flush()
        parser.print_help()

    # print("DEBUG: main() finished.", file=sys.stderr) # Debug prints removed
    # sys.stderr.flush()

if __name__ == "__main__":
    main()
