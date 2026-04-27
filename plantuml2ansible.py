import argparse
import ipaddress
import os
import re
import shutil
import sys
import yaml

from jinja2 import Environment, FileSystemLoader, TemplateNotFound


# region IdentedDumper()
# Custom YAML dumper for indenting lists properly.
class IndentedDumper(yaml.Dumper):
    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow=flow, indentless=False)


# endregion


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
# Packages installed on every managed host via bertvv.rh-base.
BASE_PACKAGES = [
    "bash-completion",
    "bind-utils",
    "git",
    "nano",
    "setroubleshoot-server",
    "tree",
    "vim-enhanced",
    "wget",
]

# The environment subnet all networks in the diagram must fall within.
# This is checked during parsing to catch misconfigured addresses early.
ENVIRONMENT_SUBNET = ipaddress.IPv4Network("172.26.0.0/16")

# Each entry maps a Jinja2 template (relative to templates/) to its output
# path (relative to the environment output directory). Adding a new file to
# the converter means adding one line here and one entry in render_context
# inside convert().
TEMPLATES = [
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

    return diagram_name, networks


# endregion


# region parse_uml()
# Parses a @startuml deployment diagram and returns a tuple of
# (diagram_name, nodes, connections).
def parse_uml(puml_text):
    # Strip block comments (/' ... '/) before line-by-line parsing.
    # re.DOTALL makes . match newlines so multi-line blocks are caught.
    block_comment_re = re.compile(r"\/\*[\s\S]*?\*\/|\/'[\s\S]*?'\/", re.DOTALL)
    puml_text = block_comment_re.sub("", puml_text)

    # Patterns compiled once, reused for every line in the loop.
    comment_re = re.compile(r"^\s*(?:'|\/\/).*")
    start_uml_regex = re.compile(r"@startuml(?:\s+(\S+))?")
    node_re = re.compile(
        r"node\s+(\w+)(?:\s+<<\w+>>)?(?:\s+as\s+\"([^\"]+)\")?\s*(\{)?"
    )
    component_re = re.compile(r"component\s+(\w+)(?:\s+as\s+\"([^\"]+)\")?")
    close_re = re.compile(r"^\}$")

    connections = []
    diagram_name = None
    nodes = {}

    # Tracks which node body is currently open.
    current_node = None

    # Role-to-role:   node.role --> node.role
    role_conn_re = re.compile(r"(\w+)\.(\w+)\s+-->\s+(\w+)\.(\w+)")

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

        # Closing brace — close the current node body.
        if close_re.match(line):
            current_node = None
            continue

        # Node opening.
        m = node_re.match(line)
        if m:
            node_id = m.group(1)
            label = m.group(2) or to_unix_hostname(node_id)
            has_body = m.group(3) is not None

            nodes[node_id] = {"label": label, "roles": []}
            current_node = node_id if has_body else None
            continue

        # Component (role) inside a node.
        m = component_re.match(line)
        if m and current_node:
            role_id = m.group(1)
            nodes[current_node]["roles"].append(role_id)
            continue

        # Role-to-role connection.
        m = role_conn_re.match(line)
        if m:
            connections.append(
                {
                    "from_node": m.group(1),
                    "from_role": m.group(2),
                    "to_node": m.group(3),
                    "to_role": m.group(4),
                }
            )
            continue

    return diagram_name, nodes, connections


# endregion


# region debug_print_nwdiag()
# Prints a structured summary of the parsed data to stdout before any files
# are written. Useful for verifying that the parser read the diagram correctly.
def debug_print_nwdiag(diagram_name, networks):
    print(bold(f"\n=== Parsed network diagram: '{diagram_name}' ===\n"))
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
def debug_print_uml(diagram_name, nodes, connections):
    print(bold(f"\n=== Parsed deployment diagram: '{diagram_name}' ===\n"))
    for node_id, node_data in nodes.items():
        print(f"  Node : {node_id} (label: '{node_data['label']}')")
        for role in node_data["roles"]:
            print(f"    - {role}")
    if connections:
        print(bold("\n  Connections:"))
        for c in connections:
            print(
                f"    {c['from_node']}.{c['from_role']} --> {c['to_node']}.{c['to_role']}"
            )
    print()


# endregion


# region load_role_config()
# Loads and validates role-config.yml. Accepts an explicit path (from --config)
# or falls back to role-config.yml next to plantuml2ansible.py.
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


# region _copy_iac_assets()
# Copy IaC assets such as the Vagrantfile as well as
# provisioning scripts when paired with .
def _copy_iac_assets(output_env_path, include_scripts=False):
    assets_src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
    items = ["Vagrantfile"]
    if include_scripts:
        items.append("scripts/")
    for item in items:
        src = os.path.join(assets_src, item)
        dst = os.path.join(output_env_path, item)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
            print(f"Copied directory: {dst}")
        elif os.path.isfile(src):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            print(f"Copied file: {dst}")


# region copy_assets()
# Copy assets such as static files and custom roles, as well as unconditional assets.
def copy_assets(present_roles, role_config, output_env_path):
    assets_src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

    # Always copy Vagrantfile + provisioning scripts
    _copy_iac_assets(output_env_path, include_scripts=True)

    # Copy custom role directories
    for role in present_roles:
        role_dir_name = role_config.get(role, {}).get("fqcn", role)
        src = os.path.join(assets_src, "ansible", "roles", role_dir_name)
        if os.path.isdir(src):
            dst = os.path.join(output_env_path, "ansible", "roles", role_dir_name)
            shutil.copytree(src, dst, dirs_exist_ok=True)
            print(f"Copied role: {dst}")

    # Copy role-triggered assets
    for role in present_roles:
        for filename in role_config.get(role, {}).get("assets", []):
            src = os.path.join(assets_src, filename)
            dst = os.path.join(output_env_path, filename)
            if os.path.isfile(src):
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                print(f"Copied asset: {dst}")
            else:
                print(
                    warn(
                        f"Warning: asset '{filename}' declared for role '{role}' not found at {src}"
                    )
                )


# endregion


# region validate_diagrams()
# Cross-validates the parsed nwdiag and uml data to ensure they are in sync.
# Every host in the deployment diagram must exist in the network diagram and
# vice versa. Exits with a list of all mismatches found rather than stopping
# at the first one.
def validate_diagrams(networks, nodes):
    errors = []

    nwdiag_hosts = {
        hostname for net_data in networks.values() for hostname in net_data["hosts"]
    }
    uml_hosts = {node_data["label"] for node_data in nodes.values()}

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
# Checks that every template in the given list exists before any rendering
# starts. All missing templates are reported at once rather than failing on the
# first one, so the user can fix them all in one go.
def validate_templates(env, template_names):
    missing = [name for name in template_names if not _template_exists(env, name)]
    if missing:
        for name in missing:
            print(
                err(f"Error: template '{name}' not found in templates/"),
                file=sys.stderr,
            )
        sys.exit(1)


def _template_exists(env, name):
    try:
        env.get_template(name)
        return True
    except TemplateNotFound:
        return False


# endregion


# region topological_sort()
# Sorts hosts based on their dependencies.
def topological_sort(hosts, host_deps):
    # Kahn's algorithm — stable (preserves diagram order among independent hosts).
    from collections import deque

    in_degree = {h: 0 for h in hosts}
    for h, predecessors in host_deps.items():
        in_degree[h] += len(predecessors)

    queue = deque(h for h in hosts if in_degree[h] == 0)
    result = []
    while queue:
        h = queue.popleft()
        result.append(h)
        for other in hosts:
            if h in host_deps.get(other, set()):
                in_degree[other] -= 1
                if in_degree[other] == 0:
                    queue.append(other)

    if len(result) != len(list(hosts)):
        print(
            err(
                "Error: circular dependency detected in role-config.yml depends_on definitions."
            ),
            file=sys.stderr,
        )
        sys.exit(1)

    return result


# endregion


# region build_playbook()
# Builds a playbook based on the deployment diagram nodes(/hosts) and the
# role configuration. Inter-host ordering is determined by depends_on (via
# topological sort); intra-host role ordering is determined by priority.
def build_playbook(role_config, host_roles):

    DEFAULT_PRIORITY = 100

    # Build a flat map of role_identifier -> set of hosts that have it.
    role_hosts = {}
    for hostname, roles in host_roles.items():
        for role in roles:
            role_hosts.setdefault(role, set()).add(hostname)

    # Topological sort of hosts based on depends_on.
    # Build a dependency graph: host -> set of hosts it must come after.
    host_deps = {hostname: set() for hostname in host_roles}
    for role, role_data in role_config.items():
        for dep_role in role_data.get("depends_on", []):
            if dep_role in role_hosts and role in role_hosts:
                for dependent_host in role_hosts[role]:
                    for provider_host in role_hosts[dep_role]:
                        if dependent_host != provider_host:
                            host_deps[dependent_host].add(provider_host)

    ordered_hosts = topological_sort(host_roles.keys(), host_deps)

    # Assemble playbook, sorting roles within each host by priority.
    playbook = []
    for hostname in ordered_hosts:
        sorted_roles = sorted(
            host_roles[hostname],
            key=lambda r: role_config.get(r, {}).get("priority", DEFAULT_PRIORITY),
        )
        playbook.append(
            {
                "hostname": hostname,
                "roles": [
                    role_config[r]["fqcn"] for r in sorted_roles if r in role_config
                ],
            }
        )

    return playbook


# endregion


# region _build_bind_zones()
# Derives bind_zones for a dns_server host from the parsed nwdiag networks.
# Each network becomes a zone with A-records for every host in that network.
def _build_bind_zones(hostname, networks):
    zones = []
    for net_name, net_data in networks.items():
        if not net_data["hosts"]:
            continue
        records = [
            {"name": h, "ip": host_data["ips"][0]}
            for h, host_data in net_data["hosts"].items()
            if host_data["ips"]
        ]
        zones.append(
            {
                "name": net_name,
                "networks": [net_data["subnet"]],
                "hosts": records,
            }
        )
    return zones


# endregion


# region build_host_vars()
# Builds host_vars files for each host based on the role configuration and
# diagram data. Static host_vars are copied verbatim from role-config.yml;
# __DIAGRAM_*__ sentinels are resolved from the parsed nwdiag data.
def build_host_vars(host_roles, role_config, networks):

    DEFAULT_PRIORITY = 100

    # Build a flat map of role_identifier -> set of hosts that have it.
    role_hosts = {}
    for hostname, roles in host_roles.items():
        for role in roles:
            role_hosts.setdefault(role, set()).add(hostname)

    # Build a flat map of hostname -> first IP across all networks.
    host_primary_ip = {}
    for net_data in networks.values():
        for hostname, host_data in net_data["hosts"].items():
            if hostname not in host_primary_ip and host_data["ips"]:
                host_primary_ip[hostname] = host_data["ips"][0]

    # Collect IPs of all hosts running dns_server.
    dns_server_ips = sorted(
        host_primary_ip[h]
        for h in role_hosts.get("dns_server", set())
        if h in host_primary_ip
    )

    # Build prometheus scrape configs from all exporter roles in the diagram.
    # Any role with a host_vars entry ending in _port is treated as an exporter.
    scrape_configs = []
    for role, role_data in role_config.items():
        if role not in role_hosts:
            continue
        port_key = next(
            (k for k in role_data.get("host_vars", {}) if k.endswith("_port")),
            None,
        )
        if port_key is None:
            continue
        port = role_data["host_vars"][port_key]
        targets = sorted(
            f"{host_primary_ip[h]}:{port}"
            for h in role_hosts[role]
            if h in host_primary_ip
        )
        if targets:
            scrape_configs.append(
                {
                    "job_name": role,
                    "static_configs": [{"targets": targets}],
                }
            )

    def resolve_sentinel(value, hostname):
        match value:
            case "__DIAGRAM_BIND_ZONES__":
                return _build_bind_zones(hostname, networks)
            case "__DIAGRAM_DNS_SERVER_IPS__":
                return dns_server_ips
            case "__DIAGRAM_SCRAPE_CONFIGS__":
                return scrape_configs
            case _:
                return value  # unknown sentinel — pass through as-is

    def resolve_host_vars(raw_vars, hostname):
        return {
            key: resolve_sentinel(value, hostname) for key, value in raw_vars.items()
        }

    # Merge resolved host_vars from each role assigned to the host,
    # sorted by priority so later roles can intentionally override earlier ones.
    result = {}
    for hostname, roles in host_roles.items():
        sorted_roles = sorted(
            roles,
            key=lambda r: role_config.get(r, {}).get("priority", DEFAULT_PRIORITY),
        )

        merged = {
            "rhbase_install_packages": list(BASE_PACKAGES),
        }

        for role in sorted_roles:
            raw = role_config.get(role, {}).get("host_vars", {})
            resolved = resolve_host_vars(raw, hostname)

            for key, value in resolved.items():
                if key == "rhbase_install_packages":
                    merged.setdefault(key, [])
                    merged[key].extend(value)
                    merged[key] = sorted(set(merged[key]))
                else:
                    merged[key] = value

        if merged:
            result[hostname] = merged

    return result


# endregion


# region build_requirements()
# Derives the Ansible Galaxy requirements from the roles present in the
# diagram. Only roles and collections actually used are included.
# bertvv.rh-base is always included as it is applied to all hosts.
def build_requirements(host_roles, role_config):
    galaxy_roles = {"bertvv.rh-base"}  # always required
    galaxy_collections = set()

    present_roles = {role for roles in host_roles.values() for role in roles}

    for role in present_roles:
        role_data = role_config.get(role, {})
        for gr in role_data.get("galaxy_roles", []):
            galaxy_roles.add(gr)
        for gc in role_data.get("galaxy_collections", []):
            galaxy_collections.add(gc)

    return {
        "roles": sorted(galaxy_roles),
        "collections": sorted(galaxy_collections),
    }


# endregion


# region convert_nwdiag()
# Handles network diagrams (@startnwdiag). Renders the Ansible inventory and
# Vagrant hosts file from the already-parsed network data.
def convert_nwdiag(diagram_name, networks, include_control=False):
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

    validate_templates(
        env,
        [
            "ansible/inventory.yml.j2",
            "vagrant-hosts.yml.j2",
        ],
    )

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

    template = env.get_template("vagrant-hosts.yml.j2")
    output_path = os.path.join(output_env_path, "vagrant-hosts.yml")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        f.write(
            template.render(
                networks=networks, all_hosts=all_hosts, include_control=include_control
            )
        )
    print(f'Generated "{output_path}"')

    _copy_iac_assets(output_env_path, include_scripts=False)


# endregion


# region convert_uml()
# Handles deployment diagrams (@startuml). Renders inventory.yml, requirements.yml,
# site.yml and host_vars from the parsed deployment diagram and network data.
def convert_uml(diagram_name, networks, nodes, connections, role_config):
    if len(networks) > 1:
        print(
            err(
                "Error: deployment diagram conversion only supports a single network. "
                "to generate a multi-network Vagrant environment, run without"
                "a deployment diagram."
            ),
            file=sys.stderr,
        )
        sys.exit(1)

    if not nodes:
        print(
            err("Error: no nodes found in diagram. Is it a valid deployment diagram?"),
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

    debug_print_uml(diagram_name, nodes, connections)

    output_env_path = os.path.join("output", diagram_name)

    env = Environment(
        loader=FileSystemLoader("templates/"),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["zip"] = zip

    env.filters["to_yaml"] = lambda value, **kwargs: yaml.dump(
        value,
        Dumper=IndentedDumper,
        default_flow_style=False,
        allow_unicode=True,
        explicit_end=False,
    )

    validate_templates(
        env,
        [
            "ansible/inventory.yml.j2",
            "ansible/requirements.yml.j2",
            "ansible/site.yml.j2",
            "ansible/host_vars/hostname.yml.j2",
        ],
    )

    roles = role_config["roles"]

    # Build host_roles once here — shared input for both build_playbook()
    # and build_host_vars() to avoid duplicating the derivation logic.
    host_roles = {
        node_data["label"]: node_data["roles"] for node_data in nodes.values()
    }

    template = env.get_template("ansible/inventory.yml.j2")
    output_path = os.path.join(output_env_path, "ansible/inventory.yml")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        f.write(template.render(networks=networks))
    print(f'Generated "{output_path}"')

    playbook = build_playbook(roles, host_roles)

    template = env.get_template("ansible/site.yml.j2")
    output_path = os.path.join(output_env_path, "ansible/site.yml")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        f.write(template.render(playbook=playbook))
    print(f'Generated "{output_path}"')

    host_vars = build_host_vars(host_roles, roles, networks)

    template = env.get_template("ansible/host_vars/hostname.yml.j2")
    for hostname, vars_dict in host_vars.items():
        output_path = os.path.join(
            output_env_path, "ansible/host_vars", f"{hostname}.yml"
        )
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w") as f:
            f.write(template.render(hostname=hostname, host_vars=vars_dict))
        print(f'Generated "{output_path}"')

    requirements = build_requirements(host_roles, roles)

    template = env.get_template("ansible/requirements.yml.j2")
    output_path = os.path.join(output_env_path, "ansible/requirements.yml")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        f.write(template.render(**requirements))
    print(f'Generated "{output_path}"')

    present_roles = {role for roles in host_roles.values() for role in roles}
    copy_assets(present_roles, roles, output_env_path)


# endregion


# region convert()
# This is the main entry point for the script. It reads the file, detects the
# diagram type, and hands it off to the appropriate conversion function.
def convert(nwdiag_path, uml_path=None, role_config_path=None):
    role_config = load_role_config(role_config_path)

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

    diagram_name, networks = parse_nwdiag(nwdiag_text)
    convert_nwdiag(diagram_name, networks)

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

        uml_diagram_name, nodes, connections = parse_uml(uml_text)
        validate_diagrams(networks, nodes)
        convert_uml(diagram_name, networks, nodes, connections, role_config)


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
        "--role-config",
        default=None,
        metavar="PATH",
        dest="role_config_path",
        help="Path to role-config.yml (default: next to plantuml2ansible.py)",
    )
    args = parser.parse_args()
    convert(
        nwdiag_path=args.nwdiag_path,
        uml_path=args.uml_path,
        role_config_path=args.role_config_path,
    )


if __name__ == "__main__":
    main()
# endregion
