import argparse
import copy
import ipaddress
import os
import re
import shutil
import sys
import yaml

from jinja2 import Environment, FileSystemLoader, TemplateNotFound


# region IndentedDumper
# Custom YAML dumper that indents list items relative to their parent key,
# rather than emitting them at the same column.  Also disables YAML anchors
# and aliases so every output file is self-contained.
class IndentedDumper(yaml.Dumper):
    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow=flow, indentless=False)

    def ignore_aliases(self, data):
        return True


# endregion


# region Colour helpers
# These functions wrap text in ANSI escape codes for coloured terminal output.
# The isatty() check ensures escape codes are only emitted when the output is
# an actual terminal; plain text is returned when stdout/stderr is redirected.
def _colourise(text, code):
    if sys.stderr.isatty():
        return f"\033[{code}m{text}\033[0m"
    return text


def err(text):
    return _colourise(text, "91")  # bright red


def warn(text):
    return _colourise(text, "93")  # bright yellow


def bold(text):
    return _colourise(text, "1")  # bold (no colour change)


# endregion


# region Constants
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

# Role families used to suppress spurious inter-host ordering constraints.
# If a host already runs any role in the same family as a dependency target,
# no cross-host ordering edge is added.  This prevents cycles between
# redundant peer servers (notably a primary and a secondary DNS server that
# each run dns_client pointing at the other).
_PEER_ROLE_FAMILIES: dict[str, frozenset[str]] = {
    "dns_server_primary": frozenset({"dns_server_primary", "dns_server_secondary"}),
    "dns_server_secondary": frozenset({"dns_server_primary", "dns_server_secondary"}),
}
# endregion


# region Utility helpers


def to_unix_hostname(identifier):
    """Convert a PlantUML host identifier to a valid Unix hostname."""
    return identifier.replace("_", "-")


def _template_exists(env, name):
    try:
        env.get_template(name)
        return True
    except TemplateNotFound:
        return False


# endregion


# region Input validation


def detect_diagram_type(puml_text):
    """Return 'nwdiag' or 'uml' based on the opening @start directive.

    Reads the first non-empty, non-comment line and matches it against the
    two supported diagram types.  Exits with an error if neither is found.
    """
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


def validate_diagrams(networks, nodes):
    """Cross-validate the nwdiag and UML diagrams for host consistency.

    Every host in the deployment diagram must appear in the network diagram
    and vice versa.  All mismatches are collected and reported together so
    the user can fix them in one pass.
    """
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


def validate_templates(env, template_names):
    """Verify that all required Jinja2 templates exist before rendering begins.

    Reports every missing template at once rather than aborting on the first
    one, so the user can fix them all in a single pass.
    """
    missing = [name for name in template_names if not _template_exists(env, name)]
    if missing:
        for name in missing:
            print(
                err(f"Error: template '{name}' not found in templates/"),
                file=sys.stderr,
            )
        sys.exit(1)


# endregion


# region Parsers


