import argparse
import ipaddress
import os
import re
import sys

from jinja2 import Environment, FileSystemLoader, TemplateNotFound

# region Colour helpers
# These functions wrap text in ANSI escape codes for coloured terminal output.
# The check on sys.stderr.isatty() makes sure escape codes are only added when
# the output is an actual terminal -- if the output is redirected to a file or
# a pipe, plain text is returned instead.
def _colourise(text, code):
    if sys.stderr.isatty():
        return f"\033[{code}m{text}\033[0m"
    return text

def err(text):
    return _colourise(text, "91")   # bright red

def warn(text):
    return _colourise(text, "93")   # bright yellow

def bold(text):
    return _colourise(text, "1")    # bold (any colour)
# endregion

# region Global variables
# The environment subnet all networks in the diagram must fall within.
# This is checked during parsing to catch misconfigured addresses early.
ENVIRONMENT_SUBNET = ipaddress.IPv4Network("172.26.0.0/16")

# Each entry maps a Jinja2 template (relative to templates/) to its output
# path (relative to the environment output directory). Adding a new file to
# the converter means adding one line here and one entry in render_context
# inside convert().
TEMPLATES = [
    ("ansible/inventory.yml.j2", "ansible/inventory.yml"),
    ("vagrant-hosts.yml.j2",     "vagrant-hosts.yml"),
]
# endregion

# region detect_diagram_type()
# Reads the first non-empty, non-comment line of the file to determine which
# kind of PlantUML diagram it is. Returns "nwdiag" for @startnwdiag and "uml"
# for @startuml. Exits with an error if neither is found.
def detect_diagram_type(puml_text):
    for line in puml_text.splitlines():
        line = re.sub(r"//.*", "", line).strip()
        if not line:
            continue
        if line.startswith("@startnwdiag"):
            return "nwdiag"
        if line.startswith("@startuml"):
            return "uml"
        # Stop at the first meaningful line -- if it is neither, the file is unsupported.
        print(err(f"Error: unrecognised diagram type '{line}'. Expected @startnwdiag or @startuml."), file=sys.stderr)
        sys.exit(1)
    print(err("Error: file appears to be empty or contains only comments."), file=sys.stderr)
    sys.exit(1)
# endregion

