# PlantUML2Ansible

## Table of Contents

<!--TODO-->

## Context

PlantUML2Ansible is a "work in progress" and Proof-of-Concept transpiler that converts network and deployment diagrams (created using PlantUML) to IaC and configuration management supported environments (provided by Vagrant & Ansible, respectively). This solution is developed as part of a bachelor's thesis within the context of Applied IT at HOGENT (and its relevant course modules such as "[Cybersecurity Advanced](https://bamaflexweb.hogent.be/BMFUIDetailxOLOD.aspx?a=193610&b=5&c=1)" and "[Infrastructure Automation](https://bamaflexweb.hogent.be/BMFUIDetailxOLOD.aspx?a=193608&b=5&c=1)".

<!--TODO-->

## Limitations

Since this is a proof-of-concept, there are noteworthy limitations to the possible input and output of this tool. Here is a non-exhaustive list:

- The environment is deployed locally with Vagrant. The to be generated Ansible code (which will be used to configure this environment) will therefore be shaped according to this backend.
- Only environments with a **single network** are supported when generating both Vagrant and Ansible code. Multiple networks can, however, be specified when only generating Vagrant code. Only IPv4 addressing is supported.
- The diagrams can only represent hosts that are to be managed by either the Vagrant or Ansible code, **unless** otherwise specified in the network diagram.
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
source .venv/bin/activate        # Windows: .venv\Scripts\activate
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

Converting a network diagram to an IaC-only supported environment with Vagrant (multiple networks supported):
```
python convert.py <nwdiag-path>
```

This is useful if you wish to have more freedom when setting up configuration management with Ansible, but you do want a ready-to-use Vagrant environment.

### Full mode (network + deployment diagram)

Converting a network diagram + corresponding deployment diagram (both in `.puml`) to an IaC (Vagrant) + configuration management (Ansible) supported environment (only **one** network supported)
```
python convert.py <nwdiag-path> <uml-path> [--role-config <role-config-path>]
```

This environment will, in addition to a Vagrant environment and Ansible inventory, set up a rudimentary yet completely Ansible-supported project based on predefined roles assigned to hosts. This setup, however, is limited to a single network, as routing is beyond the scope for this proof-of-concept. A custom role configuration file can optionally be provided.

## Input format (network + deployment diagrams)

<!--TODO-->

### Network diagram (`@startnwdiag`)

This diagram illustrates the logical topology of networks and hardware elements (in this case Vagrant VMs) in a given environment, along with their respective network and IP addresses. Multiple networks can be defined for IaC-only supported environments, as long as there are no hosts with more than 3 IP addresses.

<!--TODO-->

### Deployment diagram (`@startnwdiag`)

This diagram represents the configuration of hosts (denoted as nodes) and their components (in this case Ansible roles). As mentioned before, only hosts within a single network can be represented here.

<!--TODO-->

## Output structure

### Network diagram only

Generated (based on diagram):
- `<output-directory>/<diagram-name>/vagrant-hosts.yml` (**without** `control`)

Copied (verbatim):
- `<output-directory>/<diagram-name>/Vagrantfile`

<!--TODO-->

### Full mode (network + deployment diagram)

Generated (based on diagrams):
- `<output-directory>/<diagram-name>/vagrant-hosts.yml` (**with** `control`)
output\test_env\ansible/inventory.yml
output\test_env\ansible/site.yml
output\test_env\ansible/host_vars\dns.yml
output\test_env\ansible/host_vars\monitoring.yml
output\test_env\ansible/host_vars\web.yml
output\test_env\ansible/requirements.yml


Copied (verbatim):
- Asset `<output-directory>/<diagram-name>/Vagrantfile`
Copied asset: output\test_env\Vagrantfile
Copied directory: output\test_env\scripts/
Copied role: output\test_env\ansible\roles\role_monitoring_server
Copied role: output\test_env\ansible\roles\role_dns_client
Copied role: output\test_env\ansible\roles\role_dns_server
Copied role: output\test_env\ansible\roles\role_web_server
Copied asset: output\test_env\ansible/files/grafana_dashboards/node_exporter.json
Copied asset: output\test_env\ansible/files/grafana_dashboards/mysqld_exporter.json
Copied asset: output\test_env\ansible/files/grafana_dashboards/bind_exporter.json
Copied asset: output\test_env\ansible/files/db.sql
Copied asset: output\test_env\ansible/files/test.php
- 
<!--TODO-->

## Acknowledgements & Credits

### Ansible roles

- https://github.com/bertvv/ansible-role-bind
- https://github.com/bertvv/ansible-role-httpd
- https://github.com/bertvv/ansible-role-rh-base

### Grafana dashboards

- https://grafana.com/grafana/dashboards/14057-mysql/
- https://github.com/rfmoz/grafana-dashboards

### Other projects
- https://github.com/bertvv/ansible-skeleton ("[Infrastructure Automation](https://bamaflexweb.hogent.be/BMFUIDetailxOLOD.aspx?a=193608&b=5&c=1)"-tailored version)

<!--TODO-->

## License

<!--TODO-->