def parse_nwdiag(puml_text):
    """Parse a @startnwdiag diagram and return (diagram_name, networks).

    networks is a dict keyed by network name.  Each entry contains:
      - subnet   : network address string
      - netmask  : dotted-decimal netmask string
      - hosts    : dict of hostname -> {ips, netmasks, networks, cpus, memory}
    """
    # Remove block comments (/* ... */ and /' ... '/) before line-by-line parsing.
    # re.DOTALL lets '.' match newlines so multi-line blocks are caught.
    block_comment_re = re.compile(r"\/\*[\s\S]*?\*\/|\/'[\s\S]*?'\/", re.DOTALL)
    puml_text = block_comment_re.sub("", puml_text)

    # Compile all patterns once; they are reused for every line in the loop.
    comment_re = re.compile(r"^\s*(?:'|\/\/).*")
    start_re = re.compile(r'@startnwdiag(?:\s+"?([\w-]+)"?)?')
    network_re = re.compile(r'network\s+"?([\w.-]+)"?\s*\{')
    net_address_re = re.compile(r'address\s*=\s*"?([\d.]+/\d+)"?')
    host_re = re.compile(r"([\w-]+)\s*\[([^\]]+)\]")
    description_re = re.compile(r'description\s*=\s*"?([\w-]+)"?')
    managed_re = re.compile(r'managed\s*=\s*"?(true|false)"?', re.I)
    host_address_re = re.compile(r'address\s*=\s*"?([\d.]+)"?')
    cpus_re = re.compile(r'cpus\s*=\s*"?(\d+)"?')
    memory_re = re.compile(r'memory\s*=\s*"?(\d+)"?')

    networks = {}
    current_network = None
    diagram_name = None
    host_line_nos = {}  # hostname -> line number, used for error messages

    for _line_no, line in enumerate(puml_text.splitlines(), start=1):
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

        m = net_address_re.match(line)
        if m and current_network:
            try:
                cidr = ipaddress.IPv4Network(m.group(1), strict=False)
            except ValueError:
                print(
                    err(f"Error on line {_line_no}: invalid CIDR '{m.group(1)}'."),
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
                            f"Error on line {_line_no}: invalid IP address '{raw_ip}' for host '{hostname}'."
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

                host_line_nos[hostname] = _line_no

    # Drop networks that contain no hosts.
    networks = {k: v for k, v in networks.items() if v["hosts"]}

    # Attach the correct netmask for every network a host belongs to.
    for net_data in networks.values():
        for host_data in net_data["hosts"].values():
            host_data["netmasks"] = [
                networks[net]["netmask"] for net in host_data["networks"]
            ]

    # Validate that every host IP falls within its declared network.
    for net_data in networks.values():
        subnet = net_data.get("subnet")
        netmask = net_data.get("netmask")
        if not subnet or not netmask:
            continue
        network_obj = ipaddress.IPv4Network(f"{subnet}/{netmask}")
        for hostname, host_data in net_data["hosts"].items():
            for host_ip in host_data["ips"]:
                if ipaddress.IPv4Address(host_ip) not in network_obj:
                    _line_no = host_line_nos.get(hostname, "unknown")
                    print(
                        err(
                            f"Error on line {_line_no}: host '{hostname}' has IP {host_ip}, "
                            f"which is not within subnet {network_obj}."
                        ),
                        file=sys.stderr,
                    )
                    sys.exit(1)

    return diagram_name, networks


def parse_uml(puml_text):
    """Parse a @startuml deployment diagram and return (diagram_name, nodes, connections).

    nodes is a dict keyed by node identifier.  Each entry contains:
      - label : Unix hostname string
      - roles : list of role identifier strings

    connections is a list of dicts with keys from_node, from_role, to_node, to_role.
    """
    # Remove block comments before line-by-line parsing.
    block_comment_re = re.compile(r"\/\*[\s\S]*?\*\/|\/'[\s\S]*?'\/", re.DOTALL)
    puml_text = block_comment_re.sub("", puml_text)

    # Compile all patterns once.
    comment_re = re.compile(r"^\s*(?:'|\/\/).*")
    start_re = re.compile(r"@startuml(?:\s+(\S+))?")
    node_re = re.compile(
        r"node\s+(\w+)(?:\s+<<\w+>>)?(?:\s+as\s+\"([^\"]+)\")?\s*(\{)?"
    )
    component_re = re.compile(r"component\s+(\w+)(?:\s+as\s+\"([^\"]+)\")?")
    close_re = re.compile(r"^\}$")
    # Matches role-to-role connections of the form: node.role --> node.role
    # The arrow may carry a label, colour modifier, or thickness marker.
    role_conn_re = re.compile(r"(\w+)\.(\w+)\s+-(?:[\w]|\[[^\]]*\]|-)*>\s+(\w+)\.(\w+)")

    connections = []
    diagram_name = None
    nodes = {}
    current_node = None  # identifier of the node whose body is currently open

    for _line_no, raw_line in enumerate(puml_text.splitlines(), start=1):
        line = comment_re.sub("", raw_line).strip()
        if not line:
            continue

        m = start_re.match(line)
        if m:
            # None when no name is present; convert_uml() falls back to the filename.
            diagram_name = m.group(1)
            continue

        # Closing brace - exit the current node body.
        if close_re.match(line):
            current_node = None
            continue

        m = node_re.match(line)
        if m:
            node_id = m.group(1)
            label = m.group(2) or to_unix_hostname(node_id)
            has_body = m.group(3) is not None
            nodes[node_id] = {"label": label, "roles": []}
            current_node = node_id if has_body else None
            continue

        m = component_re.match(line)
        if m and current_node:
            nodes[current_node]["roles"].append(m.group(1))
            continue

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


# region Debug output


def debug_print_nwdiag(diagram_name, networks):
    """Print a structured summary of a parsed nwdiag diagram to stdout."""
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


def debug_print_uml(diagram_name, nodes, connections):
    """Print a structured summary of a parsed UML deployment diagram to stdout."""
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


# region Configuration loading


def load_role_config(role_config_path=None):
    """Load and validate role-config.yml.

    When no path is supplied, the file is looked up next to plantuml2ansible.py.
    Returns the full parsed YAML document on success; exits with an error otherwise.
    """
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


# region Topology helpers


def _topological_sort(hosts, host_deps):
    """Return hosts in dependency order using Kahn's algorithm.

    The sort is stable: hosts with no ordering constraint between them appear
    in the same relative order as in the input iterable.
    Exits with an error if a cycle is detected.
    """
    from collections import deque

    in_degree = {h: 0 for h in hosts}
    for predecessors in host_deps.values():
        for h in predecessors:
            if h in in_degree:
                in_degree[h] += 0  # ensure key exists (no change to count)
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


def _connections_to_host_deps(connections, nodes):
    """Derive inter-host ordering hints from UML arrow connections.

    A connection nodeA.roleX --> nodeB.roleY means nodeA must be provisioned
    after nodeB.  Two exceptions avoid spurious cycles:

    - Exact match: if nodeA already runs roleY locally, intra-host priority
      handles the ordering and no cross-host edge is needed.
    - Family match: if nodeA already runs a peer role in the same family as
      roleY (see _PEER_ROLE_FAMILIES), the constraint is also skipped.

    Returns a dict {hostname -> set of hostnames it must follow}.
    """
    label = {node_id: data["label"] for node_id, data in nodes.items()}
    host_roles = {data["label"]: set(data["roles"]) for data in nodes.values()}

    deps = {}
    for c in connections:
        from_host = label.get(c["from_node"])
        to_host = label.get(c["to_node"])
        if not from_host or not to_host or from_host == to_host:
            continue
        # Skip if the dependent host already runs the target role locally.
        if c["to_role"] in host_roles.get(from_host, set()):
            continue
        # Skip if the dependent host runs a peer role in the same family.
        family = _PEER_ROLE_FAMILIES.get(c["to_role"], set())
        if family & host_roles.get(from_host, set()):
            continue
        deps.setdefault(from_host, set()).add(to_host)

    return deps


# endregion


# region Builders


def build_playbook(role_config, host_roles, extra_host_deps=None):
    """Build a list of playbook entries ordered by dependency.

    Inter-host ordering comes from two sources:
      1. depends_on entries in role-config.yml.
      2. extra_host_deps (derived from UML arrow connections).
    Intra-host role ordering is determined by the priority field in role-config.yml.

    Returns a list of dicts with keys 'hostname' and 'roles' (list of FQCNs).
    """
    DEFAULT_PRIORITY = 100

    # Map each role identifier to the set of hosts that carry it.
    role_hosts = {}
    for hostname, roles in host_roles.items():
        for role in roles:
            role_hosts.setdefault(role, set()).add(hostname)

    # Build the dependency graph: hostname -> set of hostnames it must follow.
    host_deps = {hostname: set() for hostname in host_roles}
    for role, role_data in role_config.items():
        for dep_role in role_data.get("depends_on", []):
            if dep_role not in role_hosts or role not in role_hosts:
                continue
            for dependent_host in role_hosts[role]:
                # Skip if this host already satisfies the dependency locally.
                family = _PEER_ROLE_FAMILIES.get(dep_role, {dep_role})
                if family & set(host_roles.get(dependent_host, [])):
                    continue
                for provider_host in role_hosts[dep_role]:
                    if dependent_host != provider_host:
                        host_deps[dependent_host].add(provider_host)

    # Merge diagram-derived ordering hints; they supplement depends_on.
    if extra_host_deps:
        for host, predecessors in extra_host_deps.items():
            host_deps.setdefault(host, set()).update(predecessors)

    ordered_hosts = _topological_sort(host_roles.keys(), host_deps)

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


def build_host_vars(host_roles, role_config, networks, nodes=None, connections=None):
    """Build a per-host variable dictionary for every managed host.

    Static host_vars entries are taken verbatim from role-config.yml.
    __DIAGRAM_*__ sentinel strings are replaced with values derived from the
    parsed diagram data at resolution time.

    List-type keys listed in MERGED_KEYS are merged and de-duplicated across
    all roles on the same host; all other keys are overwritten in priority order.

    Returns a dict {hostname -> merged variable dict}.
    """
    DEFAULT_PRIORITY = 100

    # Keys whose values are lists that should be merged across roles rather
    # than overwritten.
    MERGED_KEYS = {
        "rhbase_install_packages",
        "rhbase_firewall_allow_services",
        "rhbase_firewall_allow_ports",
        "rhbase_start_services",
        "rhbase_selinux_booleans",
        "rhbase_repositories",
    }

    # Map each role identifier to the set of hosts that carry it.
    role_hosts = {}
    for hostname, roles in host_roles.items():
        for role in roles:
            role_hosts.setdefault(role, set()).add(hostname)

    # Primary IP for each host (first IP encountered across all networks).
    host_primary_ip = {}
    for net_data in networks.values():
        for hostname, host_data in net_data["hosts"].items():
            if hostname not in host_primary_ip and host_data["ips"]:
                host_primary_ip[hostname] = host_data["ips"][0]

    # IPs of all hosts running a DNS server role (primary or secondary).
    dns_server_ips = sorted(
        host_primary_ip[h]
        for h in (
            role_hosts.get("dns_server_primary", set())
            | role_hosts.get("dns_server_secondary", set())
        )
        if h in host_primary_ip
    )
    dns_secondary_ips = sorted(
        host_primary_ip[h]
        for h in role_hosts.get("dns_server_secondary", set())
        if h in host_primary_ip
    )

    # Maps (from_host, from_role) -> set of (to_host, to_role).
    # Populated from UML connections so sentinels can be filtered per-host.
    role_connections = {}
    if connections and nodes:
        label = {nid: data["label"] for nid, data in nodes.items()}
        for c in connections:
            from_host = label.get(c["from_node"])
            to_host = label.get(c["to_node"])
            if from_host and to_host:
                key = (from_host, c["from_role"])
                role_connections.setdefault(key, set()).add((to_host, c["to_role"]))

    # Prometheus scrape configs derived from all exporter roles in the diagram.
    # A role is treated as an exporter when its host_vars contain a key ending
    # in _port.
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

    # --- Sentinel resolvers ---

    def _build_bind_zones_primary(hostname, networks):
        """Build bind_zones for a dns_server_primary host.

        Each network in the diagram becomes a primary zone containing
        A-records for every host in that network.
        """
        zones = []
        forwarders = (
            role_config.get("dns_server_primary", {})
            .get("host_vars", {})
            .get("bind_forwarders", [])
        )
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
                    "type": "primary",
                    "name_servers": [
                        f"{h}.{net_name}."
                        for h in (
                            role_hosts.get("dns_server_primary", set())
                            | role_hosts.get("dns_server_secondary", set())
                        )
                    ],
                    "allow_update": dns_server_ips,
                    "also_notify": dns_secondary_ips,
                    "forwarders": list(forwarders),
                    "networks": [net_data["subnet"].rsplit(".", 1)[0]],
                    "hosts": records,
                }
            )
        return zones

    def _build_bind_zones_secondary(hostname, networks):
        """Build bind_zones for a dns_server_secondary host.

        Each network becomes a secondary zone that transfers from the primary.
        """
        zones = []
        for net_name, net_data in networks.items():
            if not net_data["hosts"]:
                continue
            zones.append(
                {
                    "name": net_name,
                    "type": "secondary",
                    "primaries": [
                        host_primary_ip[h]
                        for h in role_hosts.get("dns_server_primary", set())
                        if h in host_primary_ip
                    ],
                    "networks": [net_data["subnet"].rsplit(".", 1)[0]],
                }
            )
        return zones

    def _resolve_sentinel(value, hostname):
        match value:
            case "__DIAGRAM_DNS_SECONDARY_IPS__":
                return dns_secondary_ips

            case "__DIAGRAM_BIND_ZONES_PRIMARY__":
                return _build_bind_zones_primary(hostname, networks)

            case "__DIAGRAM_BIND_ZONES_SECONDARY__":
                return _build_bind_zones_secondary(hostname, networks)

            case "__DIAGRAM_DNS_SERVER_IPS__":
                # When connection data is available, return only the IPs of
                # DNS servers that this host explicitly connects to.
                if role_connections:
                    return sorted(
                        host_primary_ip[to_host]
                        for (to_host, to_role) in role_connections.get(
                            (hostname, "dns_client"), set()
                        )
                        if to_role in ("dns_server_primary", "dns_server_secondary")
                        and to_host in host_primary_ip
                    )
                return dns_server_ips  # fallback when no connection data is present

            case "__DIAGRAM_SCRAPE_CONFIGS__":
                # When connection data is available, filter scrape targets to
                # only those explicitly connected to the monitoring host.
                if role_connections:
                    monitoring_hosts = role_hosts.get("monitoring_server", set())
                    configs = []
                    for role, role_data in role_config.items():
                        if role not in role_hosts:
                            continue
                        port_key = next(
                            (
                                k
                                for k in role_data.get("host_vars", {})
                                if k.endswith("_port")
                            ),
                            None,
                        )
                        if port_key is None:
                            continue
                        port = role_data["host_vars"][port_key]
                        targets = sorted(
                            f"{host_primary_ip[h]}:{port}"
                            for h in role_hosts[role]
                            if h in host_primary_ip
                            # Include this target only when a monitoring host
                            # has an explicit connection to (h, role).
                            and any(
                                (h, role)
                                in role_connections.get(
                                    (mon, "monitoring_server"), set()
                                )
                                for mon in monitoring_hosts
                            )
                        )
                        if targets:
                            configs.append(
                                {
                                    "job_name": role,
                                    "static_configs": [{"targets": targets}],
                                }
                            )
                    return configs
                return scrape_configs  # fallback when no connection data is present

            case "__DIAGRAM_NETWORK_NAME__":
                return next(iter(networks))

            case "__DIAGRAM_NETMASK__":
                return next(iter(networks.values()))["netmask"]

            case "__DIAGRAM_BROADCAST__":
                net_data = next(iter(networks.values()))
                net_obj = ipaddress.IPv4Network(
                    f"{net_data['subnet']}/{net_data['netmask']}"
                )
                return str(net_obj.broadcast_address)

            case "__DIAGRAM_SUBNETS__":
                subnets = []
                for net_data in networks.values():
                    net_obj = ipaddress.IPv4Network(
                        f"{net_data['subnet']}/{net_data['netmask']}"
                    )
                    hosts = list(net_obj.hosts())
                    midpoint = len(hosts) // 2
                    subnets.append(
                        {
                            "ip": str(net_obj.network_address),
                            "netmask": str(net_obj.netmask),
                            "range_begin": str(hosts[midpoint]),
                            "range_end": str(hosts[-3]),
                        }
                    )
                return subnets

            case _:
                # Scalars (str, bool, int) are immutable - no copy needed.
                return copy.deepcopy(value)

    def _resolve_host_vars(raw_vars, hostname):
        return {
            key: _resolve_sentinel(value, hostname) for key, value in raw_vars.items()
        }

    # Merge resolved host_vars from each role assigned to the host, in
    # ascending priority order so higher-priority roles win on conflicts.
    result = {}
    for hostname, roles in host_roles.items():
        sorted_roles = sorted(
            roles,
            key=lambda r: role_config.get(r, {}).get("priority", DEFAULT_PRIORITY),
        )

        merged = {"rhbase_install_packages": list(BASE_PACKAGES)}

        for role in sorted_roles:
            raw_vars = role_config.get(role, {}).get("host_vars", {})
            resolved = _resolve_host_vars(raw_vars, hostname)

            for key, value in resolved.items():
                if key in MERGED_KEYS:
                    merged.setdefault(key, [])
                    merged[key].extend(value)
                    merged[key] = sorted(set(merged[key]))
                else:
                    merged[key] = value

        if merged:
            result[hostname] = merged

    return result


