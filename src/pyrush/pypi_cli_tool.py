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
# Attempting to integrate packaging again
from packaging.requirements import Requirement, InvalidRequirement
from packaging.version import parse as parse_version

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

def query_pypi_simple_api(package_name):
    url = f"https://pypi.org/simple/{package_name}/"
    try: response = requests.get(url); response.raise_for_status(); return response.text
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404: print(f"Package '{package_name}' not found on PyPI (404 Error).")
        else: print(f"HTTP error querying PyPI for {package_name}: {e}")
    except requests.exceptions.RequestException as e: print(f"Network error querying PyPI for {package_name}: {e}")
    return None

def parse_simple_api_html(html_content, package_name):
    soup = BeautifulSoup(html_content, 'html.parser'); files = []
    norm_pkg_name = re.sub(r"[-_.]+", "-", package_name).lower()
    for a in soup.find_all('a'):
        href = a.get('href'); fname = a.text.strip()
        if href and fname:
            v, ftype, pname = "unknown", "unknown", "unknown"
            whl = re.match(r"^(.*?)-(.*?)-(.*?)-(.*?)-(.*?)\.whl$", fname, re.IGNORECASE)
            gz = re.match(r"^(.*?)-(.*?)\.tar\.gz$", fname, re.IGNORECASE)
            zipf = re.match(r"^(.*?)-(.*?)\.zip$", fname, re.IGNORECASE)
            if whl: ftype,pname,v = "wheel",whl.group(1),whl.group(2)
            elif gz: ftype,pname,v = "sdist",gz.group(1),gz.group(2)
            elif zipf: ftype,pname,v = "sdist",zipf.group(1),zipf.group(2)
            if re.sub(r"[-_.]+", "-", pname).lower() == norm_pkg_name:
                files.append({"filename":fname,"url":href,"version":v,"type":ftype,"package_name":pname})
    return files

def select_distribution_file(files_info, package_name, target_version=None):
    if not files_info: return None
    eligible = [f for f in files_info if f['version'] == target_version] if target_version else files_info
    if not eligible and target_version: print(f"No files for version {target_version} of {package_name}."); return None
    if not target_version:
        try: eligible.sort(key=lambda x: x['version'], reverse=True)
        except TypeError: print("Warning: Could not reliably sort versions.")
    wheels = [f for f in eligible if f['type'] == 'wheel']
    if wheels: print(f"Selected wheel: {wheels[0]['filename']} (v {wheels[0]['version']})"); return wheels[0]['url']
    sdists = [f for f in eligible if f['type'] == 'sdist']
    if sdists: print(f"Selected sdist: {sdists[0]['filename']} (v {sdists[0]['version']})"); return sdists[0]['url']
    if target_version: print(f"Files for version {target_version} found, but no wheel/sdist.")
    return None

# --- Dependency Resolution ---
def get_package_metadata_json(package_name):
    url = f"https://pypi.org/pypi/{package_name}/json"
    try: response = requests.get(url); response.raise_for_status(); return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404: print(f"Package '{package_name}' not on PyPI (JSON API).")
        else: print(f"HTTP error (JSON API) for {package_name}: {e}")
    except requests.exceptions.RequestException as e: print(f"Network error (JSON API) for {package_name}: {e}")
    except requests.exceptions.JSONDecodeError as e: print(f"JSON decode error for {package_name}: {e}")
    return None

def parse_dependency_string(dep_string): # Simple parser, used when packaging is not available/reverted
    match = re.match(r"^\s*([a-zA-Z0-9._-]+)", dep_string)
    return match.group(1).strip() if match else None

MAX_RECURSION_DEPTH = 20
def resolve_dependencies_recursive(pkg_name, processed, all_deps, depth=0):
    norm_name = pkg_name.lower().replace("_", "-")
    if depth > MAX_RECURSION_DEPTH: print(f"{'  '*depth}ERR: Max depth for {norm_name}.", file=sys.stderr); return
    if norm_name in processed: return
    print(f"Processing: {norm_name}")
    processed.add(norm_name); all_deps.add(norm_name)
    meta = get_package_metadata_json(norm_name)
    if not meta and pkg_name != norm_name: meta = get_package_metadata_json(pkg_name)
    if not meta: print(f"No metadata for {pkg_name}. Skip deps."); return
    reqs = meta.get("info", {}).get("requires_dist")
    if reqs:
        for dep_s in reqs:
            dep_name = parse_dependency_string(dep_s)
            if dep_name:
                if ";" in dep_s:
                    m_str = dep_s.split(";",1)[1].strip()
                    if "extra ==" in m_str or "python_version" in m_str : pass
                resolve_dependencies_recursive(dep_name, processed, all_deps, depth + 1)
            else: print(f"Warn: Cannot parse dep string: '{dep_s}' for {pkg_name}", file=sys.stderr)
    else: print(f"No 'requires_dist' for {pkg_name}.")

