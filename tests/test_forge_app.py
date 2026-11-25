"""Tests for tools/forge-app: the token minter, the client, the gh wrapper,
the git credential helper and setup_agent.py. No network, no real key."""
import base64
import datetime as dt
import http.server
import json
import os
import pathlib
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import unittest

TOOLS = pathlib.Path(__file__).resolve().parent.parent / "tools/forge-app"
sys.path.insert(0, str(TOOLS))
import forge_client  # noqa: E402
import forge_mint  # noqa: E402


def iso(seconds_from_now):
    t = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=seconds_from_now)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def write_script(path, body):
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)


class Env(unittest.TestCase):
    """Each test gets a temp dir and a clean FORGE_* environment."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="forge-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        saved = {k: v for k, v in os.environ.items() if k.startswith("FORGE_") or k == "GH_TOKEN"}
        for k in saved:
            del os.environ[k]
        self.addCleanup(lambda: [os.environ.pop(k, None) for k in list(os.environ)
                                 if k.startswith("FORGE_") or k == "GH_TOKEN"] and None)
        self.addCleanup(os.environ.update, saved)

    def spool(self, **left):
        d = self.tmp / "spool"
        d.mkdir(exist_ok=True)
        for acct, secs in left.items():
            (d / f"{acct}.json").write_text(json.dumps(
                {"account": acct, "token": f"tok-{acct}", "expires_at": iso(secs)}))
        os.environ["FORGE_SPOOL"] = str(d)
        return d


class JWT(unittest.TestCase):
    def test_signed_with_the_key_and_short_lived(self):
        tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        key, pub = tmp / "k.pem", tmp / "k.pub"
        subprocess.run(["openssl", "genrsa", "-out", key, "2048"], check=True, capture_output=True)
        subprocess.run(["openssl", "rsa", "-in", key, "-pubout", "-out", pub], check=True, capture_output=True)
        jwt = forge_mint.app_jwt(5839392, str(key), now=1_000_000)
        header, claims, sig = jwt.split(".")
        pad = lambda s: s + "=" * (-len(s) % 4)  # noqa: E731
        self.assertEqual(json.loads(base64.urlsafe_b64decode(pad(header))), {"alg": "RS256", "typ": "JWT"})
        self.assertEqual(json.loads(base64.urlsafe_b64decode(pad(claims))),
                         {"iat": 999_940, "exp": 1_000_540, "iss": "5839392"})
        (tmp / "sig").write_bytes(base64.urlsafe_b64decode(pad(sig)))
        ok = subprocess.run(["openssl", "dgst", "-sha256", "-verify", pub, "-signature", tmp / "sig"],
                            input=f"{header}.{claims}".encode(), capture_output=True)
        self.assertEqual(ok.returncode, 0, ok.stderr)


class StubGitHub(http.server.BaseHTTPRequestHandler):
    minted = []

    def log_message(self, *a):
        pass

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._send(200, [{"id": 1, "account": {"login": "Applesauce-Labs"}},
                         {"id": 2, "account": {"login": "shermanhuman"}},
                         {"id": 3, "account": {"login": "someone-else"}}])

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        inst = self.path.split("/")[3]
        StubGitHub.minted.append((inst, body, self.headers["Authorization"]))
        self._send(201, {"token": f"ghs_{inst}", "expires_at": "2099-01-01T00:00:00Z"})


class Mint(Env):
    def test_mints_restricted_tokens_for_named_accounts_only(self):
        server = http.server.HTTPServer(("127.0.0.1", 0), StubGitHub)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        StubGitHub.minted = []
        key = self.tmp / "k.pem"
        subprocess.run(["openssl", "genrsa", "-out", key, "2048"], check=True, capture_output=True)
        spool = self.tmp / "out"
        spool.mkdir()
        os.environ.update(FORGE_APP_ID="1", FORGE_APP_KEY=str(key), FORGE_SPOOL=str(spool),
                          FORGE_ACCOUNTS="Applesauce-Labs shermanhuman", FORGE_READER="",
                          FORGE_API=f"http://127.0.0.1:{server.server_port}")
        self.assertEqual(forge_mint.main(), 0)
        self.assertEqual(sorted(m[0] for m in StubGitHub.minted), ["1", "2"])  # not someone-else
        for _, body, auth in StubGitHub.minted:
            self.assertEqual(body["permissions"]["checks"], "read")
            self.assertEqual(body["permissions"]["statuses"], "read")
            self.assertNotIn("organization_projects", body["permissions"])
            self.assertTrue(auth.startswith("Bearer "))
        for acct in ("Applesauce-Labs", "shermanhuman"):
            f = spool / f"{acct}.json"
            self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o640)
            self.assertEqual(json.loads(f.read_text())["account"], acct)
        self.assertEqual([p.name for p in spool.iterdir() if p.name.startswith(".")], [])

    def test_missing_installation_fails_but_writes_the_rest(self):
        server = http.server.HTTPServer(("127.0.0.1", 0), StubGitHub)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        key = self.tmp / "k.pem"
        subprocess.run(["openssl", "genrsa", "-out", key, "2048"], check=True, capture_output=True)
        spool = self.tmp / "out"
        spool.mkdir()
        os.environ.update(FORGE_APP_ID="1", FORGE_APP_KEY=str(key), FORGE_SPOOL=str(spool),
                          FORGE_ACCOUNTS="Applesauce-Labs nobody", FORGE_READER="",
                          FORGE_API=f"http://127.0.0.1:{server.server_port}")
        self.assertEqual(forge_mint.main(), 1)
        self.assertTrue((spool / "Applesauce-Labs.json").exists())

    @unittest.skipUnless(shutil.which("setfacl") and shutil.which("getfacl"), "needs acl tools")
    def test_reader_acl_survives_the_rename(self):
        spool = self.tmp / "acl"
        spool.mkdir()
        me = os.environ.get("USER") or subprocess.run(["id", "-un"], capture_output=True, text=True).stdout.strip()
        forge_mint.write_atomic(str(spool), "A", {"token": "t", "expires_at": iso(3600)}, me)
        acl = subprocess.run(["getfacl", "-c", spool / "A.json"], capture_output=True, text=True).stdout
        self.assertIn(f"user:{me}:r--", acl)
        self.assertNotIn("mask::---", acl)


class Owner(Env):
    def owner(self, *args):
        return forge_client.owner_from_args(list(args))

    def test_argument_forms(self):
        cases = [
            (["pr", "view", "1", "-R", "shermanhuman/oh"], "shermanhuman"),
            (["pr", "view", "1", "--repo", "github.com/shermanhuman/oh"], "shermanhuman"),
            (["pr", "view", "1", "--repo=Applesauce-Labs/sugarhouse"], "Applesauce-Labs"),
            (["pr", "view", "1", "-Rshermanhuman/oh"], "shermanhuman"),
            (["pr", "view", "https://github.com/shermanhuman/oh/pull/3"], "shermanhuman"),
            (["api", "repos/shermanhuman/oh/pulls"], "shermanhuman"),
            (["api", "/repos/Applesauce-Labs/forge"], "Applesauce-Labs"),
            (["api", "orgs/Applesauce-Labs/repos"], "Applesauce-Labs"),
            (["api", "users/shermanhuman/repos"], "shermanhuman"),
            (["repo", "list", "--owner", "shermanhuman"], "shermanhuman"),
            (["search", "issues", "is:open user:shermanhuman"], "shermanhuman"),
            (["search", "prs", "org:Applesauce-Labs is:open"], "Applesauce-Labs"),
            (["api", "search/issues?q=repo:shermanhuman/oh"], "shermanhuman"),
            (["api", "user"], None),
        ]
        for args, want in cases:
            self.assertEqual(self.owner(*args), want, args)

    def test_cwd_remote_and_override(self):
        repo = self.tmp / "r"
        subprocess.run(["git", "init", "-q", repo], check=True)
        subprocess.run(["git", "-C", repo, "remote", "add", "origin", "git@github.com:shermanhuman/oh.git"], check=True)
        self.assertEqual(forge_client.owner_for(["pr", "list"], cwd=repo), "shermanhuman")
        os.environ["FORGE_OWNER"] = "Applesauce-Labs"
        self.assertEqual(forge_client.owner_for(["pr", "list"], cwd=repo), "Applesauce-Labs")

    def test_unknown_owner_gets_the_default(self):
        self.assertEqual(forge_client.canonical("SHERMANHUMAN"), "shermanhuman")
        self.assertEqual(forge_client.canonical("cli"), "Applesauce-Labs")
        self.assertEqual(forge_client.canonical(None), "Applesauce-Labs")


class Token(Env):
    def test_local_spool(self):
        self.spool(**{"Applesauce-Labs": 3000, "shermanhuman": 3000})
        self.assertEqual(forge_client.token("shermanhuman"), "tok-shermanhuman")
        self.assertEqual(forge_client.token(None), "tok-Applesauce-Labs")

    def test_stalled_timer_fails_loudly(self):
        self.spool(**{"Applesauce-Labs": 120})
        with self.assertRaisesRegex(forge_client.ForgeError, "stopped minting"):
            forge_client.token(None)

    def fake_ssh(self, secs):
        bindir = self.tmp / "bin"
        bindir.mkdir(exist_ok=True)
        log = self.tmp / "ssh.log"
        payload = json.dumps({"account": "shermanhuman", "token": "fetched", "expires_at": iso(secs)})
        write_script(bindir / "ssh", f"echo \"$@\" >> {log}\necho '{payload}'\n")
        os.environ["PATH"] = f"{bindir}{os.pathsep}{os.environ['PATH']}"
        os.environ["FORGE_SPOOL"] = str(self.tmp / "absent")
        os.environ["FORGE_CACHE"] = str(self.tmp / "cache")
        return log

    def test_remote_fetch_then_cache(self):
        old_path = os.environ["PATH"]
        self.addCleanup(os.environ.__setitem__, "PATH", old_path)
        log = self.fake_ssh(3000)
        self.assertEqual(forge_client.token("shermanhuman"), "fetched")
        self.assertEqual(forge_client.token("shermanhuman"), "fetched")
        self.assertEqual(len(log.read_text().splitlines()), 1)  # second call from cache
        self.assertIn("soulglow cat", log.read_text())
        cached = self.tmp / "cache/shermanhuman.json"
        self.assertEqual(stat.S_IMODE(cached.stat().st_mode), 0o600)

    def test_refetch_when_under_ten_minutes_left(self):
        old_path = os.environ["PATH"]
        self.addCleanup(os.environ.__setitem__, "PATH", old_path)
        log = self.fake_ssh(3000)
        cache = self.tmp / "cache"
        cache.mkdir()
        (cache / "shermanhuman.json").write_text(json.dumps({"token": "old", "expires_at": iso(500)}))
        self.assertEqual(forge_client.token("shermanhuman"), "fetched")
        self.assertEqual(len(log.read_text().splitlines()), 1)


class Wrappers(Env):
    def setUp(self):
        super().setUp()
        self.spool(**{"Applesauce-Labs": 3000, "shermanhuman": 3000})
        fake = self.tmp / "realgh"
        write_script(fake, 'echo "token=$GH_TOKEN args=$*"\n')
        os.environ["FORGE_REAL_GH"] = str(fake)

    def gh(self, *args, env=None, cwd=None):
        return subprocess.run([sys.executable, TOOLS / "bin/gh", *args], capture_output=True, text=True,
                              env={**os.environ, **(env or {})}, cwd=cwd or self.tmp).stdout.strip()

    def test_gh_picks_the_owner_token(self):
        self.assertEqual(self.gh("pr", "list", "-R", "shermanhuman/oh"),
                         "token=tok-shermanhuman args=pr list -R shermanhuman/oh")
        self.assertEqual(self.gh("api", "user"), "token=tok-Applesauce-Labs args=api user")

    def test_gh_passes_an_existing_token_through(self):
        self.assertEqual(self.gh("api", "user", env={"GH_TOKEN": "mine"}), "token=mine args=api user")

    def test_gh_does_not_recurse(self):
        # The wrapper's own directory first on PATH and no FORGE_REAL_GH: it must
        # still reach a real gh, never itself.
        bindir = self.tmp / "realbin"
        bindir.mkdir()
        write_script(bindir / "gh", 'echo "real"\n')
        env = {k: v for k, v in os.environ.items() if k != "FORGE_REAL_GH"}
        env["PATH"] = f"{TOOLS / 'bin'}{os.pathsep}{bindir}{os.pathsep}/usr/bin:/bin"
        out = subprocess.run([sys.executable, TOOLS / "bin/gh", "--version"], capture_output=True,
                             text=True, env=env, timeout=20)
        if shutil.which("mise", path=env["PATH"]) is None:
            self.assertEqual(out.stdout.strip(), "real")

    def test_gh_refuses_to_loop(self):
        out = subprocess.run([sys.executable, TOOLS / "bin/gh", "api", "user"], capture_output=True,
                             text=True, env={**os.environ, "FORGE_GH_WRAPPED": "1"})
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("called itself", out.stderr)

    def cred(self, request):
        return subprocess.run([sys.executable, TOOLS / "bin/git-credential-forge", "get"], input=request,
                              capture_output=True, text=True, env=os.environ).stdout

    def test_credential_by_path_and_pathless(self):
        out = self.cred("protocol=https\nhost=github.com\npath=shermanhuman/oh.git\n\n")
        self.assertIn("password=tok-shermanhuman", out)
        self.assertIn("username=x-access-token", out)
        out = self.cred("protocol=https\nhost=github.com\n\n")
        self.assertIn("password=tok-Applesauce-Labs", out)
        self.assertEqual(self.cred("protocol=https\nhost=gitlab.com\npath=a/b\n\n"), "")

    def test_credential_store_is_a_no_op(self):
        out = subprocess.run([sys.executable, TOOLS / "bin/git-credential-forge", "store"],
                             input="protocol=https\nhost=github.com\npassword=x\n\n",
                             capture_output=True, text=True)
        self.assertEqual((out.returncode, out.stdout), (0, ""))


class Setup(unittest.TestCase):
    def setUp(self):
        self.home = pathlib.Path(tempfile.mkdtemp(prefix="forge-home-"))
        self.addCleanup(shutil.rmtree, self.home, True)
        (self.home / ".config/mise").mkdir(parents=True)
        (self.home / ".config/mise/config.toml").write_text('[tools]\ngh = "latest"\n\n[env]\nFOO = "1"\n')
        self.gitconfig = self.home / ".gitconfig"
        self.gitconfig.write_text('[user]\n\tname = Owner\n\temail = owner@example.com\n'
                                  '[credential "https://github.com"]\n\thelper =\n\thelper = !gh auth git-credential\n')
        fakegh = self.home / "fakegh"
        write_script(fakegh, f'f={self.home}/proto\n[ "$1 $2" = "config get" ] && cat $f 2>/dev/null && exit 0\n'
                             f'[ "$1 $2" = "config set" ] && echo "$4" > $f\n')
        (self.home / "proto").write_text("ssh\n")
        self.env = {"HOME": str(self.home), "PATH": os.environ["PATH"], "FORGE_REAL_GH": str(fakegh),
                    "GIT_CONFIG_NOSYSTEM": "1"}

    def run_setup(self, *args):
        return subprocess.run([sys.executable, TOOLS / "setup_agent.py", *args], capture_output=True,
                              text=True, env=self.env)

    def git(self, key):
        return subprocess.run(["git", "config", "--global", "--get-all", key], capture_output=True,
                              text=True, env=self.env).stdout.splitlines()

    def test_switch_and_undo(self):
        before_git = self.gitconfig.read_text()
        before_mise = (self.home / ".config/mise/config.toml").read_text()
        r = self.run_setup()
        self.assertEqual(r.returncode, 0, r.stderr)
        helper = str(self.home / ".local/share/forge-app/bin/git-credential-forge")
        self.assertEqual(self.git("credential.https://github.com.helper"), ["", helper])
        self.assertEqual(self.git("credential.https://github.com.usehttppath"), ["true"])
        self.assertEqual(self.git("url.https://github.com/.insteadof"), ["git@github.com:", "ssh://git@github.com/"])
        self.assertEqual(self.git("committer.name"), ["mapleset-forge[bot]"])
        self.assertEqual(self.git("user.name"), ["Owner"])
        self.assertEqual((self.home / "proto").read_text().strip(), "https")
        mise = (self.home / ".config/mise/config.toml").read_text()
        self.assertIn(f'_.path = ["{self.home}/.local/share/forge-app/bin"]', mise)
        self.assertTrue((self.home / ".local/share/forge-app/bin/gh").exists())
        self.assertNotEqual(self.run_setup().returncode, 0)  # refuses to switch twice

        r = self.run_setup("--undo")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.git("committer.name"), [])
        self.assertEqual(self.git("credential.https://github.com.helper"), ["", "!gh auth git-credential"])
        self.assertEqual(self.git("url.https://github.com/.insteadof"), [])
        self.assertEqual((self.home / "proto").read_text().strip(), "ssh")
        self.assertEqual((self.home / ".config/mise/config.toml").read_text(), before_mise)
        del before_git


import check_agent_identity  # noqa: E402


class Identity(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="forge-id-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def cert(self, subject):
        key, crt = self.tmp / "k.pem", self.tmp / f"{abs(hash(subject))}.crt"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", crt,
                        "-days", "1", "-subj", subject], check=True, capture_output=True)
        return base64.b64encode(crt.read_bytes()).decode()

    def kubeconfig(self, server, subject):
        path = self.tmp / "config"
        path.write_text(json.dumps({
            "apiVersion": "v1", "kind": "Config", "current-context": "c",
            "clusters": [{"name": "k", "cluster": {"server": server}}],
            "users": [{"name": "u", "user": {"client-certificate-data": self.cert(subject)}}],
            "contexts": [{"name": "c", "context": {"cluster": "k", "user": "u"}}]}))
        return str(path)

    @unittest.skipUnless(shutil.which("kubectl"), "needs kubectl")
    def test_admin_for_ny1_fails_local_admin_passes(self):
        ny1 = check_agent_identity.NY1_SERVER
        self.assertEqual(check_agent_identity.masters_for_ny1(
            self.kubeconfig(ny1, "/O=system:masters/CN=system:admin")), ["u"])
        self.assertEqual(check_agent_identity.masters_for_ny1(
            self.kubeconfig("https://127.0.0.1:6443", "/O=system:masters/CN=system:admin")), [])
        self.assertEqual(check_agent_identity.masters_for_ny1(
            self.kubeconfig(ny1, "/O=agents/CN=someone")), [])

    def test_key_fingerprint_matches_githubs_form(self):
        key = self.tmp / "app.pem"
        subprocess.run(["openssl", "genrsa", "-out", key, "2048"], check=True, capture_output=True)
        der = subprocess.run(["openssl", "rsa", "-in", key, "-pubout", "-outform", "DER"],
                             capture_output=True, check=True).stdout
        import hashlib
        want = "SHA256:" + base64.b64encode(hashlib.sha256(der).digest()).decode().rstrip("=")
        self.assertEqual(check_agent_identity.key_fingerprint(str(key)), want)
        self.assertIsNone(check_agent_identity.key_fingerprint(str(self.tmp / "missing.pem")))


if __name__ == "__main__":
    unittest.main()
