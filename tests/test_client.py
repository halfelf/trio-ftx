from trio_ftx.client import FtxClient
from trio_ftx.streams import FtxStreamManager
import trio


async def test_rest_client():
    async with trio.open_nursery() as nursery:
        async with FtxClient() as client:
            futures = await client.list_futures()
            assert isinstance(futures, list)
            assert len(futures) > 0
            for fut in futures:
                if fut.get('perpetual'):
                    assert fut.get('type') == 'perpetual'
                else:
                    assert fut.get('type') in {'future', 'move', 'prediction'}


async def test_websocket_pub():
    with trio.move_on_after(10):
        async with trio.open_nursery() as nursery:
            async with FtxClient() as client:
                stream_manager = FtxStreamManager(client)
                nursery.start_soon(stream_manager.run)

                channel, market = 'ticker', 'BTC-PERP'
                await stream_manager.subscribe(channel=channel, market=market)
                async for ticker_message in stream_manager.get_message(channel=channel, market=market):
                    assert ticker_message.get('channel') == channel
                    assert ticker_message.get('market') == market
                    assert isinstance(ticker_message.get('data').get('bid'), float)
                    assert isinstance(ticker_message.get('data').get('bidSize'), float)


async def test_websocket_private(request):
    api_key = request.config.getoption('api')
    secret_key = request.config.getoption('secret')
    with trio.move_on_after(100):
        async with trio.open_nursery() as nursery:
            async with FtxClient(api_key, secret_key) as client:
                stream_manager = FtxStreamManager(client)
                nursery.start_soon(stream_manager.run)

                await trio.sleep(5)

                channel = 'orders'
                await stream_manager.subscribe(channel=channel)
                async for order_message in stream_manager.get_message(channel=channel):
                    print(order_message)