def build_requirements(host_roles, role_config):
    """Derive the Ansible Galaxy requirements from the roles present in the diagram.

    bertvv.rh-base is always included because it is applied to every managed host.
    Only roles and collections actually referenced in the diagram are included.

    Returns a dict with keys 'roles' and 'collections', each a sorted list.
    """
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


# region IP address helpers


def get_control_ip(cidr, existing_ips):
    """Return (ip_string, netmask_string) for a control node in the given CIDR.

    The control node is assigned the second-to-last usable address
    (broadcast - 2).  Exits with an error if the network is too small or if
    the chosen address conflicts with an existing host.
    """
    net = ipaddress.ip_network(cidr, strict=False)
    if net.num_addresses < 8:
        print(
            err(
                f"Network {net} is too small (/{net.prefixlen}) to safely assign a control node IP. "
                f"Use a prefix of /29 or larger."
            ),
            file=sys.stderr,
        )
        sys.exit(1)

    control_ip = net.broadcast_address - 2
    if str(control_ip) in existing_ips:
        print(
            err(
                f"Control node IP {control_ip} conflicts with an existing host in the diagram."
            ),
            file=sys.stderr,
        )
        sys.exit(1)

    return str(control_ip), str(net.netmask)


# endregion


# region Asset copying


def _copy_iac_assets(output_env_path, include_scripts=False):
    """Copy the Vagrantfile and, optionally, the provisioning scripts directory."""
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
            print(f"Copied asset: {dst}")


