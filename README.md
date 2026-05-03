# PlantUML2Ansible

## Table of Contents

<!--TODO-->

## Context

PlantUML2Ansible is a "work in progress" and Proof-of-Concept transpiler that converts network and deployment diagrams (created using PlantUML) to IaC and configuration management supported environments (provided by Vagrant & Ansible, respectively). This solution is developed as part of a bachelor's thesis within the context of Applied IT at HOGENT (and its relevant course modules such as "[Cybersecurity Advanced](https://bamaflexweb.hogent.be/BMFUIDetailxOLOD.aspx?a=193610&b=5&c=1)" and "[Infrastructure Automation](https://bamaflexweb.hogent.be/BMFUIDetailxOLOD.aspx?a=193608&b=5&c=1)".

<!--TODO-->

## Limitations

Since this project is a proof-of-concept, there are a number of noteworthy limitations:

1. The resulting environment will be set up locally using Vagrant and will be configured using an Ansible `control` node VM. The host machine, therefore, does not require Ansible to be installed.
1. Only IPv4 is supported when defining the IP and network addresses.
1. The diagrams can only represent hosts that are to be managed by either the Vagrant or Ansible code, **unless** otherwise specified in the network diagram (`managed = false`).
1. Only nodes within a **single network** can be defined in the deployment diagram (When generating **both Vagrant and Ansible code**). The configuration of routers (as well as the more elaborate firewall rules that it implies) is a task that goes beyond the scope of demonstrating the possibility of converting UML diagrams to configuration management code.
1. Multiple networks **can** be specified when **only generating Vagrant code** and as long as there are no hosts with more than **3** defined IP addresses. This is a technical limitation due to VirtualBox's maximum of 4 network interfaces, of which the first is reserved for the NAT interface Vagrant uses.
1. The virtual machines in this environment will **only** use the **AlmaLinux** operating system, as the predefined roles for the converter are reliant on Ansible roles developed by Bert Van Vreckem. Additionally, since these roles were developed for a now deprecated version of Ansible, the Vagrant box to be used will be **"bento/almalinux-9"** instead of the more recent "bento/almalinux-10". This choice has obvious security implications for this environment, yet it is a compromise that had to be made for this proof-of-concept.

<!--TODO-->

## Prerequisites

- Git 
- Python (tested on 3.11.2)
  - `pip` dependencies (see `requirements.yml`):
    - `jinja2`
    - `pyyaml`
    - `yamllint`
- Vagrant (tested on 2.4.9)
- VirtualBox (tested on 7.2.6)

As previously mentioned; Ansible only runs on the `control` node and therefore does not have to be installed on the host machine.

## Installation

<!--TODO-->

Linux/Mac:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows:

```powershell
python3 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Usage

<!--TODO-->

### Network diagram only

Converting a network diagram to an IaC-only supported environment with Vagrant (**multiple networks** supported):

```
python convert.py <nwdiag-path>
```

This is useful if you wish to have more freedom when setting up configuration management with Ansible, but you do want a ready-to-use Vagrant environment. To that end, this setup up **does not** include a `control` node.

### Full mode (network + deployment diagram)

Converting a network diagram + corresponding deployment diagram (both in `.puml`) to an IaC (Vagrant) + configuration management (Ansible) supported environment (only **one single network** is supported):

```
python convert.py <nwdiag-path> <uml-path> [--role-config <role-config-path>]
```

This will, in addition to a Vagrant environment, set up a rudimentary yet completely Ansible-supported environment (which **does** a `control` node) based on predefined roles assigned to hosts. This environment, however, will be limited to a single network, as routing is beyond the scope for this proof-of-concept. A custom role configuration file can optionally be provided.

## Input format (network + deployment diagrams)

An important note, which might seem obvious, is that the converter assumes the provided PlantUML-based diagrams to be syntactically valid (and thus actually generate images).
The converter covers a lot of error handling in order to provide the resulting environment, but the end responsibility for correct input mostly lies with the end user.

<!--TODO-->

### Network diagram (`@startnwdiag`)

The network diagram illustrates the logical topology of networks and hardware elements (in this case Vagrant VMs) in a given environment, along with their respective network and IP addresses. Multiple networks **can** be defined for IaC-only supported environments, as long as there are no hosts with more than **3** IP addresses.

Here follows an example of a possible network diagram (single-line comments are denoted using apostrophes (`'`)):

```
@startnwdiag test_env
' Specify diagram name above, otherwise falls back on filename for output directory
' Note: this name must match with that of the deployment diagram.

' Network definition
'
' Format: network <network_name> { ... }
network test.lan {
  ' Subnet definition
  '
  ' Format: address = <network-address>/<prefix-length>
  address = "172.26.0.0/24"

  ' Host definition
  '
  ' Notes:
  ' - By default the <description> attribute will be used as the resulting hostname;
  '   <host_identifier> is the fallback if <description> is unused.
  ' - Underscores in the hostname will be converted to hyphens, due to Unix conventions
  ' - Hosts with the "managed = false" flag will be rendered by PlantUML, but ignored
  '   by the converter.
  '
  ' Format: <host_identifier> [description = <description> address = <ipv4_address>, cpus = <amt_cores>, memory = <amt_gb_ram>, managed = <true|false>]
  dns [description = "dns", address = "172.26.0.20"]
  monitoring [description = "monitoring", address = "172.26.0.30", cpus = 2, memory = 2048]
  web [description = "web", address = "172.26.0.10"]
}

network virtualbox_nat {
  address = "10.0.2.0/24"

  dns [address = "10.0.2.15", managed = false]
  monitoring [address = "10.0.2.15", managed = false]
  web [address = "10.0.2.15", managed = false]
  virtualbox_nat_gateway [address = "10.0.2.2", managed = false]
  virtualbox_nat_dns [address = "10.0.2.3", managed = false]
}

real_internet [shape = cloud]
virtualbox_nat_gateway -- real_internet

@endnwdiag
```



The PlantUML code above will generate the following image:

![](https://www.plantuml.com/plantuml/png/ZLGxRzim4DxrAmvQijYAuwGFf8uHT2Wwj4M18bCG29HqaeX8f40UxGXf_dkFj6MxiWraa-_nFJwIlhSa3Abr8KK5X9PILAle0lvqcCko1ryteWKbMWIHwHLEG5EDPYqjGYcQna8cycVG2ahPO9WhjG7jg7F4-mPpqgPdp5-Qy1QebdO3rpfBq0hAQrXBghaZ27G930y5TetkMrGqI8Wy0j9QcsVkbb99abf55rp-fWt3t8BQjXVRZzJJBE4LaYI1jsXeUvj98nIyHW1irMNSESJaQkWCkA8e35eBTplawRQql5nqXXTVfcozedePmS5qVFLfdim_9hDaTZc_YQC0-btRasG-7NiRFgVmjVSZmZKKqbWKQ7CZEx-m145aPEO8ERQcWGp1MIn0s33BtBmcLGKrC_a4lWHGW8KlfBBWK6KfqIn1XfLmZE4GPJcYuW6dF7go5VQW2ZGsrym2KldjWMQl9jTgXOPO4cce-wv6PITGEEJV321VDXFAKzWDRaZ53jS08Mw54XKZt7bn5cCe6r7j60nw6TpEUlZD9qaFFtzCW2C1MIdDZQrZRbEz5sIIewCzpkJn802c7qM_lmcoMzsampMOGDwvK1OjfI4UhhNOyiqVgbMM6j5oUUzjGSRXt-1m-HG15CgE-MEknPEJbse-Y_rIgvKaRVZ4ZtRthJCGrxDu9tr-87W-k_diiTUO7O5oxGpQbHVq5kqUsaeQSgB9z4kg1C7hw77Cl8VzqmZcZ_jN7vXjT1t6jj-_vGszVtpa8Aq4uLhqfn3cxm8uu_7wr387QL0qgLI4XYE5HrkB3daWRxGhdg8pugPJ-6ylYkvH5Pk_-7y0)

<!--TODO-->

### Deployment diagram (`@startnwdiag`)

The deployment diagram represents the configuration of hosts (denoted as nodes) and their components (in this case Ansible roles). As mentioned before, only hosts within a single network can be represented here.

<!--TODO-->

 ## Output structure<!-- in `<output_directory>/<diagram_name>/` -->

### Network diagram only

Generated (based on diagram):
- `vagrant-hosts.yml` (**without** `control`)

Copied (verbatim):
- `Vagrantfile`

<!--TODO-->

### Full mode (network + deployment diagram)

Generated (based on diagrams):
- `vagrant-hosts.yml` (**with** `control`)
- Inventory file (`ansible/inventory.yml`)
  - As the environment is deployed locally with Vagrant, the inventory will therefore be shaped according to this backend.
- `ansible/site.yml`
- `ansible/host_vars/dns.yml`
- `ansible/host_vars/monitoring.yml`
- `ansible/host_vars/web.yml`
- `ansible/requirements.yml`


Copied (verbatim):
- `Vagrantfile`
- `scripts/`
- `ansible/roles/<role_name>/` (for each defined role)
- `ansible/files/grafana/dashboards/<grafana_dashboard>.json` (for each defined exporter)
- `ansible/files/db.sql` (when using `role_web_server`)
- `ansible/files/test.php` (when using `role_web_server`)

<!--TODO-->

## Acknowledgements & Credits

### Ansible Galaxy roles & collections

- Bert Van Vreckem. (2015a). *bertvv/ansible-role-bind: Sets up ISC BIND as an authoritative DNS server on several Linux distros & FreeBSD*. GitHub. https://github.com/bertvv/ansible-role-bind
  - This was used for the custom role `role_dns_server`, which deploys a primary (and secondary) nameserver.

- Bert Van Vreckem. (2015b). *bertvv/ansible-role-dhcp: Ansible role for setting up ISC DHCPD on RHEL/CentOS 7*. GitHub. https://github.com/bertvv/ansible-role-dhcp
  - This was used for the custom role `role_dhcp_server`, which deploys a DHCP server.

- Bert Van Vreckem. (2015c). *bertvv/ansible-role-httpd: A simple Ansible role for installing and configuring the Apache web server for RHEL/CentOS 7 and Fedora 28*. GitHub. https://github.com/bertvv/ansible-role-httpd
  - This was used for the custom role `role_web_server`, which deploys a very simple Apache web server (including a small, built-in MariaDB database).

- Bert Van Vreckem. (2016). *bertvv/ansible-role-rh-base: Ansible role for basic setup of a server with a RedHat-based Linux distribution (CentOS, Fedora, RHEL, ...)*. GitHub. https://github.com/bertvv/ansible-role-rh-base
  - This was used for executing various basic configuration tasks (such as setting up the firewall and installing packages) on every VM (currently all running AlmaLinux 9).

- Grafana Labs. (2026). *grafana/grafana-ansible-collection: grafana.grafana Ansible collection provides modules and roles for managing various resources on Grafana Cloud and roles to manage and deploy Grafana Agent and Grafana*. GitHub. https://github.com/grafana/grafana-ansible-collection
  - This was used for the custom role `role_monitoring_server`, which deploys a Prometheus + Grafana monitoring stack.

- Prometheus Monitoring Community. (2026). *prometheus-community/ansible: Ansible Collection for Prometheus. GitHub*. https://github.com/prometheus-community/ansible
  - This was used for the custom role `role_monitoring_server` as well as the various exporters (node, MySQL, BIND).

### Grafana dashboards

- F., R. (2025). *rfmoz/grafana-dashboards: Grafana dashboards*. GitHub. https://github.com/rfmoz/grafana-dashboards
  - This was used for the Grafana dashboards for Apache Exporter (altered slightly), Bind Exporter, and Node Exporter.

- Grafana Labs. (2024). *MySQL Exporter Quickstart and Dashboard*. Grafana Labs. https://grafana.com/grafana/dashboards/14057-mysql/
  - This was used for the Grafana dashboard for MySQL Exporter.

### Other projects

- Bert Van Vreckem. (2025). *bertvv/ansible-skeleton: An opinionated skeleton for Ansible projects with a development environment powered by Vagrant*. GitHub. https://github.com/bertvv/ansible-skeleton
  - This was used to set up a local, Vagrant- and Ansible-ready virtual environment. A tailor-made version of this project (used in the HOGENT course module "[Infrastructure Automation](https://bamaflexweb.hogent.be/BMFUIDetailxOLOD.aspx?a=193608&b=5&c=1)") has been used and altered (notably `Vagrantfile` and `scripts/control.sh`) for the purposes of this proof-of-concept.

- HoGentTIN. (2025a). *HoGentTIN/cybersecurity-advanced-lab-template: Cybersecurity Advanced - lab environment template*. GitHub. https://github.com/HoGentTIN/cybersecurity-advanced-lab-template
  - The network diagram for the lab template of this course module was used and slightly altered as input (without corresponding deployment diagram) for this proof-of-concept.

- HoGentTIN. (2025b). *HoGentTIN/infra-labs: Lab assignments for the Infrastructure Automation course*. GitHub. https://github.com/HoGentTIN/infra-labs
  - The labs 2 and 3 of this course module were used as references for creating network- and deployment diagrams as input for this proof-of-concept.

## License

<!--TODO-->
