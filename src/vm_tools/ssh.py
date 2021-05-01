import subprocess
from tempfile import NamedTemporaryFile

class Ssh:

    def __init__(self, identity, host, username):
        self.userHostStr = username + '@' + host
        self.ssh_args = ["ssh", "-i", identity, "-o", "StrictHostKeyChecking=no"]
        self.sftp_args = ["sftp", "-i", identity, "-o", "StrictHostKeyChecking=no"]

    def setup_env(self):        
        script = """@
@mkdir runner
@cd runner
@mkdir build
@mkdir cache
@mkdir scripts
"""
        self._run_sftp_script(script)

    def copy_file(self, src, dst):
        script = "@put \"{}\" \"{}\"".format(src,dst)
        self._run_sftp_script(script)

    def test_connect(self, timeout=30):
        return self.run_command('exit', options=['-o', 'ConnectTimeout={}'.format(timeout)], check=False)

    def run_command(self, cmd, options=[], check=True):
        args = list(self.ssh_args)
        args.extend(options)
        args.extend([self.userHostStr, cmd])
        return subprocess.run(args, check=check)

    def _run_sftp_script(self, str):
        with NamedTemporaryFile() as f:
            f.write(str.encode('ascii'))
            f.flush()
            
            args = list(self.sftp_args)
            args.extend(["-b", f.name, self.userHostStr])

            subprocess.run(args, check=True)

