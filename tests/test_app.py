import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app import AppServer, Config, Scanner, Store, local_device, parse_arp

ARP = '192.168.1.2\taa:bb:cc:dd:ee:ff\tVendor Name\n'

class StoreTests(unittest.TestCase):
    def setUp(self):
        host_patch = patch('app.local_device', return_value=None)
        host_patch.start()
        self.addCleanup(host_patch.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.temp.name) / 'lan.sqlite3'))
        with patch.dict(os.environ, {'IFACES':'eth0'}, clear=True):
            self.config = Config()
        self.config.interfaces = ['eth0']
        self.scanner = Scanner(self.config, self.store)

    def tearDown(self):
        self.temp.cleanup()

    def scan(self, output=ARP):
        with patch('app.subprocess.run', return_value=subprocess.CompletedProcess([],0,output,'')):
            self.assertTrue(self.scanner.trigger())
            self.scanner.thread.join(3)
        self.assertFalse(self.scanner.lock.locked())

    def test_parser_validates_normalizes_deduplicates(self):
        text='Interface: eth0\nnot-an-ip aa:bb:cc:dd:ee:ff X\n192.168.1.3 badmac X\n'+ARP.upper()+ARP
        devices=parse_arp(text,'eth0')
        self.assertEqual(len(devices),1)
        self.assertEqual(devices[0]['mac'],'aa:bb:cc:dd:ee:ff')
        self.assertEqual(devices[0]['vendor'],'Vendor Name')

    def test_metadata_survives_ip_change_and_restart(self):
        self.scan()
        d=self.store.devices()[0]
        self.store.update(d['id'],{'known':True,'name':'NAS','description':'<b>Backup</b>'})
        self.scan(ARP.replace('192.168.1.2','192.168.1.99'))
        restored=Store(self.store.path).devices()[0]
        self.assertEqual(restored['id'],d['id'])
        self.assertEqual(restored['ip'],'192.168.1.99')
        self.assertEqual(restored['description'],'<b>Backup</b>')
        self.assertEqual(restored['name'],'NAS')
        self.assertTrue(restored['known'])

    def test_successful_empty_scan_sets_offline_preserving_last_seen(self):
        self.scan()
        stamp=self.store.devices()[0]['last_seen']
        self.scan('')
        self.assertFalse(self.store.devices()[0]['online'])
        self.assertEqual(self.store.devices()[0]['last_seen'],stamp)

    def test_failed_interface_discards_partial_scan(self):
        self.scan()
        self.config.interfaces=['eth0','eth1']
        responses=[subprocess.CompletedProcess([],0,'',''),subprocess.CompletedProcess([],1,'','Permission denied')]
        with patch('app.subprocess.run',side_effect=responses):
            self.scanner.trigger();self.scanner.thread.join(3)
        self.assertTrue(self.store.devices()[0]['online'])
        self.assertEqual(self.store.scan_history()[0]['status'],'error')

    def test_timeout_and_missing_binary_preserve_online(self):
        self.scan()
        for exc in [subprocess.TimeoutExpired('arp-scan',60),FileNotFoundError()]:
            with patch('app.subprocess.run',side_effect=exc):
                self.scanner.trigger();self.scanner.thread.join(3)
            self.assertTrue(self.store.devices()[0]['online'])
            self.assertEqual(self.store.scan_history()[0]['status'],'error')
            self.assertFalse(self.scanner.lock.locked())

    def test_duplicate_scan_request_is_rejected(self):
        started,release=threading.Event(),threading.Event()
        def blocking(*a,**kw):
            started.set();release.wait(3)
            return subprocess.CompletedProcess([],0,ARP,'')
        with patch('app.subprocess.run',side_effect=blocking):
            self.assertTrue(self.scanner.trigger());started.wait(1)
            try:self.assertFalse(self.scanner.trigger())
            finally:release.set();self.scanner.thread.join(3)
        self.assertEqual(len(self.store.scan_history()),1)

    def test_validation(self):
        self.scan()
        for changes in [{'known':'true'},{'known':1},{'name':'x'*101},{'description':'x'*2001},{'ip':'1.2.3.4'},{}]:
            with self.assertRaises(ValueError):self.store.update(1,changes)
        with self.assertRaises(KeyError):self.store.update(999,{'known':True})

    def test_identity_is_per_interface(self):
        self.scan()
        self.config.interfaces=['eth1']
        self.scan()
        self.assertEqual(len(self.store.devices()),2)
        self.assertTrue(all(d['online'] for d in self.store.devices()))

    def test_host_is_included_once_and_metadata_survives(self):
        host = dict(ip='172.20.20.7', mac='02:11:22:33:44:55', interface='eth0', vendor='')
        with patch('app.local_device', return_value=host):
            self.scan('')
            device = self.store.devices()[0]
            self.store.update(device['id'], {'known': True, 'name': 'Docker host'})
            host['ip'] = '172.20.20.8'
            self.scan('172.20.20.7 02:11:22:33:44:55 Vendor')
        devices = self.store.devices()
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]['id'], device['id'])
        self.assertEqual(devices[0]['ip'], '172.20.20.8')
        self.assertTrue(devices[0]['online'])
        self.assertTrue(devices[0]['known'])
        self.assertEqual(devices[0]['name'], 'Docker host')
        self.assertEqual(self.store.scan_history()[0]['found'], 1)

    def test_restart_marks_interrupted_scan_as_error(self):
        with self.store.connect() as db:
            db.execute("INSERT INTO scans (started_at,status) VALUES ('2026-01-01','running')")
        self.assertEqual(Store(self.store.path).scan_history()[0]['status'],'error')

