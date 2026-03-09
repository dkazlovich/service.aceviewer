# -*- coding: utf-8 -*-
import sys
import socket
import threading
import tempfile
import json
import os
import re
import uuid
import urllib.request
import time
import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs
from http.server import BaseHTTPRequestHandler, HTTPServer


class ThreadedHTTPServer(HTTPServer):
    allow_reuse_address = True


_CACHED_COLOR = None
ADDON = xbmcaddon.Addon()
_window = xbmcgui.Window(10000)
_our_stream = {
    'active': False,
    'title': 'Ace Stream',
    'start_time': 0,
    'stat_url': None,
    'switching': False,
}

_IPV4_RE = re.compile(r'^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$')


def is_valid_lan_ip(ip):
    if not ip:
        return False
    m = _IPV4_RE.match(ip)
    if not m:
        return False
    parts = [int(g) for g in m.groups()]
    if any(p > 255 for p in parts):
        return False
    if parts[0] in (0, 127):
        return False
    return True


def get_local_ip():
    ip = xbmc.getInfoLabel('Network.IPAddress')
    if is_valid_lan_ip(ip):
        return ip
    for _ in range(2):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(2)
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
            s.close()
            if is_valid_lan_ip(ip):
                return ip
        except Exception:
            pass
        time.sleep(0.5)
    return None


def get_ace_config():
    ip = ADDON.getSetting('ace_engine_ip') or '127.0.0.1'
    port = ADDON.getSetting('ace_engine_port') or '6878'
    return f'http://{ip}:{port}', f'{ip}:{port}'.lower()


def get_html_path():
    return os.path.join(
        xbmcvfs.translatePath(ADDON.getAddonInfo('path')),
        'resources', 'web', 'index.html'
    )


def argb_to_hex(val):
    val = val.strip()
    if len(val) == 8:
        result = '#' + val[2:]
    elif val.startswith('#'):
        result = val
    else:
        return None
    return result if re.match(r'^#[0-9a-fA-F]{6}$', result) else None


def get_accent_color():
    global _CACHED_COLOR
    if _CACHED_COLOR:
        return _CACHED_COLOR
    res_color = '#03A9F4'
    try:
        skin_path = xbmcvfs.translatePath('special://skin/')
        guisettings = xbmcvfs.translatePath('special://masterprofile/guisettings.xml')
        theme = None
        if os.path.exists(guisettings):
            with open(guisettings, 'r', encoding='utf-8') as f:
                gs = f.read()
            m = re.search(r'<setting id="lookandfeel.skincolors">([^<]+)</setting>', gs)
            if m:
                theme = m.group(1).strip()
        if not theme:
            theme = xbmc.getInfoLabel('Skin.CurrentTheme')
        check_files = []
        if theme:
            check_files.append(os.path.join(skin_path, 'colors', theme + '.xml'))
        check_files.append(os.path.join(skin_path, 'colors', 'defaults.xml'))
        found = False
        for theme_file in check_files:
            if found:
                break
            if os.path.exists(theme_file):
                with open(theme_file, 'r', encoding='utf-8') as f:
                    data = f.read()
                for name in ['button_focus', 'button', 'ButtonFocus', 'selected']:
                    m = re.search(rf'<color name="{name}"[^>]*>([^<]+)</color>', data)
                    if m:
                        hex_c = argb_to_hex(m.group(1))
                        if hex_c:
                            res_color = hex_c
                            found = True
                            break
    except Exception:
        pass
    _CACHED_COLOR = res_color
    return _CACHED_COLOR


