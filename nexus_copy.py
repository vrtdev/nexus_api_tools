#!/usr/bin/env python3

"""
Backup ( & restore Nexus repos).

https://help.sonatype.com/en/uploading-components.html
"""

import argparse
import os
import json
import re
import yaml
import requests
from requests.auth import HTTPBasicAuth
import pprint
import subprocess
import getpass
from datetime import datetime

source_server = os.environ.get('SOURCE_NEXUS_SERVER')
source_user = os.environ.get('SOURCE_NEXUS_USER')
source_password = os.environ.get('SOURCE_NEXUS_PASSWORD')

destination_server = os.environ.get('DESTINATION_NEXUS_SERVER')
destination_user = os.environ.get('DESTINATION_NEXUS_USER')
destination_password = os.environ.get('DESTINATION_NEXUS_PASSWORD')

api_path = 'service/rest/v1'
local_path = './'
asset_type_filters = {
    'apt': r'.(deb|udeb)$',
    'npm': r'.tgz$',
    'maven2': r'.(jar|zip|xml|pom|war|ear)$',
    'yum': r'.(rpm|drpm)$',
    'pypi': r'.tar.gz$',
    'rubygems': r'.gem$',
    'nuget': r'.nupkg$',
}


def log_print(*msg):
    now = datetime.now()
    print(f"{now} : ", ' '.join(msg))


def set_nexus_source_server(server=None):
    global source_server
    if server is not None:
        source_server = server


def set_nexus_destination_server(server=None):
    global destination_server
    if server is not None:
        destination_server = server


def get_file_mime_type(file):
    p = subprocess.Popen(["file", "--brief", "--mime-type", file], stdout=subprocess.PIPE)
    (output, _) = p.communicate()
    p.wait()
    mime_type = output.decode().rstrip()
    return mime_type


def api_call(url, type='GET', files={}, data={}, direction='source'):
    """Generic Nexus Rest API call."""
    start = datetime.now()
    auth = {}
    return_value = {}
    if direction == 'source':
        url = f"{source_server}/{url}"
        username = source_user
        password = source_password
    elif direction == 'destination':
        url = f"{destination_server}/{url}"
        username = destination_user
        password = destination_password

    log_print(f"api_call : type={type} direction={direction} url={url}")

    try:
        if password is not None:
            auth = HTTPBasicAuth(username, password)

        if type == 'GET':
            response = requests.get(url, auth=auth)
        elif type == 'POST':
            response = requests.post(url, files=files, data=data, auth=auth)
        else:
            log_print(f"Unsupported method '{type}'... ")
        response.raise_for_status()
        if response.text is not None and response.text != '':
            return_value = json.loads(response.text)

        end = datetime.now()
        call_time = end - start
        # log_print(f"url={url}, files={files}, data={data}, auth={auth}")
        log_print(f"api_call done. time taken : {call_time}")
        return return_value
    except requests.exceptions.ConnectionError as e:
        log_print(f"Nexus api {type} call failed. Error Connecting:", e)
        raise SystemExit(e)
    except requests.exceptions.Timeout as e:
        log_print(f"Nexus api {type} call failed. Timeout Error:", e)
        raise SystemExit(e)
    except requests.exceptions.HTTPError as e:
        log_print(f"Nexus api {type} call failed. HTTPError : {e}")
        log_print(f"url={url}, files={files}, data={data}, auth={auth}")
        raise SystemExit(e)
    except requests.exceptions.RequestException as e:
        log_print(f"Nexus api {type} call failed. RequestException : {e}")
        raise SystemExit(e)
    except Exception as e:
        log_print(f"Nexus api {type} call failed. Exception : {e}")
        raise SystemExit(e)


def api_get(request, files={}, data={}, direction='source'):
    url = f"{api_path}/{request}"
    return api_call(url, 'GET', files, data, direction)


def api_post(request, files={}, data={}):
    url = f"{api_path}/{request}"
    return api_call(url, 'POST', files, data, 'destination')


def get_continuationtoken(data):
    """Check for a continuationtoken and pass the url request string to fetch the next page."""
    if ('continuationToken' in data) and (data['continuationToken'] is not None):
        return f"&continuationToken={data['continuationToken']}"
    else:
        return False


