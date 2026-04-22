import argparse
import ipaddress
import os
import re
import sys
import yaml

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
    return _colourise(text, "91")  # bright red


def warn(text):
    return _colourise(text, "93")  # bright yellow


def bold(text):
    return _colourise(text, "1")  # bold (any colour)


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
    ("vagrant-hosts.yml.j2", "vagrant-hosts.yml"),
]
# endregion


# region detect_diagram_type()
# Reads the first non-empty, non-comment line of the file to determine which
# kind of PlantUML diagram it is. Returns "nwdiag" for @startnwdiag and "uml"
# for @startuml. Exits with an error if neither is found.
def detect_diagram_type(puml_text):
    comment_re = re.compile(r"'.*|//.*")
    startnwdiag_re = re.compile(r"@startnwdiag")
    startuml_re = re.compile(r"@startuml")

    for line in puml_text.splitlines():
        line = comment_re.sub("", line).strip()
        if not line:
            continue
        if startnwdiag_re.match(line):
            return "nwdiag"
        if startuml_re.match(line):
            return "uml"
        print(
            err(
                f"Error: unrecognised diagram type '{line}'. Expected @startnwdiag or @startuml."
            ),
            file=sys.stderr,
        )
        sys.exit(1)
    print(
        err("Error: file appears to be empty or contains only comments."),
        file=sys.stderr,
    )
    sys.exit(1)


# endregion


# region to_unix_hostname()
# Convert a PlantUML identifier to a Unix-compatible hostname.
def to_unix_hostname(identifier):
    return identifier.replace("_", "-")


# endregion


# region parse_nwdiag()
# Parses a @startnwdiag network diagram and returns the diagram name and networks.
def parse_nwdiag(puml_text):
    # Strip block comments (/' ... '/) before line-by-line parsing.
    # re.DOTALL makes . match newlines so multi-line blocks are caught.
    block_comment_re = re.compile(r"\/\*[\s\S]*?\*\/|\/'[\s\S]*?'\/", re.DOTALL)
    puml_text = block_comment_re.sub("", puml_text)

    # Patterns compiled once, reused for every line in the loop.
    comment_re = re.compile(r"^\s*(?:'|\/\/).*")
    start_re = re.compile(r'@startnwdiag(?:\s+"?([\w-]+)"?)?')
    network_re = re.compile(r'network\s+"?([\w-]+)"?\s*\{')
    network_address_re = re.compile(r'address\s*=\s*"?([\d.]+/\d+)"?')
    host_re = re.compile(r"([\w-]+)\s*\[([^\]]+)\]")
    description_re = re.compile(r'description\s*=\s*"?([\w-]+)"?')
    managed_re = re.compile(r'managed\s*=\s*"?(true|false)"?', re.I)
    host_address_re = re.compile(r'address\s*=\s*"?([\d.]+)"?')
    cpus_re = re.compile(r'cpus\s*=\s*"?(\d+)"?')
    memory_re = re.compile(r'memory\s*=\s*"?(\d+)"?')

    networks = {}
    current_network = None
    diagram_name = None
    host_line_numbers = {}

    for line_number, line in enumerate(puml_text.splitlines(), start=1):
        line = comment_re.sub("", line).strip()
        if not line:
            continue

        m = start_re.match(line)
        if m:
            diagram_name = m.group(1)
            continue

        m = network_re.match(line)
        if m:
            current_network = m.group(1)
            networks[current_network] = {"subnet": None, "netmask": None, "hosts": {}}
            continue

        m = network_address_re.match(line)
        if m and current_network:
            try:
                cidr = ipaddress.IPv4Network(m.group(1), strict=False)
            except ValueError:
                print(
                    err(f"Error on line {line_number}: invalid CIDR '{m.group(1)}'."),
                    file=sys.stderr,
                )
                sys.exit(1)
            networks[current_network]["subnet"] = str(cidr.network_address)
            networks[current_network]["netmask"] = str(cidr.netmask)
            continue

        m = host_re.match(line)
        if m and current_network:
            identifier = m.group(1)
            attrs = m.group(2)

            desc_match = description_re.search(attrs)
            hostname = (
                desc_match.group(1) if desc_match else to_unix_hostname(identifier)
            )

            managed_match = managed_re.search(attrs)
            host_is_managed = (
                managed_match.group(1) != "false" if managed_match else True
            )

            addr_match = host_address_re.search(attrs)
            if addr_match and host_is_managed:
                raw_ip = addr_match.group(1)
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

                cpus_match = cpus_re.search(attrs)
                memory_match = memory_re.search(attrs)

                if hostname not in networks[current_network]["hosts"]:
                    networks[current_network]["hosts"][hostname] = {
                        "ips": [str(ip)],
                        "networks": [current_network],
                        "cpus": int(cpus_match.group(1)) if cpus_match else 1,
                        "memory": int(memory_match.group(1)) if memory_match else 512,
                    }
                else:
                    networks[current_network]["hosts"][hostname]["ips"].append(str(ip))
                    networks[current_network]["hosts"][hostname]["networks"].append(
                        current_network
                    )

                host_line_numbers[hostname] = line_number

    networks = {k: v for k, v in networks.items() if v["hosts"]}

    for _, net_data in networks.items():
        for hostname, host_data in net_data["hosts"].items():
            host_data["netmasks"] = [
                networks[net]["netmask"] for net in host_data["networks"]
            ]

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


