python_ver := '3.11.5'
python_subdir := if os_family() == "windows" { "/Scripts" } else { "/bin" }
python_exec := if os_family() == "windows" { "/python.exe" } else { "/python3" }
system_python := if os_family() == "windows" { ".pyenv/shims" } else { "${HOME}/.pyenv/versions/" + python_ver + "/bin/python3" }
zappa := './.venv/' + python_subdir + '/zappa'

default:
  @just --list

# Bootstrap Python Env. Valid Types: 'deploy' & 'dev'
bootstrap venv_dir='.venv' type="deploy":
  if test ! -e {{ venv_dir }}; then {{ system_python }} -m venv {{ venv_dir }}; fi
  ./{{ venv_dir }}{{ python_subdir }}{{ python_exec }} -m pip install --upgrade pip
  ./{{ venv_dir }}{{ python_subdir }}{{ python_exec }} -m pip install --upgrade -r requirements.txt {{ if type == 'dev' { '-r dev_requirements.txt' } else { '' } }}

_aws_login AWS_PROFILE:
  @aws --profile {{ AWS_PROFILE }} sts get-caller-identity || aws sso login

_zappa CMD ACCT ENV:
  @just _aws_login "$(yq '.{{ ENV }}.profile_name' envs/{{ ACCT }}.yml)"
  {{ zappa }} {{ CMD }} -s envs/{{ ACCT }}.yml {{ ENV }}

# Deploy new environment
deploy ACCT='test' ENV='dev': (_zappa "deploy" ACCT ENV)

# Certify new environment
certify ACCT='test' ENV='dev': (_zappa "certify" ACCT ENV)

# Update existing environment
update ACCT='test' ENV='dev': (_zappa "update" ACCT ENV)

# Check status of existing environment
status ACCT='test' ENV='dev': (_zappa "status" ACCT ENV)

# Check logs of running environment
logs ACCT='test' ENV='dev': (_zappa "tail" ACCT ENV)

# Undeploy a running environment
undeploy ACCT='test' ENV='dev': (_zappa "undeploy" ACCT ENV)