def yield_items(repo, type, direction='source'):
    """Download page per page of items of type 'assets' or 'components' from a repo and yield each item, reducing memory footprint."""
    data = api_get(f"{type}?repository={repo}", None, None, direction)
    for item in data['items']:
        yield item
    while (token_req := get_continuationtoken(data)) and (token_req is not False):
        more_data = api_get(f"{type}?repository={repo}{token_req}", None, None, direction)
        for item in more_data['items']:
            yield item
        data = more_data


def get_asset(id):
    return api_get(f"assets/{id}")


def get_repo_components(repo, direction='source', count=0):
    components = {}
    components_fetched = 0
    for component in yield_items(repo, 'components', direction):
        components_fetched += 1
        # print(f"component:{component}")
        name = f"{component['name']}:{component['version']}"
        if 'format' in component:
            if component['format'] == 'docker':
                components[name] = {
                    'format': component['format'],
                    'group': component['group'],
                    'name': component['name'],
                    'version': component['version'],
                    'repository': component['repository'],
                }
                log_print(f"Added component:{name} - {components_fetched}")
        if count > 0 and components_fetched >= count:
            break
    return components


def get_repo_assets(repo, direction='source', type='components'):
    other = []
    assets = {}
    count = 0
    for item in yield_items(repo, type, direction):
        # log_print(f"item:{item}")
        if type == 'components':
            item_assets = item['assets']
        elif type == 'assets':
            item_assets = [item]
        for asset in item_assets:
            # log_print(f"asset:{asset}")
            filter = asset_type_filters.get(asset['format'], None)
            if filter is None or re.search(rf"{filter}", asset['path']):
                count += 1
                if 'format' in asset:
                    if asset['format'] == 'maven2':
                        if 'maven2' in asset:
                            assets[asset['path']] = {
                                'format': asset['format'],
                                'downloadUrl': asset['downloadUrl'],
                                'path': asset['path'],
                                'id': asset['id'],
                                'maven2': asset['maven2'],
                                'contentType': asset['contentType']
                            }
                            if 'classifier' in asset['maven2']:
                                assets[asset['path']]['classifier'] = asset['maven2']['classifier']
                    elif asset['format'] == 'npm':
                        if 'npm' in asset:
                            assets[asset['path']] = {
                                'format': asset['format'],
                                'downloadUrl': asset['downloadUrl'],
                                'path': asset['path'],
                                'id': asset['id'],
                                'npm': asset['npm'],
                                'contentType': asset['contentType']
                            }
                    else:
                        assets[asset['path']] = {
                            'format': asset['format'],
                            'downloadUrl': asset['downloadUrl'],
                            'path': asset['path'],
                            'id': asset['id']
                        }
                else:
                    other.append(asset['path'])
                log_print(f"Added asset:{asset['path']} - {count}")
            # else:
            #     log_print(f"Ignoring filtered asset:{asset['path']}")
    return assets, other


def list_repo_assets(repo):
    count = 0
    for asset in yield_items(repo, 'assets'):
        log_print("asset:")
        pprint.pprint(asset)
        count += len(asset)
    log_print(f"asset_count:{count}")


def list_repo_components(repo):
    count = 0
    for component in yield_items(repo, 'components'):
        log_print("component:")
        pprint.pprint(component)
        count += len(component['assets'])
    log_print(f"asset_count:{count}")


def download_repo_assets(repo, path='.', force_download=False):
    assets, _ = get_repo_assets(repo)
    if not path.endswith('/'):
        path = f"{path}/"
    count = 0
    items = len(assets)
    for _, asset in assets.items():
        count += 1
        local_file = f"{path}{asset['path']}"
        if not os.path.exists(local_file) or force_download:
            if not os.path.exists(os.path.dirname(local_file)):
                log_print(f"Creating directory : {path}{os.path.dirname(asset['path'])}")
                os.makedirs(os.path.dirname(local_file), exist_ok=True)
            log_print(f"Downloading asset '{asset['downloadUrl']}' to '{local_file}' - {count}/{items}")
            response = requests.get(asset['downloadUrl'], allow_redirects=True)
            open(local_file, 'wb').write(response.content)
        else:
            log_print(f"Skipping download of '{local_file}' as it already exists. - {count}/{items}")