# region parse_uml()
# Parses a @startuml deployment diagram and returns a tuple of
# (diagram_name, frames, routers, connections).
def parse_uml(puml_text):
    # Strip block comments (/' ... '/) before line-by-line parsing.
    # re.DOTALL makes . match newlines so multi-line blocks are caught.
    block_comment_re = re.compile(r"\/\*[\s\S]*?\*\/|\/'[\s\S]*?'\/", re.DOTALL)
    puml_text = block_comment_re.sub("", puml_text)

    # Patterns compiled once, reused for every line in the loop.
    comment_re = re.compile(r"^\s*(?:'|\/\/).*")
    start_uml_regex = re.compile(r"@startuml(?:\s+(\S+))?")
    frame_re = re.compile(r"frame\s+(\w+)\s*\{")
    node_re = re.compile(
        r"node\s+(\w+)(?:\s+<<(\w+)>>)?(?:\s+as\s+\"([^\"]+)\")?\s*(\{)?"
    )
    component_re = re.compile(r"component\s+(\w+)(?:\s+as\s+\"([^\"]+)\")?")
    close_re = re.compile(r"^\}$")

    connections = []
    diagram_name = None
    frames = {}
    routers = {}

    # Tracks nesting so the parser knows which frame/node is currently open.
    current_frame = None
    current_node = None

    # Arrow patterns.
    # Role-to-role:   frame.node.role --> frame.node.role
    role_conn_re = re.compile(r"(\w+)\.(\w+)\.(\w+)\s+-->\s+(\w+)\.(\w+)\.(\w+)")
    # Router-to-frame/node:  identifier --- identifier
    router_conn_re = re.compile(r"(\w+)\s+---\s+(\w+)")

    for line_number, raw_line in enumerate(puml_text.splitlines(), start=1):
        line = comment_re.sub("", raw_line).strip()
        if not line:
            continue

        # Diagram name.
        m = start_uml_regex.match(line)
        if m:
            diagram_name = m.group(
                1
            )  # None if absent; falls back to filename in convert_uml()
            continue

        # Closing brace — pop one level of nesting.
        if close_re.match(line):
            if current_node is not None:
                current_node = None
            elif current_frame is not None:
                current_frame = None
            continue

        # Frame opening.
        m = frame_re.match(line)
        if m:
            current_frame = m.group(1)
            current_node = None
            frames[current_frame] = {"nodes": {}}
            continue

        # Node opening.
        m = node_re.match(line)
        if m:
            node_id = m.group(1)
            stereotype = m.group(2)  # e.g. "router" from <<router>>
            label = m.group(3) or to_unix_hostname(node_id)
            has_body = m.group(4) is not None  # True if line ends with {

            if stereotype and stereotype.lower() == "router":
                routers[node_id] = {"label": to_unix_hostname(label), "connects": []}
                # Router nodes have no components, so we do not set current_node.
                current_node = None
            elif current_frame is not None:
                frames[current_frame]["nodes"][node_id] = {
                    "label": label,
                    "roles": [],
                }
                current_node = node_id if has_body else None
            continue

        # Component (role) inside a node.
        m = component_re.match(line)
        if m and current_frame and current_node:
            role_id = m.group(1)
            frames[current_frame]["nodes"][current_node]["roles"].append(role_id)
            continue

        # Role-to-role connection.
        m = role_conn_re.match(line)
        if m:
            connections.append(
                {
                    "from_frame": m.group(1),
                    "from_node": m.group(2),
                    "from_role": m.group(3),
                    "to_frame": m.group(4),
                    "to_node": m.group(5),
                    "to_role": m.group(6),
                }
            )
            continue

        # Router-to-frame connection.
        m = router_conn_re.match(line)
        if m:
            left, right = m.group(1), m.group(2)
            if left in routers:
                routers[left]["connects"].append(right)
            elif right in routers:
                routers[right]["connects"].append(left)
            continue

    # Drop empty frames (e.g. `frame beta {}` with no hosts yet).
    frames = {k: v for k, v in frames.items() if v["nodes"]}

    return diagram_name, frames, routers, connections