class SettingsTests(unittest.TestCase):
    def test_first_start_waits_for_interface_and_settings_survive_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(str(Path(folder) / 'settings.sqlite3'))
            config = Config()
            scanner = Scanner(config, store)
            self.assertEqual(config.interval, 600)
            self.assertEqual(config.interfaces, [])
            scanner.schedule()
            try:
                time.sleep(1.2)
                self.assertEqual(store.scan_history(), [])
                self.assertIsNone(scanner.next_scan)
                with self.assertRaisesRegex(ValueError, 'Settings'):
                    scanner.trigger()
                settings = dict(interfaces=['br0', 'br0'], interval=900, timeout=30, timezone='UTC')
                scanner.configure(settings)
                self.assertIsNotNone(scanner.next_scan)
            finally:
                scanner.stop.set()
            restored = Config()
            Scanner(restored, Store(store.path))
            self.assertEqual(restored.settings(), dict(settings, interfaces=['br0']))
            restored_scanner = Scanner(restored, store)
            restored_scanner.configure(dict(restored.settings(), interfaces=[]))
            self.assertIsNone(restored_scanner.next_scan)

    def test_invalid_settings_and_busy_scan_preserve_saved_values(self):
        with tempfile.TemporaryDirectory() as folder:
            scanner = Scanner(Config(), Store(str(Path(folder) / 'settings.sqlite3')))
            original = scanner.config.settings()
            for changes in [{'interfaces':['eth0;echo']}, {'interfaces':'eth0'}, {'interval':True},
                            {'interval':9}, {'timeout':601}, {'timezone':'Unknown/Zone'}, {'extra':1}]:
                with self.assertRaises(ValueError):
                    scanner.configure(dict(original, **changes))
            self.assertEqual(scanner.config.settings(), original)
            self.assertIsNone(scanner.store.load_settings())
            scanner.lock.acquire()
            try:
                self.assertFalse(scanner.configure(dict(original, interval=1200)))
            finally:
                scanner.lock.release()
            self.assertEqual(scanner.config.settings(), original)

class LocalDeviceTests(unittest.TestCase):
    def test_reads_primary_ipv4_and_mac_from_configured_interface(self):
        output = json.dumps([{'address': '02:AA:BB:CC:DD:EE', 'addr_info': [
            {'family': 'inet', 'local': '172.20.20.9', 'secondary': True},
            {'family': 'inet', 'local': '172.20.20.7'}]}])
        with patch('app.subprocess.run', return_value=subprocess.CompletedProcess([], 0, output, '')) as run:
            self.assertEqual(local_device('br0'), dict(ip='172.20.20.7', mac='02:aa:bb:cc:dd:ee', interface='br0', vendor=''))
        self.assertEqual(run.call_args.args[0], ['ip', '-j', 'address', 'show', 'dev', 'br0'])

    def test_missing_ipv4_loopback_and_query_failure(self):
        for link in [{'address': '02:11:22:33:44:55', 'addr_info': []},
                     {'address': '00:00:00:00:00:00', 'addr_info': [{'family': 'inet', 'local': '127.0.0.1'}]}]:
            with patch('app.subprocess.run', return_value=subprocess.CompletedProcess([], 0, json.dumps([link]), '')):
                self.assertIsNone(local_device('eth0'))
        with patch('app.subprocess.run', return_value=subprocess.CompletedProcess([], 1, '', 'No such device')):
            with self.assertRaisesRegex(RuntimeError, 'Reading host address'):
                local_device('eth0')

