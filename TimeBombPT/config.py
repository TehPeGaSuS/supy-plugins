###
# Copyright (c) 2010, quantumlemur
# Copyright (c) 2020, oddluck <oddluck@riseup.net>
# Copyright (c) 2025, PeGaSuS <droider.pc@gmail.com>
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#   * Redistributions of source code must retain the above copyright notice,
#     this list of conditions, and the following disclaimer.
#   * Redistributions in binary form must reproduce the above copyright notice,
#     this list of conditions, and the following disclaimer in the
#     documentation and/or other materials provided with the distribution.
#   * Neither the name of the author of this software nor the name of
#     contributors to this software may be used to endorse or promote products
#     derived from this software without specific prior written consent.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
###

import supybot.conf as conf
import supybot.registry as registry


def configure(advanced):
    # This will be called by supybot to configure this module.  advanced is
    # a bool that specifies whether the user identified himself as an advanced
    # user or not.  You should effect your configuration by manipulating the
    # registry as appropriate.
    from supybot.questions import expect, anything, something, yn

    conf.registerPlugin("TimeBombPT", True)


TimeBombPT = conf.registerPlugin("TimeBombPT")
# This is where your configuration variables (if any) should go.  For example:
# conf.registerGlobalValue(TimeBombPT, 'someConfigVariableName',
#     registry.Boolean(False, """Help for someConfigVariableName."""))
conf.registerGlobalValue(
    TimeBombPT,
    "colors",
    registry.SpaceSeparatedListOfStrings(
        [
            "Azul",
            "Vermelho",
            "Verde",
            "Amarelo",
            "Laranja",
            "Castanho",
            "Roxo",
            "Rosa",
            "Marrom",
            "Cinza",
            "Preto",
            "Branco",
            "Bege",
            "Dourado",
            "Prateado",
            "Turquesa",
            "Ciano",
            "Magenta",
            "Lilas",
            "Violeta",
            "Bordeaux",
            "Salmao",
            "Mostarda",
            "Lavanda",
            "Ameixa",
            "Caqui",
            "Fucsia",
            "Esmeralda",
            "Oliva",
            "Safira",
            "Indigo",
            "Coral",
            "Pessego",
            "Caramelo",
            "Chocolate",
            "Areia",
            "Granada",
            "Ambar",
            "Petroleo",
            "Terracota",
            "Pardo",
            "Champanhe",
            "Pastel",
            "Ferrugem",
        ],
        """O conjunto de cores possíveis dos fios da bomba-relógio""",
    ),
)


conf.registerGlobalValue(
    TimeBombPT,
    "shortcolors",
    registry.SpaceSeparatedListOfStrings(
        [
            "Vermelho",
            "Laranja",
            "Amarelo",
            "Verde",
            "Azul",
            "Lilas",
            "Rosa",
            "Preto",
            "Castanho",
            "Cinza",
            "Branco",
        ],
        """O conjunto de cores possíveis dos fios da bomba-relógio quando há 
           poucos fios""",
    ),
)

conf.registerChannelValue(
    TimeBombPT,
    "randomExclusions",
    registry.SpaceSeparatedListOfStrings(
        [],
        """Uma lista de nicks que devem ser excluídos do bombardeamento 
           aleatório""",
    ),
)

conf.registerChannelValue(
    TimeBombPT,
    "exclusions",
    registry.SpaceSeparatedListOfStrings(
        [],
        """Uma lista de nicks que devem ser completamente excluídos 
           de serem bombardeados""",
    ),
)

conf.registerChannelValue(
    TimeBombPT,
    "allowBombs",
    registry.Boolean(
        False,
        """Determina se as bombas-relógio são permitidas 
           no canal.""",
    ),
)

conf.registerChannelValue(
    TimeBombPT,
    "bombHistory",
    registry.SpaceSeparatedListOfStrings(
        [], """Carimbos de data/hora, remetentes e vítimas de bombas anteriores no canal"""
    ),
)

