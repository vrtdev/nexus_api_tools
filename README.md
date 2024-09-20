# nexus_api_tools

Nexus API tools

Tools to migrate repositories between Nexus servers.

This tool can modify the DockerRootDir / data-root setting so it should NOT be run on a Docker server.

## Installation

```bash
python3 -m venv --clear venv
. venv/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
./nexus_copy.py --help
```

## Action file

The Action file that can be passed as an argumet to the --file parameter is a yaml file with the following structure:

```yaml
config:
  # local_path: 
  source_server: https://<source repo server>
  # source_user: admin
  # source_password: admin123
  destination_server: https://<destination repo server>
  # destination_user: admin
  # destination_password: admin123
  docker_source_server: <source docker repo server>
  docker_destination_server: <destination docker repo server>
  default_action: both
actions:
  # - repo: <repo-name>
    # description: Get & upload <repo-name> repo
    # type: <type>
    # action: both  # default, can be omitted
    # path: data/<repo>  # default, can be omitted
    # active: true  # default, can be omitted
```
