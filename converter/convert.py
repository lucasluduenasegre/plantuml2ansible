import argparse
import ipaddress
import os
import re
import sys

from jinja2 import Environment, FileSystemLoader, TemplateNotFound


# region Colour helpers
def _colourise(text, code):
    if sys.stderr.isatty():
        return f"\033[{code}m{text}\033[0m"
    return text


def err(text):
    return _colourise(text, "91")  # bright red


def warn(text):
    return _colourise(text, "93")  # bright yellow


def bold(text):
    return _colourise(text, "1")  # bold (any colour)


# endregion


# region parse_nwdiag
def parse_nwdiag(puml_text):
    networks = {}
    current_network = None
    # Track line numbers per hostname for second-pass subnet validation
    host_line_numbers = {}
    diagram_name = None

    ENVIRONMENT_SUBNET = ipaddress.IPv4Network("172.26.0.0/16")

    for line_number, line in enumerate(puml_text.splitlines(), start=1):
        line = re.sub(r"//.*", "", line).strip()

        # Extract diagram name from @startnwdiag
        start_match = re.match(r"@startnwdiag(?:\s+([\w-]+))?", line)
        if start_match:
            diagram_name = start_match.group(1)  # None if no name given

        net_match = re.match(r"network\s+([\w-]+)\s*\{", line)
        if net_match:
            current_network = net_match.group(1)
            networks[current_network] = {"subnet": None, "netmask": None, "hosts": {}}

        addr_match = re.match(r"address\s*=\s*([\d.]+/\d+)", line)
        if addr_match and current_network:
            try:
                cidr = ipaddress.IPv4Network(addr_match.group(1), strict=False)
            except ValueError:
                print(
                    err(
                        f"Error on line {line_number}: invalid CIDR '{addr_match.group(1)}'."
                    ),
                    file=sys.stderr,
                )
                sys.exit(1)

            # ↓ Add this block
            if not cidr.subnet_of(ENVIRONMENT_SUBNET):
                print(
                    err(
                        f"Error on line {line_number}: network '{current_network}' "
                        f"({cidr}) is not within the allowed environment subnet {ENVIRONMENT_SUBNET}."
                    ),
                    file=sys.stderr,
                )
                sys.exit(1)

            networks[current_network]["subnet"] = str(cidr.network_address)
            networks[current_network]["netmask"] = str(cidr.netmask)

        host_match = re.match(r"([\w-]+)\s*\[([^\]]+)\]", line)
        if host_match and current_network:
            identifier = host_match.group(1)
            attrs = host_match.group(2)

            label_match = re.search(r'label\s*=\s*"?([\w-]+)"?', attrs)
            hostname = (
                label_match.group(1) if label_match else identifier.replace("_", "-")
            )

            ip_match = re.search(r'address\s*=\s*"?([\d.]+)"?', attrs)
            if ip_match:
                raw_ip = ip_match.group(1)
                try:
                    ip = ipaddress.IPv4Address(raw_ip)
                    networks[current_network]["hosts"][hostname] = str(ip)
                    host_line_numbers[hostname] = line_number
                except ValueError:
                    print(
                        err(
                            f"Error on line {line_number}: invalid IP address '{raw_ip}' for host '{hostname}'."
                        ),
                        file=sys.stderr,
                    )
                    sys.exit(1)
                cpus_match = re.search(r"cpus\s*=\s*(\d+)", attrs)
                memory_match = re.search(r"memory\s*=\s*(\d+)", attrs)

                networks[current_network]["hosts"][hostname] = {
                    "ip": str(ip),
                    "cpus": int(cpus_match.group(1)) if cpus_match else 1,
                    "memory": int(memory_match.group(1)) if memory_match else 512,
                }

    # Second pass: validate all host IPs against their subnet
    # (handles cases where address = line appears after host definitions)
    for net_name, net_data in networks.items():
        subnet = net_data.get("subnet")
        netmask = net_data.get("netmask")
        if not subnet or not netmask:
            continue
        network_obj = ipaddress.IPv4Network(f"{subnet}/{netmask}")
        for hostname, host_data in net_data["hosts"].items():
            if ipaddress.IPv4Address(host_data["ip"]) not in network_obj:
                line_number = host_line_numbers.get(hostname, "unknown")
                print(
                    err(
                        f"Error on line {line_number}: host '{hostname}' has IP {ip}, which is not within subnet {network_obj}."
                    ),
                    file=sys.stderr,
                )
                sys.exit(1)

    return networks, diagram_name


# endregion


# region convert
def convert(puml_path):
    if not os.path.isfile(puml_path):
        print(f"Error: file not found: {puml_path}", file=sys.stderr)
        sys.exit(1)

    with open(puml_path) as f:
        networks, diagram_name = parse_nwdiag(f.read())

    if not networks:
        print(
            err(f"Error: no networks found in {puml_path}. Is it a valid nwdiag file?"),
            file=sys.stderr,
        )
        sys.exit(1)

    if not diagram_name:
        # Fall back to the filename if @startnwdiag has no name
        diagram_name = os.path.splitext(os.path.basename(puml_path))[0]
        print(
            warn(
                f"Warning: no diagram name found in file, using '{diagram_name}' from filename."
            )
        )

    # Create required directories in output folder
    output_env_path = os.path.join("output", diagram_name)
    output_env_ansible_path = os.path.join(output_env_path, "ansible")
    paths = [output_env_path, output_env_ansible_path]
    for path in paths:
        os.makedirs(path, exist_ok=True)

    # Load templates
    env = Environment(
        loader=FileSystemLoader("templates/"), trim_blocks=True, lstrip_blocks=True
    )

    # Then use output_env_path in your open() calls:

    # Render Ansible inventory
    try:
        inventory = env.get_template("inventory.yml.j2")
    except TemplateNotFound:
        print(
            err("Error: template 'inventory.yml.j2' not found in templates/"),
            file=sys.stderr,
        )
        sys.exit(1)
    with open(os.path.join(output_env_path, "inventory.yml"), "w") as f:
        f.write(inventory.render(networks=networks))
    print(
        f'Generated Ansible inventory "{os.path.join(output_env_ansible_path, "inventory.yml")}"'
    )

    # Render Vagrant hosts
    try:
        vagrant = env.get_template("vagrant-hosts.yml.j2")
    except TemplateNotFound:
        print(
            err("Error: template 'vagrant-hosts.yml.j2' not found in templates/"),
            file=sys.stderr,
        )
        sys.exit(1)
    with open(os.path.join(output_env_ansible_path, "vagrant-hosts.yml"), "w") as f:
        f.write(vagrant.render(networks=networks))
    print(
        f'Generated Vagrant hosts file "{os.path.join(output_env_path, "vagrant-hosts.yml")}"'
    )


# endregion


# region main
def main():
    parser = argparse.ArgumentParser(
        description="Convert PlantUML nwdiag to Ansible inventory"
    )
    parser.add_argument("puml_path", help="Path to the .puml input file")
    args = parser.parse_args()
    convert(puml_path=args.puml_path)


if __name__ == "__main__":
    main()
# endregion
