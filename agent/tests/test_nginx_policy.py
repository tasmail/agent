"""Native nginx policy rendering; no listeners, daemons or external requests."""

import json
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from agent.server import Server


class TestNginxPolicy(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = {
            "name": "n1.example.test",
            "benches_directory": str(self.root / "benches"),
            "nginx_directory": str(self.root),
        }
        self.save()
        self.server = Server(str(self.root))
        self.output = self.root / "rendered.conf"
        self.context = {
            "name": "n1.example.test",
            "web_port": 18000,
            "socketio_port": 19000,
            "domain": "example.test",
            "nginx_directory": str(self.root),
            "tls_directory": str(self.root),
            "pages_directory": str(self.root),
            "error_pages_directory": str(self.root),
            "hosts": {"example.test": {}},
            "upstreams": {},
            "wildcards": [],
            "bench_name": "fixture",
            "bench_name_slug": "fixture",
            "standalone": False,
            "sites": [SimpleNamespace(name="site.example.test", host="*.example.test")],
            "domains": {},
            "sites_directory": str(self.root),
            "http_timeout": 120,
            "code_server": {"name": "code.example.test", "port": 8088},
        }

    def save(self):
        (self.root / "config.json").write_text(json.dumps(self.config))

    def render(self, template, **context):
        self.save()
        self.server._render_template(template, {**self.context, **context}, str(self.output))
        return self.output.read_text()

    def enable(self):
        self.config.update(
            nginx_server_include="/etc/nginx/edge-server.conf",
            nginx_backend_server_include="/etc/nginx/backend-server.conf",
            nginx_canonical_forwarding=True,
            nginx_external_real_ip=True,
        )

    def test_public_proxy_guards_and_single_real_ip_owner_survive_regeneration(self):
        self.enable()
        for _ in range(2):
            text = self.render("proxy/nginx.conf.jinja2")
            self.assertEqual(text.count("include /etc/nginx/edge-server.conf;"), 2)
            self.assertNotIn("real_ip_header CF-Connecting-IP;", text)
            self.assertRegex(text, r"server\s*\{\s*include /etc/nginx/edge-server.conf;\s*listen 80;")
        hosts = {"example.test": {}, "custom.test": {"redirect": "example.test"}}
        self.assertEqual(
            self.render("proxy/nginx.conf.jinja2", hosts=hosts).count("include /etc/nginx/edge-server.conf;"),
            3,
        )
        # Local metrics listeners are deliberately outside the edge policy.
        self.assertNotRegex(text, r"include /etc/nginx/edge-server.conf;\s*listen 127\.0\.0\.1:")

    def test_agent_and_backend_use_separate_includes(self):
        self.enable()
        self.assertIn("include /etc/nginx/edge-server.conf;", self.render("agent/nginx.conf.jinja2"))
        self.config.pop("nginx_server_include")
        self.assertNotIn("backend-server.conf", self.render("agent/nginx.conf.jinja2"))
        for _ in range(2):
            self.assertEqual(
                self.render("bench/nginx.conf.jinja2").count("include /etc/nginx/backend-server.conf;"), 2
            )

    def test_standalone_and_code_server_guards_survive_regeneration(self):
        self.enable()
        for _ in range(2):
            text = self.render("bench/nginx.conf.jinja2", standalone=True)
            self.assertEqual(text.count("include /etc/nginx/edge-server.conf;"), 3)
            self.assertNotIn("backend-server.conf", text)

    def test_canonical_forwarding_in_every_proxied_location(self):
        self.enable()
        for template in ["proxy/nginx.conf.jinja2", "agent/nginx.conf.jinja2", "bench/nginx.conf.jinja2"]:
            with self.subTest(template=template):
                text = self.render(
                    template, monitor=True, registry=True, analytics=True, log=True, trace=True
                )
                passes = len(re.findall(r"(?m)^\s*proxy_pass\s", text))
                self.assertGreater(passes, 0)
                self.assertNotIn("$proxy_add_x_forwarded_for", text)
                self.assertEqual(text.count("proxy_set_header X-Forwarded-For $remote_addr;"), passes)
                self.assertEqual(text.count("proxy_set_header X-Real-IP $remote_addr;"), passes)

    def test_default_rendering_has_no_policy_and_keeps_legacy_real_ip(self):
        proxy = self.render("proxy/nginx.conf.jinja2")
        self.assertNotIn("edge-server.conf", proxy)
        self.assertIn("real_ip_header CF-Connecting-IP;", proxy)
        self.assertIn("$proxy_add_x_forwarded_for", self.render("bench/nginx.conf.jinja2"))

    def test_native_vts_module_accounting_and_authenticated_metrics_survive_regeneration(self):
        directory = self.root / "nginx"
        directory.mkdir()
        self.config.update(
            nginx_directory=str(directory),
            nginx_vts_module_enabled=True,
            web_port=18000,
            tls_directory=str(self.root),
        )
        self.save()
        for _ in range(2):
            server = Server(str(self.root))
            server._generate_nginx_config()
            server._generate_agent_nginx_config()
            main = (directory / "nginx.conf").read_text()
            endpoint = (self.root / "nginx.conf").read_text()
            self.assertEqual(main.count("load_module modules/ngx_http_vhost_traffic_status_module.so;"), 1)
            self.assertEqual(len(re.findall(r"(?m)^\s*vhost_traffic_status_zone\b", main)), 1)
            self.assertIn("vhost_traffic_status_zone shared:vhost_traffic_status:256m;", main)
            self.assertIn("location /metrics/nginx {", endpoint)
            self.assertIn("vhost_traffic_status_display_format prometheus;", endpoint)
            self.assertIn('auth_basic "Prometheus";', endpoint)
            self.assertIn("auth_basic_user_file", endpoint)

    def test_native_vts_remains_disabled_by_default(self):
        main = self.render("nginx/nginx.conf.jinja2")
        endpoint = self.render("agent/nginx.conf.jinja2")
        self.assertNotIn("ngx_http_vhost_traffic_status_module.so", main)
        self.assertNotIn("vhost_traffic_status_zone", main)
        self.assertNotIn("location /metrics/nginx {", endpoint)

    def test_invalid_options_fail_before_overwriting_output(self):
        self.output.write_text("previous valid configuration")
        for key, values in {
            "nginx_server_include": [
                True,
                [],
                "relative.conf",
                "/etc/a.conf; return 200;",
                "/tmp/a\n.conf",
                "/etc/../a.conf",
                "/tmp/$host.conf",
                "/tmp/*.conf",
            ],
            "nginx_backend_server_include": ["relative.conf", {}],
            "nginx_canonical_forwarding": ["false", 0, None],
            "nginx_external_real_ip": ["true", 1, []],
        }.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    self.config[key] = value
                    with self.assertRaises(ValueError):
                        self.render("agent/nginx.conf.jinja2")
                    self.assertEqual(self.output.read_text(), "previous valid configuration")
                    self.config.pop(key)
