uv_install := if os_family() == "windows" { 'powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"' } else { "curl -LsSf https://astral.sh/uv/install.sh | sh" }

# This list
default:
  @just --list

# Ensure `uv` is installed
bootstrap:
  {{ uv_install }}

_aws_login AWS_PROFILE:
  @aws --profile {{ AWS_PROFILE }} sts get-caller-identity || aws sso login

_zappa CMD ACCT ENV:
  @just _aws_login "$(yq '.{{ ENV }}.profile_name' envs/{{ ACCT }}.yml)"
  uv run zappa {{ CMD }} -s envs/{{ ACCT }}.yml {{ ENV }}

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