import os
import zipfile
import argparse
import re

def get_package_name_from_wheel_filename(filename):
    """
    Extracts the package name from a wheel filename.
    Example: flask-2.0.1-py3-none-any.whl -> flask
    """
    match = re.match(r"^(.*?)-.*?\.whl$", os.path.basename(filename))
    if match:
        return match.group(1)
    return "unknown_package"

def install_wheel(wheel_path, target_dir):
    """
    Installs a downloaded .whl file to a target directory.
    """
    package_name = get_package_name_from_wheel_filename(wheel_path)
    print(f"Attempting to install package: {package_name}")
    print(f"Source wheel file: {wheel_path}")
    print(f"Target directory: {target_dir}")

    if not wheel_path.endswith(".whl"):
        print(f"Error: Invalid file format. Expected a .whl file, got {wheel_path}")
        return False

    if not os.path.exists(wheel_path):
        print(f"Error: Wheel file not found at {wheel_path}")
        return False

    if not zipfile.is_zipfile(wheel_path):
        print(f"Error: File is not a valid ZIP archive (or corrupted wheel): {wheel_path}")
        return False

    try:
        # Create the target directory if it doesn't exist
        os.makedirs(target_dir, exist_ok=True)
        print(f"Ensured target directory exists: {target_dir}")

        # Extract the wheel file
        with zipfile.ZipFile(wheel_path, 'r') as wheel_zip:
            print(f"Extracting contents of {os.path.basename(wheel_path)} to {target_dir}...")
            wheel_zip.extractall(path=target_dir)

        print(f"Successfully installed {package_name} to {target_dir}")
        return True

    except zipfile.BadZipFile:
        print(f"Error: Bad ZIP file or corrupted wheel: {wheel_path}")
        return False
    except IOError as e:
        print(f"Error: File I/O error during installation: {e}")
        return False
    except OSError as e:
        print(f"Error: OS error during installation (e.g., permissions, disk full): {e}")
        return False
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Install a .whl package file to a target directory.")
    parser.add_argument("wheel_file_path", help="Path to the .whl file.")
    parser.add_argument("target_directory", help="Path to the target installation directory (e.g., ./target_env/site-packages/).")

    args = parser.parse_args()

    if install_wheel(args.wheel_file_path, args.target_directory):
        print("Installation completed successfully.")
    else:
        print("Installation failed.")