# --- Combined Download Logic ---
def download_package_simple_latest(pkg_name, dl_dir, use_cache=True, cache_path=None):
    norm_q_name = pkg_name.lower().replace("_", "-")
    print(f"Processing package for download: {norm_q_name} (original: {pkg_name})")
    html = query_pypi_simple_api(norm_q_name)
    if not html: err="Simple API query failed."; print(f"  ERR: {err}"); return pkg_name,None,err
    files = parse_simple_api_html(html, norm_q_name)
    if not files: err="No files on Simple API."; print(f"  ERR: {err}"); return pkg_name,None,err
    url = select_distribution_file(files, norm_q_name, None)
    if not url: err="No suitable file selected."; print(f"  ERR: {err}"); return pkg_name,None,err
    fname = url.split('/')[-1].split('#')[0]
    dl_path = download_file(url,dl_dir,fname,use_cache,cache_path)
    if dl_path: return pkg_name, dl_path, None
    else: err=f"Download failed for {norm_q_name} from {url}."; return pkg_name,None,err

# --- Command Handlers ---
def handle_resolve_command(args):
    print(f"--- Resolving dependencies for {args.package_name} ---")
    all_deps=set(); processed=set()
    resolve_dependencies_recursive(args.package_name, processed, all_deps, 0)
    print("\nAll unique dependencies:"); [print(f"- {d}") for d in sorted(list(all_deps))]
    print("--- Resolution finished ---")

def handle_download_command(args):
    print(f"--- Downloading: {args.package_name} {args.version or '(latest)'} to {os.path.abspath(args.output_dir)} ---")
    use_cache=not args.no_cache; cache_dir=get_cache_dir(args.cache_dir) if use_cache else None
    if use_cache:
        print(f"--- Cache enabled. Cache directory: {cache_dir} ---")
    else: print("--- Cache disabled ---")
    pkg_to_dl = args.package_name
    html = query_pypi_simple_api(pkg_to_dl)
    if not html: print(f"No Simple API page for {pkg_to_dl}."); print("--- Download finished ---"); return
    files = parse_simple_api_html(html, pkg_to_dl)
    if not files: print(f"No files for {pkg_to_dl}."); print("--- Download finished ---"); return
    url = select_distribution_file(files, pkg_to_dl, args.version)
    if url: fname=url.split('/')[-1].split('#')[0]; print(f"Selected: {fname}"); download_file(url,args.output_dir,fname,use_cache,cache_dir)
    else: print(f"No suitable file for {pkg_to_dl} {args.version or '(latest)'}.")
    print("--- Download finished ---")