def copy_assets(present_roles, role_config, output_env_path):
    """Copy the Vagrantfile, scripts, custom role directories, and static assets.

    Custom roles are looked up under assets/ansible/roles/<fqcn>.
    Role-triggered assets are declared under the 'assets' key in role-config.yml.
    """
    assets_src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

    _copy_iac_assets(output_env_path, include_scripts=True)

    # Copy custom role directories (if any exist in the assets folder).
    for role in present_roles:
        role_dir_name = role_config.get(role, {}).get("fqcn", role)
        src = os.path.join(assets_src, "ansible", "roles", role_dir_name)
        if os.path.isdir(src):
            dst = os.path.join(output_env_path, "ansible", "roles", role_dir_name)
            shutil.copytree(src, dst, dirs_exist_ok=True)
            print(f"Copied role: {dst}")

    # Copy static assets declared per role in role-config.yml.
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


# region Converters


def convert_nwdiag(diagram_name, networks, include_control=False):
    """Render vagrant-hosts.yml and copy IaC assets for a nwdiag diagram.

    When include_control is True, a control node entry is added to
    vagrant-hosts.yml using get_control_ip() to select a safe address.
    """
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
        loader=FileSystemLoader("templates/"), trim_blocks=True, lstrip_blocks=True
    )
    env.filters["zip"] = zip

    validate_templates(env, ["ansible/inventory.yml.j2", "vagrant-hosts.yml.j2"])

    # Flatten per-network host entries into a single host table, merging IPs
    # and netmasks for hosts that appear in multiple networks.
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

    # Derive a CIDR string from the first network so get_control_ip() can work.
    first_net = next(iter(networks.values()))
    cidr = f"{first_net['subnet']}/{first_net['netmask']}"

    existing_ips = {ip for host_data in all_hosts.values() for ip in host_data["ips"]}
    control_ip, control_netmask = (
        get_control_ip(cidr, existing_ips) if include_control else (None, None)
    )

    template = env.get_template("vagrant-hosts.yml.j2")
    output_path = os.path.join(output_env_path, "vagrant-hosts.yml")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        f.write(
            template.render(
                networks=networks,
                all_hosts=all_hosts,
                include_control=include_control,
                control_ip=control_ip,  # None when include_control is False
                control_netmask=control_netmask,
            )
        )
    print(f"Generated {output_path}")

    _copy_iac_assets(output_env_path, include_scripts=False)