class ApiTests(unittest.TestCase):
    def setUp(self):
        host_patch = patch('app.local_device', return_value=None)
        host_patch.start()
        self.addCleanup(host_patch.stop)
        self.temp=tempfile.TemporaryDirectory()
        with patch.dict(os.environ,{'IFACES':'eth0'},clear=True):self.config=Config()
        self.config.interfaces = ['eth0']
        self.store=Store(str(Path(self.temp.name)/'test.sqlite3'))
        with self.store.connect() as db:
            scan_id=db.execute("INSERT INTO scans (started_at,status) VALUES ('2026-01-01','running')").lastrowid
        self.store.apply_scan(parse_arp(ARP,'eth0'),['eth0'],scan_id)
        self.scanner=Scanner(self.config,self.store)
        self.server=AppServer(('127.0.0.1',0),self.config,self.store,self.scanner)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base='http://127.0.0.1:'+str(self.server.server_port)

    def tearDown(self):
        self.scanner.stop.set()
        if self.scanner.thread:self.scanner.thread.join(3)
        self.server.shutdown();self.server.server_close();self.thread.join(3);self.temp.cleanup()

    def request(self,path,method='GET',body=None,headers=None):
        h={}
        if body is not None:h['Content-Type']='application/json'
        h.update(headers or {})
        req=Request(self.base+path,method=method,data=json.dumps(body).encode() if body is not None else None,headers=h)
        try:
            with urlopen(req,timeout=3) as response:return response.status,response.read(),response.headers
        except HTTPError as response:return response.code,response.read(),response.headers

    def test_public_api_health_and_static_allowlist(self):
        self.assertEqual(self.request('/api/state')[0],200)
        self.assertEqual(self.request('/healthz')[0],200)
        self.assertEqual(self.request('/')[0],200)
        self.assertEqual(self.request('/../app.py')[0],404)
        self.assertEqual(self.request('/app.js')[0],200)
        self.assertEqual(self.request('/theme.js')[0],200)
        self.assertIn("script-src 'self'",self.request('/')[2]['Content-Security-Policy'])

    def test_patch_persists_and_requires_json_same_origin(self):
        self.assertEqual(self.request('/api/devices/1','PATCH',{'known':True,'description':'Office'})[0],200)
        state=json.loads(self.request('/api/state')[1])
        self.assertEqual(next(d for d in state['devices'] if d['id']==1)['description'],'Office')
        self.assertEqual(self.request('/api/devices/1','PATCH',{'known':False},headers={'Origin':'https://evil.invalid'})[0],403)
        self.assertEqual(self.request('/api/devices/1','PATCH',{'known':False},headers={'Content-Type':'text/plain'})[0],415)
        self.assertEqual(self.request('/api/devices/1','PATCH',{'known':'yes'})[0],400)
        self.assertEqual(self.request('/api/devices/999','PATCH',{'known':True})[0],404)
        self.assertEqual(self.request('/api/devices/1','PATCH',[])[0],400)

    def test_settings_api_and_unconfigured_start(self):
        self.scanner.configure(dict(self.config.settings(), interfaces=[]))
        self.assertEqual(self.request('/')[0], 200)
        self.assertEqual(self.request('/api/scan', 'POST', {})[0], 400)
        settings = dict(interfaces=['eth0'], interval=600, timeout=40, timezone='Europe/Berlin')
        self.assertEqual(self.request('/api/settings', 'PATCH', settings)[0], 200)
        self.assertEqual(json.loads(self.request('/api/state')[1])['config'], settings)
        self.assertEqual(self.request('/api/settings', 'PATCH', dict(settings, interval=0))[0], 400)
        self.assertEqual(self.request('/api/settings', 'PATCH', settings, headers={'Origin':'https://evil.invalid'})[0], 403)
        self.scanner.lock.acquire()
        try:
            self.assertEqual(self.request('/api/settings', 'PATCH', settings)[0], 409)
        finally:
            self.scanner.lock.release()

    def test_manual_scan(self):
        started, release = threading.Event(), threading.Event()
        def scan_result(*args, **kwargs):
            started.set()
            release.wait(3)
            return subprocess.CompletedProcess([],0,ARP,'')
        with patch('app.subprocess.run',side_effect=scan_result):
            self.assertEqual(self.request('/api/scan','POST',{})[0],202)
            started.wait(1)
            try:
                self.assertEqual(self.request('/api/scan','POST',{})[0],409)
            finally:
                release.set()
                self.scanner.thread.join(3)
        self.assertEqual(self.store.scan_history()[0]['status'],'success')
        self.assertEqual(self.store.scan_history()[0]['found'],1)

if __name__=='__main__':unittest.main()