# endregion


# region debug_print_nwdiag()
# Prints a structured summary of the parsed data to stdout before any files
# are written. Useful for verifying that the parser read the diagram correctly.
def debug_print_nwdiag(diagram_name, networks):
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
        else:
            print("    Hosts   : (none)")
        print()


# endregion


# region debug_print_uml()
# Similar to debug_print_nwdiag().
def debug_print_uml(diagram_name, frames, routers, connections):
    print(bold(f"\n=== Parsed deployment diagram: '{diagram_name}' ===\n"))
    for frame_id, frame_data in frames.items():
        print(bold(f"  Frame: {frame_id}"))
        for node_id, node_data in frame_data["nodes"].items():
            print(f"    Node : {node_id} (label: '{node_data['label']}')")
            for role in node_data["roles"]:
                print(f"      - {role}")
    if routers:
        print(bold("\n  Routers:"))
        for router_id, router_data in routers.items():
            print(
                f"    {router_id} (label: '{router_data['label']}') -> {router_data['connects']}"
            )
    if connections:
        print(bold("\n  Connections:"))
        for c in connections:
            print(
                f"    {c['from_frame']}.{c['from_node']}.{c['from_role']} --> {c['to_frame']}.{c['to_node']}.{c['to_role']}"
            )
    print()


# endregion


# region load_role_config()
# Loads and validates role-config.yml. Accepts an explicit path (from --config)
# or falls back to role-config.yml next to convert.py.
def load_role_config(role_config_path=None):
    if role_config_path is None:
        role_config_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "role-config.yml"
        )

    if not os.path.isfile(role_config_path):
        print(
            err(f"Error: role configuration file not found: {role_config_path}"),
            file=sys.stderr,
        )
        sys.exit(1)

    with open(role_config_path) as f:
        try:
            role_config = yaml.safe_load(f)
        except yaml.YAMLError as e:
            print(
                err(f"Error: failed to parse role configuration file: {e}"),
                file=sys.stderr,
            )
            sys.exit(1)

    if "roles" not in role_config or not isinstance(role_config["roles"], dict):
        print(
            err("Error: role-config.yml must contain a top-level 'roles' mapping."),
            file=sys.stderr,
        )
        sys.exit(1)

    return role_config


# endregion


# region validate_diagrams()
# Cross-validates the parsed nwdiag and uml data to ensure they are in sync.
# Every host in the deployment diagram must exist in the network diagram and
# vice versa. Exits with a list of all mismatches found rather than stopping
# at the first one.
def validate_diagrams(networks, frames):
    errors = []

    # Collect the flat set of hostnames from each diagram.
    nwdiag_hosts = {
        hostname for net_data in networks.values() for hostname in net_data["hosts"]
    }
    uml_hosts = {
        node_data["label"]
        for frame_data in frames.values()
        for node_data in frame_data["nodes"].values()
    }

    for hostname in sorted(uml_hosts - nwdiag_hosts):
        errors.append(
            f"  Host '{hostname}' is in the deployment diagram but not in the network diagram."
        )

    for hostname in sorted(nwdiag_hosts - uml_hosts):
        errors.append(
            f"  Host '{hostname}' is in the network diagram but not in the deployment diagram."
        )

    if errors:
        print(err("Error: diagrams are out of sync:"), file=sys.stderr)
        for error in errors:
            print(err(error), file=sys.stderr)
        sys.exit(1)


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
            print(
                err(f"Error: template '{name}' not found in templates/"),
                file=sys.stderr,
            )
        sys.exit(1)


# endregion


