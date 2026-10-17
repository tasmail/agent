"""Offline regression coverage of real backup upload and restore callables."""

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import boto3

from agent.bench import Bench
from agent.site import Site
from agent.snapshot_recovery import SnapshotRecovery

AUTH = {
    "ACCESS_KEY": "test-access",
    "SECRET_KEY": "test-secret",
    "REGION": "hel1",
    "PROVIDER": "AWS S3",
    "ENDPOINT_URL": "https://hel1.your-objectstorage.com",
}


class TestBackupEndpoints(unittest.TestCase):
    def test_actual_upload_methods_pass_endpoint_to_sdk(self):
        for method in (Site.upload_offsite_backup, SnapshotRecovery.upload_backup_files_to_s3):
            for endpoint in (AUTH["ENDPOINT_URL"], None, ""):
                for region in ("hel1", None):
                    with self.subTest(method=method.__name__, endpoint=endpoint, region=region):
                        self.check_upload(method, endpoint, region)

    def check_upload(self, method, endpoint, region):
        auth = {**AUTH, "ENDPOINT_URL": endpoint, "REGION": region}
        expected = {"aws_access_key_id": AUTH["ACCESS_KEY"], "aws_secret_access_key": AUTH["SECRET_KEY"]}
        if region:
            expected["region_name"] = region
        if endpoint:
            expected["endpoint_url"] = endpoint
        sdk_client = boto3.client
        clients = []

        def strict_client(service, **kwargs):
            self.assertEqual(service, "s3")
            self.assertEqual(kwargs, expected)
            client = sdk_client(service, **kwargs)
            if endpoint:
                self.assertEqual(client.meta.endpoint_url, endpoint)
            else:
                self.assertIn("amazonaws.com", client.meta.endpoint_url)
            clients.append(client)
            client.upload_fileobj = Mock()
            return client

        with tempfile.TemporaryDirectory() as directory:
            files = {}
            for name in ("database", "site_config", "public", "private"):
                path = Path(directory) / name
                path.write_bytes(name.encode())
                files[name] = {"file": name, "path": str(path)}
            kwargs = (
                {"keep_files_locally_after_offsite_backup": True}
                if method == Site.upload_offsite_backup
                else {}
            )
            with patch("boto3.client", side_effect=strict_client) as factory:
                result = method.__wrapped__(
                    None, files, {"bucket": "customer", "auth": auth, "path": "site/date"}, **kwargs
                )
            factory.assert_called_once()
            self.assertEqual(result, {name: "site/date/" + name for name in files})
            self.assertEqual(clients[0].upload_fileobj.call_count, 4)
            for upload, name in zip(clients[0].upload_fileobj.call_args_list, files):
                self.assertEqual(upload.args[1:], ("customer", "site/date/" + name))
                self.assertTrue(Path(files[name]["path"]).exists())

    def test_streaming_job_selects_custom_endpoint_before_starting_io(self):
        from agent.backup_storage import streaming_endpoint

        site = SimpleNamespace(
            backup_encryption_enabled=False,
            streamed_backup_prefix=Mock(return_value="test-stream"),
            name="site.test",
            bench=SimpleNamespace(directory="/unused"),
        )
        for endpoint in (AUTH["ENDPOINT_URL"], None):
            auth = {**AUTH, "ENDPOINT_URL": endpoint}
            expected = ("Other", endpoint) if endpoint else ("AWS", "s3.hel1.amazonaws.com")
            with patch("agent.site.shutil.which", return_value="rclone"), patch(
                "agent.site.streaming_endpoint", wraps=streaming_endpoint
            ) as select, patch("agent.site.os.sysconf", side_effect=RuntimeError("stop before IO")):
                with self.assertRaisesRegex(RuntimeError, "stop before IO"):
                    Site.backup_job.__wrapped__(
                        site, offsite={"bucket": "customer", "path": "date", "auth": auth}, stream=True
                    )
                select.assert_called_once()
                self.assertEqual(streaming_endpoint(*select.call_args.args), expected)

    def test_invalid_endpoints_fail_without_echoing_credentials(self):
        from agent.backup_storage import endpoint_options

        for endpoint in (
            "http://host",
            "https://user:secret@host",
            "https://host/path",
            "https://host?q=x",
            "https://host#x",
            "https://",
            "https://host:invalid",
            123,
        ):
            with self.subTest(endpoint=endpoint), self.assertRaisesRegex(
                ValueError, "Invalid backup endpoint"
            ) as error:
                endpoint_options({**AUTH, "ENDPOINT_URL": endpoint})
            self.assertNotIn(str(endpoint), str(error.exception))
        for key in ("ACCESS_KEY", "SECRET_KEY"):
            with self.assertRaisesRegex(ValueError, "explicit credentials"):
                endpoint_options({**AUTH, key: ""})

    def test_restore_download_preserves_custom_signed_urls(self):
        response = Mock()
        response.headers = {}
        response.iter_content.return_value = [b"backup"]
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        urls = [
            AUTH["ENDPOINT_URL"] + "/customer/" + name + "?signature=test"
            for name in ("db.sql.gz", "public.tar", "private.tar")
        ]
        with tempfile.TemporaryDirectory() as directory, patch(
            "agent.utils.requests.get", return_value=response
        ) as get:
            result = Bench.download_files.__wrapped__(
                SimpleNamespace(sites_directory=directory), "restore", *urls
            )
            self.assertEqual([c.args[0] for c in get.call_args_list], [urls[0], urls[2], urls[1]])
            for name in ("database", "public", "private"):
                self.assertEqual(Path(result[name]).read_bytes(), b"backup")
                self.assertTrue(os.path.commonpath([directory, result[name]]) == directory)