# region parse_nwdiag()
def parse_nwdiag(puml_text):
    networks = {}
    current_network = None
    # Keeps track of which line each hostname was last seen on, so that the
    # second-pass IP validation can report a useful line number on error.
    host_line_numbers = {}
    diagram_name = None

    for line_number, line in enumerate(puml_text.splitlines(), start=1):
        # Strip inline comments before processing each line.
        line = re.sub(r"//.*", "", line).strip()

        # The @startnwdiag line optionally carries a diagram name that is used
        # later as the output directory name.
        start_nwdiag_regex = re.match(r'@startnwdiag(?:\s+"?([\w-]+)"?)?', line)
        if start_nwdiag_regex:
            diagram_name = start_nwdiag_regex.group(1)  # falls back to filename in convert()

        # A new network block resets current_network and creates an empty entry.
        network_regex = re.match(r'network\s+"?([\w-]+)"?\s*\{', line)
        if network_regex:
            current_network = network_regex.group(1)
            networks[current_network] = {"subnet": None, "netmask": None, "hosts": {}}

        # The address line inside a network block defines the subnet in CIDR
        # notation. The subnet and netmask are stored separately for use in
        # the Vagrant hosts template.
        network_address_regex = re.match(r'address\s*=\s*"?([\d.]+/\d+)"?', line)
        if network_address_regex and current_network:
            try:
                cidr = ipaddress.IPv4Network(network_address_regex.group(1), strict=False)
            except ValueError:
                print(
                    err(f"Error on line {line_number}: invalid CIDR '{network_address_regex.group(1)}'."),
                    file=sys.stderr,
                )
                sys.exit(1)

            networks[current_network]["subnet"] = str(cidr.network_address)
            networks[current_network]["netmask"] = str(cidr.netmask)

        # A host line has the form: hostname [attr = value, ...].
        # The attributes block is parsed separately for each known attribute.
        host_regex = re.match(r"([\w-]+)\s*\[([^\]]+)\]", line)
        if host_regex and current_network:
            identifier = host_regex.group(1)
            attrs = host_regex.group(2)

            # The description attribute overrides the identifier as the hostname.
            # Any underscores in the identifier are converted to hyphens to follow
            # Unix hostname conventions.
            host_description_regex = re.search(r'description\s*=\s*"?([\w-]+)"?', attrs)
            hostname = (
                host_description_regex.group(1) if host_description_regex else identifier.replace("_", "-")
            )

            # Hosts with managed = false are skipped entirely and not added to
            # the output. This allows the diagram to include unmanaged devices
            # (e.g. external routers) for documentation purposes.
            host_managed_regex = re.search(r'managed\s*=\s*"?(true|false)"?', attrs, re.I)
            host_is_managed = host_managed_regex.group(1) != "false" if host_managed_regex else True

            host_address_regex = re.search(r'address\s*=\s*"?([\d.]+)"?', attrs)
            if host_address_regex and host_is_managed:
                raw_ip = host_address_regex.group(1)
                try:
                    ip = ipaddress.IPv4Address(raw_ip)
                except ValueError:
                    print(
                        err(f"Error on line {line_number}: invalid IP address '{raw_ip}' for host '{hostname}'."),
                        file=sys.stderr,
                    )
                    sys.exit(1)

                # Optional resource attributes for Vagrant. If not specified,
                # sensible defaults are used (1 CPU, 512 MB RAM, AlmaLinux 9).
                host_cpus_regex   = re.search(r'cpus\s*=\s*"?(\d+)"?', attrs)
                host_memory_regex = re.search(r'memory\s*=\s*"?(\d+)"?', attrs)
                host_box_regex    = re.search(r'box\s*=\s*"?([^"]+)"?', attrs)

                # If this hostname already exists in the network (i.e. it appears
                # in multiple network blocks), its IP and network name are appended
                # to the existing entry rather than creating a duplicate.
                if hostname not in networks[current_network]["hosts"]:
                    networks[current_network]["hosts"][hostname] = {
                        "ips":      [str(ip)],
                        "networks": [current_network],
                        "cpus":     int(host_cpus_regex.group(1))   if host_cpus_regex   else 1,
                        "memory":   int(host_memory_regex.group(1)) if host_memory_regex else 512,
                        "box":      host_box_regex.group(1)         if host_box_regex    else "almalinux/9",
                    }
                else:
                    networks[current_network]["hosts"][hostname]["ips"].append(str(ip))
                    networks[current_network]["hosts"][hostname]["networks"].append(current_network)

                host_line_numbers[hostname] = line_number

    # Drop any networks that ended up with no managed hosts. This can happen
    # when all hosts in a network have managed = false set, or when a network
    # block was added to the diagram purely for documentation purposes.
    networks = {k: v for k, v in networks.items() if v["hosts"]}

    # Now that all networks have been parsed, each host's list of network names
    # can be resolved to the corresponding netmasks. This is done in a separate
    # pass because the address = line for a network might appear after the host
    # definitions that reference it.
    for _, net_data in networks.items():
        for hostname, host_data in net_data["hosts"].items():
            host_data["netmasks"] = [
                networks[net]["netmask"] for net in host_data["networks"]
            ]

    # Second pass: confirm that every host IP actually falls within the subnet
    # of the network it belongs to. Checked after parsing so that it works
    # regardless of the order in which address = and host lines appear.
    for _, net_data in networks.items():
        subnet  = net_data.get("subnet")
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

