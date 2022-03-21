from __future__ import annotations  # compatibility for py <3.10

import hmac
import time
import warnings

import json
from typing import Dict, Tuple

import trio
import trio_websocket

from ftx.client import FtxClient


# class BinanceSocketType(str, Enum):
#     SPOT = 'Spot'
#     USD_M_FUTURES = 'USD_M_Futures'
#     COIN_M_FUTURES = 'Coin_M_Futures'
#     OPTIONS = 'Vanilla_Options'
#     ACCOUNT = 'Account'


class FtxStreamManager:
    STREAM_URL = 'wss://ftx.com/ws/'

    def __init__(self, client):
        """
        DO NOT USE THIS TO CREATE INSTANCE
        """
        self.client: FtxClient = client
        self.futures_conn = None
        self.futures_coin_conn = None
        self.spot_conn = None

        self.commands_send_chan: trio.MemorySendChannel
        self.commands_recv_chan: trio.MemoryReceiveChannel
        self.commands_send_chan, self.commands_recv_chan = trio.open_memory_channel(100)

        self.msg_channels: Dict[Tuple, Tuple[trio.MemorySendChannel, trio.MemoryReceiveChannel]] = {}
        # self.msg_send_chan, self.msg_recv_chan = trio.open_memory_channel(0)
        self.logged_in = trio.Event()

    async def __aenter__(self):
        return self

    async def __aexit__(self):
        pass

    async def _get_message(self, conn: trio_websocket.WebSocketConnection, task_status=trio.TASK_STATUS_IGNORED):
        task_status.started()
        while True:
            message = await conn.get_message()
            await self._on_message(message)

    async def run(self):
        async with trio_websocket.open_websocket_url(self.STREAM_URL) as conn:
            async with trio.open_nursery() as nursery:
                await nursery.start(self._check_command, conn)
                await nursery.start(self.heartbeat, conn, 60, 15)
                await nursery.start(self._get_message, conn)
                if self.client.api_key and self.client.api_secret:
                    # authentication
                    await self.authentication(conn)

    async def _check_command(self, conn: trio_websocket.WebSocketConnection, task_status=trio.TASK_STATUS_IGNORED):
        task_status.started()
        async for request in self.commands_recv_chan:
            # print(request)
            await conn.send_message(json.dumps(request))
        # print('check end')

    async def authentication(self, conn: trio_websocket.WebSocketConnection):
        ts = int(time.time() * 1000)
        req = {
            'op':   'login',
            'args': {
                'key':  self.client.api_key,
                'sign': hmac.new(
                        self.client.api_secret.encode(), f'{ts}websocket_login'.encode(), 'sha256').hexdigest(),
                'time': ts,
            }
        }
        await conn.send_message(json.dumps(req))
        await trio.sleep(1)

    async def subscribe(self, channel: str, market: str = '') -> None:
        req = {'op': 'subscribe', 'channel': channel}
        if market:
            req['market'] = market
        await self.commands_send_chan.send(req)
        self.msg_channels[(channel, market)] = trio.open_memory_channel(1000)

    async def unsubscribe(self, channel: str, market: str) -> None:
        req = {'op': 'unsubscribe', 'channel': channel}
        if market:
            req['market'] = market
        await self.commands_send_chan.send(req)

    @staticmethod
    async def heartbeat(conn: trio_websocket.WebSocketConnection, timeout: int, interval: int,
                        task_status=trio.TASK_STATUS_IGNORED):
        task_status.started()
        while True:
            with trio.fail_after(timeout):
                await conn.ping()
            await trio.sleep(interval)

    async def _on_message(self, message):
        msg = json.loads(message)
        typ = msg.get('type')
        print(msg)
        if typ == 'subscribed':
            pass
        elif typ == 'update':
            channel, market = msg.get('channel'), msg.get('market', '')
            await self.msg_channels[(channel, market)][0].send(msg)
        elif typ == 'pong':
            # logging.debug('pong')
            pass
        elif typ == 'unsubscribed':
            self.msg_channels.pop((msg.get('channel'), msg.get('market')))
        elif typ == 'error':
            warnings.warn(f"error message: {msg}")
        else:
            warnings.warn(f"unclassified message: {msg}")

    async def get_message(self, channel: str, market: str = ''):
        chan = self.msg_channels[(channel, market)][1]
        async for msg in chan:
            yield msg
