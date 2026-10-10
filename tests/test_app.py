import base64
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app import AppServer, Config, Scanner, Store, parse_arp

ARP = '192.168.1.2\taa:bb:cc:dd:ee:ff\tVendor Name\n'

class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.temp.name) / 'lan.sqlite3'))
        with patch.dict(os.environ, {'IFACES':'eth0','DEMO':'false'}, clear=True):
            self.config = Config()
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

    def test_restart_marks_interrupted_scan_as_error(self):
        with self.store.connect() as db:
            db.execute("INSERT INTO scans (started_at,status) VALUES ('2026-01-01','running')")
        self.assertEqual(Store(self.store.path).scan_history()[0]['status'],'error')

class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        with patch.dict(os.environ,{'DEMO':'true','AUTH_PASSWORD':'test-only-password'},clear=True):self.config=Config()
        self.store=Store(str(Path(self.temp.name)/'demo.sqlite3'));self.store.seed_demo()
        self.scanner=Scanner(self.config,self.store)
        self.server=AppServer(('127.0.0.1',0),self.config,self.store,self.scanner)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base='http://127.0.0.1:'+str(self.server.server_port)
        self.auth='Basic '+base64.b64encode(b'admin:test-only-password').decode()

    def tearDown(self):
        self.scanner.stop.set()
        if self.scanner.thread:self.scanner.thread.join(3)
        self.server.shutdown();self.server.server_close();self.thread.join(3);self.temp.cleanup()

    def request(self,path,method='GET',body=None,headers=None,auth=True):
        h={'Authorization':self.auth} if auth else {}
        if body is not None:h['Content-Type']='application/json'
        h.update(headers or {})
        req=Request(self.base+path,method=method,data=json.dumps(body).encode() if body is not None else None,headers=h)
        try:
            with urlopen(req,timeout=3) as response:return response.status,response.read(),response.headers
        except HTTPError as response:return response.code,response.read(),response.headers

    def test_auth_health_and_static_allowlist(self):
        self.assertEqual(self.request('/api/state',auth=False)[0],401)
        self.assertEqual(self.request('/healthz',auth=False)[0],200)
        self.assertEqual(self.request('/')[0],200)
        self.assertEqual(self.request('/../app.py')[0],404)
        self.assertEqual(self.request('/app.js')[0],200)
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

    def test_manual_scan_and_seed_is_idempotent(self):
        self.store.seed_demo();self.assertEqual(len(self.store.devices()),10)
        self.assertEqual(self.request('/api/scan','POST',{})[0],202)
        self.assertEqual(self.request('/api/scan','POST',{})[0],409)
        self.scanner.thread.join(3)
        self.assertEqual(self.store.scan_history()[0]['status'],'success')
        self.assertEqual(self.store.scan_history()[0]['found'],8)

if __name__=='__main__':unittest.main()
