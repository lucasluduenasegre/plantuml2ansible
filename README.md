# PlantUML2Ansible

## Table of Contents

<!--TODO-->

## Context

PlantUML2Ansible is a "work in progress" and Proof-of-Concept transpiler that converts network and deployment diagrams (created using PlantUML) to IaC and configuration management supported environments (provided by Vagrant & Ansible, respectively). This solution is developed as part of a bachelor's thesis within the context of Applied IT at HOGENT (and its relevant course modules such as "[Cybersecurity Advanced](https://bamaflexweb.hogent.be/BMFUIDetailxOLOD.aspx?a=193610&b=5&c=1)" and "[Infrastructure Automation](https://bamaflexweb.hogent.be/BMFUIDetailxOLOD.aspx?a=193608&b=5&c=1)".

<!--TODO-->

## Limitations

Since this is a proof-of-concept, there are noteworthy limitations to the possible input and output of this tool. Here is a non-exhaustive list:

- The environment is deployed locally with Vagrant. The to be generated Ansible code (which will be used to configure this environment) will therefore be shaped according to this backend.
- Only environments with a **single network** are supported when generating **both Vagrant and Ansible code**, as configuring routing is beyond the scope for this proof-of-concept.
- **Multiple networks** can be specified when **only generating Vagrant code**, so long as there are no hosts with more than **3** IP addresses. This is a technical limitation due to VirtualBox's maximum of 4 network interfaces, of which the first is reserved for the NAT interface Vagrant uses.
- Only IPv4 addressing is supported.
- The diagrams can only represent hosts that are to be managed by either the Vagrant or Ansible code, **unless** otherwise specified in the network diagram (`managed = false`).
- The virtual machines in this environment will use the AlmaLinux 9 operating system (more specifically the Vagrant base box "bento/almalinux-9"). The reason is because the Ansible roles by Bert Van Vreckem were developed for a now deprecated version of Ansible, which is not provided by AlmaLinux 10. Much of the functionality provided by these roles is limited when ran on AlmaLinux 10. This choice has obvious security implications for this environment, yet it is one of the compromises that had to be made for this proof-of-concept.

<!--TODO-->

## Prerequisites

- Git 
- Python (tested on 3.14.4)
  - `pip` dependencies:
    - `jinja2`
    - `pyyaml`
    - `yamllint`
- Vagrant (tested on 2.4.9)
- VirtualBox (tested on 7.2.8)

Ansible only runs on the control node and therefore does not have to be installed on the host machine.

## Installation

<!--TODO-->

Linux/Mac:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install jinja2
```

Windows:
```powershell
python3 -m venv .venv
.venv\Scripts\activate
pip install jinja2
```

## Usage

<!--TODO-->

### Network diagram only

Converting a network diagram to an IaC-only supported environment with Vagrant (**multiple networks** supported):

```
python convert.py <nwdiag-path>
```

This is useful if you wish to have more freedom when setting up configuration management with Ansible, but you do want a ready-to-use Vagrant environment.

### Full mode (network + deployment diagram)

Converting a network diagram + corresponding deployment diagram (both in `.puml`) to an IaC (Vagrant) + configuration management (Ansible) supported environment (only **one single network** is supported):

```
python convert.py <nwdiag-path> <uml-path> [--role-config <role-config-path>]
```

This environment will, in addition to a Vagrant environment and Ansible inventory, set up a rudimentary yet completely Ansible-supported project based on predefined roles assigned to hosts. This setup, however, is limited to a single network, as routing is beyond the scope for this proof-of-concept. A custom role configuration file can optionally be provided.

## Input format (network + deployment diagrams)

<!--TODO-->

### Network diagram (`@startnwdiag`)

This diagram illustrates the logical topology of networks and hardware elements (in this case Vagrant VMs) in a given environment, along with their respective network and IP addresses. Multiple networks **can** be defined for IaC-only supported environments, as long as there are no hosts with more than **3** IP addresses.

<!--TODO-->

### Deployment diagram (`@startnwdiag`)

This diagram represents the configuration of hosts (denoted as nodes) and their components (in this case Ansible roles). As mentioned before, only hosts within a single network can be represented here.

<!--TODO-->

## Output structure in `<output_directory>/<diagram_name>/`

### Network diagram only

Generated (based on diagram):
- `vagrant-hosts.yml` (**without** `control`)

Copied (verbatim):
- `Vagrantfile`

<!--TODO-->

### Full mode (network + deployment diagram)

Generated (based on diagrams):
- `vagrant-hosts.yml` (**with** `control`)
- `ansible/inventory.yml`
- `ansible/site.yml`
- `ansible/host_vars/dns.yml`
- `ansible/host_vars/monitoring.yml`
- `ansible/host_vars/web.yml`
- `ansible/requirements.yml`


Copied (verbatim):
- `Vagrantfile`
- `scripts/`
- `ansible/roles/<role_name>/` (for each defined role)
- `ansible/files/grafana_dashboards/<grafana_dashboard>.json` (for each defined exporter)
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
  - This was used for the Grafana dashboards for Node Exporter and Bind Exporter.

- Grafana Labs. (2024). *MySQL Exporter Quickstart and Dashboard*. Grafana Labs. https://grafana.com/grafana/dashboards/14057-mysql/
  - This was used for the Grafana dashboard for MySQL Exporter.

### Other projects

- Bert Van Vreckem. (2025). *bertvv/ansible-skeleton: An opinionated skeleton for Ansible projects with a development environment powered by Vagrant*. GitHub. https://github.com/bertvv/ansible-skeleton
  - This was used to set up a local, Vagrant- and Ansible-ready virtual environment. A tailor-made version of this project (used in the HOGENT course module "[Infrastructure Automation](https://bamaflexweb.hogent.be/BMFUIDetailxOLOD.aspx?a=193608&b=5&c=1)") has been used and slightly altered (notably `Vagrantfile` and `scripts/control.sh`) for this proof-of-concept.

- HoGentTIN. (2025a). *HoGentTIN/cybersecurity-advanced-lab-template: Cybersecurity Advanced - lab environment template*. GitHub. https://github.com/HoGentTIN/cybersecurity-advanced-lab-template
  - The network diagram for the lab template of this course module was used and slightly altered as input for this proof-of-concept

- HoGentTIN. (2025b). *HoGentTIN/infra-labs: Lab assignments for the Infrastructure Automation course*. GitHub. https://github.com/HoGentTIN/infra-labs
  - The labs 2 and 3 of this course module were used as references for creating network- and deployment diagrams as input for this proof-of-concept.

## License

<!--TODO-->
