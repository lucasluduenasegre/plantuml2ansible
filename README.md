# PlantUML2Ansible

## Context

PlantUML2Ansible is a "work in progress" and proof-of-concept converter that converts network and deployment diagrams (created using PlantUML) to IaC and configuration management supported environments (provided by Vagrant & Ansible, respectively).

This solution is developed as part of a bachelor's thesis within the context of Applied IT at HOGENT (and its relevant course modules such as "[Cybersecurity Advanced](https://bamaflexweb.hogent.be/BMFUIDetailxOLOD.aspx?a=193610&b=5&c=1)" and "[Infrastructure Automation](https://bamaflexweb.hogent.be/BMFUIDetailxOLOD.aspx?a=193608&b=5&c=1)".

<!--TODO: motivation-->

Further clarification on the motivation, research, and code behind this project can be found on the thesis's [repository](https://github.com/lucasluduenasegre/latex-hogent-bachproef-nl-25-26-luduenasegrelucas).

## Limitations

Since this project is a proof-of-concept, there are a number of noteworthy limitations (which will be elaborated upon later, in the relevant sections):

1. Only hosts/nodes within a **single network** can be defined in the deployment diagram when generating **both Vagrant and Ansible code**. The configuration of routers (as well as the more elaborate firewall rules that it implies) is a task that goes beyond the scope of this proof-of-concept, which is to demonstrate the possibility of converting UML diagrams to configuration management code. As such, each VM will have internet access through their unique NAT interface, provided by Vagrant.
2. Multiple networks **can** be specified when **only generating Vagrant code** and as long as there are no hosts with more than **3** defined IP addresses. This is a technical limitation due to VirtualBox's maximum of 4 network interfaces, of which the first is reserved for the NAT interface Vagrant uses.
3. The resulting environment will be set up locally using Vagrant and will be configured using an Ansible `control` node VM. The host machine, therefore, does not require Ansible to be installed. The `control` node's IP address will, by default, be the broadcast address of the network minus two.
4. Only IPv4 is supported when defining the IP and network addresses.
5. The diagrams should only represent hosts that are to be managed by either the Vagrant or Ansible code, **unless** otherwise specified in the network diagram (`managed = false`).
6. The virtual machines in this environment will **only** use the **AlmaLinux** operating system, as the predefined roles for the converter are reliant on Ansible roles developed by Bert Van Vreckem. Additionally, since these roles were developed for a now deprecated version of Ansible, the Vagrant box to be used will be **"bento/almalinux-9"** instead of the more recent "bento/almalinux-10". This choice has obvious security implications for this environment, yet it is a compromise that had to be made for this proof-of-concept.

<!--TODO-->

## Prerequisites & Installation

- Git
- Python (tested on 3.11.2)
  - `pip` dependencies (see `requirements.txt`):
    - `jinja2`
    - `pyyaml`
- Vagrant (tested on 2.4.9)
- VirtualBox (tested on 7.2.6)

Ansible only runs on the `control` node VM and therefore does not have to be installed on the host machine.

To set up the converter, clone the repository, create a virtual Python environment, and install the Python dependencies:

```bash
git clone git@github.com:lucasluduenasegre/plantuml2ansible.git
cd plantuml2ansible
python3 -m venv .venv
source .venv/bin/activate # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Basic Example

<!--TODO-->

## Usage

<!--TODO-->

### Full mode (network + deployment diagram)

Converting a network diagram + corresponding deployment diagram (both in `.puml`) to an IaC (Vagrant) + configuration management (Ansible) supported environment:

```
python plantuml2ansible.py [--nwdiag] <nwdiag_path> [--uml] <uml_path> [--role-config <role_config_path>]
```

This is the main use case of this tool, and will set up a Vagrant environment as well as a rudimentary yet completely Ansible-supported environment (including a `control` node) based on predefined roles assigned to the hosts.

The `control` node's IP address will, by default, be the broadcast address of the network minus two.

Only hosts/nodes within a **single network** can be defined in the deployment diagram for this use case. The configuration of routers (as well as the more elaborate firewall rules that it implies) is a task that goes beyond the scope of this proof-of-concept, which is to demonstrate the possibility of converting UML diagrams to configuration management code. As such, each VM will have internet access through their unique NAT interface, provided by Vagrant.

By default, the converter will use `role-config.yml` (in the same directory as the script) as the configuration file for predefined roles (which will be covered later). A custom role configuration file can optionally be provided.

### Network diagram only

Converting a network diagram to an IaC-only supported environment with Vagrant:

```
python plantuml2ansible.py [--nwdiag] <nwdiag_path>
```

This is useful if you wish to have a ready-to-use Vagrant environment, but you do want more freedom when setting up configuration management (with or without Ansible). To that end, this environment **will not** include a `control` node.

Multiple networks **can** be specified for this use case, as long as there are no hosts with more than **3** defined IP addresses. This is a technical limitation due to VirtualBox's maximum of 4 network interfaces, of which the first is reserved for the NAT interface Vagrant uses.

This is not the main use case of this tool, but it does demonstrate the ability to handle multiple networks with Vagrant, and it serves as a base for future extensions to this project.

## Input format (network + deployment diagrams)

An **important note**, which might seem obvious, is that the converter assumes the provided PlantUML-based diagrams to be syntactically valid (and thus actually render images).
The converter covers a lot of error handling in order to accurately provide the desired
environment, but the responsibility for correct input mostly lies with the end user.
Therefore, always try to render your `.puml`-files before proceeding.

In PlantUML, single-line comments are denoted using `'` or `//` (with no preceding content) and multi-line comments using `/'` to start and `'/` to end.

