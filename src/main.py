"""
cryptobot is a multithreaded application that uses WebSockets and FIX protocol
to trade crypto on gdax (now Coinbase Pro).

This program was written to explore the world of high-frequency trading with
cryptocurrency rather than to apply a rigorous trading strategy so it isn't
necessarily profitable. A simple market making approach is implemented where
the bot enters on the side of the order book with the most volume at the most
competitive bid and ask prices and it exits on the other side, capturing the
spread. There are two reasons the bot enters on the side with the most volume:
	1.  If the opposite was done, it could be easy for the bot to enter a
		position where the market keeps moving against it and it can't get out
		of it's position.
	2.  This methodology is very straightforward which makes it easier to take
		the focus off of the trading strategy and put more effort on the
		technical problems of managing the order book, managing orders, etc.

There was a lot to learn so the code in this bot was iterated on very quickly
so that it would run without errors. There are better ways to implement this
program (like using min and max heaps to keep track of the most competitive
bid and ask prices, for example) and some of the notable shortcomings are
labeled with a TODO. Shortcuts were purposefully taken so that development
would be quicker and more bugs could be squashed.

Development for cryptobot stopped in approximately May 2018, and as such,
many functionalities are most likely broken.

Requirements:
	Python 3.6
	gdax v1.06
	numpy
	websocket v0.40.0
"""

import threading
import time

from .fix_trader import FIXTrader
from .gdax_account import GDAXAccount
from .load_config import load_api_keys
from .log import Log
from .orderbook_ws import OrderBookWebSocket
from .fix_heartbeat_manager import fix_heartbeat_manager
from .reply_manager import reply_manager
from .strategy_manager import strategy_manager


def main():
	"""
	main function that initializes the data structures and functions necessary
	to communicate with GDAX, handle orders, and log messages.

	Returns:
		None
	"""

	# Load acount information
	api_key, api_secret_key, api_passphrase = load_api_keys()

	# General setup
	logger = Log()
	ob_updated_cond = threading.Condition()

	# Setup trading objects
	account = GDAXAccount(api_key, api_secret_key, api_passphrase, logger)
	orderbook_ws = OrderBookWebSocket(ob_updated_cond, logger)
	orderbook_ws.start()
	fix_trader = FIXTrader(
		api_key, api_secret_key, api_passphrase, account,
		orderbook_ws, ob_updated_cond, logger
	)

	# Give the order book a moment to populate and fix_trader a moment to log on
	time.sleep(1)

	# fix_heartbeat_manager and reply_manager both operate in a separate
	# thread for convenience
	threading.Thread(target=fix_heartbeat_manager, args=(fix_trader,)).start()
	threading.Thread(target=reply_manager, args=(fix_trader, logger)).start()

	# Execute strategy
	strategy_manager(fix_trader, logger)


if __name__ == '__main__':
	main()