def handle_install_command(args):
    target_dir = args.target_dir
    if not target_dir:
        print_verbose("No target directory specified. Auto-determining...")
        target_dir = determine_target_install_dir()
        if target_dir: print(f"Using auto-determined target: {target_dir}\nUse --target-dir to override.")
        else: print("ERR: No suitable target dir. Use --target-dir.", file=sys.stderr); sys.exit(1)

    print(f"--- Full install: {args.package_name} to {os.path.abspath(target_dir)} ---")
    use_cache=not args.no_cache; cache_dir=get_cache_dir(args.cache_dir) if use_cache else None
    if use_cache: print(f"--- Cache enabled. Cache directory: {cache_dir} ---")
    else: print("--- Cache disabled ---")

    all_deps=set(); processed=set()
    print(f"\nStep 1: Resolving {args.package_name}...")
    resolve_dependencies_recursive(args.package_name, processed, all_deps, 0)
    if not all_deps: print("No deps. Abort."); print("--- Install finished ---"); return

    dl_intermed_dir="./downloads"; os.makedirs(dl_intermed_dir, exist_ok=True)
    print(f"\nStep 2: Download {len(all_deps)} pkgs to '{dl_intermed_dir}' (max {args.max_workers} workers)...")
    sorted_deps=sorted(list(all_deps)); dl_results=[]; good_wheels=[]
    worker = functools.partial(download_package_simple_latest, dl_dir=dl_intermed_dir, use_cache=use_cache, cache_path=cache_dir)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        fm = {executor.submit(worker, n): n for n in sorted_deps}
        for i, f in enumerate(concurrent.futures.as_completed(fm)):
            pkg_n_done=fm[f]
            try:
                name_returned_by_worker, path, error = f.result()
                dl_results.append({"name":name_returned_by_worker,"path":path,"error":error,"status":"OK" if path else "FAIL"})
                if path:
                    print(f"  OK DL [{i+1}/{len(sorted_deps)}] {name_returned_by_worker} to {path}")
                    good_wheels.append(path)
                else:
                    print(f"  FAIL DL [{i+1}/{len(sorted_deps)}] {name_returned_by_worker}. Err: {error}")
            except Exception as exc:
                print(f"  EXC DL [{i+1}/{len(sorted_deps)}] {pkg_n_done} generated: {exc}")
                dl_results.append({"name":pkg_n_done,"path":None,"error":str(exc),"status":"EXC"})
    print("\nDL Summary:"); dl_ok=len(good_wheels); print(f"  {dl_ok}/{len(dl_results)} DLed OK.")
    if dl_ok < len(dl_results): print("  Failed/Skipped DLs:"); [print(f"    - {r['name']}: {r['error']}") for r in dl_results if r["status"] != "OK"]

    if good_wheels:
        print(f"\nStep 3: Install {len(good_wheels)} pkgs to {target_dir} (max {args.max_workers} workers)...")
        inst_results=[]
        inst_script=os.path.join(os.path.dirname(os.path.abspath(__file__)),"package_installer.py")
        if not os.path.exists(inst_script): print(f"  ERR: {inst_script} not found. No install.");
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=args.max_workers) as executor:
                fm_inst = {executor.submit(subprocess.run, [sys.executable,inst_script,wheel,target_dir],capture_output=True,text=True): wheel for wheel in good_wheels}
                for i,f in enumerate(concurrent.futures.as_completed(fm_inst)):
                    whl_done=fm_inst[f]; pkg_whl_name=os.path.basename(whl_done).split('-',1)[0]
                    try:
                        res=f.result()
                        if res.returncode==0:
                            print(f"  OK Inst [{i+1}/{len(good_wheels)}] {pkg_whl_name}")
                            inst_results.append({"name":pkg_whl_name,"status":"OK"})
                        else:
                            print(f"  FAIL Inst [{i+1}/{len(good_wheels)}] {pkg_whl_name}.\n    Stdout:\n{res.stdout.strip()}\n    Stderr:\n{res.stderr.strip()}")
                            inst_results.append({"name":pkg_whl_name,"status":"FAIL","error":res.stderr})
                    except Exception as exc:
                        print(f"  EXC Inst [{i+1}/{len(good_wheels)}] {pkg_whl_name} generated: {exc}")
                        inst_results.append({"name":pkg_whl_name,"status":"EXC","error":str(exc)})
            print("\nInstall Summary:"); inst_ok_cnt=sum(1 for r in inst_results if r["status"]=="OK"); print(f"  {inst_ok_cnt}/{len(inst_results)} installed OK.")
            if inst_ok_cnt < len(inst_results): print("  Failed/Skipped Installs:"); [print(f"    - {r['name']}: {r.get('error','N/A')}") for r in inst_results if r["status"] != "OK"]
    else: print("\nStep 3: Install skipped, no pkgs DLed.")
    print("--- Full install process finished ---")

def main():
    # Minimal test for packaging library
    print("--- Starting minimal packaging library test ---", file=sys.stderr)
    sys.stderr.flush()
    test_passed = False
    try:
        # Test import and basic usage
        # from packaging.requirements import Requirement, InvalidRequirement # Already at top
        # from packaging.version import parse as parse_version # Already at top

        print("Successfully imported 'packaging' modules.", file=sys.stderr)
        sys.stderr.flush()

        test_version_str = "1.2.3"
        parsed_version = parse_version(test_version_str) # Uses top-level import
        print(f"Parsed version '{test_version_str}': {parsed_version}", file=sys.stderr)
        sys.stderr.flush()

        test_req_str = "requests>2.0"
        req = Requirement(test_req_str) # Uses top-level import
        print(f"Parsed requirement '{test_req_str}': Name='{req.name}', Specifier='{req.specifier!s}', Markers='{req.marker!s}'", file=sys.stderr)
        sys.stderr.flush()

        test_complex_req_str = "sphinxcontrib-applehelp; extra == 'docs_html'"
        complex_req = Requirement(test_complex_req_str)
        print(f"Successfully parsed complex requirement: Name='{complex_req.name}', Specifier='{complex_req.specifier!s}', Markers='{complex_req.marker!s}'", file=sys.stderr)
        sys.stderr.flush()

        test_passed = True
    except Exception as e:
        print(f"Error during minimal packaging test: {e}", file=sys.stderr)
        sys.stderr.flush()

    if test_passed:
        print("--- Minimal packaging library test: SUCCEEDED ---", file=sys.stderr)
    else:
        print("--- Minimal packaging library test: FAILED ---", file=sys.stderr)
    sys.stderr.flush()

    print("Exiting after minimal packaging test. Main CLI logic will not run.", file=sys.stderr)
    sys.stderr.flush()
    return # IMPORTANT: Exit after the test

    # Original argparse and command handling logic remains below this return,
    # but will not be executed during this specific test.
    # parser = argparse.ArgumentParser(description="PyRush: PyPI Package Management Tool")
    # # ... (rest of main) ...

if __name__ == "__main__":
    main()