def convert_uml(diagram_name, networks, nodes, connections, role_config):
    """Render inventory.yml, site.yml, host_vars, and requirements.yml for a UML diagram.

    Also copies static role assets via copy_assets().
    Only single-network environments are supported at this stage.
    """
    if len(networks) > 1:
        print(
            err(
                "Error: deployment diagram conversion only supports a single network. "
                "To generate a multi-network Vagrant environment, run without a deployment diagram."
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
        loader=FileSystemLoader("templates/"), trim_blocks=True, lstrip_blocks=True
    )
    env.filters["zip"] = zip
    env.filters["to_yaml"] = lambda value, **_kwargs: yaml.dump(
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

    # Derive host_roles once and share it across build_playbook() and
    # build_host_vars() to avoid duplicating the derivation logic.
    host_roles = {
        node_data["label"]: node_data["roles"] for node_data in nodes.values()
    }

    template = env.get_template("ansible/inventory.yml.j2")
    output_path = os.path.join(output_env_path, "ansible/inventory.yml")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        f.write(template.render(networks=networks))
    print(f"Generated {output_path}")

    diagram_deps = _connections_to_host_deps(connections, nodes)
    playbook = build_playbook(roles, host_roles, extra_host_deps=diagram_deps)

    template = env.get_template("ansible/site.yml.j2")
    output_path = os.path.join(output_env_path, "ansible/site.yml")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        f.write(template.render(playbook=playbook))
    print(f"Generated {output_path}")

    host_vars = build_host_vars(
        host_roles, roles, networks, nodes=nodes, connections=connections
    )

    template = env.get_template("ansible/host_vars/hostname.yml.j2")
    for hostname, vars_dict in host_vars.items():
        output_path = os.path.join(
            output_env_path, "ansible/host_vars", f"{hostname}.yml"
        )
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w") as f:
            f.write(template.render(hostname=hostname, host_vars=vars_dict))
        print(f"Generated {output_path}")

    requirements = build_requirements(host_roles, roles)

    template = env.get_template("ansible/requirements.yml.j2")
    output_path = os.path.join(output_env_path, "ansible/requirements.yml")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        f.write(template.render(**requirements))
    print(f"Generated {output_path}")

    present_roles = {role for roles in host_roles.values() for role in roles}
    copy_assets(present_roles, roles, output_env_path)


# endregion


# region Entry point


def convert(nwdiag_path, uml_path=None, role_config_path=None):
    """Orchestrate the full conversion pipeline.

    Reads both input files, validates them, and calls the appropriate
    converter functions.  A stale output directory is removed before any
    new files are written so the output directory always reflects the
    current diagram.
    """
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

    output_env_path = os.path.join("output", diagram_name or "unnamed")
    if os.path.exists(output_env_path):
        shutil.rmtree(output_env_path)
        print(warn(f"Warning: removed previous output at '{output_env_path}'"))

    convert_nwdiag(diagram_name, networks, include_control=uml_path is not None)

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

        if uml_diagram_name and diagram_name and uml_diagram_name != diagram_name:
            print(
                warn(
                    f"Warning: diagram name mismatch - nwdiag is '{diagram_name}', "
                    f"uml is '{uml_diagram_name}'. Using nwdiag name '{diagram_name}' "
                    f"for the output directory."
                )
            )

        validate_diagrams(networks, nodes)
        convert_uml(diagram_name, networks, nodes, connections, role_config)


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