def upload_component(repo, local_file, repo_file, asset_type, mime_type):
    """Upload single component <file> to <repo>"""
    data = None
    if repo_file is None:
        repo_file = local_file
    repo_path = os.path.dirname(repo_file)
    repo_filename = os.path.basename(repo_file)
    if asset_type == 'raw':
        data = {"raw.directory": f"{repo_path}", "raw.asset1.filename": f"{repo_filename}"}
        files = [(f"{asset_type}.asset1", (repo_file, open(local_file, 'rb'), mime_type))]
    elif asset_type == 'maven2':
        data = get_maven_info(repo_file)
        files = [(f"{asset_type}.asset1", (repo_file, open(local_file, 'rb'), mime_type))]
    elif asset_type == 'yum':
        data = {"yum.directory": f"{repo_path}", "yum.asset.filename": f"{repo_filename}"}
        files = [(f"{asset_type}.asset", (repo_file, open(local_file, 'rb'), mime_type))]
    else:  # apt, npm, pypi, raw, docker, gem, nuget
        files = [(f"{asset_type}.asset", (repo_file, open(local_file, 'rb'), mime_type))]
    api_post(f"components?repository={repo}", files, data)


def upload_components(repo, asset_type, path='.', overwrite=False):
    """Upload all component files found in <path> to <repo>"""
    if not path.endswith('/'):
        path = f"{path}/"
    filter = asset_type_filters.get(asset_type, None)
    assets = []
    if not overwrite:
        assets, _ = get_repo_assets(repo, 'destination')
    count = 0
    file_count = 0
    for root, _, files in os.walk(path):
        file_count += len(files)
    for root, _, files in os.walk(path):
        for name in files:
            count += 1
            # log_print(f"root:{root} - name:{name}")
            local_file = os.path.join(root, name)
            if filter is None or re.search(rf"{filter}", name):
                repo_file = local_file.removeprefix(path)
                if not repo_file.startswith('/'):
                    repo_file = f"/{repo_file}"
                if not overwrite:
                    # log_print(f"repo_file:{repo_file} - assets:{assets.keys()}")
                    if repo_file in assets.keys():
                        log_print(f"NOT uploading: local_file:{local_file}, it already exists in repo. - {count}/{file_count}")
                        continue
                mime_type = get_file_mime_type(local_file)
                log_print(f"Uploading: local_file:{local_file} - repo_file:{repo_file} - mime_type:{mime_type} - {count}/{file_count}")
                upload_component(repo, local_file, repo_file, asset_type, mime_type)
            else:
                log_print(f"Ignoring filtered local_file:{local_file} - {count}/{file_count}")


def get_maven_info(repo_file):
    """Get maven info from a maven file path"""
    parts = repo_file.split('/')
    if parts[0] == '':
        parts.pop(0)
    file_name = parts.pop(-1)
    version = parts.pop(-1)
    artifact_id = parts.pop(-1)
    groupid = '.'.join(parts)
    # extension = file_name.replace(f"{artifact_id}-{version}.", '')
    extension = re.search(rf"{asset_type_filters['maven2']}", file_name).group(0).lstrip('.')
    info = {
        'maven2.groupId': groupid,
        'maven2.artifactId': artifact_id,
        'maven2.version': version,
        'maven2.asset1.extension': extension
    }
    base_name = file_name.replace(f".{extension}", '')
    f = rf'{version}-.+$'
    r = re.search(f, base_name)
    if r:
        classifier = r.group(0).replace(f'{version}-', '')
        info['maven2.asset1.classifier'] = classifier
    return info


# Docker
# https://docs.docker.com/engine/install/debian/

def set_docker_image_download_path(root_dir='/var/lib/jenkins/nexus3/data/docker-images'):
    docker_info = subprocess.run(['docker', 'info', '--format', 'json'], capture_output=True)
    docker_info_o = docker_info.stdout.decode()
    docker_info_json = json.loads(docker_info_o)
    docker_root_dir = docker_info_json['DockerRootDir']
    print(f"Current DockerRootDir : {docker_root_dir}")
    if docker_root_dir != root_dir:
        log_print(f"Setting DockerRootDir to {root_dir}")
        subprocess.run(['systemctl', 'stop', 'docker'])
        open('/etc/docker/daemon.json', 'w').write(f'{"data-root": "{root_dir}"}')
        subprocess.run(['systemctl', 'start', 'docker'])


def list_local_docker_images(filter=None):
    containers = {}
    containers_json = subprocess.run(['docker', 'images', '--format', 'json'], capture_output=True)
    for container in containers_json.stdout.decode().splitlines():
        container_o = json.loads(container)
        if filter is None or re.search(rf"{filter}", container_o['Repository']):
            containers[f"{container_o['Repository']}:{container_o['Tag']}"] = container_o
    return containers