# region debug_print()
# Prints a structured summary of the parsed data to stdout before any files
# are written. Useful for verifying that the parser read the diagram correctly.
def debug_print(diagram_name, networks):
    print(bold(f"\n=== Parsed diagram: '{diagram_name}' ===\n"))
    for net_name, net_data in networks.items():
        print(bold(f"  Network: {net_name}"))
        print(f"    Subnet  : {net_data['subnet']}/{net_data['netmask']}")
        if net_data["hosts"]:
            print("    Hosts   :")
            for hostname, host_data in net_data["hosts"].items():
                ips = ", ".join(
                    f"{ip} ({nm})"
                    for ip, nm in zip(host_data["ips"], host_data["netmasks"])
                )
                print(f"      - {hostname}")
                print(f"          IPs      : {ips}")
                print(f"          Networks : {', '.join(host_data['networks'])}")
                print(f"          CPUs     : {host_data['cpus']}")
                print(f"          Memory   : {host_data['memory']} MB")
                print(f"          Base box : {host_data['box']}")
        else:
            print("    Hosts   : (none)")
        print()
# endregion

# region validate_templates()
# Checks that every template listed in TEMPLATES exists before any rendering
# starts. All missing templates are reported at once rather than failing on the
# first one, so the user can fix them all in one go.
def validate_templates(env):
    missing_templates = []
    for template_path, _ in TEMPLATES:
        try:
            env.get_template(template_path)
        except TemplateNotFound:
            missing_templates.append(template_path)
    if missing_templates:
        for name in missing_templates:
            print(err(f"Error: template '{name}' not found in templates/"), file=sys.stderr)
        sys.exit(1)
# endregion

# region convert()
# This is the main entry point for the script. It reads the file, detects the 
# diagram type, and hands it off to the appropriate conversion function.
def convert(puml_path):
    if not os.path.isfile(puml_path):
        print(err(f"Error: file not found: {puml_path}"), file=sys.stderr)
        sys.exit(1)

    with open(puml_path) as f:
        puml_text = f.read()

    diagram_type = detect_diagram_type(puml_text)

    if diagram_type == "nwdiag":
        convert_nwdiag(puml_text)
    elif diagram_type == "uml":
        convert_uml(puml_text)
# endregion

# region convert_nwdiag()
# Handles network diagrams (@startnwdiag). Parses the diagram, renders the
# Ansible inventory and Vagrant hosts file from the extracted data.
def convert_nwdiag(puml_text):
    networks, diagram_name = parse_nwdiag(puml_text)

    if not networks:
        print(err("Error: no networks found in diagram. Is it a valid nwdiag file?"), file=sys.stderr)
        sys.exit(1)

    if not diagram_name:
        # There is no clean way to fall back to a filename here since convert_nwdiag()
        # no longer receives the path. If this fallback is important, puml_path can
        # be passed as an optional second argument.
        print(warn("Warning: no diagram name found in file. Output directory will be named 'unnamed'."))
        diagram_name = "unnamed"

    debug_print(diagram_name, networks)

    output_env_path = os.path.join("output", diagram_name)

    env = Environment(
        loader=FileSystemLoader("templates/"),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["zip"] = zip

    validate_templates(env)

    all_hosts = {}
    for net_data in networks.values():
        for hostname, host_data in net_data["hosts"].items():
            if hostname not in all_hosts:
                all_hosts[hostname] = {
                    "ips":      list(host_data["ips"]),
                    "netmasks": list(host_data["netmasks"]),
                    "cpus":     host_data["cpus"],
                    "memory":   host_data["memory"],
                    "box":      host_data["box"],
                }
            else:
                for ip, netmask in zip(host_data["ips"], host_data["netmasks"]):
                    if ip not in all_hosts[hostname]["ips"]:
                        all_hosts[hostname]["ips"].append(ip)
                        all_hosts[hostname]["netmasks"].append(netmask)

    render_context = {
        "ansible/inventory.yml.j2": {"networks": networks},
        "vagrant-hosts.yml.j2":     {"networks": networks, "all_hosts": all_hosts},
    }

    for template_name, output_relative_path in TEMPLATES:
        template    = env.get_template(template_name)
        output_path = os.path.join(output_env_path, output_relative_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w") as f:
            f.write(template.render(**render_context[template_name]))
        print(f'Generated "{output_path}"')
# endregion

# region convert_uml()
# Handles deployment diagrams (@startuml). Not yet implemented.
def convert_uml(puml_text):
    print(err("Error: deployment diagram parsing is not yet implemented."), file=sys.stderr)
    sys.exit(1)
# endregion

# region main()
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