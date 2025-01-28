#!/usr/bin/env python3

"""
Backup ( & restore Nexus repos).

https://help.sonatype.com/en/uploading-components.html
"""

import argparse
import getpass
import json
import mimetypes
import os
import pprint
import re
import subprocess
from dataclasses import replace
from datetime import datetime

import requests
from requests.auth import HTTPBasicAuth

from config import NexusCopyConfig, NexusServer, Action

mimetypes.init()

SOURCE = NexusServer(
    host=os.environ.get('SOURCE_NEXUS_SERVER'),
    user=os.environ.get('SOURCE_NEXUS_USER'),
    password=os.environ.get('SOURCE_NEXUS_PASSWORD'),
)
DESTINATION = NexusServer(
    host=os.environ.get('DESTINATION_NEXUS_SERVER'),
    user=os.environ.get('DESTINATION_NEXUS_USER'),
    password=os.environ.get('DESTINATION_NEXUS_PASSWORD'),
)
API_PATH = 'service/rest/v1'
ASSET_TYPE_FILTERS = {
    'apt': r'.(deb|udeb)$',
    'npm': r'.tgz$',
    'maven2': r'.(jar|zip|xml|pom|war|ear)$',
    'yum': r'.(rpm|drpm)$',
    'pypi': r'.tar.gz$',
    'rubygems': r'.gem$',
    'nuget': r'.nupkg$',
}


def log_print(*msgs):
    now = datetime.now()
    print(f"{now} : ", ' '.join(msgs))