def docker_login(server, username, password):
    subprocess.run(['docker', 'login', server, '-u', username, '-p', password])


def download_repo_assets_docker(server, repo):
    set_docker_image_download_path()
    components = get_repo_components(repo, 'source', 0)
    source_count = len(components)
    count = 0
    for _, component in components.items():
        count += 1
        image_url = f"{server}/{component['name']}:{component['version']}"
        log_print(f"docker pull {image_url} - {count}/{source_count}")
        subprocess.run(['docker', 'pull', image_url])
    log_print(f"asset_count:{count}")
    return count


def upload_components_docker(repo, destination):
    set_docker_image_download_path()
    if not destination.endswith('/'):
        destination = f"{destination}/"
    docker_login(destination, destination_user, destination_password)
    images = list_local_docker_images(rf'^{destination}',)
    source_count = len(images)
    image_count = 0
    for image, _ in images.items():
        image_count += 1
        if image.startswith(destination):
            log_print(f"docker push {image} - {image_count}/{source_count}")
            subprocess.run(['docker', 'push', image])


def tag_docker_images(source, destination):
    set_docker_image_download_path()
    if not source.endswith('/'):
        source = f"{source}/"
    if not destination.endswith('/'):
        destination = f"{destination}/"
    images = list_local_docker_images()
    source_count = len(images)
    image_count = 0
    for image, _ in images.items():
        image_count += 1
        image_path = image.replace(source, '')
        # log_print(f"Tagging Docker images from {image} to {destination}{image_path}")
        if image.startswith(source):
            if f"{destination}{image_path}" not in images:
                log_print(f"docker tag {image} {destination}{image_path} - {image_count}/{source_count}")
                subprocess.run(['docker', 'tag', image, f"{destination}{image_path}"])
            else:
                log_print(f"Skipping docker tag {image} {destination}{image_path} as it already exists. - {image_count}/{source_count}")

# Cleanup ALL Docker images
# docker rmi -f $(docker images -aq)