def fetch_ace_title(content_id):
    ace_base, _ = get_ace_config()
    try:
        transfer_id = str(uuid.uuid4())
        encoded_url = urllib.request.quote(f'acestream://{content_id}')
        url = f'{ace_base}/api/v1/upload?transfer_id={transfer_id}&action=analyze&download_url={encoded_url}'
        req = urllib.request.Request(url, method='POST', headers={'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=5) as r:
            result = json.loads(r.read().decode('utf-8'))
            title = result.get('title') or (result.get('data') or {}).get('title')
            return title if title else 'Ace Stream'
    except Exception:
        return 'Ace Stream'


def show_qr_window(ip, port):
    if not is_valid_lan_ip(ip):
        xbmcgui.Dialog().notification(
            'AceViewer', ADDON.getLocalizedString(32012),
            xbmcgui.NOTIFICATION_ERROR, 4000
        )
        return
    xbmc.executebuiltin('ActivateWindow(busydialognocancel)')
    try:
        addon_path = xbmcvfs.translatePath(ADDON.getAddonInfo('path'))
        sys.path.insert(0, addon_path)
        from qrsvg import qr_png
        png_data = qr_png(f'http://{ip}:{port}', scale=20, margin=4)
        tmp = os.path.join(tempfile.gettempdir(), 'aceviewer_qr.png')
        with open(tmp, 'wb') as f:
            f.write(png_data)
        xbmc.executebuiltin('Dialog.Close(busydialognocancel)')

        class QRWindow(xbmcgui.WindowDialog):
            def __init__(self):
                super().__init__()
                sw, sh = self.getWidth(), self.getHeight()
                size = min(sw, sh) - 180
                x = (sw - size) // 2
                y = (sh - size) // 2 - 30
                self.addControl(xbmcgui.ControlImage(x, y, size, size, tmp, aspectRatio=0))
                self.addControl(xbmcgui.ControlLabel(
                    x, y + size + 16, size, 40,
                    f'http://{ip}:{port}',
                    font='font13', textColor='0xFFFFFFFF', alignment=6
                ))
                self.addControl(xbmcgui.ControlLabel(
                    x, y + size + 52, size, 36,
                    ADDON.getLocalizedString(32013),
                    font='font12', textColor='0xFF888888', alignment=6
                ))

            def onAction(self, action):
                self.close()

        w = QRWindow()
        w.doModal()
        del w
        try:
            os.remove(tmp)
        except Exception:
            pass
    except Exception as e:
        xbmc.executebuiltin('Dialog.Close(busydialognocancel)')
        xbmcgui.Dialog().notification('AceViewer', str(e), xbmcgui.NOTIFICATION_ERROR, 4000)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def handle_error(self, request, client_address):
        pass

    def do_GET(self):
        if self.path in ('/', '/index.html'):
            try:
                with open(get_html_path(), 'r', encoding='utf-8') as f:
                    html = f.read().replace('__ACCENT_COLOR__', get_accent_color())
                hostname = xbmc.getInfoLabel('System.FriendlyName') or 'host'
                html = html.replace('__DEVICE_INFO__', hostname)
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(html.encode('utf-8'))
            except Exception as e:
                self.send_error(500, str(e))
        elif self.path == '/show_qr':
            ip = get_local_ip()
            port = xbmcaddon.Addon().getSetting('web_control_port') or '57860'
            threading.Thread(target=show_qr_window, args=(ip, port)).start()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(b'<script>window.close();</script>')
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path != '/command':
            self.send_error(404)
            return
        try:
            length = int(self.headers.get('Content-Length', 0))
            data = json.loads(self.rfile.read(length))
            action = data.get('action')

            if action == 'play':
                cid = data.get('id', '')
                if not cid:
                    self._ok({'status': 'error', 'message': 'no id'})
                    return
                _our_stream['switching'] = True
                _window.clearProperty('aceviewer_abort')
                if xbmc.getCondVisibility('Player.HasMedia'):
                    xbmc.Player().stop()
                title = fetch_ace_title(cid)
                _our_stream.update({
                    'active': True,
                    'title': title,
                    'start_time': time.time(),
                    'stat_url': None,
                    'switching': False,
                })
                url = f'plugin://service.aceviewer/?mode=play&id={cid}&title={urllib.request.quote(title)}'
                xbmc.executebuiltin(f'PlayMedia("{url}",noresume)')
                self._ok({'status': 'ok'})

            elif action == 'stop':
                _our_stream.update({
                    'active': False,
                    'title': 'Ace Stream',
                    'start_time': 0,
                    'stat_url': None,
                    'switching': False,
                })
                _window.clearProperty('aceviewer_stat_url')
                _window.setProperty('aceviewer_abort', '1')
                self._ok({'status': 'ok'})
                try:
                    xbmc.Player().stop()
                except Exception:
                    pass

            elif action == 'status':
                ace_base, ace_host = get_ace_config()
                has_media = xbmc.getCondVisibility('Player.HasMedia')
                curr_path = xbmc.getInfoLabel('Player.FilenameAndPath').lower()
                k_title = xbmc.getInfoLabel('Player.Title')
                is_ace = any(x in curr_path for x in ['service.aceviewer', ace_host, 'acestream'])
                stat_url = _window.getProperty('aceviewer_stat_url')
                stat_data = {}
                if stat_url:
                    try:
                        with urllib.request.urlopen(stat_url, timeout=1) as r:
                            stat_data = json.loads(r.read().decode('utf-8')).get('response') or {}
                    except Exception:
                        pass
                ace_status = stat_data.get('status')
                peers = stat_data.get('peers')
                speed_down = stat_data.get('speed_down')
                speed_up = stat_data.get('speed_up')
                title = k_title if (k_title and k_title != 'Stream') else _our_stream['title']

                if has_media and is_ace and ace_status != 'prebuf':
                    self._ok({'playing': True, 'prebuf': False, 'peers': peers, 'speed_down': speed_down, 'speed_up': speed_up, 'title': title})
                elif stat_url and ace_status == 'prebuf':
                    self._ok({'playing': False, 'prebuf': True, 'peers': peers, 'speed_down': speed_down, 'speed_up': speed_up, 'title': title})
                elif _our_stream.get('switching'):
                    self._ok({'playing': False, 'prebuf': True, 'peers': None, 'speed_down': None, 'speed_up': None, 'title': _our_stream['title']})
                elif has_media and is_ace:
                    self._ok({'playing': True, 'prebuf': False, 'peers': None, 'speed_down': None, 'speed_up': None, 'title': title})
                else:
                    self._ok({'playing': False, 'prebuf': False, 'title': ''})

            else:
                self._ok({'status': 'error', 'message': 'unknown action'})

        except Exception as e:
            self._ok({'status': 'error', 'message': str(e)})

    def _ok(self, data):
        try:
            body = json.dumps(data).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass


server = None


def _start_server(port):
    global server
    try:
        server = ThreadedHTTPServer(('', port), Handler)
        threading.Thread(target=server.serve_forever).start()
    except Exception as e:
        xbmcgui.Dialog().notification('AceViewer', str(e), xbmcgui.NOTIFICATION_ERROR, 4000)


def _stop_server():
    global server
    if server:
        try:
            server.shutdown()
            server.server_close()
        except Exception:
            pass
        server = None


class AceMonitor(xbmc.Monitor):
    def onNotification(self, sender, method, data):
        if sender == 'service.aceviewer' and method == 'Other.show_qr':
            ip = get_local_ip()
            port = xbmcaddon.Addon().getSetting('web_control_port') or '57860'
            threading.Thread(target=show_qr_window, args=(ip, port)).start()

    def onSettingsChanged(self):
        addon = xbmcaddon.Addon()
        is_enabled = addon.getSetting('web_control_enabled').lower() == 'true'
        if not is_enabled:
            _stop_server()
            return
        try:
            new_port = int(addon.getSetting('web_control_port') or 57860)
        except (ValueError, TypeError):
            new_port = 57860
        if not (1024 <= new_port <= 65535):
            new_port = 57860
        if server and server.server_address[1] == new_port:
            return
        _stop_server()
        _start_server(new_port)


if __name__ == '__main__':
    monitor = AceMonitor()
    if ADDON.getSetting('web_control_enabled').lower() == 'true':
        try:
            port = int(ADDON.getSetting('web_control_port') or 57860)
        except (ValueError, TypeError):
            port = 57860
        if not (1024 <= port <= 65535):
            port = 57860
        _start_server(port)

    flag_path = os.path.join(tempfile.gettempdir(), 'aceviewer_show_qr')
    while not monitor.waitForAbort(1):
        if os.path.exists(flag_path):
            try:
                os.remove(flag_path)
            except Exception:
                pass
            ip = get_local_ip()
            port = xbmcaddon.Addon().getSetting('web_control_port') or '57860'
            threading.Thread(target=show_qr_window, args=(ip, port)).start()

    _stop_server()
