"""Verify the publisher cannot silently select paid hardware or overwrite another Space."""

import unittest
from contextlib import redirect_stdout
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock, patch

import manage
from huggingface_hub import SpaceHardware
from huggingface_hub.errors import RepositoryNotFoundError


class PublisherTests(unittest.TestCase):
    def client(self):
        api = Mock()
        api.whoami.return_value = {"name": "sana-test-owner", "emailVerified": True}
        api.get_space_runtime.return_value = SimpleNamespace(
            stage="BUILDING",
            hardware=SpaceHardware.ZERO_A10G,
            requested_hardware=SpaceHardware.ZERO_A10G,
        )
        return api

    def run_with(self, api):
        with (
            patch.object(manage, "HfApi", return_value=api),
            patch.object(
                manage, "local_values", return_value={"HF_TOKEN": "hf_fake_for_test"}
            ),
            patch.object(manage, "save_local") as saved,
            redirect_stdout(StringIO()),
        ):
            manage.run("publish")
            return saved

    def test_new_space_uses_only_zero_gpu_and_explicit_source_files(self):
        api = self.client()
        api.repo_info.side_effect = RepositoryNotFoundError("test: absent")
        self.run_with(api)
        creation = api.create_repo.call_args.kwargs
        self.assertEqual(creation["space_hardware"], SpaceHardware.ZERO_A10G)
        self.assertEqual(creation["repo_id"], "sana-test-owner/sana-story-lab")
        self.assertEqual(
            [s["key"] for s in creation["space_secrets"]], ["SANA_SPACE_KEY"]
        )
        self.assertNotIn("hf_fake_for_test", str(creation))
        allowed = api.upload_folder.call_args.kwargs["allow_patterns"]
        self.assertEqual(
            set(allowed),
            {
                "app.py",
                "engine.py",
                "service.py",
                "protocol.py",
                "README.md",
                "requirements.txt",
            },
        )
        api.request_space_hardware.assert_not_called()

    def test_unrelated_existing_space_is_not_overwritten(self):
        api = self.client()
        api.get_space_variables.return_value = {}
        with self.assertRaises(SystemExit):
            self.run_with(api)
        api.upload_folder.assert_not_called()
        api.add_space_secret.assert_not_called()

    def test_existing_paid_hardware_is_not_changed_or_published(self):
        api = self.client()
        api.get_space_variables.return_value = {
            "SANA_PROJECT": SimpleNamespace(value="learn-sana")
        }
        api.get_space_runtime.return_value.hardware = SpaceHardware.T4_SMALL
        with self.assertRaises(SystemExit):
            self.run_with(api)
        api.upload_folder.assert_not_called()
        api.request_space_hardware.assert_not_called()


if __name__ == "__main__":
    unittest.main()
