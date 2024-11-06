import re
from os.path import dirname
import subprocess

# Run pip list and filter for "ovos-" packages
result = subprocess.run(['pip', 'list', '--format=freeze'], capture_output=True, text=True)
packages = result.stdout.splitlines()

stable_constraints = []
testing_constraints = []

# Regular expression to capture package name and version, with optional alpha tag
pattern = re.compile(r'^(ovos-[\w-]+)==(\d+)\.(\d+)\.(\d+)(a\d+)?$')

for package in packages:
    match = pattern.match(package)
    if match:
        name, major, minor, patch, alpha = match.groups()
        major = stable_major = int(major)
        minor = stable_minor = int(minor)
        patch = int(patch)
        print(package)
        stable_constraints.append(f"{name}<{major}.{minor + 1}.0")
        testing_constraints.append(f"{name}<{major+1}.0.0")

base = f"{dirname(dirname(__file__))}/requirements"

# Write stable and testing constraints to respective files
with open(f'{base}/constraints-stable.txt', 'w') as stable_file:
    stable_file.write("\n".join(stable_constraints))

with open(f'{base}/constraints-testing.txt', 'w') as testing_file:
    testing_file.write("\n".join(testing_constraints))

print("Constraints files generated: constraints-stable.txt and constraints-testing.txt")
