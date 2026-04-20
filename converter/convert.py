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
        # Ignore comments
        line = re.sub(r"//.*", "", line).strip()

        # Extract diagram name from @startnwdiag
        start_nwdiag_regex = re.match(r"@startnwdiag(?:\s+([\w-]+))?", line)
        if start_nwdiag_regex:
            diagram_name = start_nwdiag_regex.group(1) # If unset, falls back to filename in convert()

        network_regex = re.match(r"network\s+([\w-]+)\s*\{", line)
        if network_regex:
            current_network = network_regex.group(1)
            networks[current_network] = {"subnet": None, "netmask": None, "hosts": {}}

        network_address_regex = re.match(r"address\s*=\s*([\d.]+/\d+)", line)
        if network_address_regex and current_network:
            try:
                cidr = ipaddress.IPv4Network(network_address_regex.group(1), strict=False)
            except ValueError:
                print(
                    err(
                        f"Error on line {line_number}: invalid CIDR '{network_address_regex.group(1)}'."
                    ),
                    file=sys.stderr,
                )
                sys.exit(1)

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

        host_regex = re.match(r"([\w-]+)\s*\[([^\]]+)\]", line)
        if host_regex and current_network:
            # Default identifier is the first word
            identifier = host_regex.group(1)
            attrs = host_regex.group(2)

            # Sets the hostname based on the description variable in the attributes, otherwise falls back on the previously defined identifier
            host_description_regex = re.search(r'description\s*=\s*"?([\w-]+)"?', attrs)
            hostname = (
                # Underscores will be converted to hyphens due to Unix conventions
                host_description_regex.group(1) if host_description_regex else identifier.replace("_", "-")
            )

            host_address_regex = re.search(r'address\s*=\s*"?([\d.]+)"?', attrs)
            if host_address_regex:
                raw_ip = host_address_regex.group(1)
                try:
                    ip = ipaddress.IPv4Address(raw_ip)
                except ValueError:
                    print(
                        err(
                            f"Error on line {line_number}: invalid IP address '{raw_ip}' for host '{hostname}'."
                        ),
                        file=sys.stderr,
                    )
                    sys.exit(1)

                host_cpus_regex = re.search(r"cpus\s*=\s*(\d+)", attrs)
                host_memory_regex = re.search(r"memory\s*=\s*(\d+)", attrs)

                # ↓ This block replaces the old single assignment
                if hostname not in networks[current_network]["hosts"]:
                    networks[current_network]["hosts"][hostname] = {
                        "ips": [str(ip)],
                        "networks": [
                            current_network
                        ],  # ← store network name, not netmask
                        "cpus": int(host_cpus_regex.group(1)) if host_cpus_regex else 1,
                        "memory": int(host_memory_regex.group(1)) if host_memory_regex else 512,
                    }
                else:
                    networks[current_network]["hosts"][hostname]["ips"].append(str(ip))
                    networks[current_network]["hosts"][hostname]["networks"].append(
                        current_network
                    )

                host_line_numbers[hostname] = line_number

    # Resolve netmasks now that all network address= lines have been parsed
    for _, net_data in networks.items():
        for hostname, host_data in net_data["hosts"].items():
            host_data["netmasks"] = [
                networks[net]["netmask"] for net in host_data["networks"]
            ]

    # Second pass: validate all host IPs against their subnet
    # (handles cases where address = line appears after host definitions)
    for _, net_data in networks.items():
        subnet = net_data.get("subnet")
        netmask = net_data.get("netmask")
        if not subnet or not netmask:
            continue
        network_obj = ipaddress.IPv4Network(f"{subnet}/{netmask}")
        for hostname, host_data in net_data["hosts"].items():
            for host_ip in host_data["ips"]:
                if ipaddress.IPv4Address(host_ip) not in network_obj:
                    line_number = host_line_numbers.get(hostname, "unknown")
                    print(
                        err(
                            f"Error on line {line_number}: host '{hostname}' has IP {host_ip}, "
                            f"which is not within subnet {network_obj}."
                        ),
                        file=sys.stderr,
                    )
                    sys.exit(1)

    return networks, diagram_name


# endregion

# region debug_print
def debug_print(diagram_name, networks):
    print(bold(f"\n=== Parsed diagram: '{diagram_name}' ===\n"))
    for net_name, net_data in networks.items():
        print(bold(f"  Network: {net_name}"))
        print(f"    Subnet : {net_data['subnet']}/{net_data['netmask']}")
        if net_data["hosts"]:
            print("    Hosts  :")
            for hostname, host_data in net_data["hosts"].items():
                ips = ", ".join(
                    f"{ip} ({nm})"
                    for ip, nm in zip(host_data["ips"], host_data["netmasks"])
                )
                print(f"      - {hostname}")
                print(f"          IPs     : {ips}")
                print(f"          CPUs    : {host_data['cpus']}")
                print(f"          Memory  : {host_data['memory']} MB")
                print(f"          Networks: {', '.join(host_data['networks'])}")
        else:
            print("    Hosts  : (none)")
        print()
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

    debug_print(diagram_name, networks)

    # Create required directories in output folder
    output_env_path = os.path.join("output", diagram_name)
    output_env_ansible_path = os.path.join(output_env_path, "ansible")
    paths = [output_env_path, output_env_ansible_path]
    for path in paths:
        os.makedirs(path, exist_ok=True)

    # Load templates
    env = Environment(
        loader=FileSystemLoader("templates/"),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["zip"] = zip

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
    with open(os.path.join(output_env_ansible_path, "inventory.yml"), "w") as f:
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

    all_hosts = {}
    for net_data in networks.values():
        for hostname, host_data in net_data["hosts"].items():
            if hostname not in all_hosts:
                all_hosts[hostname] = {
                    "ips": list(host_data["ips"]),
                    "netmasks": list(host_data["netmasks"]),
                    "cpus": host_data["cpus"],
                    "memory": host_data["memory"],
                }
            # Merge IPs and netmasks from subsequent network appearances
            else:
                for ip, netmask in zip(host_data["ips"], host_data["netmasks"]):
                    if ip not in all_hosts[hostname]["ips"]:
                        all_hosts[hostname]["ips"].append(ip)
                        all_hosts[hostname]["netmasks"].append(netmask)

    with open(os.path.join(output_env_path, "vagrant-hosts.yml"), "w") as f:
        f.write(vagrant.render(networks=networks, all_hosts=all_hosts))
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
