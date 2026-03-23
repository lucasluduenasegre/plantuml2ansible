#! /bin/bash
#
# Provisioning script for Ansible control node

#---------- Bash settings ------------------------------------------------------

# Enable "Bash strict mode"
set -o errexit   # abort on nonzero exitstatus
set -o nounset   # abort on unbound variable
set -o pipefail  # don't mask errors in piped commands

#---------- Variables ----------------------------------------------------------

# Location of provisioning scripts and files
readonly PROVISIONING_SCRIPTS="/vagrant/scripts/"
export PROVISIONING_SCRIPTS
# Location of files to be copied to this server
readonly PROVISIONING_FILES="${PROVISIONING_SCRIPTS}/${HOSTNAME}"
export PROVISIONING_FILES

#---------- Load utility functions --------------------------------------------

# shellcheck source=/dev/null
source ${PROVISIONING_SCRIPTS}/util.sh

#---------- Provision host ----------------------------------------------------

log "Starting server specific provisioning tasks on host ${HOSTNAME}"

log "Installing Ansible and dependencies"

dnf install -y \
  epel-release

dnf install -y \
  bash-completion \
  bats \
  bind-utils \
  mc \
  psmisc \
  python3-libselinux \
  python3-libsemanage \
  python3-netaddr \
  python3-pip \
  python3-PyMySQL \
  sshpass \
  tree \
  vim-enhanced

log "Adding Ansible hosts to ~/.ssh/known_hosts"

sudo --login --non-interactive --user=vagrant -- bash << 'EOF'
grep -oP "^\s*ip:\s*\K\S+" /vagrant/vagrant-hosts.yml | sort -u | while read -r ip; do
  ssh-keyscan -H "${ip}" >> ~/.ssh/known_hosts 2>/dev/null
done
EOF

log "Installing Ansible Python modules"

sudo --login --non-interactive --user=vagrant -- bash -c "pip install ansible paramiko jmespath"

log "Installing Ansible requirements from Ansible Galaxy"

sudo --login --non-interactive --user=vagrant -- bash -c "ansible-galaxy install -r /vagrant/ansible/requirements.yml"

# log "Running \"router-config.yml\"-playbook"

# sudo --login --non-interactive --user=vagrant -- bash -c "ansible-playbook -i /vagrant/ansible/inventory-alpha.yml /vagrant/ansible/router-config.yml"

log "Running \"site-alpha.yml\"-playbook"

sudo --login --non-interactive --user=vagrant -- bash -c "ansible-playbook -i /vagrant/ansible/inventory-alpha.yml /vagrant/ansible/site-alpha.yml -vvvv"