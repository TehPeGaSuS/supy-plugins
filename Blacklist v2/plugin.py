import json
import os
import time
import threading
import re
import logging
import urllib.request
import urllib.parse
from supybot.commands import *
from supybot import callbacks, conf, ircmsgs, ircutils, schedule

try:
    from supybot.i18n import PluginInternationalization
    _ = PluginInternationalization('Blacklist')
except ImportError:
    _ = lambda x: x

logger = logging.getLogger('supybot.plugins.Blacklist')

class Blacklist(callbacks.Plugin):
    """Manages channel security with a numbered blacklist and ID-based deletion."""
    
    banmasks = {
        0: '*!ident@host', 1: '*!*ident@host', 2: '*!*@host',
        3: '*!*ident@*.phost', 4: '*!*@*.phost', 5: 'nick!ident@host',
        6: 'nick!*ident@host', 7: 'nick!*@host', 8: 'nick!*ident@*.phost',
        9: 'nick!*@*.phost', 10: '*!ident@*'
    }
    
    threaded = True

    def __init__(self, irc):
        super().__init__(irc)
        self.dbfile = os.path.join(str(conf.supybot.directories.data), 'Blacklist', 'blacklist.json')
        self._db_lock = threading.RLock()
        self.db = {}
        self._initdb()

    def _initdb(self):
        try:
            if not os.path.exists(os.path.dirname(self.dbfile)):
                os.makedirs(os.path.dirname(self.dbfile))
            if os.path.exists(self.dbfile):
                with open(self.dbfile, 'r') as f:
                    self.db = json.load(f)
            else:
                self._dbWrite()
        except Exception as e:
            logger.error(f"Error loading DB: {e}")

    def _dbWrite(self):
        with self._db_lock:
            try:
                with open(self.dbfile, 'w') as f:
                    json.dump(self.db, f, indent=2)
            except Exception as e:
                logger.error(f"Error writing DB: {e}")

    def _createMask(self, irc, target, num):
        if ircutils.isUserHostmask(target): return target
        try:
            hostmask = irc.state.nickToHostmask(target)
            nick, ident, host = ircutils.splitHostmask(hostmask)
            template = self.banmasks.get(num, self.banmasks[2])
            return template.replace("nick", nick).replace("ident", ident).replace("host", host)
        except: return None

    def _createPastebin(self, content):
        """Uploads content to dpaste.com."""
        try:
            api_url = 'https://dpaste.com/api/v2/'
            post_data = {'content': content, 'syntax': 'text', 'expiry_days': 7}
            data = urllib.parse.urlencode(post_data).encode('utf-8')
            req = urllib.request.Request(api_url, data=data, method='POST')
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.read().decode('utf-8').strip() + ".txt"
        except Exception as e:
            logger.error(f"Pastebin upload failed: {e}")
            return "Error: Pastebin service unavailable."
    
    def _internal_add(self, channel, mask, adder, reason, is_bot_cmd=False, expiry_at=None):
        """Grava na DB com a flag is_bot_cmd e o timestamp de expiração."""
        c_lower = channel.lower()
        with self._db_lock:
            if c_lower not in self.db: self.db[c_lower] = {}
            # Agora guardamos 5 elementos: adder, created_at, reason, is_bot_cmd, expiry_at
            self.db[c_lower][mask] = [adder, time.time(), reason, is_bot_cmd, expiry_at]
            self._dbWrite()

    def _internal_del(self, channel, mask):
        """Remove da DB com segurança."""
        c_lower = channel.lower()
        with self._db_lock:
            if c_lower in self.db and mask in self.db[c_lower]:
                del self.db[c_lower][mask]
                if not self.db[c_lower]:
                    del self.db[c_lower]
                self._dbWrite()
                return True
        return False
        
    def _timer_expire(self, irc, channel, mask, remove_from_db=True):
        """Remove o ban do IRC. Remove da DB apenas se remove_from_db for True."""
        if remove_from_db:
            if self._internal_del(channel, mask):
                logger.info(f"Full expiry: {mask} removed from IRC and DB in {channel}")
        else:
            logger.info(f"IRC cleanup: {mask} removed from IRC list but KEPT in bot DB for {channel}")
        
        irc.queueMsg(ircmsgs.unban(channel, mask))

    def bantype(self, irc, msg, args):
        """Lists available mask types."""
        m = [f"({k}) {v}" for k, v in self.banmasks.items()]
        irc.reply(" | ".join(m[0:4]))
        irc.reply(" | ".join(m[4:8]))
        irc.reply(" | ".join(m[8:11]))
    bantype = wrap(bantype, ['admin'])

    def add(self, irc, msg, args, channel, target, reason):
        """[<channel>] <nick|mask> [<reason>]
        Adds a mask to the blacklist (Permanent in DB, temporary +b in IRC).
        """
        mask = self._createMask(irc, target, self.registryValue('maskNumber', channel))
        if not mask:
            irc.error("Could not create hostmask.")
            return
        reason = reason or self.registryValue('banReason', channel)
        
        # Calcula o timestamp de expiração para a DB
        expiry = self.registryValue('banlistExpiry', channel)
        expiry_at = time.time() + (expiry * 60) if expiry > 0 else None
        
        # Grava na DB como bot_cmd=True
        self._internal_add(channel, mask, msg.nick, reason, is_bot_cmd=True)
        irc.queueMsg(ircmsgs.ban(channel, mask))
        
        if not ircutils.isUserHostmask(target) and target in irc.state.channels[channel].users:
            irc.queueMsg(ircmsgs.kick(channel, target, reason))

        # Agenda a limpeza do +b no IRC (usa expiry, e False para manter na DB)
        expiry = self.registryValue('banlistExpiry', channel)
        if expiry > 0:
            schedule.addEvent(self._timer_expire, time.time() + (expiry * 60), 
                             name=f"irc_cleanup_{channel}_{mask}", 
                             args=(irc, channel, mask, False)) 
            
        irc.replySuccess()
    add = wrap(add, [('checkChannelCapability', 'op'), 'channel', 'somethingWithoutSpaces', optional('text')])

    def delete(self, irc, msg, args, channel, target):
        """[<channel>] <mask|ID>
        Removes a mask by its string or its ID number from the list.
        """
        c_lower = channel.lower()
        mask_to_del = None

        if target.isdigit():
            idx = int(target)
            with self._db_lock:
                if c_lower in self.db:
                    masks = list(self.db[c_lower].keys())
                    if 1 <= idx <= len(masks):
                        mask_to_del = masks[idx-1]
                    else:
                        irc.error(f"Invalid ID. Range is 1 to {len(masks)}.")
                        return
        else:
            mask_to_del = target

        if mask_to_del and self._internal_del(channel, mask_to_del):
            irc.queueMsg(ircmsgs.unban(channel, mask_to_del))
            # Tenta remover TODOS os tipos de agendamento possíveis
            for prefix in ['auto_unban', 'irc_cleanup', 'expire']:
                try:
                    schedule.removeEvent(f"{prefix}_{channel}_{mask_to_del}")
                except KeyError:
                    pass
            irc.replySuccess()
        else:
            irc.error(f"Ban not found for: {target}")
    delete = wrap(delete, [('checkChannelCapability', 'op'), 'channel', 'somethingWithoutSpaces'])

    def timer(self, irc, msg, args, channel, target, minutes, reason):
        """[<channel>] <nick|mask> [<minutes>] [<reason>]
        Applies a temporary ban. If minutes are not provided, uses banTimerExpiry.
        """
        mask = self._createMask(irc, target, self.registryValue('maskNumber', channel))
        if not mask:
            irc.error("Could not create hostmask.")
            return

        # Se não deres minutos no IRC, ele vai buscar ao banTimerExpiry
        if minutes is None:
            minutes = self.registryValue('banTimerExpiry', channel)
            if minutes <= 0:
                irc.error("Please specify minutes or set a default banTimerExpiry > 0.")
                return

        # Para a DB guardamos vazio (limpa a list), para o kick usamos o padrão
        db_reason = reason or ""
        kick_reason = reason or "Temporary ban"
        
        expiry_at = time.time() + (minutes * 60)
        
        # is_bot_cmd=True para o timer
        self._internal_add(channel, mask, msg.nick, db_reason, is_bot_cmd=True, expiry_at=expiry_at)
        irc.queueMsg(ircmsgs.ban(channel, mask))
        
        # Kick imediato com a razão (vê "Temporary ban" se não escreveres nada)
        if not ircutils.isUserHostmask(target) and target in irc.state.channels[channel].users:
            irc.queueMsg(ircmsgs.kick(channel, target, kick_reason))
            
        # Agenda a remoção TOTAL (IRC + DB)
        schedule.addEvent(self._timer_expire, expiry_at, 
                         name=f"auto_unban_{channel}_{mask}", 
                         args=(irc, channel, mask, True)) # True = Apaga tudo no fim
        
        irc.reply(f"Ban of {minutes}m scheduled for {mask}.")

    timer = wrap(timer, [('checkChannelCapability', 'op'), 'channel', 'somethingWithoutSpaces', optional('positiveInt'), optional('text')])
        
    def stats(self, irc, msg, args, channel):
        """[<channel>]"""
        c_lower = channel.lower()
        count = len(self.db.get(c_lower, {}))
        irc.reply(f"Channel {channel} has {count} bans in the blacklist.")
    stats = wrap(stats, [('checkChannelCapability', 'op'), 'channel'])

    def list(self, irc, msg, args, channel):
        """[<channel>]
        Lists all blacklisted masks with elapsed and remaining time.
        """
        c_lower = channel.lower()
        if c_lower not in self.db or not self.db[c_lower]:
            irc.reply("List is empty.")
            return

        ban_count = len(self.db[c_lower])
        max_inline = self.registryValue('maxInlineEntries', channel) or 5
        output_list = []
        full_text = f"Numbered Ban List for {channel} ({ban_count} entries):\n" + "="*45 + "\n"
        now = time.time()
        
        for i, (m, data) in enumerate(self.db[c_lower].items(), 1):
            adder = data[0]
            created_at = data[1]
            reason = data[2]
            expiry_at = data[4] if len(data) > 4 else None
            
            elapsed = int(now - created_at) // 60
            remaining_str = ""
            
            if expiry_at:
                rem = int(expiry_at - now) // 60
                if rem > 0:
                    remaining_str = f" [{rem}m left]"
                else:
                    remaining_str = " [expiring...]"
            
            # Lógica de exibição da razão: 
            # Oculta se for vazia, "Temporary ban" ou "*manual ban"
            reason_display = ""
            if reason and reason not in ["Temporary ban", "*manual ban", ""]:
                reason_display = f": {reason}"
            elif reason == "*manual ban":
                reason_display = " [manual]"
            
            entry = f"[{i}] {m} ({elapsed}m ago by {adder}){remaining_str}{reason_display}"
            output_list.append(entry)
            full_text += entry + "\n"

        if ban_count > max_inline:
            url = self._createPastebin(full_text)
            irc.reply(f"Ban list too large ({ban_count} entries). View here: {url}")
        else:
            irc.reply(" | ".join(output_list))
            
    list = wrap(list, [('checkChannelCapability', 'op'), 'channel'])
    
    def kick(self, irc, msg, args, channel, nick, reason):
        """[<channel>] <nick> [<reason>]"""
        if nick not in irc.state.channels[channel].users:
            irc.error(f"{nick} is not in the channel.")
            return
        reason = reason or "Kicked by an operator."
        irc.queueMsg(ircmsgs.kick(channel, nick, reason))
    kick = wrap(kick, [('checkChannelCapability', 'op'), 'channel', 'nick', optional('text')])

    def doMode(self, irc, msg):
        """Sincroniza a DB com bans/unbans manuais no IRC."""
        channel = msg.args[0]
        if len(msg.args) < 3 or ircutils.strEqual(msg.nick, irc.nick): 
            return
            
        mode_change, mask = msg.args[1], msg.args[2]
        c_lower = channel.lower()

        if mode_change == '+b':
            with self._db_lock:
                exists = c_lower in self.db and mask in self.db[c_lower]
            
            if not exists:
                expiry = self.registryValue('banlistExpiry', channel)
                expiry_at = time.time() + (expiry * 60) if expiry > 0 else None
                
                self._internal_add(channel, mask, msg.nick, "*manual ban", is_bot_cmd=False, expiry_at=expiry_at)
                if expiry > 0:
                    schedule.addEvent(self._timer_expire, expiry_at, 
                                     name=f"expire_{channel}_{mask}", 
                                     args=(irc, channel, mask, True))
        
        elif mode_change == '-b':
            with self._db_lock:
                entry = self.db.get(c_lower, {}).get(mask)
                
            if entry:
                # Verificamos se foi um comando do bot (índice 3 na lista)
                # Se for bot_cmd=True, NÃO apagamos da DB, apenas paramos os timers
                is_bot_cmd = entry[3] if len(entry) > 3 else False
                
                if not is_bot_cmd:
                    self._internal_del(channel, mask)
                    logger.info(f"Manual unban: {mask} removed from DB (was manual ban)")
                else:
                    logger.info(f"Manual unban: {mask} kept in DB (is bot blacklist entry)")

            # Limpamos os timers de qualquer forma para não dar erro depois
            for prefix in ['auto_unban', 'irc_cleanup', 'expire']:
                try:
                    schedule.removeEvent(f"{prefix}_{channel}_{mask}")
                except KeyError:
                    pass

    def doJoin(self, irc, msg):
        if ircutils.strEqual(msg.nick, irc.nick): return
        channel = msg.args[0]
        c_lower = channel.lower()
        enabled = self.registryValue('enabled', channel)
        if enabled and c_lower in self.db:
            for mask in self.db[c_lower]:
                if ircutils.hostmaskPatternEqual(mask, msg.prefix):
                    reason = self.db[c_lower][mask][2]
                    irc.queueMsg(ircmsgs.ban(channel, mask))
                    irc.queueMsg(ircmsgs.kick(channel, msg.nick, reason))
                    break

Class = Blacklist