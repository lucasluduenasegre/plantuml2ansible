# PlantUML2Ansible

## Table of Contents

<!--TODO-->

## Context

PlantUML2Ansible is a "work in progress" and Proof-of-Concept transpiler that converts network and deployment diagrams (created using PlantUML) to IaC and configuration management supported environments (provided by Vagrant & Ansible). This solution is developed as part of a bachelor's thesis within the context of Applied IT at HOGENT (and its relevant course modules such as "Cybersecurity Advanced" and "Infrastructure Automation").

<!--TODO-->

## Limitations

Since this is a proof-of-concept, there are a number of noteworthy limitations to the possible input and output of this tool:

- The environment is deployed locally with Vagrant. The to be generated Ansible-code (which will be used to configure this environment) will therefore be shaped according to this backend.
- The virtual machines in this environment will use the AlmaLinux 9 operating system (more specifically the Vagrant base box "bento/almalinux-9"). The reason is because the Ansible roles developed by Bert Van Vreckem were developed for a now deprecated version of Ansible, which is not provided by AlmaLinux 10. Much of the functionality provided by these roles is limited or even hindered when ran on AlmaLinux 10. This choice has obvious security implications for this environment, yet it is one of the compromises that had to be made for this proof-of-concept.
- The hosts in this environment are located under the local (class B) IPv4 network 172.26.0.0/16 (only IPv4 will be supported). Multiple networks/subnets are supported, as long as they fall within this overarching network. One can assume that the entire environment can be accessed by the Ansible control node (with IP address 172.26.0.2/16).

<!--TODO-->

## Prerequisites

- Git
- Vagrant
- VirtualBox 7.1 or higher
<!--TODO-->

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

## Basic usage

<!--TODO-->

### IaC-only

Converting a network diagram to an IaC-only supported environment (Vagrant environment + Ansible inventory):
```
python convert.py <nwdiag.puml>
```

This is useful if you wish to have more freedom when setting up configuration management with Ansible, but you do want a ready-to-use Vagrant environment and corresponding Ansible inventory.

### IaC + configuration management

Converting a network diagram + corresponding deployment diagram to an IaC + configuration management supported environment (full Vagrant + Ansible environment)
```
python convert.py <nwdiag.puml> <uml.puml>
```

This environment will, in addition to a Vagrant environment and Ansible inventory, set up a rudimentary yet completely Ansible-supported project based on predefined roles assigned to hosts.

### Custom role(s) configuration

Using a custom role configuration file:
```
python convert.py <nwdiag.puml> <uml.puml> --config <role-config.yml>
```

## Acknowledgements & Credits

- https://github.com/bertvv/ansible-role-bind
- https://github.com/bertvv/ansible-role-httpd
- https://github.com/bertvv/ansible-role-rh-base
- https://github.com/bertvv/ansible-skeleton ([Infrastructure Automation](https://bamaflexweb.hogent.be/BMFUIDetailxOLOD.aspx?a=193608&b=5&c=1)-tailored version)

<!--TODO-->

## License

<!--TODO-->