### Network diagram (`@startnwdiag`)

The network diagram illustrates the logical topology of networks and hardware elements (in this case Vagrant VMs) in a given environment, along with their respective network/IP addresses and optional attributes such as hardware specifications (amount of RAM and CPU cores).
Multiple networks **can** be defined for IaC-only supported environments, as long as there are no hosts with more than **3** defined IP addresses.

Here follows an example of a possible network diagram:

```plantuml
@startnwdiag test_env
/'
Diagram name definition

Format: @startnwdiag <diagram_name>

Note: if no diagram name is specified, the filename is used as a fallback for
naming the output directory. This name should match the deployment diagram's.
'/

/'
Network definition

Format:
network <network_name> {
  address = <network_address>/<prefix_length>
  color = <color_value>
... 
}

Notes:
- Only IPv4 is supported when defining network addresses.
- "color" is an optional, visual attribute that will be rendered
  by PlantUML but ignored by the converter. See the following
  link for reading material on styling elements with colors:
    - https://plantuml.com/color
'/
network test.lan {
  address = "172.26.0.0/24"

  /'
  Host definition
  
  Format:
  <host_identifier> [address = <ipv4_address>, description = <description>, cpus = <amt_cores>, memory = <amt_gb_ram>, managed = <true|false>, shape = <shape>, color = <color_value>]
  
  Notes:
  - The only mandatory attribute is "address", all others are optional.
    Only IPv4 is supported when defining IP addresses.
  - By default the <description> attribute (which is rendered by PlantUML)
    will be used as the resulting hostname; <host_identifier> is the
    fallback if <description> is unused.
  - Underscores in the hostname will be converted to hyphens, due to 
    Unix conventions.
  - Hosts with the "managed = false" flag will be ignored by the converter
    but still rendered by PlantUML.
  - Like "color", "shape" is a purely visual attribute and will ignored by
    the converter. See the following link for reading material on styling
    elements with shapes (based on deployment diagram objects):
      - https://plantuml.com/deployment-diagram
  '/
  unmanaged_router [address = "172.26.0.254", managed = false, shape = node, color = LightSalmon]
  dns [description = "dns", address = "172.26.0.20", shape = node]
  monitoring [description = "monitoring", address = "172.26.0.30", cpus = 2, memory = 2048, shape = node]
  web [description = "web", address = "172.26.0.10", shape = node]
}

/'
Note: the following network is shown to demonstrate the possibility of defining
multiple networks, as well as unmanaged hosts. When generating both Vagrant and
Ansible code, the following hosts (and subsequently, the network) will not be
covered by the converter.
'/
network unmanaged.lan {
  address = "172.26.10.0/24"
  color = LightSalmon

  unmanaged_router [address = "172.26.10.254", managed = false, shape = node, color = LightSalmon]
  unmanaged_workstation [address = "172.26.10.128", managed = false, shape = node, color = LightSalmon]
}

@endnwdiag
```

The PlantUML code above will generate the following image:

![](https://www.plantuml.com/plantuml/svg/fLPHRzj637xNho3qaWH8vCJBjYBBWcuOXWt8kW9jjuTWC4uwshhbTAVTKNQDhVzzvCcAx4RfWXKeK9daVH-F_CZBoqWgaDjeerP066c1RftDZh8Vs11K0qur21gNnXaotcNPZpuqYgxWuEIrxiCN4dwJPQyyuHMO9JWFUX_9H8WjLcPfK9y2rGXBOt5mTH4rg0WAbihQKbNtiFGXOxTngnJjEsexOio05VcmBU1jRMAF7MlVMGsSNLMdO8sjzTi67Gr97CKYEvfbSi5NI1iVxgVkbhcTxthtqLyB_iu0bDO1OuHlH-VET3ExRWE3lLzOT2kgRpYwyjO7YKqVYxMo7PUdA0h8FlHLYbVP6Vpgx1P-Vhs-JFNfsjO7GWsR6bsVdrn_I6f7Xx7Wata2pkMSSk1RkOUofx0siLCM554mPKS8L2k2ZR4MIeI0JcD0dG6KMtXjbQDtlzm21u9PESyUiKi9A-_MoCc40juWzWtprleDPyIdhN6fHOoeD9ka-1WCCti7aRPMR6XHUX2Pdkg-97nh080pg8dQU3MRjP93rzYYyiqiXKYVXYkBC0kE-AW3-SNNysB-LN5UdC_cbtd6Jcuim4y-qdvV0VZVq5k0wvhz2wFHaUWmtC3TNbTDkxvyQEafmyGgc5HNyUxzP6VLTkcCQcXH-O1oeC66TJbOL-M2PITcvTGAjTWfTFWF2pmYssEjMXIhV8XXKZ9_z7VO2KOAzrQ6GMJ3m5gHK8xDDX7otHNoKr3MWgSQGmGLy44aXRJWMT9Z_xxgXFxxhNXLPqaqSLYNlKIEDxMfQe4U9BSlk9EKmI3AOVW5ZwaOMgYbLp9ztqoqpQHW0HdtXLaU9YD1dHFiFl5taaPCpGBZ4jb0iSja5Bq6yb1lsnfTP2LqAB-5Zb7C-pxC2KjV5D7Te7B1pSUUfsxdiBHgDR0yEMb2a4OnaaHE5QwdkpNtE2o0KyYJWFfD06qNq6uVRm7MIiy_aWlTVuxwimOz8HqEUyefmd6ffBdUJQnayEMVM54y4Lr_OYcC9yzs9pcUTmH0vtQ5NWJVSLPmDxKYvbzUSfK-QiauVyvh78VlrgngUgDiuvsCddOHxWutGSusnfjaEiyFSGM2aGpvm6LwX3IwdW3yWW67NJFVsp3pyyiNZvasM3wYODiJs1UFa_qWx-Fk2JzKmR2FJUGZVkDa7ZHo_f62ebuphO_HbCOQse9VFkoGh961RYqE897pYPoijVp_sCCqZR60tsK1hT0X0mjrwQc6twJlZaJ6sNUEQHYkaiOTvjbZmB6eFNPbnBywT6ItAMpWF-a7mNc24hFAht7osTjxXiOaF_4MNGoF4Ko9ANkcN2y-JwyZHQeqgQI3QPwB-Ol_noCwUObEzty2_Wi0)

### Deployment diagram (`@startuml`)

The deployment diagram represents the configuration of hosts (denoted as nodes) and their components (in this case predefined Ansible roles). As mentioned before, only hosts/nodes within a **single network** can be defined in this diagram for IaC + configuration management supported environments.

The following is an example of a possible deployment diagram:

```plantuml
@startuml test_env
/'
Diagram name definition

Format: @startuml <diagram_name>

Note: if no diagram name is specified, the filename is used as a fallback for
naming the output directory. This name should match the network diagram's.
'/

' Make each component per node unique
set separator .

' Purely visual, won't have any effect on the parser
left to right direction

/'
Host definition

Notes:
- By default <description> will be used as the resulting hostname;
<host_identifier> is the fallback if <description> is unused.
- Underscores in the hostname will be converted to hyphens, due to Unix conventions.

Format:
node <host_identifier> as <description>
'/
node dns as "dns" {

    /'
    Role definition

    Format:
    component <role_identifier> as <role_name>
    '/
    component bind_exporter
    component dns_client
    component dns_server_primary
    component node_exporter
}

node monitoring {
    component dns_client
    component monitoring_server
    component node_exporter
}

node web as "web" {
    component dns_client
    component mysqld_exporter
    component node_exporter
    component web_server
}

/'
Role-to-role connections

Note: Arrows must always point from left to right, but can be styled according to
      https://crashedmind.github.io/PlantUMLHitchhikersGuide/layout/layout.html

Format:
<host_identifier>.<role_identifier> --> <host_identifier>.<role_identifier>
'/
dns.dns_client -[#teal]-> dns.dns_server_primary

monitoring.dns_client -[#teal]-> dns.dns_server_primary
monitoring.monitoring_server -[#coral]-> dns.bind_exporter
monitoring.monitoring_server -[#coral]-> dns.node_exporter
monitoring.monitoring_server -[#coral]-> monitoring.node_exporter
monitoring.monitoring_server -[#coral]-> web.mysqld_exporter
monitoring.monitoring_server -[#coral]-> web.node_exporter

web.dns_client -[#teal]-> dns.dns_server_primary

@enduml
```

This code will render the following image:

![](https://www.plantuml.com/plantuml/svg/dLJ1Rjms4BtpAmRkOIzUxTqrZBGesXoQ8YYQKr4ikEB86fZYA3D3RuGW_rwHpaOHr8Etlb3Wl3Tl_EPntwXviJn4C5GxOdfsXvtxXVoZ-06I7n02TfJ8Y9Dplx8CtkvWeTs75-onO1-S-uCDxu0wI0pX-pQae2Esr166Mx0UeQE8br9M3E0LF7G-nfDldw1ZSNEPqcD5SxOn6mGIR8rbQk2ldlIbj_QSOu31MzjNS48xipnT9jXfutO7vtRmpZyXe9zXBGyZ9qm68mea3WWvqSUCJj50SVJYZGMQGdkV1UC4pwJPnriuSzePzFuPmQS9iEkmDU1KjMUYehY8dO4n23tsbx6BXyNVjwosyhMufdTk3pzFvTxdQBEpgAtGM10FSAOOuOGNewgIeCx0Ob3FQiM97zrz-JnIm6J5Qda0gk35L-hMhQlzgVHjvW4-f82YBGigKAhCI_DlCxISdb4C0nX3Fuqz9hs5a16CvmRqwGMHIdjjlgN6LPEt0tfT3rHMLQ4XQIdUpESDV7OE0E2mgyUV7DV9B9SNdVAzhFTUPkn6i5xMp5RuBBbcdIY58tuQMGnbNIjp7Tj8cEm_2eeoctCSXGOlqnfGOxPq_U9U_i-14nbBMUJdrqejdA-Ahr8wuwawEfytLsXD-Z5ktTWeRMf5xpBUbvhyihUzyRxONrAINbw5NduuVXBXiyAGrS37ivyKHgPaq0aFi7fJjt3A1grF9P9gKomFesrPGZ7Is47zwyr6lJiSMl7QOnWeXUQHhC-dXlZmFlfa7zxz_fQixNjwGj7VCWKyH3znjgz7qziGbnnl8jniCxRVFy0hS2Nh8McpU0_xltymzF6VkK6jR3FbbkLVHVoUjybFeRSi2t_r0gwZraXSJrsg_xD3oLkpIkkrvBMkArVNhUODff27-2y0)

### Role configuration (`role-config.yml`)

There are a number of predefined roles that can be specified for each managed host in the deployment diagram. Much of the information required by each role (in the form of `host_vars`) will be derived from information gathered from the network and deployment diagrams.

The roles are defined in a configuration file called `role-config.yml` (found in the same directory as `plantuml2ansible.py`), which looks like this:

```yaml
# role-config.yml
# Maps simplified role identifiers (as used in deployment diagrams) to their
# fully qualified Ansible role names and associated metadata.
#
# Notes:
#   - "fqcn" (the "Fully Qualified Collection Name") is the name that will be used
#     in the roles section of a host's play in the playbook. This is also the only
#     required key, all others are optional.
#   - "priority" directs the execution order of the role within a host's play.
#     Roles with lower priority values run first, and 100 is the default value.
#   - "depends_on" directs which roles must be applied on other hosts before this
#     role's host play runs. For example, hosts with the "dns_server_*" role must
#     complete their play before the hosts with "dns_client".
#   - "galaxy_roles" and "galaxy_collections" represent the Ansible Galaxy roles
#     and collections that must be installed on the Ansible control node prior
#     to running the playbook.
#   - "assets" represent the files under the "assets/" directory that are to be
#     copied to the Ansible control node prior to running the playbook.
#   - "host_vars" are the variables (in YAML format) written to the host's 
#     host_vars file. Sentinels prefixed with __DIAGRAM_ are placeholders which 
#     will be resolved by the converter at build time, derived from
#     diagram information.
#
# Format:
# roles:
#   <role_identifier>:
#     fqcn: <fqcn>
#     priority: <priority>
#     depends_on:
#       - <role_identifier>
#       ...
#     galaxy_roles:
#       - <ansible_galaxy_role_name>
#     galaxy_collections:
#       - <ansible_galaxy_collection_name>
#     host_vars:
#       <host_vars_in_yaml_format>
#   ...   
---
roles:
  dhcp_server:
    fqcn: bertvv.dhcp
    priority: 10
    depends_on:
      - dns_server_primary
      - dns_server_secondary
    galaxy_roles:
      - bertvv.dhcp
    host_vars:
      rhbase_firewall_allow_services:
        - dhcp
      dhcp_global_default_lease_time: 14400
      dhcp_global_max_lease_time: 14400
      dhcp_global_domain_name: __DIAGRAM_NETWORK_NAME__
      dhcp_global_broadcast_address: __DIAGRAM_BROADCAST__
      dhcp_global_subnet_mask: __DIAGRAM_NETMASK__
      dhcp_global_domain_name_servers: __DIAGRAM_DNS_SERVER_IPS__
      dhcp_subnets: __DIAGRAM_SUBNETS__
  # Other roles below
```

## Available roles

The following subsections will highlight the core functionality of each predefined role. The FQCN (Fully Qualified Collection Name) of each role (which will be used in the playbook) will be displayed in the title of each section in a monospace typeface.

### `dhcp_server`

<!--TODO-->

### `dns_server_primary` (BIND9)

<!--TODO-->

### `dns_server_secondary` (BIND9)

<!--TODO-->

### `dns_client`

<!--TODO-->

### `monitoring_server` (Grafana + Prometheus stack)

<!--TODO-->

### Prometheus exporters

<!--TODO-->

#### `apache_exporter`

<!--TODO-->

#### `bind_exporter`

<!--TODO-->

#### `mysqld_exporter`

<!--TODO-->

#### `node_exporter`

<!--TODO-->

### `web_server` (Apache + MariaDB stack)

<!--TODO-->

## Output structure<!-- in `<output_directory>/<diagram_name>/` -->

The following sections describe the file structure the converter will copy and generate, based on the employed use case.

### Network diagram only

Copied (verbatim):

- **`Vagrantfile`**
  - File that describes the general provisioning of each host managed by Vagrant. The hosts in this environment will **only** use **"bento/almalinux-9"** as their base box.

Generated (based on diagram):

- **`vagrant-hosts.yml`** (**without** `control`)
  - File that defines each managed host listed in the network diagram, their hostname, IP address(es), and hardware specifications. Hosts with **multiple** IP addresses **can** be defined here.

### Full mode (network + deployment diagram)

Copied (verbatim):

- **`Vagrantfile`**
- **`scripts/`**
  - Provisioning scripts (`scripts/control.sh` and `scripts/util.sh`) for the Ansible `control` node.
- **`ansible/roles/<role_name>/`** (for each defined role in the deployment diagram)
  - Predefined (custom) Ansible roles, which correspond to the FQCN of a role entry in `role-config.yml`.
- **`ansible/files/grafana/dashboards/<grafana_dashboard>.json`** (for each defined exporter role in the deployment diagram)
  - Monitoring dashboards to be provisioned for the Prometheus + Grafana monitoring stack (deployed using the role `monitoring_server`).
- **`ansible/files/db.sql`** (when `role_web_server` is defined in the deployment diagram)
  - Very small, simple, and local MySQL database.
- **`ansible/files/test.php`** (when `role_web_server` is defined in the deployment diagram)
  - Simple PHP page that queries the aforementioned database.

Generated (based on diagrams):

- **`vagrant-hosts.yml`** (**including** `control`)
  - Only hosts with **single** IP addresses can be defined here.
- **`ansible/inventory.yml`**
  - Similar to `vagrant-hosts.yml`; defines each managed hosts (and corresponding IP addresses) listed in the network diagram, which will be configured by Ansible. Some Vagrant-specific variables are also defined here.
- **`ansible/site.yml`**
  - The main playbook of the Ansible environment, assigning the roles listed for each host (as defined in the deployment diagram), as well as general prerequisites for all hosts.
- **`ansible/requirements.yml`**
  - File describing the required roles and collections to be downloaded from Ansible Galaxy, mostly as dependencies for the predefined roles.
- **`ansible/host_vars/<hostname>.yml`** (for each defined host in the deployment diagram)
  - (Role-specific) variables for each managed host to be configured by Ansible, mainly derived from information in both diagrams (network/IP addresses, hostnames, asset paths, ...).

## Acknowledgements & Credits

### Ansible Galaxy roles & collections

- Bert Van Vreckem. (2015a). _bertvv/ansible-role-bind: Sets up ISC BIND as an authoritative DNS server on several Linux distros & FreeBSD_. GitHub. https://github.com/bertvv/ansible-role-bind
  - This was used for the custom role `role_dns_server`, which deploys a primary (and secondary) nameserver.

- Bert Van Vreckem. (2015b). _bertvv/ansible-role-dhcp: Ansible role for setting up ISC DHCPD on RHEL/CentOS 7_. GitHub. https://github.com/bertvv/ansible-role-dhcp
  - This was used for the custom role `role_dhcp_server`, which deploys a DHCP server.

- Bert Van Vreckem. (2015c). _bertvv/ansible-role-httpd: A simple Ansible role for installing and configuring the Apache web server for RHEL/CentOS 7 and Fedora 28_. GitHub. https://github.com/bertvv/ansible-role-httpd
  - This was used for the custom role `role_web_server`, which deploys a very simple Apache web server (including a small, built-in MariaDB database).

- Bert Van Vreckem. (2016). _bertvv/ansible-role-rh-base: Ansible role for basic setup of a server with a RedHat-based Linux distribution (CentOS, Fedora, RHEL, ...)_. GitHub. https://github.com/bertvv/ansible-role-rh-base
  - This was used for executing various basic configuration tasks (such as setting up the firewall and installing packages) on every VM (currently all running AlmaLinux 9).

- Grafana Labs. (2026). _grafana/grafana-ansible-collection: grafana.grafana Ansible collection provides modules and roles for managing various resources on Grafana Cloud and roles to manage and deploy Grafana Agent and Grafana_. GitHub. https://github.com/grafana/grafana-ansible-collection
  - This was used for the custom role `role_monitoring_server`, which deploys a Prometheus + Grafana monitoring stack.

- Prometheus Monitoring Community. (2026). _prometheus-community/ansible: Ansible Collection for Prometheus. GitHub_. https://github.com/prometheus-community/ansible
  - This was used for the custom role `role_monitoring_server` as well as the various exporters (node, MySQL, BIND).

### Grafana dashboards

- F., R. (2025). _rfmoz/grafana-dashboards: Grafana dashboards_. GitHub. https://github.com/rfmoz/grafana-dashboards
  - This was used for the Grafana dashboards for Apache Exporter (altered slightly), Bind Exporter, and Node Exporter.

- Grafana Labs. (2024). _MySQL Exporter Quickstart and Dashboard_. Grafana Labs. https://grafana.com/grafana/dashboards/14057-mysql/
  - This was used for the Grafana dashboard for MySQL Exporter.

### Other projects

- Bert Van Vreckem. (2025). _bertvv/ansible-skeleton: An opinionated skeleton for Ansible projects with a development environment powered by Vagrant_. GitHub. https://github.com/bertvv/ansible-skeleton
  - This was used to set up a local, Vagrant- and Ansible-ready virtual environment. A tailor-made version of this project (used in the HOGENT course module "[Infrastructure Automation](https://bamaflexweb.hogent.be/BMFUIDetailxOLOD.aspx?a=193608&b=5&c=1)") has been used and altered for the purposes of this proof-of-concept. Notably `Vagrantfile` has been changed to allow the creation of VMs with multiple network interfaces, and `scripts/control.sh` to automatically accept SSH host key fingerprints for each host in `vagrant-hosts.yml`.

- HoGentTIN. (2025a). _HoGentTIN/cybersecurity-advanced-lab-template: Cybersecurity Advanced - lab environment template_. GitHub. https://github.com/HoGentTIN/cybersecurity-advanced-lab-template
  - The network diagram for the lab template of this course module was used and slightly altered as input (without a corresponding deployment diagram) for this proof-of-concept.

- HoGentTIN. (2025b). _HoGentTIN/infra-labs: Lab assignments for the Infrastructure Automation course_. GitHub. https://github.com/HoGentTIN/infra-labs
  - The labs 2 and 3 of this course module were used as references for creating network- and deployment diagrams as input for this proof-of-concept (excluding `r001` and `srv003`).

## License

<!--TODO-->