# region convert()
# This is the main entry point for the script. It reads the file, detects the
# diagram type, and hands it off to the appropriate conversion function.
def convert(nwdiag_path, uml_path=None, config_path=None):
    config = load_role_config(config_path)

    if not os.path.isfile(nwdiag_path):
        print(err(f"Error: file not found: {nwdiag_path}"), file=sys.stderr)
        sys.exit(1)

    with open(nwdiag_path) as f:
        nwdiag_text = f.read()

    nwdiag_type = detect_diagram_type(nwdiag_text)
    if nwdiag_type != "nwdiag":
        print(
            err(
                f"Error: expected a @startnwdiag file, got '{nwdiag_type}': {nwdiag_path}"
            ),
            file=sys.stderr,
        )
        sys.exit(1)

    networks, diagram_name = parse_nwdiag(nwdiag_text)
    convert_nwdiag(networks, diagram_name)

    if uml_path is not None:
        if not os.path.isfile(uml_path):
            print(err(f"Error: file not found: {uml_path}"), file=sys.stderr)
            sys.exit(1)

        with open(uml_path) as f:
            uml_text = f.read()

        uml_type = detect_diagram_type(uml_text)
        if uml_type != "uml":
            print(
                err(f"Error: expected a @startuml file, got '{uml_type}': {uml_path}"),
                file=sys.stderr,
            )
            sys.exit(1)

        uml_diagram_name, frames, routers, connections = parse_uml(uml_text)
        # Cross-validation and convert_uml() call go here in the next steps.
        convert_uml(
            uml_text, networks, diagram_name, frames, routers, connections, config
        )


# endregion


# region convert_nwdiag()
# Handles network diagrams (@startnwdiag). Renders the Ansible inventory and
# Vagrant hosts file from the already-parsed network data.
def convert_nwdiag(networks, diagram_name):
    if not networks:
        print(
            err("Error: no networks found in diagram. Is it a valid nwdiag file?"),
            file=sys.stderr,
        )
        sys.exit(1)

    if not diagram_name:
        print(
            warn(
                "Warning: no diagram name found in file. Output directory will be named 'unnamed'."
            )
        )
        diagram_name = "unnamed"

    debug_print_nwdiag(diagram_name, networks)

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
                    "ips": list(host_data["ips"]),
                    "netmasks": list(host_data["netmasks"]),
                    "cpus": host_data["cpus"],
                    "memory": host_data["memory"],
                }
            else:
                for ip, netmask in zip(host_data["ips"], host_data["netmasks"]):
                    if ip not in all_hosts[hostname]["ips"]:
                        all_hosts[hostname]["ips"].append(ip)
                        all_hosts[hostname]["netmasks"].append(netmask)

    render_context = {
        "ansible/inventory.yml.j2": {"networks": networks},
        "vagrant-hosts.yml.j2": {"networks": networks, "all_hosts": all_hosts},
    }

    for template_name, output_relative_path in TEMPLATES:
        template = env.get_template(template_name)
        output_path = os.path.join(output_env_path, output_relative_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w") as f:
            f.write(template.render(**render_context[template_name]))
        print(f'Generated "{output_path}"')


# endregion


# region convert_uml()
# Handles network diagrams (@startnwdiag).
def convert_uml(puml_text, puml_path):
    diagram_name, frames, routers, connections = parse_uml(puml_text)

    debug_print_uml(diagram_name, frames, routers, connections)

    if not frames:
        print(
            err(
                "Error: no frames/networks found in diagram. Is it a valid deployment diagram?"
            ),
            file=sys.stderr,
        )
        sys.exit(1)

    if not diagram_name:
        print(
            warn(
                "Warning: no diagram name found in file. Output directory will be named after the filename of the diagram."
            )
        )
        diagram_name = os.path.splitext(os.path.basename(puml_path))[0]

    # Template rendering will go here once the data structure is validated.


# endregion


# region main()
def main():
    parser = argparse.ArgumentParser(
        description="Convert PlantUML diagrams to Ansible and Vagrant configuration"
    )
    parser.add_argument("nwdiag_path", help="Path to the @startnwdiag input file")
    parser.add_argument(
        "uml_path",
        nargs="?",
        help="Path to the @startuml deployment diagram (optional)",
    )
    parser.add_argument(
        "--config",
        default=None,
        metavar="PATH",
        help="Path to role-config.yml (default: next to convert.py)",
    )
    args = parser.parse_args()
    convert(
        nwdiag_path=args.nwdiag_path, uml_path=args.uml_path, config_path=args.config
    )


if __name__ == "__main__":
    main()
# endregion