conf.registerChannelValue(
    TimeBombPT,
    "rateLimitTime",
    registry.Integer(
        1800,
        """Tempo em segundos durante o qual as bombas anteriores são recordadas 
           e contam para o limite de bombas""",
    ),
)

conf.registerChannelValue(
    TimeBombPT,
    "rateLimitSender",
    registry.Float(
        5.0, """Média de bombas/hora permitidas no passado rateLimitTime de cada anfitrião"""
    ),
)

conf.registerChannelValue(
    TimeBombPT,
    "rateLimitVictim",
    registry.Float(
        3.0,
        """Média de bombas/hora permitidas no passado rateLimitTime visando um determinado nick""",
    ),
)

conf.registerChannelValue(
    TimeBombPT,
    "rateLimitTotal",
    registry.Float(9.0, """Total médio de bombas/hora permitido no passado rateLimitTime"""),
)

conf.registerChannelValue(
    TimeBombPT,
    "minWires",
    registry.PositiveInteger(
        2,
        """Determina o número mínimo de fios que uma bomba-relógio terá.""",
    ),
)

conf.registerChannelValue(
    TimeBombPT,
    "maxWires",
    registry.PositiveInteger(
        4,
        """Determina o número máximo de fios que uma bomba-relógio terá.""",
    ),
)

conf.registerChannelValue(
    TimeBombPT,
    "minTime",
    registry.PositiveInteger(
        45,
        """Determina o tempo mínimo de um temporizador de bomba-relógio, em segundos.""",
    ),
)

conf.registerChannelValue(
    TimeBombPT,
    "maxTime",
    registry.PositiveInteger(
        70,
        """Determina o tempo máximo de um temporizador de bomba-relógio, em segundos.""",
    ),
)

conf.registerChannelValue(
    TimeBombPT,
    "minRandombombTime",
    registry.PositiveInteger(
        60,
        """Determina o tempo mínimo de um temporizador de bomba aleatória, 
           que deve, em geral, ser superior ao tempo mínimo da bomba alvo, 
           para permitir que alguém que não esteja a prestar atenção possa 
           responder.""",
    ),
)

conf.registerChannelValue(
    TimeBombPT,
    "maxRandombombTime",
    registry.PositiveInteger(
        120,
        """Determina o tempo máximo de um temporizador de bomba aleatória, 
           que deve, em geral, ser maior do que o tempo máximo da bomba alvo, 
           para permitir que alguém que não esteja a prestar atenção possa 
           responder.""",
    ),
)

conf.registerChannelValue(
    TimeBombPT,
    "showArt",
    registry.Boolean(
        False,
        """Determina se deve ser mostrada uma bomba de arte ASCII aquando 
           da detonação ou uma simples mensagem.""",
    ),
)

conf.registerChannelValue(
    TimeBombPT,
    "bombActiveUsers",
    registry.Boolean(
        True,
        """Determina se apenas os utilizadores activos devem ser bombardeados 
           aleatoriamente""",
    ),
)

conf.registerChannelValue(
    TimeBombPT,
    "joinIsActivity",
    registry.Boolean(
        False,
        """Determina se as entradas no canal devem contar como atividade para 
           bombas aleatórias""",
    ),
)

conf.registerChannelValue(
    TimeBombPT,
    "allowSelfBombs",
    registry.Boolean(False, """Permitir que o bot se bombardeie a si próprio?"""),
)

conf.registerChannelValue(
    TimeBombPT,
    "idleTime",
    registry.PositiveInteger(
        30,
        """O número de minutos antes de alguém ser contado como inativo para 
           bombas aleatórias, se a verificação de inatividade estiver activada.""",
    ),
)

conf.registerChannelValue(
    TimeBombPT,
    "showCorrectWire",
    registry.Boolean(
        False,
        """Determina se o fio correto será mostrado quando uma bomba detona.""",
    ),
)

conf.registerGlobalValue(
    TimeBombPT,
    "debug",
    registry.Boolean(
        False,
        """Determina se a informação de depuração será mostrada.""",
    ),
)

# vim:set shiftwidth=4 tabstop=4 expandtab textwidth=79:
