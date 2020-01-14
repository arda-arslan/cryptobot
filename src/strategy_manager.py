from .truncate import truncate


def strategy_manager(fix_trader, logger, gdax_min_trade_size_btc=.001):
	"""
	Determines whether to enter a position by checking if there are any
	outstanding orders. If not, it creates an order on the side with more
	orders and attempts to capture the spread between the bid and ask prices.

	TODO: make strategy_manager() run only if the order book updates
	Currently, if the order book is updated and the update moves the
	most competitive bid or ask price, ob_updated_cond is notified and
	outstanding orders check if they should be canceled given this new info.
	Updating strategy_manager() to run on this notification would make
	cryptobot more event-driven and fit in with the way existing orders
	handle order book updates.

	Parameters:
		fix_trader: FIXTrader
			Used to pull account holding information, to know whether there
			are any outstanding orders as well as making a new order if
			the market conditions are right as determined by the strategy.
		logger: Log
			Used to log messages as needed.
		gdax_min_trade_size_btc: float
			Ensures that the GDAX minimum bitcoin trade size criteria is met
			before attempting to place an order.

	Returns:
		None
	"""

	while True:
		with fix_trader.account.account_lock:

			if fix_trader.order_tracker.orders_by_cl_oid:
				order_exists = True
			else:
				order_exists = False

			if order_exists:
				# Not in the order-making "hot path"
				# It's OK to print anything in the log queue
				logger.flush()
				# The code following continue only applies if there are no
				# outstanding orders
				continue

			usd_holding, btc_holding = fix_trader.account.usd, fix_trader.account.btc
			usd_holding_truncated = truncate(usd_holding, 2)
			btc_holding_truncated = truncate(btc_holding, 8)

			recent_price = fix_trader.orderbook_ws.recent_price
			best_buy_size = fix_trader.orderbook_ws.best_buy_size
			best_sell_size = fix_trader.orderbook_ws.best_sell_size

			if best_buy_size > best_sell_size:
				strategy = 'buy'
			else:
				strategy = 'sell'

			if strategy == 'buy':
				min_trade_usd = gdax_min_trade_size_btc * recent_price
				if usd_holding > min_trade_usd:
					message = \
						f'Entering Strategy: Buy, Holdings: ${usd_holding_truncated}, ' \
						f'BTC: {btc_holding_truncated} ' \
						f'Buy Side Size: {best_buy_size} ' \
						f'Sell Side Size {best_sell_size}'
					logger.add(message)
					fix_trader.organize_order('buy')
			elif strategy == 'sell':
				if btc_holding > gdax_min_trade_size_btc:
					message = \
						f'Entering Strategy: Sell, Holdings: ${usd_holding_truncated}, ' \
						f'BTC: {btc_holding_truncated} ' \
						f'Buy Side Size: {best_buy_size} ' \
						f'Sell Side Size {best_sell_size}'
					logger.add(message)
					fix_trader.organize_order('sell')
