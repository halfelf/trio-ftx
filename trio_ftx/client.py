import time
import urllib.parse
from typing import Optional, Dict, Any, List

import hmac
import httpx

from ciso8601 import parse_datetime
from urllib.parse import urlparse, quote


class FtxClient:
    _ENDPOINT = 'https://ftx.com/api/'

    def __init__(self, api_key=None, api_secret=None, subaccount_name=None) -> None:
        """
        DO NOT USE THIS TO CREATE INSTANCE
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self._subaccount_name = subaccount_name
        self._session: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        self._session = httpx.AsyncClient()
        return self

    async def __aexit__(self, exc_type=None, exc_value=None, traceback=None):
        await self._session.aclose()

    async def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        resp = await self._session.get(self._ENDPOINT + path, params=params)
        return self._process_response(resp)

    async def _get_auth(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        headers = self._generate_headers('GET', path, params=params)
        resp = await self._session.get(self._ENDPOINT + path, params=params, headers=headers)
        return self._process_response(resp)

    async def _post_auth(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        headers = self._generate_headers('POST', path, params=params)
        resp = await self._session.post(self._ENDPOINT + path, params=params, headers=headers)
        return self._process_response(resp)

    async def _delete_auth(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        headers = self._generate_headers('DELETE', path, params=params)
        resp = await self._session.delete(self._ENDPOINT + path, params=params, headers=headers)
        return self._process_response(resp)

    def _generate_headers(self, method: str, path: str, **kwargs) -> Any:
        request = self._session.build_request(method, self._ENDPOINT + path, **kwargs)
        parsed = urlparse(str(request.url))

        ts = int(time.time() * 1000)
        signature_payload = f'{ts}{request.method}{parsed.path}'.encode()
        if request.content:
            signature_payload += request.content
        signature = hmac.new(self._api_secret.encode(), signature_payload, 'sha256').hexdigest()
        headers = {
            'FTX-KEY':  self._api_key,
            'FTX-SIGN': signature,
            'FTX-TS':   str(ts)
        }
        if self._subaccount_name:
            headers['FTX-SUBACCOUNT'] = quote(self._subaccount_name)

        return headers

    def _process_response(self, response: httpx.Response) -> Any:
        try:
            data = response.json()
        except ValueError:
            response.raise_for_status()
            raise
        else:
            if not data['success']:
                raise Exception(data['error'])
            return data['result']

    async def list_futures(self) -> List[dict]:
        return await self._get('futures')

    async def list_markets(self) -> List[dict]:
        # await self._session.get(url, data=, headers=,)
        return await self._get('markets')

    async def get_orderbook(self, market: str, depth: int = None) -> dict:
        return await self._get(f'markets/{market}/orderbook', {'depth': depth})

    async def get_trades(self, market: str) -> dict:
        return await self._get(f'markets/{market}/trades')

    async def get_account_info(self) -> dict:
        return await self._get(f'account')

    async def get_open_orders(self, market: str = None) -> List[dict]:
        return await self._get(f'orders', {'market': market})

    async def get_order_history(self, market: str = None, side: str = None, order_type: str = None,
                                start_time: float = None,
                                end_time: float = None) -> List[dict]:
        return await self._get(f'orders/history',
                               {'market':   market, 'side': side, 'orderType': order_type, 'start_time': start_time,
                                'end_time': end_time})

    async def get_conditional_order_history(self, market: str = None, side: str = None, type: str = None,
                                            order_type: str = None,
                                            start_time: float = None, end_time: float = None) -> List[dict]:
        return await self._get(f'conditional_orders/history',
                               {'market':     market, 'side': side, 'type': type, 'orderType': order_type,
                                'start_time': start_time, 'end_time': end_time})

    async def modify_order(
            self, existing_order_id: Optional[str] = None,
            existing_client_order_id: Optional[str] = None, price: Optional[float] = None,
            size: Optional[float] = None, client_order_id: Optional[str] = None,
    ) -> dict:
        assert (existing_order_id is None) ^ (existing_client_order_id is None), \
            'Must supply exactly one ID for the order to modify'
        assert (price is None) or (size is None), 'Must modify price or size of order'
        path = f'orders/{existing_order_id}/modify' if existing_order_id is not None else \
            f'orders/by_client_id/{existing_client_order_id}/modify'
        return await self._post_auth(path, {
            **({'size': size} if size is not None else {}),
            **({'price': price} if price is not None else {}),
            **({'clientId': client_order_id} if client_order_id is not None else {}),
        })

    async def get_conditional_orders(self, market: str = None) -> List[dict]:
        return await self._get(f'conditional_orders', {'market': market})

    async def place_order(self, market: str, side: str, price: float, size: float, type: str = 'limit',
                          reduce_only: bool = False, ioc: bool = False, post_only: bool = False,
                          client_id: str = None) -> dict:
        return await self._post_auth('orders', {'market':     market,
                                                'side':       side,
                                                'price':      price,
                                                'size':       size,
                                                'type':       type,
                                                'reduceOnly': reduce_only,
                                                'ioc':        ioc,
                                                'postOnly':   post_only,
                                                'clientId':   client_id,
                                                })

    async def place_conditional_order(
            self, market: str, side: str, size: float, type: str = 'stop',
            limit_price: float = None, reduce_only: bool = False, cancel: bool = True,
            trigger_price: float = None, trail_value: float = None
    ) -> dict:
        """
        To send a Stop Market order, set type='stop' and supply a trigger_price
        To send a Stop Limit order, also supply a limit_price
        To send a Take Profit Market order, set type='trailing_stop' and supply a trigger_price
        To send a Trailing Stop order, set type='trailing_stop' and supply a trail_value
        """
        assert type in ('stop', 'take_profit', 'trailing_stop')
        assert type not in ('stop', 'take_profit') or trigger_price is not None, \
            'Need trigger prices for stop losses and take profits'
        assert type not in ('trailing_stop',) or (trigger_price is None and trail_value is not None), \
            'Trailing stops need a trail value and cannot take a trigger price'

        return await self._post_auth('conditional_orders',
                                     {'market':               market, 'side': side, 'triggerPrice': trigger_price,
                                      'size':                 size, 'reduceOnly': reduce_only, 'type': 'stop',
                                      'cancelLimitOnTrigger': cancel, 'orderPrice': limit_price})

    async def cancel_order(self, order_id: str) -> dict:
        return await self._delete_auth(f'orders/{order_id}')

    async def cancel_orders(self, market_name: str = None, conditional_orders: bool = False,
                            limit_orders: bool = False) -> dict:
        return await self._delete_auth(f'orders', {'market':                market_name,
                                                   'conditionalOrdersOnly': conditional_orders,
                                                   'limitOrdersOnly':       limit_orders,
                                                   })

    async def get_fills(self) -> List[dict]:
        return await self._get_auth(f'fills')

    async def get_balances(self) -> List[dict]:
        return await self._get_auth('wallet/balances')

    async def get_deposit_address(self, ticker: str) -> dict:
        return await self._get_auth(f'wallet/deposit_address/{ticker}')

    async def get_positions(self, show_avg_price: bool = False) -> List[dict]:
        return await self._get_auth('positions', {'showAvgPrice': show_avg_price})

    async def get_position(self, name: str, show_avg_price: bool = False) -> dict:
        return next(filter(lambda x: x['future'] == name, await self.get_positions(show_avg_price)), None)

    async def get_all_trades(self, market: str, start_time: float = None, end_time: float = None) -> List:
        ids = set()
        limit = 100
        results = []
        while True:
            response = await self._get(f'markets/{market}/trades', {
                'end_time':   end_time,
                'start_time': start_time,
            })
            deduped_trades = [r for r in response if r['id'] not in ids]
            results.extend(deduped_trades)
            ids |= {r['id'] for r in deduped_trades}
            print(f'Adding {len(response)} trades with end time {end_time}')
            if len(response) == 0:
                break
                #  "time": "2019-03-20T18:16:23.397991+00:00"
            end_time = min(parse_datetime(t['time']) for t in response).timestamp()
            if len(response) < limit:
                break
        return results