class NexusCopy:
    ncconfig: NexusCopyConfig

    def __init__(self, ncconfig: NexusCopyConfig):
        self.ncconfig = ncconfig

    def run(self):
        for action in self.ncconfig.actions:
            action.source = replace(self.ncconfig.source).merge(action.source)
            action.destination = replace(self.ncconfig.destination).merge(action.destination)

            log_print(f"Processing action : {action.repo} -> {action.target_repo}")
            # pprint.pprint(action)

            if not action.active:
                log_print("Action is not active: ❌❌")
                continue

            log_print("Action: ✅✅")
            print("\t----------------------")

            act = action.action or self.ncconfig.default_action
            print(f"\taction : {act}")
            match act:
                case 'list_assets':
                    self.list_repo_assets(action.repo, action.source)
                    return
                case 'list_components':
                    self.list_repo_components(action.repo, action.source)
                    return
                case _:
                    pass

            path = config.local_path
            if path == '.':
                path += '/data'
            path += '/'
            path += action.path or action.repo
            print(f"\tpath : {path}")

            if action.repo_type == 'docker':
                match act:
                    case 'download_assets':
                        self.download_repo_assets_docker(action.source, action.repo)
                        return
                    case 'upload_components':
                        self.tag_docker_images(action.source, action.destination)
                        self.upload_components_docker(action.destination)
                        return
                    case 'both':
                        self.download_repo_assets_docker(action.source, action.repo)
                        self.tag_docker_images(action.source, action.destination)
                        self.upload_components_docker(action.destination)
                        return

            else:
                match act:
                    case 'download_assets':
                        self.download_repo_assets(action.repo, action.source, path)
                        return
                    case 'upload_components':
                        self.upload_components(action.target_repo, action.destination, action.repo_type, path)
                        return
                    case 'both':
                        self.download_repo_assets(action.repo, action.source, path)
                        self.upload_components(action.target_repo, action.destination, action.repo_type, path)
                        return

    @staticmethod
    def get_file_mime_type(some_file):
        return mimetypes.guess_file_type(some_file)[0]

    @staticmethod
    def api_call(url, server: NexusServer, method='GET', files=[], data={}):
        """Generic Nexus Rest API call."""
        start = datetime.now()
        auth = {}
        return_value = {}
        url = f"{server.host}/{url}"

        log_print(f"api_call : method={method} url={url}")

        try:
            if server.password:
                auth = HTTPBasicAuth(server.user, server.password)

            match method:
                case 'GET':
                    response = requests.get(url, auth=auth)
                case 'POST':
                    response = requests.post(url, files=files, data=data, auth=auth)
                case _:
                    log_print(f"Unsupported method '{method}'")
                    raise requests.exceptions.HTTPError(f"Unsupported method '{method}'")

            response.raise_for_status()
            if response.text and response.text != '':
                return_value = json.loads(response.text)

            end = datetime.now()
            call_time = end - start
            # log_print(f"url={url}, files={files}, data={data}, auth={auth}")
            log_print(f"api_call done. time taken: {call_time}")
            return return_value
        except requests.exceptions.ConnectionError as e:
            log_print(f"Nexus api {method} call failed. Error Connecting:", e)
            raise SystemExit(e)
        except requests.exceptions.Timeout as e:
            log_print(f"Nexus api {method} call failed. Timeout Error:", e)
            raise SystemExit(e)
        except requests.exceptions.HTTPError as e:
            log_print(f"Nexus api {method} call failed. HTTPError : {e}")
            log_print(f"url={url}, files={files}, data={data}, auth={auth}")
            raise SystemExit(e)
        except requests.exceptions.RequestException as e:
            log_print(f"Nexus api {method} call failed. RequestException : {e}")
            raise SystemExit(e)
        except Exception as e:
            log_print(f"Nexus api {method} call failed. Exception : {e}")
            raise SystemExit(e)

    def api_get(self, request, server: NexusServer, files=[], data={}):
        url = f"{API_PATH}/{request}"
        return self.api_call(url, server, 'GET', files, data)

    def api_post(self, request, server: NexusServer, files=[], data={}):
        url = f"{API_PATH}/{request}"
        return self.api_call(url, server, 'POST', files, data)

    @staticmethod
    def get_continuationtoken(data):
        """Check for a continuationtoken and pass the url request string to fetch the next page."""
        if ('continuationToken' in data) and (data['continuationToken'] is not None):
            return f"&continuationToken={data['continuationToken']}"
        else:
            return False

    def yield_items(self, repo, item_type, server: NexusServer):
        """Download page per page of items of item_type 'assets' or 'components' from a repo and yield each item, reducing memory footprint."""
        data = self.api_get(f"{item_type}?repository={repo}", server)
        for item in data['items']:
            yield item
        while (token_req := self.get_continuationtoken(data)) and (token_req is not False):
            more_data = self.api_get(f"{item_type}?repository={repo}{token_req}", server)
            for item in more_data['items']:
                yield item
            data = more_data

    def get_asset(self, asset_id, server: NexusServer):
        return self.api_get(f"assets/{asset_id}", server)

    def get_repo_components(self, repo, server: NexusServer, count=0):
        components = {}
        components_fetched = 0
        for component in self.yield_items(repo, 'components', server):
            components_fetched += 1
            # print(f"component: {component}")
            name = f"{component['name']}: {component['version']}"
            if 'format' in component:
                if component['format'] == 'docker':
                    components[name] = {
                        'format': component['format'],
                        'group': component['group'],
                        'name': component['name'],
                        'version': component['version'],
                        'repository': component['repository'],
                    }
                    log_print(f"Added component: {name} - {components_fetched}")
            if components_fetched >= count > 0:
                break
        return components

    def get_repo_assets(self, repo, server: NexusServer, item_type='components'):
        other = []
        assets = {}
        count = 0
        for item in self.yield_items(repo, item_type, server):
            # log_print(f"item: {item}")
            match item_type:
                case 'components':
                    item_assets = item['assets']
                case 'assets':
                    item_assets = [item]
                case _:
                    raise ValueError(f"Invalid item_type: {item_type}")
            for asset in item_assets:
                # log_print(f"asset: {asset}")
                filter = ASSET_TYPE_FILTERS.get(asset['format'])
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
                    log_print(f"Added asset: {asset['path']} - {count}")
                # else:
                #     log_print(f"Ignoring filtered asset: {asset['path']}")
        return assets, other

    def list_repo_assets(self, repo, server: NexusServer):
        log_print(f"Listing Assets for repo : {repo}")
        count = 0
        for asset in self.yield_items(repo, 'assets', server):
            log_print("asset:")
            pprint.pprint(asset)
            count += len(asset)
        log_print(f"asset count: {count}")

    def list_repo_components(self, repo, server: NexusServer):
        log_print(f"Listing Components for repo : {repo}")
        count = 0
        for component in self.yield_items(repo, 'components', server):
            log_print("component:")
            pprint.pprint(component)
            count += len(component['assets'])
        log_print(f"component count: {count}")

    def download_repo_assets(self, repo, server: NexusServer, path='.', force_download=False):
        log_print(f"Downloading Assets from repo : {args.download_assets}")
        assets, _ = self.get_repo_assets(repo, server)
        count = 0
        items = len(assets)
        for _, asset in assets.items():
            count += 1
            local_file = f"{path}/{asset['path']}"
            if not os.path.exists(local_file) or force_download:
                if not os.path.exists(os.path.dirname(local_file)):
                    log_print(f"Creating directory : {path}/{os.path.dirname(asset['path'])}")
                    os.makedirs(os.path.dirname(local_file), exist_ok=True)
                log_print(f"Downloading asset '{asset['downloadUrl']}' to '{local_file}' - {count}/{items}")
                response = requests.get(asset['downloadUrl'], allow_redirects=True)
                with open(local_file, 'wb') as f:
                    f.write(response.content)
            else:
                log_print(f"Skipping download of '{local_file}' as it already exists. - {count}/{items}")

    def upload_component(self, repo, server: NexusServer, local_file, repo_file, asset_type, mime_type):
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
            data = self.get_maven_info(repo_file)
            files = [(f"{asset_type}.asset1", (repo_file, open(local_file, 'rb'), mime_type))]
        elif asset_type == 'yum':
            data = {"yum.directory": f"{repo_path}", "yum.asset.filename": f"{repo_filename}"}
            files = [(f"{asset_type}.asset", (repo_file, open(local_file, 'rb'), mime_type))]
        else:  # apt, npm, pypi, raw, docker, gem, nuget
            files = [(f"{asset_type}.asset", (repo_file, open(local_file, 'rb'), mime_type))]
        self.api_post(f"components?repository={repo}", server, files, data)

    def upload_components(self, repo, server: NexusServer, asset_type, path='.', overwrite=False):
        """Upload all component files found in <path> to <repo>"""
        filter = ASSET_TYPE_FILTERS.get(asset_type)
        log_print(f"Uploading {asset_type} Components to repo : {repo} with filter : {filter}")
        assets = []
        if not overwrite:
            assets, _ = self.get_repo_assets(repo, server)
        count = 0
        file_count = 0
        for root, _, files in os.walk(path):
            file_count += len(files)
        for root, _, files in os.walk(path):
            for name in files:
                count += 1
                # log_print(f"root: {root} - name: {name}")
                local_file = os.path.join(root, name)
                if filter is None or re.search(rf"{filter}", name):
                    repo_file = local_file.removeprefix(path)
                    if not repo_file.startswith('/'):
                        repo_file = f"/{repo_file}"
                    if not overwrite:
                        # log_print(f"repo_file: {repo_file} - assets: {assets.keys()}")
                        if repo_file in assets.keys():
                            log_print(f"NOT uploading: local_file: {local_file}, it already exists in repo. - {count}/{file_count}")
                            continue
                    mime_type = self.get_file_mime_type(local_file)
                    log_print(f"Uploading: local_file: {local_file} - repo_file: {repo_file} - mime_type: {mime_type} - {count}/{file_count}")
                    self.upload_component(repo, server, local_file, repo_file, asset_type, mime_type)
                else:
                    log_print(f"Ignoring filtered local_file: {local_file} - {count}/{file_count}")

    @staticmethod
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
        extension = re.search(rf"{ASSET_TYPE_FILTERS['maven2']}", file_name).group(0).lstrip('.')
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
    @staticmethod
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

    @staticmethod
    def list_local_docker_images(image_filter=None):
        containers = {}
        containers_json = subprocess.run(['docker', 'images', '--format', 'json'], capture_output=True)
        for container in containers_json.stdout.decode().splitlines():
            container_o = json.loads(container)
            if image_filter is None or re.search(rf"{image_filter}", container_o['Repository']):
                containers[f"{container_o['Repository']}: {container_o['Tag']}"] = container_o
        return containers

    @staticmethod
    def docker_login(server: NexusServer):
        subprocess.run(['docker', 'login', server.docker_host, '-u', server.user, '-p', server.password])

    def download_repo_assets_docker(self, server: NexusServer, repo):
        self.set_docker_image_download_path()
        components = self.get_repo_components(repo, server, 0)
        source_count = len(components)
        count = 0
        for _, component in components.items():
            count += 1
            image_url = f"{server.docker_host}/{component['name']}: {component['version']}"
            log_print(f"docker pull {image_url} - {count}/{source_count}")
            subprocess.run(['docker', 'pull', image_url])
        log_print(f"asset_count: {count}")
        return count

    def upload_components_docker(self, server: NexusServer):
        self.set_docker_image_download_path()
        self.docker_login(server)
        images = self.list_local_docker_images(rf'^{server.docker_host}')
        source_count = len(images)
        image_count = 0
        for image, _ in images.items():
            image_count += 1
            if image.startswith(server.docker_host):
                log_print(f"docker push {image} - {image_count}/{source_count}")
                subprocess.run(['docker', 'push', image])

    def tag_docker_images(self, source: NexusServer, destination: NexusServer):
        self.set_docker_image_download_path()
        images = self.list_local_docker_images()
        source_count = len(images)
        image_count = 0
        for image, _ in images.items():
            image_count += 1
            image_path = image.replace(source.docker_host, '')
            # log_print(f"Tagging Docker images from {image} to {destination}{image_path}")
            if image.startswith(source.docker_host):
                if f"{destination.docker_host}{image_path}" not in images:
                    log_print(f"docker tag {image} {destination.docker_host}{image_path} - {image_count}/{source_count}")
                    subprocess.run(['docker', 'tag', image, f"{destination.docker_host}{image_path}"])
                else:
                    log_print(f"Skipping docker tag {image} {destination.docker_host}{image_path} as it already exists. - {image_count}/{source_count}")