if __name__ == "__main__":
    msg = "Nexus API functions"
    parser = argparse.ArgumentParser(description=msg)
    parser.add_argument("--source-server", help="Source Server to use. Can also be set via SOURCE_NEXUS_SERVER env variable.")
    parser.add_argument(
        "--destination-server", help="Destination Server to use. Can also be set via DESTINATION_NEXUS_SERVER env variable."
    )
    parser.add_argument("--source-user", help="Source server username. Can also be set via SOURCE_NEXUS_USER env variable.")
    parser.add_argument("--source-password", help="""Source server password. If passed without value the script will prompt for a password.
                        Can also be set via SOURCE_NEXUS_PASSWORD env variable.""", nargs='?', const='ask', default=None)
    parser.add_argument("--destination-user", help="Destination server username. Can also be set via DESTINATION_NEXUS_USER env variable.")
    parser.add_argument(
        "--destination-password", help="""Destination server password. If passed without value the script will prompt for a password.
        Can also be set via DESTINATION_NEXUS_PASSWORD env variable.""", nargs='?', const='ask', default=None
    )

    parser.add_argument("--file", help="File to read actions from. Yaml format.")

    parser.add_argument("--list-assets", help="Repo to list assets from.")
    parser.add_argument("--list-components", help="Repo to list components from.")
    parser.add_argument("--local-path", help="Local path to download to / upload from. Default = './'", default='./')
    parser.add_argument("--download-assets", help="Repo to download from.")
    parser.add_argument("--upload-type", help="Repo type to upload.")
    parser.add_argument("--upload-components", help="Repo to upload components to.")

    args = parser.parse_args()

    if args.source_server:
        set_nexus_source_server(server=args.source_server)

    if args.destination_server:
        set_nexus_destination_server(server=args.destination_server)

    if args.source_user:
        source_user = args.source_user

    if args.source_password == 'ask':
        try:
            print('Enter Source Nexus Password:')
            source_password = getpass.getpass()
        except Exception as e:
            log_print('ERROR getting source password')
            raise SystemExit(e)
    elif args.source_password:
        source_password = args.source_password

    if args.destination_user:
        destination_user = args.destination_user

    if args.destination_password == 'ask':
        try:
            log_print('Enter destination Nexus Password:')
            destination_password = getpass.getpass()
        except Exception as e:
            log_print('ERROR getting destination password')
            raise SystemExit(e)
    elif args.destination_password:
        destination_password = args.destination_password

    if args.local_path:
        local_path = args.local_path
        if not local_path.endswith('/'):
            local_path = f"{local_path}/"

    log_print(f"Local path : {local_path}")
    log_print(f"Source Server : {source_server}")
    if source_password is not None:
        log_print(f"\tUsing Source Username : {source_user}, and provided password")
    log_print(f"Destination Server : {destination_server}")
    if destination_password is not None:
        log_print(f"\tUsing Destination Username : {destination_user}, and provided password")

    # Read from action file
    if args.file:
        file = args.file
        if not os.path.isfile(file):
            log_print(f"File '{file}' does not exist.")
            raise SystemExit(f"File '{file}' does not exist.")
        with open(file, 'r') as f:
            config_file = yaml.safe_load(f)
        if 'config' in config_file:
            config = config_file['config']
            if 'default_action' in config:
                default_action = config['default_action']
            else:
                default_action = 'both'
            if 'source_server' in config:
                set_nexus_source_server(config['source_server'])
            if 'destination_server' in config:
                set_nexus_destination_server(config['destination_server'])
            if 'source_user' in config:
                source_user = config['source_user']
            if 'source_password' in config:
                source_password = config['source_password']
            if 'destination_user' in config:
                destination_user = config['destination_user']
            if 'destination_password' in config:
                destination_password = config['destination_password']
            if 'local_path' in config:
                local_path = config['local_path']
            if 'docker_source_server' in config:
                docker_source_server = config['docker_source_server']
            if 'docker_destination_server' in config:
                docker_destination_server = config['docker_destination_server']
        for action in config_file['actions']:
            if 'active' in action and not action['active']:
                log_print("Action is not active: ❌❌")
                for key, value in action.items():
                    print(f"\t{key} : {value}")
            else:
                log_print("Action: ✅✅")
                action_type = action['type']
                act = action.get('action', default_action)
                path = action.get('path', f'data/{action["repo"]}')
                for key, value in action.items():
                    print(f"\t{key} : {value}")
                print("\t----------------------")
                print(f"\taction : {act}")
                print(f"\tpath : {path}")
                if act == 'list_assets':
                    list_repo_assets(action['repo'])
                if act == 'list_components':
                    list_repo_components(action['repo'])

                if action_type == 'docker':
                    if 'source' in action:
                        src_server = action['source']
                    else:
                        src_server = docker_source_server
                    if 'destination' in action:
                        dest_server = action['destination']
                    else:
                        dest_server = docker_destination_server

                    if act == 'download_assets':
                        download_repo_assets_docker(src_server, action['repo'])
                    if act == 'upload_components':
                        tag_docker_images(src_server, dest_server)
                        upload_components_docker(action['repo'], dest_server)
                    if act == 'both':
                        download_repo_assets_docker(src_server, action['repo'])
                        tag_docker_images(src_server, dest_server)
                        upload_components_docker(action['repo'], dest_server)
                else:
                    if act == 'download_assets':
                        download_repo_assets(action['repo'], path)
                    if act == 'upload_components':
                        upload_components(action['repo'], action_type, path)
                    if act == 'both':
                        download_repo_assets(action['repo'], path)
                        upload_components(action['repo'], action_type, path)

                # if 'cleanup' in config and config['cleanup']:
                #     log_print("\tCleaning up...")
                #     if act in ['download_assets', 'both']:
                #         log_print(f"\tCleaning up {path}")
                #         subprocess.run(['rm', '-rf', path])
                #     log_print("\tCleaning up done...")

    if args.list_assets:
        log_print(f"Listing Assets for repo : {args.list_assets}")
        list_repo_assets(args.list_assets)

    if args.list_components:
        log_print(f"Listing Components for repo : {args.list_components}")
        list_repo_components(args.list_components)

    if args.download_assets:
        log_print(f"Downloading Assets from repo : {args.download_assets}")
        download_repo_assets(args.download_assets, local_path)

    if args.upload_components and args.upload_type:
        r_type = args.upload_type
        log_print(f"Uploading {args.upload_type} Components to repo : {args.upload_components} with filter : {filter}")
        upload_components(args.upload_components, args.upload_type, local_path)
