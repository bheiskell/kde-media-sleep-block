#!/usr/bin/env python3
import logging
import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

class MediaMonitor:
    def __init__(self, logger=logging.getLogger(__name__)):
        self.logger = logger

        self.cookie = None
        self.playing_players = set()

        self.bus = dbus.SessionBus()
        bus_obj = self.bus.get_object('org.freedesktop.DBus', '/org/freedesktop/DBus')
        self.bus_iface = dbus.Interface(bus_obj, 'org.freedesktop.DBus')


    def start(self):
        self.logger.info("Starting MediaMonitor")

        loop = GLib.MainLoop()

        self.bus_iface.connect_to_signal('NameOwnerChanged', self._name_owner_changed)
        self._check_existing_players()

        try:
            loop.run()
        except Exception as e:
            self.logger.error(f"Error in main loop: {str(e)}")
            if self.cookie:
                self._allow_suspend()

    def _name_owner_changed(self, name, old_owner, new_owner):
        """
        Monitor for a different media player taking control.
        """
        if not name.startswith('org.mpris.MediaPlayer2.'):
            return

        if new_owner:
            self.logger.info(f"New player detected: {name}")
            self._add_player(name)
        else:
            self.logger.info(f"Player removed: {name}")
            self._remove_player(name)

    def _check_existing_players(self):
        """
        Handle case when players are already running before the script starts.
        """
        self.logger.debug("Checking for existing players")
        for service in self.bus_iface.ListNames():
            if service.startswith('org.mpris.MediaPlayer2.'):
                self.logger.info(f"Found existing player: {service}")
                self._add_player(service)

    def _add_player(self, service):
        """
        Track a media player.
        """
        player = self.bus.get_object(service, '/org/mpris/MediaPlayer2')
        props = dbus.Interface(player, 'org.freedesktop.DBus.Properties')

        props.connect_to_signal('PropertiesChanged', 
                              lambda *args: self._properties_changed(service, *args))

        try:
            status = props.Get('org.mpris.MediaPlayer2.Player', 'PlaybackStatus')
            if status == 'Playing':
                self.logger.info(f"Player {service} is playing")
                self.playing_players.add(service)
                self._update_inhibit()
        except:
            pass

    def _remove_player(self, service):
        """
        Stop tracking a media player.
        """
        if service in self.playing_players:
            self.playing_players.remove(service)
            self._update_inhibit()

    def _properties_changed(self, service, interface, changed, invalidated):
        """
        Handle changes to the playback status.
        """
        if interface != 'org.mpris.MediaPlayer2.Player':
            return
        if not 'PlaybackStatus' in changed:
            return

        if changed['PlaybackStatus'] == 'Playing':
            self.playing_players.add(service)
        else:
            self.playing_players.discard(service)
        self._update_inhibit()

    def _player_names(self):
        player_names = []
        for service in self.playing_players:
            try:
                player = self.bus.get_object(service, '/org/mpris/MediaPlayer2')
                props = dbus.Interface(player, 'org.freedesktop.DBus.Properties')
                identity = props.Get('org.mpris.MediaPlayer2', 'Identity')
                player_names.append(str(identity))
            except Exception as e:
                self.logger.warning(f"Could not get player name for {player}: {str(e)}")
                player_names.append(player.replace('org.mpris.MediaPlayer2.', ''))
        return player_names

    def _update_inhibit(self):
        """
        Handle updates to actually inhibit (or uninhibit) sleep.
        """
        if self.playing_players:
            self._prevent_suspend()
        else:
            self._allow_suspend()

    def _prevent_suspend(self):
        if self.cookie:
            self._allow_suspend()

        player_names = ', '.join(self._player_names())
        message = f'{player_names} is currently playing'
        self.logger.info(f"Preventing suspend for players: {player_names}")

        screensaver = self.bus.get_object('org.freedesktop.ScreenSaver', '/ScreenSaver')
        inhibit = screensaver.get_dbus_method('Inhibit', 'org.freedesktop.ScreenSaver')
        self.cookie = inhibit('Media Player Monitor', message)

    def _allow_suspend(self):
        if not self.cookie:
            return

        self.logger.info("Allowing suspend")
        screensaver = self.bus.get_object('org.freedesktop.ScreenSaver', '/ScreenSaver')
        uninhibit = screensaver.get_dbus_method('UnInhibit', 'org.freedesktop.ScreenSaver')
        uninhibit(self.cookie)
        self.cookie = None

if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
    )
    DBusGMainLoop(set_as_default=True)
    MediaMonitor().start()