# Cleanup ALL Docker images
# docker rmi -f $(docker images -aq)


if __name__ == "__main__":
    msg = "Nexus API functions"
    parser = argparse.ArgumentParser(description=msg)
    parser.add_argument(
        "--file",
        help="Action file to configure actions to perform. Yaml format."
    )
    parser.add_argument(
        "--source-server",
        help="""
            Source Server to use.
            Can also be set via SOURCE_NEXUS_SERVER env variable or in the action file.
        """
    )
    parser.add_argument(
        "--destination-server",
        help="""
            Destination Server to use. Can also be set via DESTINATION_NEXUS_SERVER env variable or in the action file.
            """
    )
    parser.add_argument(
        "--source-user",
        help="Source server username. Can also be set via SOURCE_NEXUS_USER env variable or in the action file."
    )
    parser.add_argument(
        "--source-password",
        help="""
            Source server password. If passed without value the script will prompt for a password.
            Can also be set via SOURCE_NEXUS_PASSWORD env variable or in the action file.
        """,
        nargs='?', const='ask', default=None
    )
    parser.add_argument(
        "--destination-user",
        help="Destination server username. Can also be set via DESTINATION_NEXUS_USER env variable or in the action file."
    )
    parser.add_argument(
        "--destination-password",
        help="""
            Destination server password. If passed without value the script will prompt for a password.
            Can also be set via DESTINATION_NEXUS_PASSWORD env variable or in the action file.
        """,
        nargs='?', const='ask', default=None
    )
    parser.add_argument("--list-assets", help="Repo to list assets from.")
    parser.add_argument("--list-components", help="Repo to list components from.")
    parser.add_argument("--local-path", help="Local path to download to / upload from. Default = '.'", default='.')
    parser.add_argument("--download-assets", help="Repo to download from.")
    parser.add_argument("--upload-type", help="Repo type to upload.")
    parser.add_argument("--upload-components", help="Repo to upload components to.")

    args = parser.parse_args()

    # Read from action file
    if args.file:
        file = args.file
        if not os.path.isfile(file):
            log_print(f"File '{file}' does not exist.")
            raise SystemExit(f"File '{file}' does not exist.")
        config = NexusCopyConfig.from_yaml(file)
    else:
        config = NexusCopyConfig(actions=[])

    # Apply environment variables
    config.source.merge(SOURCE)
    config.destination.merge(DESTINATION)

    # Apply commandline configuration flags

    if args.source_server:
        config.source.host = args.source_server
        config.source.fix_paths()
    if args.source_user:
        config.source.user = args.source_user
    if args.source_password == 'ask':
        try:
            print('Enter Source Nexus Password:')
            config.source.password = getpass.getpass()
        except Exception as e:
            log_print('ERROR getting source password')
            raise SystemExit(e)
    elif args.source_password:
        config.source.password = args.source_password

    if args.destination_server:
        config.destination.host = args.destination_server
        config.destination.fix_paths()
    if args.destination_user:
        config.destination.user = args.destination_user
    if args.destination_password == 'ask':
        try:
            print('Enter Destination Nexus Password:')
            config.destination.password = getpass.getpass()
        except Exception as e:
            log_print('ERROR getting destination password')
            raise SystemExit(e)
    elif args.destination_password:
        config.destination.password = args.destination_password

    if args.local_path:
        config.local_path = args.local_path
        config.fix_paths()

    log_print(f"Local path : {config.local_path}")
    log_print(f"Source Server : {config.source.host}")
    if config.source.password is not None:
        log_print(f"\tUsing Source Username : {config.source.user}, and provided password")
    log_print(f"Destination Server : {config.destination.host}")
    if config.destination.password is not None:
        log_print(f"\tUsing Destination Username : {config.destination.user}, and provided password")

    if args.list_assets:
        config.actions.append(Action(repo=args.list_assets, action='list_assets'))

    if args.list_components:
        config.actions.append(Action(repo=args.list_components, action='list_components'))

    if args.download_assets:
        config.actions.append(Action(repo=args.download_assets, action='download_assets'))

    if args.upload_components and args.upload_type:
        config.actions.append(Action(repo=args.upload_components, repo_type=args.upload_type, action='upload_components'))

    NexusCopy(config).run()
