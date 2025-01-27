from config import NexusCopyConfig, NexusServer, Action
import pytest
import yaml


class TestConfig:

    def test_from_yaml_nonexistent_file(self):
        """Test from_yaml method with a file that does not exist"""
        with pytest.raises(FileNotFoundError):
            NexusCopyConfig.from_yaml("nonexistent_file.yaml")

    def test_from_yaml_empty_file(self, tmp_path):
        """Test from_yaml method with an empty file"""
        empty_yaml = tmp_path / "empty_file.yaml"
        empty_yaml.write_text("")
        with pytest.raises(AttributeError):
            NexusCopyConfig.from_yaml(str(empty_yaml))

    def test_from_yaml_extra_fields(self, tmp_path):
        """Test from_yaml method with extra unexpected fields"""
        extra_fields_yaml = tmp_path / "extra_fields.yaml"
        extra_fields_yaml.write_text("""
        source:
          host: test.com
          extra_field: value
        actions:
          - repo: test_repo
            repo_type: test
            unexpected: field
        """)
        with pytest.raises(TypeError):
            NexusCopyConfig.from_yaml(str(extra_fields_yaml))

    def test_from_yaml_file_not_found(self):
        """Test from_yaml method with non-existent file"""
        with pytest.raises(FileNotFoundError):
            NexusCopyConfig.from_yaml("non_existent_file.yaml")

    def test_from_yaml_invalid_repo_type(self, tmp_path):
        """Test from_yaml method with invalid repo type"""
        invalid_action_yaml = tmp_path / "invalid_action.yaml"
        invalid_action_yaml.write_text("""
        actions:
          - repo: test_repo
            repo_type: invalid_type
        """)
        config = NexusCopyConfig.from_yaml(str(invalid_action_yaml))
        assert len(config.actions) == 1
        assert config.actions[0].repo_type == "invalid_type"

    def test_from_yaml_invalid_yaml(self, tmp_path):
        """Test from_yaml method with invalid YAML content"""
        invalid_yaml = tmp_path / "invalid.yaml"
        invalid_yaml.write_text("invalid: yaml: content:")
        with pytest.raises(yaml.YAMLError):
            NexusCopyConfig.from_yaml(str(invalid_yaml))

    def test_from_yaml_valid_configuration(self, tmp_path):
        """
        Test that from_yaml method correctly parses a valid YAML configuration file
        and returns a NexusCopyConfig object with expected attributes.
        """
        # Create a temporary YAML file with test data
        yaml_content = {
            'source': {
                'host': 'source.example.com',
                'user': 'source_user',
                'password': 'source_pass',
                'docker_host': 'source_docker.example.com'
            },
            'destination': {
                'host': 'dest.example.com',
                'user': 'dest_user',
                'password': 'dest_pass',
                'docker_host': 'dest_docker.example.com'
            },
            'default_action': 'copy',
            'local_path': '/tmp/local',
            'actions': [
                {
                    'repo': 'repo1',
                    'repo_type': 'maven',
                    'description': 'Test repo 1',
                    'action': 'copy'
                },
                {
                    'repo': 'repo2',
                    'repo_type': 'npm',
                    'description': 'Test repo 2',
                    'action': 'mirror'
                }
            ]
        }
        yaml_file = tmp_path / "test_config.yaml"
        with open(yaml_file, 'w') as f:
            yaml.dump(yaml_content, f)

        # Call the from_yaml method
        config = NexusCopyConfig.from_yaml(str(yaml_file))

        # Assert that the returned object is an instance of NexusCopyConfig
        assert isinstance(config, NexusCopyConfig)

        # Assert that the source and destination are correctly parsed
        assert isinstance(config.source, NexusServer)
        assert config.source.host == 'source.example.com'
        assert config.source.user == 'source_user'
        assert config.source.password == 'source_pass'
        assert config.source.docker_host == 'source_docker.example.com'

        assert isinstance(config.destination, NexusServer)
        assert config.destination.host == 'dest.example.com'
        assert config.destination.user == 'dest_user'
        assert config.destination.password == 'dest_pass'
        assert config.destination.docker_host == 'dest_docker.example.com'

        # Assert that default_action and local_path are correctly parsed
        assert config.default_action == 'copy'
        assert config.local_path == '/tmp/local'

        # Assert that actions are correctly parsed
        assert len(config.actions) == 2
        assert all(isinstance(action, Action) for action in config.actions)
        assert config.actions[0].repo == 'repo1'
        assert config.actions[0].repo_type == 'maven'
        assert config.actions[0].description == 'Test repo 1'
        assert config.actions[0].action == 'copy'
        assert config.actions[1].repo == 'repo2'
        assert config.actions[1].repo_type == 'npm'
        assert config.actions[1].description == 'Test repo 2'
        assert config.actions[1].action == 'mirror'

    def test_set_host(self, tmp_path):
        """Test host setter method - will not automatically add trailing '/'"""
        yaml_content = {
            'local_path': '/tmp/local/',
            'actions': [
                {
                    'repo': 'repo1',
                    'repo_type': 'maven',
                },
            ],
        }
        yaml_file = tmp_path / "test_config.yaml"
        with open(yaml_file, 'w') as f:
            yaml.dump(yaml_content, f)

        config = NexusCopyConfig.from_yaml(str(yaml_file))
        assert config.local_path == "/tmp/local"

        config.local_path = "test"
        assert config.local_path == "test"
        config.fix_paths()
        assert config.local_path == "test"

        config.local_path = "test/"
        assert config.local_path == "test/"
        config.fix_paths()
        assert config.local_path == "test"
