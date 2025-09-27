# Copyright (c) 2022, Mike Oxlong
# V1.02 - Improved version with better error handling, thread safety, and security
###


import json
import os
import time
import threading
import re
import json, os, time, threading, re
import random
import string
import urllib.request
import urllib.parse
import logging
from contextlib import contextmanager

from supybot.commands import *
from supybot import callbacks, conf, ircmsgs, ircutils, schedule

try:
    from supybot.i18n import PluginInternationalization
    _ = PluginInternationalization('Blacklist')
except ImportError:
    # Placeholder that allows to run the plugin on a bot
    # without the i18n module
    _ = lambda x: x

# Set up logging
logger = logging.getLogger('supybot.plugins.Blacklist')

class Blacklist(callbacks.Plugin):
    """A custom ban tracking plugin to keep a channel's banlist cleaner"""
    
    banmasks = {
        0: '*!ident@host',
        1: '*!*ident@host',
        2: '*!*@host',
        3: '*!*ident@*.phost',
        4: '*!*@*.phost',
        5: 'nick!ident@host',
        6: 'nick!*ident@host',
        7: 'nick!*@host',
        8: 'nick!*ident@*.phost',
        9: 'nick!*@*.phost',
        10: '*!ident@*'
    }
    
    threaded = True
    
    def __init__(self, irc):
        super().__init__(irc)  # Python 3 style super()
        self.dbfile = os.path.join(str(conf.supybot.directories.data), 'Blacklist', 'blacklist.json')
        self._db_lock = threading.RLock()
        self.db = {}
        self._initdb()
    
    def _initdb(self):
        """Initialize database with proper error handling"""
        try:
            if os.path.exists(self.dbfile):
                with open(self.dbfile, 'r') as f:
                    self.db = json.load(f)
                logger.info(f"Loaded blacklist database with {sum(len(channel_bans) for channel_bans in self.db.values())} total bans")
            else:
                self.db = {}
                self._dbWrite()
        except (IOError, json.JSONDecodeError) as e:
            logger.error(f"Failed to load blacklist database: {e}")
            self.db = {}
            # Create backup of corrupted file
            if os.path.exists(self.dbfile):
                backup = f"{self.dbfile}.backup.{int(time.time())}"
                os.rename(self.dbfile, backup)
                logger.warning(f"Backed up corrupted database to {backup}")
    
    @contextmanager
    def _get_db(self):
        """Thread-safe context manager for database access"""
        with self._db_lock:
            yield self.db
    
    def _dbWrite(self):
        """Thread-safe database write with atomic file operation"""
        def write_thread():
            with self._db_lock:
                try:
                    os.makedirs(os.path.dirname(self.dbfile), exist_ok=True)
                    # Write to temporary file first, then rename (atomic operation)
                    temp_file = f"{self.dbfile}.tmp.{os.getpid()}"
                    with open(temp_file, 'w') as f:
                        json.dump(self.db, f, indent=2)  # Pretty print
                    os.replace(temp_file, self.dbfile)  # Atomic replace
                    logger.debug("Database written successfully")
                except Exception as e:
                    logger.error(f"Failed to write database: {e}")
        
        threading.Thread(target=write_thread, daemon=True).start()
    
    def _validate_mask(self, mask):
        """Validate hostmask format"""
        if not mask or not isinstance(mask, str):
            return False
        
        # Basic hostmask pattern validation
        pattern = r'^[^!@]+![^@]+@.+$'
        return re.match(pattern, mask) is not None
    
    def _elapsed(self, inp):
        """Convert timestamp to human-readable time elapsed"""
        lapsed = int(time.time() - inp)
        periods = [
            (31536000, 'y'),  # year
            (2592000, 'mo'),  # month
            (604800, 'w'),    # week
            (86400, 'd'),     # day
            (3600, 'h'),      # hour
            (60, 'm'),        # minute
            (1, 's')          # second
        ]
        
        for seconds, unit in periods:
            if lapsed >= seconds:
                return f'{int(lapsed/seconds)}{unit}'
        return '0s'
        lapsed = int(time.time()-inp)
        L = (1, 60, 3600, 86400, 604800, 2592000, 31536000)
        T = ('s', 'm', 'h', 'd', 'w', 'mo')
        for l, t in zip(L, T):
            if lapsed < L[L.index(l)+1]:
                return f'{int(lapsed/l)}{t}'
        return f'{int(lapsed/60/60/24/365)}y'
    
    def _createPastebin(self, content):
        """Create a paste on pastebin.net using the official API"""
        try:
            # Pastebin API parameters
            api_dev_key = self.registryValue("pastebinapikey")
            api_paste_code = content
            api_paste_private = '1'  # 0=public, 1=unlisted, 2=private
            api_paste_name = 'Ban List Export'
            api_paste_expire_date = 'N'  # Never expiration
            api_paste_format = 'text'
            
            # Prepare the POST data
            post_data = {
                'api_dev_key': api_dev_key,
                'api_paste_code': api_paste_code,
                'api_paste_private': api_paste_private,
                'api_paste_name': api_paste_name,
                'api_paste_expire_date': api_paste_expire_date,
                'api_paste_format': api_paste_format,
                'api_option': 'paste'
            }
            
            # Encode the data
            encoded_data = urllib.parse.urlencode(post_data).encode('utf-8')
            
            # Make the request
            request = urllib.request.Request('https://pastebin.com/api/api_post.php', data=encoded_data)
            response = urllib.request.urlopen(request)
            
            # Get the response URL
            result = response.read().decode('utf-8')
            
            # Check if the response is a valid URL
            if result.startswith('https://pastebin.com/'):
                # Convert to raw URL format
                paste_id = result.split('/')[-1]
                raw_url = f'https://pastebin.com/raw/{paste_id}'
                return raw_url
            else:
                return f"Error: {result}"
                
        except Exception as e:
            return f"Error creating pastebin: {str(e)}"
    
    def _createMask(self, irc, target, num):
        """Create ban mask with validation"""
        try:
            nick, ident, host = ircutils.splitHostmask(irc.state.nickToHostmask(target))
            
            # Validate components
            if not all([nick, ident, host]):
                raise ValueError("Invalid hostmask components")
            
            mask_template = self.banmasks.get(num, self.banmasks[2])
            
            # Create the mask - only escape nick and host, not ident
            mask = mask_template.replace("nick", re.escape(nick)) \
                            .replace("ident", ident) \
                            .replace("host", re.escape(host)) \
                            .replace("phost", re.escape(host.split(".", 1)[1]) if "." in host else re.escape(host))
            
            if not self._validate_mask(mask):
                raise ValueError("Generated invalid mask")
                
            return mask
        except Exception as e:
            logger.error(f"Error creating mask for {target}: {e}")
            raise
    
    def _createPastebin(self, content):
        """Improved pastebin creation with retry logic"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                api_dev_key = self.registryValue("pastebinapikey")
                if not api_dev_key:
                    return "Error: Pastebin API key not configured"
                
                post_data = {
                    'api_dev_key': api_dev_key,
                    'api_paste_code': content,
                    'api_paste_private': '1',
                    'api_paste_name': 'Ban List Export',
                    'api_paste_expire_date': '1W',  # 1 week expiration
                    'api_paste_format': 'text',
                    'api_option': 'paste'
                }
                
                encoded_data = urllib.parse.urlencode(post_data).encode('utf-8')
                request = urllib.request.Request(
                    'https://pastebin.com/api/api_post.php',
                    data=encoded_data,
                    headers={'User-Agent': 'Supybot-Blacklist-Plugin/1.0'}
                )
                
                with urllib.request.urlopen(request, timeout=30) as response:
                    result = response.read().decode('utf-8')
                
                if result.startswith('https://pastebin.com/'):
                    paste_id = result.split('/')[-1]
                    return f'https://pastebin.com/raw/{paste_id}'
                else:
                    if attempt == max_retries - 1:  # Last attempt
                        return f"Error: {result}"
                    time.sleep(2 ** attempt)  # Exponential backoff
                    
            except Exception as e:
                if attempt == max_retries - 1:
                    return f"Error creating pastebin: {str(e)}"
                time.sleep(2 ** attempt)
        
        return "Error: Max retries exceeded"
    
    def _remove_from_db(self, channel, mask):
        """Thread-safe removal from database"""
        with self._get_db() as db:
            if channel in db and mask in db[channel]:
                del db[channel][mask]
                if not db[channel]:  # Remove empty channel
                    del db[channel]
                self._dbWrite()
                logger.info(f"Removed {mask} from {channel} database")

    def doMode(self, irc, msg):
        """Handle mode changes (bans)"""
        try:
            if (msg.args[1:] and msg.args[1] == '+b' and 
                not ircutils.hostmaskPatternEqual(msg.prefix, irc.prefix) and 
                self.registryValue('addManualBans', msg.args[0]) and 
                irc.state.channels[msg.args[0]].isHalfopPlus(irc.nick) and 
                not ircutils.strEqual(msg.nick, irc.nick)):
                
                channel = msg.args[0]
                mask = msg.args[2]
                
                with self._get_db() as db:
                    if channel not in db or mask not in db[channel]:
                        if channel not in db:
                            db[channel] = {}
                        db[channel][mask] = [msg.nick, time.time(), '*user-added ban']
                        self._dbWrite()
                        irc.reply(f'"{mask}" added to the banlist for {channel}.')
                        logger.info(f"Added manual ban {mask} in {channel} by {msg.nick}")
        except Exception as e:
            logger.error(f"Error in doMode: {e}")

    def doJoin(self, irc, msg):
        """Handle user joins and apply bans"""
        try:
            channel = msg.args[0]
            if (self.registryValue('enabled', channel) and 
                irc.state.channels[channel].isHalfopPlus(irc.nick) and 
                not ircutils.strEqual(msg.nick, irc.nick) and 
                channel in self.db):
                
                with self._get_db() as db:
                    for mask, (adder, timestamp, reason) in db[channel].items():
                        if ircutils.hostmaskPatternEqual(mask, msg.prefix):
                            irc.queueMsg(ircmsgs.ban(channel, mask))
                            irc.queueMsg(ircmsgs.kick(channel, msg.nick, reason))
                            
                            expiry_time = self.registryValue('banlistExpiry', channel) * 60
                            event_name = f'bl_unban_{channel}_{hash(mask)}'
                            
                            # Remove any existing event to avoid duplicates
                            try:
                                schedule.removeEvent(event_name)
                            except KeyError:
                                pass
                            
                            schedule.addEvent(
                                lambda: irc.queueMsg(ircmsgs.unban(channel, mask)),
                                time.time() + expiry_time,
                                event_name
                            )
                            logger.info(f"Applied ban {mask} to {msg.nick} in {channel}")
                            break
        except Exception as e:
            logger.error(f"Error in doJoin: {e}")

    def add(self, irc, msg, args, channel, target, reason):
        """[<channel>] <nick|mask> [<reason>]
        
        Add <nick|hostmask> to blacklist database (requires #channel,op capability)"""
        self._ban(irc, msg, args, channel, target, None, reason)
    add = wrap(add, [('checkChannelCapability', 'op'), 'channel',
                     'somethingWithoutSpaces', optional('text')])

    def timer(self, irc, msg, args, channel, target, timer, reason):
        """[<channel>] <nick|mask> [<expiry>] [<reason>]
        
        Add <nick|hostmask> to blacklist database, expiry is given in minutes (requires #channel,op capability)"""
        if not timer:
            timer = self.registryValue('banTimerExpiry', channel)
        self._ban(irc, msg, args, channel, target, timer, reason)
    timer = wrap(timer, [('checkChannelCapability', 'op'), 'channel',
                         'somethingWithoutSpaces', optional('PositiveInt'),
                         optional('text')])
   def kick(self, irc, msg, args, channel, target, reason):
        """[<channel>] <nick> [<reason>]
        
        Kick a user from the channel without adding to blacklist (requires #channel,op capability)"""
        self._kick(irc, msg, args, channel, target, reason)
    kick = wrap(kick, [('checkChannelCapability', 'op'), 'channel',
                      'somethingWithoutSpaces', optional('text')])

    def _kick(self, irc, msg, args, channel, target, reason):
        """Internal method to handle kicking users"""
        # Validation checks
        checks = [
            (self.registryValue('enabled', channel), f'Database is disabled in {channel}.'),
            (irc.state.channels[channel].isHalfopPlus(irc.nick), f'I have no powers in {channel}.'),
            (channel in irc.state.channels, f'I\'m not in {channel}.'),
        ]
        
        for condition, error_msg in checks:
            if not condition:
                irc.error(error_msg)
                return
    
    def _kick(self, irc, msg, args, channel, target, reason):
        """Internal method to handle kicking users"""
        if not self.registryValue('enabled', channel):
            irc.error(f'Database is disabled in {channel}.')
            return
        if not irc.state.channels[channel].isHalfopPlus(irc.nick):
            irc.error(f'I have no powers in {channel}.')
            return
        if channel not in irc.state.channels:
            irc.error(f'I\'m not in {channel}.')
            return
        
        # Only allow nicknames for kick command (not hostmasks)
        if not irc.isNick(target):
            irc.error(f'Invalid nick: {target}')
            return
            
        if ircutils.strEqual(target, irc.nick):
            irc.error('You want me to kick myself?!')
            return
            
        if target not in irc.state.channels[channel].users:
            irc.error(f'"{target}" is not in {channel}.')
            return
        
        if not reason:
            reason = self.registryValue('kickReason', channel)
        
        # Kick the user
        irc.queueMsg(ircmsgs.kick(channel, target, reason))
        irc.reply(f'"{target}" has been kicked from {channel}.')
    
    def _ban(self, irc, msg, args, channel, target, timer, reason):
        if not self.registryValue('enabled', channel):
            irc.error(f'Database is disabled in {channel}.')
            return
            
        if ircutils.strEqual(target, irc.nick):
            irc.error('You want me to kick myself?!')
            return
            
        if target not in irc.state.channels[channel].users:
            irc.error(f'"{target}" is not in {channel}.')
            return
        
        if not reason:
            reason = self.registryValue('kickReason', channel)
        
        # Kick the user
        irc.queueMsg(ircmsgs.kick(channel, target, reason))
        irc.reply(f'"{target}" has been kicked from {channel}.')
        logger.info(f"Kicked {target} from {channel} by {msg.nick}")

    def _ban(self, irc, msg, args, channel, target, timer, reason):
        """Improved ban method with better validation"""
        # Validation checks
        checks = [
            (self.registryValue('enabled', channel), f'Database is disabled in {channel}.'),
            (irc.state.channels[channel].isHalfopPlus(irc.nick), f'I have no powers in {channel}.'),
            (channel in irc.state.channels, f'I\'m not in {channel}.'),
        ]
        
        for condition, error_msg in checks:
            if not condition:
                irc.error(error_msg)
                return
        
        # Process target
        if ircutils.isUserHostmask(target):
            if ircutils.hostmaskPatternEqual(target, irc.prefix):
                irc.error('Cannot blacklist myself!')
                return
            mask = target
        elif irc.isNick(target):
            if ircutils.strEqual(target, irc.nick):
                irc.error('Cannot blacklist myself!')
                return
            if target not in irc.state.channels[channel].users:
                irc.error(f'"{target}" is not in {channel}.')
                return
            try:
                mask_num = self.registryValue('maskNumber', channel)
                if mask_num not in self.banmasks:
                    mask_num = 2  # Default to *!*@host
                    logger.warning(f"Invalid maskNumber for {channel}, using default")
                mask = self._createMask(irc, target, mask_num)
            except Exception as e:
                irc.error(f'Error creating ban mask: {e}')
                return
        else:
            irc.error('Invalid nick or banmask.')
            return
        
        # Check if already banned
        if mask in irc.state.channels[channel].bans:
            irc.error(f'"{mask}" is already banned in {channel}.')
            return
        
        # Set default reason
        if not reason:
            reason = self.registryValue('banReason', channel)
        
        # Update database
        with self._get_db() as db:
            if channel not in db:
                db[channel] = {}
            db[channel][mask] = [msg.nick, int(time.time()), reason]
        
        self._dbWrite()
        
        # Apply ban and kick matching users
        irc.queueMsg(ircmsgs.ban(channel, mask))
        
        for nick in irc.state.channels[channel].users:
            if ircutils.hostmaskPatternEqual(mask, irc.state.nickToHostmask(nick)):
                irc.queueMsg(ircmsgs.kick(channel, nick, reason))
        
        # Schedule unban
        expiry_time = timer * 60 if timer else self.registryValue('banlistExpiry', channel) * 60
        event_name = f'bl_unban_{channel}_{hash(mask)}'
        
        # Remove any existing event to avoid duplicates
        try:
            schedule.removeEvent(event_name)
        except KeyError:
            pass
        
        schedule.addEvent(
            lambda: irc.queueMsg(ircmsgs.unban(channel, mask)),
            time.time() + expiry_time,
            event_name
        )
        
        # Schedule database cleanup if timer is set
        if timer:
            db_event_name = f'bl_db_unban_{channel}_{hash(mask)}'
            try:
                schedule.removeEvent(db_event_name)
            except KeyError:
                pass
            
            schedule.addEvent(
                self._remove_from_db,
                time.time() + (timer * 60),
                args=(channel, mask),
                name=db_event_name
            )
        
        irc.reply(f'"{mask}" added to banlist for {channel}.')
        logger.info(f"Added ban {mask} in {channel} by {msg.nick}")

    def remove(self, irc, msg, args, channel, mask):
        """[<channel>] <mask>
        
        Remove a mask from the blacklist database (requires #channel,op capability)"""
        if channel not in irc.state.channels:
            irc.error(f'I\'m not in {channel}.')
            return
        
        with self._get_db() as db:
            if channel not in db or mask not in db[channel]:
                irc.error(f'"{mask}" is not in my banlist for {channel}.')
                return
            
            # Remove scheduled events
            event_names = [
                f'bl_unban_{channel}_{hash(mask)}',
                f'bl_db_unban_{channel}_{hash(mask)}'
            ]
            
            for event_name in event_names:
                try:
                    schedule.removeEvent(event_name)
                except KeyError:
                    pass
            
            # Remove ban from channel if present
            if mask in irc.state.channels[channel].bans:
                irc.queueMsg(ircmsgs.unban(channel, mask))
            
            # Remove from database
            del db[channel][mask]
            if not db[channel]:  # Remove empty channel
                del db[channel]
            self._dbWrite()
        
        irc.reply(f'"{mask}" removed from the banlist in {channel}.')
        logger.info(f"Removed ban {mask} from {channel} by {msg.nick}")
    
    remove = wrap(remove, [('checkChannelCapability', 'op'), 'channel', 'text'])

    def list(self, irc, msg, args, channel):
        """[<channel>]
        Returns a list of banmasks stored in <channel> (requires #channel,op capability)"""
        with self._get_db() as db:
            if channel not in db:
                irc.reply(f'The banlist for {channel} is currently empty.')
                return
            
            ban_count = len(db[channel])
            
            # Get the maximum inline entries from configuration
            max_inline = self.registryValue('maxInlineEntries', channel)
            if max_inline is None:  # Fallback if not set
                max_inline = 5
            
            # Use pastebin for large lists (more than maxInlineEntries entries)
            if ban_count > max_inline:
                # Create formatted content for pastebin
                content = f"Ban List for {channel} - {ban_count} entries\n"
                content += "=" * 60 + "\n\n"
                
                for banmask, (adder, timestamp, reason) in db[channel].items():
                    elapsed = self._elapsed(timestamp)
                    content += f"Mask: {banmask}\n"
                    content += f"Added by: {adder} ({elapsed} ago)\n"
                    content += f"Reason: {reason}\n"
                    content += "-" * 40 + "\n"
                
                # Create pastebin URL
                pastebin_url = self._createPastebin(content)
                if pastebin_url.startswith('https://'):
                    irc.reply(f"Ban list too large ({ban_count} entries). View at: {pastebin_url}")
                else:
                    # Fallback to regular display if pastebin fails
                    irc.reply(f"Pastebin failed: {pastebin_url}. Displaying first {max_inline} entries:")
                    self._display_ban_list(irc, channel, db[channel], limit=max_inline)
            else:
                self._display_ban_list(irc, channel, db[channel])
    
        if channel not in self.db:
            irc.reply(f'The banlist for {channel} is currently empty.')
            return
        
        # FOR TESTING: Change 5 to 0 to trigger pastebin for any number of entries
        # In production, you'd use: if len(self.db[channel]) > 5:
        if len(self.db[channel]) > 5:  # Changed to 0 for testing with 1 entry

            # Create formatted content for pastebin
            content = f"Ban List for {channel}\n"
            content += "=" * 50 + "\n\n"
            
            for banmask, v in self.db[channel].items():
                elapsed = self._elapsed(v[1])
                content += f"{banmask} - Added by {v[0]} {elapsed} ago (reason: {v[2]})\n"
            
            # Create pastebin URL
            pastebin_url = self._createPastebin(content)
            irc.reply(f"Ban list too large ({len(self.db[channel])} entries). View at: {pastebin_url}")
        else:
            # Original behavior for 5 or fewer entries
            padwidth = len(max((mask for mask in self.db[channel])))
            for banmask, v in self.db[channel].items():
                elapsed = self._elapsed(v[1])
                irc.reply(f'{banmask.ljust(padwidth, " ")} - Added by {v[0]} {elapsed} ago (reason: {v[2]})')
    list = wrap(list, [('checkChannelCapability', 'op'), 'channel'])
    
    def _display_ban_list(self, irc, channel, bans, limit=None):
        """Display ban list in channel"""
        ban_list = list(bans.items())
        if limit:
            ban_list = ban_list[:limit]
            if len(bans) > limit:
                irc.reply(f"Showing first {limit} of {len(bans)} entries:")
        
        for banmask, (adder, timestamp, reason) in ban_list:
            elapsed = self._elapsed(timestamp)
            irc.reply(f'{banmask} - Added by {adder} {elapsed} ago (reason: {reason})')

    def cleanup(self, irc, msg, args, channel):
        """[<channel>] - Clean up expired bans from database"""
        with self._get_db() as db:
            if channel not in db:
                irc.reply(f'No bans found for {channel}.')
                return
            
            expired = []
            current_time = time.time()
            expiry_duration = self.registryValue('banlistExpiry', channel) * 60
            
            for mask, (adder, timestamp, reason) in list(db[channel].items()):
                if current_time - timestamp > expiry_duration:
                    expired.append(mask)
                    del db[channel][mask]
            
            if expired:
                self._dbWrite()
                irc.reply(f'Removed {len(expired)} expired bans from {channel}.')
                logger.info(f"Cleaned up {len(expired)} expired bans from {channel}")
            else:
                irc.reply(f'No expired bans found in {channel}.')
    
    cleanup = wrap(cleanup, [('checkChannelCapability', 'op'), 'channel'])

    def stats(self, irc, msg, args, channel):
        """[<channel>] - Show ban statistics"""
        with self._get_db() as db:
            if channel not in db:
                irc.reply(f'No bans found for {channel}.')
                return
            
            total_bans = len(db[channel])
            if total_bans == 0:
                irc.reply(f'No bans found for {channel}.')
                return
            
            timestamps = [v[1] for v in db[channel].values()]
            oldest = min(timestamps)
            newest = max(timestamps)
            
            irc.reply(f'Bans in {channel}: {total_bans} total, '
                     f'oldest: {self._elapsed(oldest)} ago, '
                     f'newest: {self._elapsed(newest)} ago')
    
    stats = wrap(stats, [('checkChannelCapability', 'op'), 'channel'])

Class = Blacklist

# vim:set shiftwidth=4 softtabstop=4 expandtab textwidth=79:
