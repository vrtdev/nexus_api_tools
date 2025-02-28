# nexus_api_tools

Nexus API tools

Tools to migrate repositories between Nexus servers.

Note: Nexus API does not support uploading to Maven SNAPSHOT repositories.

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

The Action file that can be passed as an argument to the --file parameter is a yaml file with the following structure:

```yaml
source:
  host: https://nexus-public.core.a51.be
  docker_host: <source docker repo host>
  user: admin
  password: FILL_PASSWORD_HERE
destination:
  host: https://nexus.core.a51.be
  docker_host: <destination docker repo host>
  user: admin
  password: admin123
local_path: some_dir
default_action: both
actions:
  - repo: <repo-name>
    description: Get & upload <repo-name> repo
    repo_type: <repo_type>
    action: both  # default, can be omitted
    path: data/<repo>  # default, can be omitted
    active: true  # default, can be omitted
  - repo: docker
    description: Get & upload docker repo
    repo_type: docker
    source:
      docker_host: <source docker repo host>
    destination:
      docker_host: <destination docker repo host>
    active: false
  - repo: vrt-releases
    target_repo: public-vrt-maven-releases
    description: Get & upload vrt-releases repo
    repo_type: maven2
  - repo: vrtnu-design-system
    target_repo: public-vrtnu-design-system
    description: Get & upload vrtnu-design-system repo
    repo_type: npm
  - repo: vrt-npm
    target_repo: public-vrt-npm
    description: Get & upload vrt-npm repo
    repo_type: npm
```
