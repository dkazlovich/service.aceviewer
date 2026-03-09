# -*- coding: utf-8 -*-
import sys
import os
import json
import tempfile
import urllib.parse
import urllib.request
import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin

ADDON = xbmcaddon.Addon()
_window = xbmcgui.Window(10000)


def get_ace_base():
    ip = ADDON.getSetting('ace_engine_ip') or '127.0.0.1'
    port = ADDON.getSetting('ace_engine_port') or '6878'
    return f'http://{ip}:{port}'


def play_stream(content_id, match_title):
    xbmc.PlayList(xbmc.PLAYLIST_VIDEO).clear()
    _window.clearProperty('aceviewer_abort')
    ace_base = get_ace_base()
    session_url = f'{ace_base}/ace/getstream?id={content_id}&format=json'
    try:
        with urllib.request.urlopen(session_url, timeout=10) as resp:
            session = json.loads(resp.read().decode('utf-8'))
        data = session.get('response')
        if not data:
            xbmcgui.Dialog().notification('AceViewer', ADDON.getLocalizedString(32016), xbmcgui.NOTIFICATION_ERROR, 3000)
            xbmcplugin.setResolvedUrl(addon_handle, False, xbmcgui.ListItem())
            return
        if session.get('error'):
            xbmcgui.Dialog().notification('AceViewer', ADDON.getLocalizedString(32017) % session.get('error'), xbmcgui.NOTIFICATION_ERROR, 3000)
            xbmcplugin.setResolvedUrl(addon_handle, False, xbmcgui.ListItem())
            return
        playback_url = data['playback_url']
        stat_url = data['stat_url']
        command_url = data['command_url']
        _window.setProperty('aceviewer_stat_url', stat_url)
    except TimeoutError:
        xbmcgui.Dialog().notification('AceViewer', ADDON.getLocalizedString(32018), xbmcgui.NOTIFICATION_ERROR, 3000)
        xbmcplugin.setResolvedUrl(addon_handle, False, xbmcgui.ListItem())
        return
    except Exception:
        xbmcgui.Dialog().notification('AceViewer', ADDON.getLocalizedString(32019), xbmcgui.NOTIFICATION_ERROR, 3000)
        xbmcplugin.setResolvedUrl(addon_handle, False, xbmcgui.ListItem())
        return

    monitor = xbmc.Monitor()
    ready = False
    for _ in range(60):
        if monitor.abortRequested() or _window.getProperty('aceviewer_abort') == '1':
            _window.clearProperty('aceviewer_abort')
            xbmcplugin.setResolvedUrl(addon_handle, False, xbmcgui.ListItem())
            return
        try:
            with urllib.request.urlopen(stat_url, timeout=5) as resp:
                stat = json.loads(resp.read().decode('utf-8'))
            if stat.get('response', {}).get('status') == 'dl':
                ready = True
                break
        except Exception:
            pass
        xbmc.sleep(1000)

    if not ready:
        xbmcgui.Dialog().notification('AceViewer', ADDON.getLocalizedString(32018), xbmcgui.NOTIFICATION_ERROR, 3000)
        xbmcplugin.setResolvedUrl(addon_handle, False, xbmcgui.ListItem())
        return

    li = xbmcgui.ListItem(path=playback_url)
    li.setContentLookup(False)
    li.getVideoInfoTag().setTitle(match_title)
    xbmcplugin.setResolvedUrl(addon_handle, True, li)

    player = xbmc.Player()
    for _ in range(150):
        if player.isPlaying() or monitor.abortRequested():
            break
        xbmc.sleep(200)
    else:
        xbmcgui.Dialog().notification('AceViewer', ADDON.getLocalizedString(32018), xbmcgui.NOTIFICATION_ERROR, 3000)
        try:
            urllib.request.urlopen(f'{command_url}?method=stop', timeout=2)
        except Exception:
            pass
        _window.clearProperty('aceviewer_stat_url')
        return
    while player.isPlaying() and not monitor.abortRequested():
        if monitor.waitForAbort(1):
            break

    try:
        urllib.request.urlopen(f'{command_url}?method=stop', timeout=2)
    except Exception:
        pass
    _window.clearProperty('aceviewer_stat_url')


if __name__ == '__main__':
    addon_handle = int(sys.argv[1])
    params = urllib.parse.parse_qs(sys.argv[2][1:] if len(sys.argv) > 2 else '')
    mode = params.get('mode', [None])[0]
    if mode == 'play':
        play_stream(params['id'][0], params.get('title', ['Ace Stream'])[0])
    else:
        flag_path = os.path.join(tempfile.gettempdir(), 'aceviewer_show_qr')
        with open(flag_path, 'w'):
            pass
        xbmcplugin.endOfDirectory(addon_handle, succeeded=False)
