#!/usr/bin/env python3
"""LANytic HTTP API, ARP discovery, and persistent SQLite device inventory."""
import ipaddress
import json
import logging
import os
from pathlib import Path
import re
import signal
import sqlite3
import subprocess
import threading
import time
from datetime import datetime, timezone
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parent

def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')

class Config:
    def __init__(self):
        self.host = os.getenv('HOST', '127.0.0.1')
        self.port = int(os.getenv('PORT', '8840'))
        self.interfaces = []
        self.interval = 600
        self.timeout = 60
        self.timezone = 'Europe/Berlin'
        self.db = os.getenv('DB_PATH', str(ROOT / 'data' / 'lan.sqlite3'))

    def settings(self):
        return dict(interfaces=list(self.interfaces), interval=self.interval,
                    timeout=self.timeout, timezone=self.timezone)

    @staticmethod
    def validate(settings):
        if set(settings) != {'interfaces', 'interval', 'timeout', 'timezone'}:
            raise ValueError('Required settings: interfaces, interval, timeout, timezone.')
        interfaces = settings['interfaces']
        if (not isinstance(interfaces, list) or len(interfaces) > 32 or
                any(not isinstance(i, str) or not re.fullmatch(r'[a-zA-Z0-9_.:-]{1,32}', i) for i in interfaces)):
            raise ValueError('Enter valid interface names, separated by spaces (maximum 32).')
        if type(settings['interval']) is not int or not 10 <= settings['interval'] <= 2147483647:
            raise ValueError('Scan interval must be an integer between 10 and 2147483647 seconds.')
        if type(settings['timeout']) is not int or not 1 <= settings['timeout'] <= 600:
            raise ValueError('Scan timeout must be an integer between 1 and 600 seconds.')
        tz = settings['timezone']
        if not isinstance(tz, str) or len(tz) > 128:
            raise ValueError('Enter a valid IANA timezone, e.g. Europe/Berlin.')
        try:
            ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError('Enter a valid IANA timezone, e.g. Europe/Berlin.') from None
        return dict(settings, interfaces=list(dict.fromkeys(interfaces)))

    def apply(self, settings):
        self.interfaces = settings['interfaces']
        self.interval = settings['interval']
        self.timeout = settings['timeout']
        self.timezone = settings['timezone']
        os.environ['TZ'] = self.timezone
        if hasattr(time, 'tzset'):
            time.tzset()

def parse_arp(output, interface):
    devices = {}
    for line in output.splitlines():
        fields = line.split(None, 2)
        if len(fields) < 2:
            continue
        try:
            ip = str(ipaddress.IPv4Address(fields[0]))
        except ipaddress.AddressValueError:
            continue
        mac = fields[1].lower()
        if not re.fullmatch(r'(?:[0-9a-f]{2}:){5}[0-9a-f]{2}', mac):
            continue
        devices[mac] = dict(ip=ip, mac=mac, interface=interface,
                            vendor=fields[2].strip() if len(fields) == 3 else '')
    return list(devices.values())

def local_device(interface):
    result = subprocess.run(['ip', '-j', 'address', 'show', 'dev', interface],
                            capture_output=True, text=True, timeout=10, check=False)
    if result.returncode:
        raise RuntimeError('Reading host address on %s failed: %s' % (interface, result.stderr.strip()[:500]))
    for link in json.loads(result.stdout):
        mac = link.get('address', '').lower()
        if not re.fullmatch(r'(?:[0-9a-f]{2}:){5}[0-9a-f]{2}', mac) or mac == '00:00:00:00:00:00':
            continue
        addresses = [a for a in link.get('addr_info', []) if a.get('family') == 'inet']
        addresses.sort(key=lambda a: bool(a.get('secondary', False)))
        for address in addresses:
            ip = ipaddress.IPv4Address(address['local'])
            if not ip.is_loopback and not ip.is_unspecified:
                return dict(ip=str(ip), mac=mac, interface=interface, vendor='')
    return None

class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS devices (
                    id INTEGER PRIMARY KEY, mac TEXT NOT NULL, interface TEXT NOT NULL,
                    ip TEXT NOT NULL, vendor TEXT NOT NULL DEFAULT '',
                    name TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '',
                    known INTEGER NOT NULL DEFAULT 0, online INTEGER NOT NULL DEFAULT 1,
                    first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
                    UNIQUE(mac, interface));
                CREATE TABLE IF NOT EXISTS scans (
                    id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
                    status TEXT NOT NULL, found INTEGER NOT NULL DEFAULT 0, error TEXT);
            ''')
            db.execute("UPDATE scans SET status='error', error='Scan interrupted by a restart.', finished_at=? WHERE status='running'", (now(),))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def load_settings(self):
        with self.connect() as db:
            row = db.execute('SELECT value FROM settings WHERE id=1').fetchone()
            return json.loads(row['value']) if row else None

    def save_settings(self, settings):
        with self.connect() as db:
            db.execute('INSERT INTO settings (id,value) VALUES (1,?) ON CONFLICT(id) DO UPDATE SET value=excluded.value',
                       (json.dumps(settings),))

    def devices(self):
        with self.connect() as db:
            rows = [dict(r) for r in db.execute('SELECT * FROM devices')]
        for r in rows:
            r['known'], r['online'] = bool(r['known']), bool(r['online'])
        return sorted(rows, key=lambda r: (not r['online'], int(ipaddress.IPv4Address(r['ip'])), r['interface']))

    def apply_scan(self, observations, interfaces, scan_id):
        stamp = now()
        with self.connect() as db:
            for interface in interfaces:
                db.execute('UPDATE devices SET online=0 WHERE interface=?', (interface,))
            for d in observations:
                db.execute('''INSERT INTO devices (mac,interface,ip,vendor,first_seen,last_seen)
                    VALUES (?,?,?,?,?,?) ON CONFLICT(mac,interface) DO UPDATE SET
                    ip=excluded.ip, vendor=excluded.vendor, online=1, last_seen=excluded.last_seen''',
                    (d['mac'], d['interface'], d['ip'], d['vendor'], stamp, stamp))
            db.execute("UPDATE scans SET finished_at=?,status='success',found=? WHERE id=?", (stamp, len(observations), scan_id))
            db.execute('DELETE FROM scans WHERE id NOT IN (SELECT id FROM scans ORDER BY id DESC LIMIT 100)')

    def update(self, device_id, changes):
        allowed = {'known', 'name', 'description'}
        if not changes or not isinstance(changes, dict) or set(changes) - allowed:
            raise ValueError('Allowed fields: known, name, description.')
        for key, value in changes.items():
            if key == 'known':
                if type(value) is not bool:
                    raise ValueError('known must be true or false.')
            elif not isinstance(value, str) or len(value) > (100 if key == 'name' else 2000):
                raise ValueError('Name: maximum 100 characters. Description: maximum 2000 characters.')
        with self.connect() as db:
            cursor = db.execute('UPDATE devices SET ' + ','.join(k + '=?' for k in changes) + ' WHERE id=?',
                                list(changes.values()) + [device_id])
            if not cursor.rowcount:
                raise KeyError('Device not found.')

    def scan_history(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM scans ORDER BY id DESC LIMIT 100')]

class Scanner:
    def __init__(self, config, store):
        self.config, self.store = config, store
        saved = store.load_settings()
        config.apply(Config.validate(saved) if saved is not None else config.settings())
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.next_scan = None
        self.thread = None

    def configure(self, settings):
        settings = Config.validate(settings)
        if not self.lock.acquire(blocking=False):
            return False
        try:
            previous_interfaces = self.config.interfaces
            self.store.save_settings(settings)
            self.config.apply(settings)
            self.next_scan = ((time.time() if previous_interfaces != self.config.interfaces else time.time() + self.config.interval)
                              if self.config.interfaces else None)
        finally:
            self.lock.release()
        return True

    def trigger(self):
        if not self.lock.acquire(blocking=False):
            return False
        if not self.config.interfaces:
            self.lock.release()
            raise ValueError('Configure a LAN interface in Settings before scanning.')
        try:
            self.thread = threading.Thread(target=self.run, daemon=True)
            self.thread.start()
        except Exception:
            self.lock.release()
            raise
        return True

    def run(self):
        scan_id = None
        try:
            with self.store.connect() as db:
                scan_id = db.execute("INSERT INTO scans (started_at,status) VALUES (?,'running')", (now(),)).lastrowid
            interfaces = self.config.interfaces
            if not interfaces:
                raise RuntimeError('Configure a LAN interface in Settings before scanning.')
            observations = []
            for interface in interfaces:
                result = subprocess.run(['arp-scan', '--localnet', '--interface='+interface, '--retry=2', '--plain', '--ignoredups'],
                                        capture_output=True, text=True, timeout=self.config.timeout, check=False)
                if result.returncode:
                    raise RuntimeError('Scan on %s failed: %s' % (interface, result.stderr.strip()[:500]))
                devices = {d['mac']: d for d in parse_arp(result.stdout, interface)}
                host = local_device(interface)
                if host:
                    devices[host['mac']] = host
                observations.extend(devices.values())
            self.store.apply_scan(observations, interfaces, scan_id)
        except Exception as exc:
            message = str(exc)
            if isinstance(exc, FileNotFoundError):
                message = 'A scanner dependency is missing. Use the Docker image or install arp-scan and iproute2 on the host.'
            logging.error('Scan failed: %s', message)
            if scan_id is not None:
                with self.store.connect() as db:
                    db.execute("UPDATE scans SET status='error',finished_at=?,error=? WHERE id=?", (now(), message, scan_id))
                    db.execute('DELETE FROM scans WHERE id NOT IN (SELECT id FROM scans ORDER BY id DESC LIMIT 100)')
        finally:
            self.next_scan = time.time() + self.config.interval if self.config.interfaces else None
            self.lock.release()

    def schedule(self):
        self.next_scan = time.time() if self.config.interfaces else None
        def loop():
            while not self.stop.wait(1):
                next_scan = self.next_scan
                if not self.lock.locked() and next_scan is not None and time.time() >= next_scan:
                    try:
                        self.trigger()
                    except ValueError:
                        pass
        threading.Thread(target=loop, daemon=True).start()

class AppServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, config, store, scanner):
        self.config, self.store, self.scanner = config, store, scanner
        super().__init__(address, Handler)

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(15)
        return connection, address

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        logging.info('%s %s', self.address_string(), fmt % args)

    def respond(self, status, body, content_type='application/json; charset=utf-8', extra=None):
        raw = json.dumps(body, ensure_ascii=False).encode() if content_type.startswith('application/json') else body
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/healthz':
            self.respond(200, {'status':'ok'})
            return
        if path == '/api/state':
            scanner = self.server.scanner
            self.respond(200, {'devices':self.server.store.devices(), 'scans':self.server.store.scan_history(),
                'config':self.server.config.settings(),
                'scanning':scanner.lock.locked(), 'next_scan':scanner.next_scan})
        elif path in ('/', '/app.js', '/style.css', '/favicon.svg', '/theme.js'):
            file = ROOT / 'static' / ('index.html' if path == '/' else path[1:])
            mime = {'/':'text/html; charset=utf-8','/app.js':'text/javascript; charset=utf-8','/style.css':'text/css; charset=utf-8','/favicon.svg':'image/svg+xml','/theme.js':'text/javascript; charset=utf-8'}[path]
            self.respond(200, file.read_bytes(), mime)
        else:
            self.respond(404, {'error':'Not found.'})

    def mutate(self):
        origin = self.headers.get('Origin')
        if (origin and urlsplit(origin).netloc != self.headers.get('Host')) or self.headers.get('Sec-Fetch-Site') == 'cross-site':
            self.respond(403, {'error':'Cross-site request rejected.'})
            return
        if self.headers.get('Content-Type','').split(';')[0] != 'application/json':
            self.respond(415, {'error':'Content-Type application/json is required.'})
            return
        try:
            size = int(self.headers.get('Content-Length','0'))
            if not 0 < size <= 16384:
                raise ValueError('Invalid request size.')
            changes = json.loads(self.rfile.read(size))
            if not isinstance(changes, dict):
                raise ValueError('A JSON object is required.')
            path = urlsplit(self.path).path
            if self.command == 'POST' and path == '/api/scan':
                if self.server.scanner.trigger():
                    self.respond(202, {'status':'started'})
                else:
                    self.respond(409, {'error':'A scan is already running.'})
            elif self.command == 'PATCH' and path == '/api/settings':
                if self.server.scanner.configure(changes):
                    self.respond(200, {'status':'saved'})
                else:
                    self.respond(409, {'error':'Wait for the current scan to finish before changing settings.'})
            elif self.command == 'PATCH' and re.fullmatch(r'/api/devices/[0-9]+',path):
                self.server.store.update(int(path.rsplit('/',1)[1]), changes)
                self.respond(200, {'status':'saved'})
            else:
                self.respond(404, {'error':'Not found.'})
        except (ValueError, UnicodeDecodeError) as exc:
            self.respond(400, {'error':str(exc)})
        except KeyError:
            self.respond(404, {'error':'Device not found.'})

    do_POST = mutate
    do_PATCH = mutate

def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    config = Config()
    store = Store(config.db)
    scanner = Scanner(config, store)
    server = AppServer((config.host,config.port),config,store,scanner)
    scanner.schedule()
    def shutdown(*_):
        scanner.stop.set()
        threading.Thread(target=server.shutdown,daemon=True).start()
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    logging.info('LANytic running at http://%s:%s', config.host, config.port)
    try:
        server.serve_forever()
    finally:
        scanner.stop.set()
        server.server_close()
        if scanner.thread:
            scanner.thread.join(timeout=config.timeout * max(1,len(config.interfaces)) + 2)

if __name__ == '__main__':
    main()
