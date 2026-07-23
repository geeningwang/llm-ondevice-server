import http.server
import socketserver
import ssl
import os
import json
import sqlite3
import re
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs

WEB_ROOT = '/home/admin_jingnw_altostrat_com/gemma4weights/www'
DB_PATH = '/home/admin_jingnw_altostrat_com/gemma4weights/telemetry.db'
CERT_PATH = '/etc/letsencrypt/live/34.134.65.149.nip.io/fullchain.pem'
KEY_PATH = '/etc/letsencrypt/live/34.134.65.149.nip.io/privkey.pem'

VALID_THERMAL = {'Normal', 'Light Heat', 'Moderate', 'Throttled', 'Critical'}
SESSION_RE = re.compile(r'^/api/telemetry/sessions/([^/]+)$')


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS telemetry_sessions (
            session_id TEXT PRIMARY KEY,
            model_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS telemetry_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL REFERENCES telemetry_sessions(session_id) ON DELETE CASCADE,
            client_timestamp TEXT NOT NULL,
            cpu_percent REAL NOT NULL,
            total_pss_mb REAL NOT NULL,
            native_heap_mb REAL NOT NULL,
            tokens_per_second REAL NOT NULL,
            gpu_percent REAL,
            thermal_status TEXT NOT NULL,
            server_received_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_telemetry_samples_session_time
        ON telemetry_samples (session_id, client_timestamp ASC);
    ''')
    conn.close()


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA foreign_keys=ON')
    return conn


class TelemetryHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_ROOT, **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip('/')

        if path == '/api/telemetry/sessions':
            self._handle_list_sessions(parsed)
        elif m := SESSION_RE.match(path):
            self._handle_get_session(m.group(1))
        else:
            super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip('/')

        if path == '/api/telemetry/status':
            self._handle_upload()
        else:
            self._send_json(404, {'status': 'error', 'message': 'Not found'})

    def _read_json_body(self):
        length = int(self.headers.get('Content-Length', 0))
        if length == 0:
            return None
        return json.loads(self.rfile.read(length))

    def _send_json(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_upload(self):
        try:
            payload = self._read_json_body()
        except (json.JSONDecodeError, TypeError):
            self._send_json(400, {'status': 'error', 'message': 'Invalid JSON'})
            return

        if not payload or not all(k in payload for k in ('session_id', 'model_id', 'samples')):
            self._send_json(400, {
                'status': 'error',
                'message': 'Invalid payload: missing session_id, model_id, or samples array'
            })
            return

        session_id = payload['session_id']
        model_id = payload['model_id']
        samples = payload['samples']

        if not isinstance(samples, list) or len(samples) == 0:
            self._send_json(400, {'status': 'error', 'message': 'samples must be a non-empty array'})
            return

        required_fields = ('timestamp', 'cpu_percent', 'total_pss_mb', 'native_heap_mb',
                           'tokens_per_second', 'thermal_status')
        for s in samples:
            if not all(f in s for f in required_fields):
                self._send_json(400, {'status': 'error', 'message': f'Sample missing required fields'})
                return
            if s['thermal_status'] not in VALID_THERMAL:
                self._send_json(400, {
                    'status': 'error',
                    'message': f"Invalid thermal_status: {s['thermal_status']}"
                })
                return

        now = datetime.now(timezone.utc).isoformat()
        conn = get_db()
        try:
            row = conn.execute('SELECT session_id FROM telemetry_sessions WHERE session_id = ?',
                               (session_id,)).fetchone()
            is_new = row is None

            if is_new:
                conn.execute(
                    'INSERT INTO telemetry_sessions (session_id, model_id, created_at, last_updated_at) VALUES (?, ?, ?, ?)',
                    (session_id, model_id, now, now))
            else:
                conn.execute(
                    'UPDATE telemetry_sessions SET last_updated_at = ? WHERE session_id = ?',
                    (now, session_id))

            conn.executemany(
                '''INSERT INTO telemetry_samples
                   (session_id, client_timestamp, cpu_percent, total_pss_mb, native_heap_mb,
                    tokens_per_second, gpu_percent, thermal_status, server_received_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                [(session_id, s['timestamp'], s['cpu_percent'], s['total_pss_mb'],
                  s['native_heap_mb'], s['tokens_per_second'], s.get('gpu_percent'),
                  s['thermal_status'], now) for s in samples])

            conn.commit()

            total = conn.execute('SELECT COUNT(*) FROM telemetry_samples WHERE session_id = ?',
                                 (session_id,)).fetchone()[0]
        finally:
            conn.close()

        self._send_json(201 if is_new else 200, {
            'status': 'success',
            'message': f'Batch of {len(samples)} telemetry samples appended',
            'session_id': session_id,
            'total_samples': total
        })

    def _handle_list_sessions(self, parsed):
        params = parse_qs(parsed.query)
        limit = min(int(params.get('limit', [50])[0]), 500)
        offset = int(params.get('offset', [0])[0])

        conn = get_db()
        try:
            total = conn.execute('SELECT COUNT(*) FROM telemetry_sessions').fetchone()[0]
            rows = conn.execute('''
                SELECT s.session_id, s.model_id, s.created_at, s.last_updated_at,
                       COUNT(m.id) as sample_count
                FROM telemetry_sessions s
                LEFT JOIN telemetry_samples m ON s.session_id = m.session_id
                GROUP BY s.session_id
                ORDER BY s.last_updated_at DESC
                LIMIT ? OFFSET ?
            ''', (limit, offset)).fetchall()
        finally:
            conn.close()

        self._send_json(200, {
            'status': 'success',
            'total_sessions': total,
            'sessions': [{
                'session_id': r['session_id'],
                'model_id': r['model_id'],
                'sample_count': r['sample_count'],
                'created_at': r['created_at'],
                'last_updated_at': r['last_updated_at']
            } for r in rows]
        })

    def _handle_get_session(self, session_id):
        conn = get_db()
        try:
            session = conn.execute(
                'SELECT * FROM telemetry_sessions WHERE session_id = ?',
                (session_id,)).fetchone()

            if not session:
                self._send_json(404, {'status': 'error', 'message': 'Session ID not found'})
                return

            agg = conn.execute('''
                SELECT
                    COUNT(*) as sample_count,
                    AVG(cpu_percent) as avg_cpu_percent,
                    MAX(cpu_percent) as max_cpu_percent,
                    AVG(total_pss_mb) as avg_total_pss_mb,
                    MAX(total_pss_mb) as max_total_pss_mb,
                    AVG(native_heap_mb) as avg_native_heap_mb,
                    MAX(native_heap_mb) as max_native_heap_mb,
                    AVG(tokens_per_second) as avg_tokens_per_second,
                    MAX(tokens_per_second) as max_tokens_per_second,
                    SUM(CASE WHEN thermal_status IN ('Throttled', 'Critical') THEN 1 ELSE 0 END) as throttled_samples_count
                FROM telemetry_samples WHERE session_id = ?
            ''', (session_id,)).fetchone()

            samples = conn.execute('''
                SELECT client_timestamp, cpu_percent, total_pss_mb, native_heap_mb,
                       tokens_per_second, gpu_percent, thermal_status
                FROM telemetry_samples WHERE session_id = ?
                ORDER BY client_timestamp ASC
            ''', (session_id,)).fetchall()
        finally:
            conn.close()

        self._send_json(200, {
            'status': 'success',
            'session_id': session['session_id'],
            'model_id': session['model_id'],
            'created_at': session['created_at'],
            'last_updated_at': session['last_updated_at'],
            'sample_count': agg['sample_count'],
            'aggregations': {
                'avg_cpu_percent': round(agg['avg_cpu_percent'], 1) if agg['avg_cpu_percent'] else 0,
                'max_cpu_percent': agg['max_cpu_percent'] or 0,
                'avg_total_pss_mb': round(agg['avg_total_pss_mb'], 1) if agg['avg_total_pss_mb'] else 0,
                'max_total_pss_mb': agg['max_total_pss_mb'] or 0,
                'avg_native_heap_mb': round(agg['avg_native_heap_mb'], 1) if agg['avg_native_heap_mb'] else 0,
                'max_native_heap_mb': agg['max_native_heap_mb'] or 0,
                'avg_tokens_per_second': round(agg['avg_tokens_per_second'], 1) if agg['avg_tokens_per_second'] else 0,
                'max_tokens_per_second': agg['max_tokens_per_second'] or 0,
                'throttled_samples_count': agg['throttled_samples_count'] or 0
            },
            'history': [{
                'timestamp': s['client_timestamp'],
                'cpu_percent': s['cpu_percent'],
                'total_pss_mb': s['total_pss_mb'],
                'native_heap_mb': s['native_heap_mb'],
                'tokens_per_second': s['tokens_per_second'],
                'gpu_percent': s['gpu_percent'],
                'thermal_status': s['thermal_status']
            } for s in samples]
        })

    def log_message(self, format, *args):
        pass


class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


if __name__ == '__main__':
    init_db()
    httpd = ThreadedHTTPServer(('0.0.0.0', 443), TelemetryHandler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CERT_PATH, KEY_PATH)
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    print('HTTPS server running on port 443 (static + telemetry API)')
    httpd.serve_forever()
