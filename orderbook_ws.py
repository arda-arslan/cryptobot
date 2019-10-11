import json

import gdax
import numpy as np
import websocket


class OrderBookWebSocket(gdax.WebsocketClient):

	def __init__(
			self, ob_updated_cond, logger,
			order_book_products=['BTC-USD'], ignore_cutoff=.01):
		"""
		Processes order book messages coming from the web socket.

		TODO Change order book data structure from array to heap
		Arrays aren't a great data structure for insertions but were used
		for simplicity and quick development. Changing self.ob_buys and
		self.ob_sells to use a heap (since only the most competitive bid and
		ask prices matter for a spread-capturing algorithm) would allow
		for O(1) lookups for the most competitive bid and ask prices, just like
		arrays,	but also offer O(log n) insertions vs O(n) for arrays.

		Parameters:
			ob_updated_cond: threading.Condition
				Stops race conditions when order book is being updated and used
				to notify threads when a new 'best' price is seen
			logger: Log
				Used to log messages as needed.
			order_book_products: list
				Name(s) of pair(s) to subscribe to.
				Note: Only ['BTC-USD'] is currently supported.
			ignore_cutoff: float
				The % cutoff for orders to ignore when replicating the
				order book.
				e.g. ignore_cutoff = .01 means only orders within 1% of
				the recently traded price will be placed in the order book.
				This helps keep the order book small and speedy.
		"""

		super(OrderBookWebSocket, self).__init__(
			products=order_book_products
		)
		self.logger = logger
		self.ob_updated_cond = ob_updated_cond
		# Ping GDAX to get initial values for order book, best prices and sizes
		# and recent prices
		# We rebuild these values from the order book snapshot we receive as
		# the first message in our websocket subscription
		self.ob_buys, self.ob_sells = self.setup_order_books()
		self.best_buy_price = self.ob_buys[-1, 0]
		self.best_buy_size = self.ob_buys[-1, 1]
		self.best_sell_price = self.ob_sells[0, 0]
		self.best_sell_size = self.ob_sells[0, 1]
		self.ignore_cutoff = ignore_cutoff
		self.ignore_cutoff_lower = 1 - self.ignore_cutoff
		self.ignore_cutoff_upper = 1 + self.ignore_cutoff
		# Assume the recently traded price is the average of the bid and ask
		# (We just need a number to start with before the official numbers
		#  come in through the WebSocket)
		self.recent_price = (self.best_buy_price + self.best_sell_price) / 2
		self.recent_price_lower = self.ignore_cutoff_lower * self.recent_price
		self.recent_price_upper = self.ignore_cutoff_upper * self.recent_price

	def setup_order_books(self):
		"""
		Grabs the 50 most competitive bids and asks via REST call through the
		public GDAX client to get the bids and asks order books populated.

		Returns:
			ob_buys: numpy.ndarray
				Array of arrays of length 2 which contain price in the 0th
				index and size in the 1st index. Sorted from lowest to
				highest price so the most competitive buy price is the
				last element.
			ob_sells: numpy.ndarray
				Array of arrays of length 2 which contain price in the 0th
				index and size in the 1st index. Sorted from lowest to
				highest price so the most competitive sell price is the
				first element.
		"""

		# Ping for the top 50 bids and asks to get the order book populated
		# pinged_order_book is a list of lists of length 3
		# [<price>, <size>, <# of people who have an order at this price>]
		public_client = gdax.PublicClient()
		pinged_order_book = public_client.get_product_order_book(
			'BTC-USD', level=2
		)

		# Trim off the number of people who have an order at a given price
		ob_buys = np.array(
			[np.float64(item[:2]) for item in pinged_order_book['bids']]
		)
		ob_sells = np.array(
			[np.float64(item[:2]) for item in pinged_order_book['asks']]
		)

		# Sort by price in ascending order
		ob_buys.sort(axis=0)
		ob_sells.sort(axis=0)

		return ob_buys, ob_sells

	def _connect(self):
		"""
		Overwrites _connect method of gdax.WebsocketClient for more
		customized websocket messages.

		Returns:
			None
		"""

		if self.products is None:
			self.products = ["BTC-USD"]
		elif not isinstance(self.products, list):
			self.products = [self.products]

		if self.url[-1] == "/":
			self.url = self.url[:-1]

		self.ws = websocket.create_connection(self.url)
		self.stop = False

		sub_params = {
			"type": "subscribe",
			"product_ids": self.products,
			"channels": ['level2']
		}
		self.ws.send(json.dumps(sub_params))

		# sub_params = {'type': 'subscribe', 'product_ids': self.products}
		# self.ws.send(json.dumps(sub_params))
		if self.type == "heartbeat":
			sub_params = {"type": "heartbeat", "on": True}
			self.ws.send(json.dumps(sub_params))

	def on_message(self, msg):
		"""
		Overwrites on_message method of gdax.WebsocketClient for more
		advanced message handling.
		Updates order book to reflect current market and notifies any
		outstanding orders to determine whether they should exit their
		position given this new market information.

		Parameters:
			msg: dict
				Holds updated information about the new state of the order
				book at a given price.

		Returns:
			None
		"""

		# Update book if there are coins to be traded at the price
		# Drop row if there are no more coins to be traded at that price
		# to keep the order book small for efficiency
		self.ob_updated_cond.acquire()
		old_best_buy_price = self.best_buy_price
		old_best_buy_size = self.best_buy_size
		old_best_sell_price = self.best_sell_price
		old_best_sell_size = self.best_sell_size

		try:
			if 'changes' in msg:
				info = msg['changes'][0]
				side = info[0]
				price = np.float64(info[1])
				size = np.float64(info[2])
				if size != 0:
					if self.recent_price_lower < price < self.recent_price_upper:
						# Update order_book
						new = np.array([[price, size]], dtype=np.float64)
						if side == 'buy':
							# Note that we have to drop the old price or else
							# we have multiples of the same prices and the
							# order sizes are inaccurate
							self.ob_buys = self.ob_buys[
								self.ob_buys[:, 0] != price]
							insert_ind = self.ob_buys[:, 0].searchsorted(price)
							self.ob_buys = np.concatenate(
								(self.ob_buys[:insert_ind], new, self.ob_buys[insert_ind:])
							)
						else:
							self.ob_sells = self.ob_sells[
								self.ob_sells[:, 0] != price]
							insert_ind = self.ob_sells[:, 0].searchsorted(price)
							self.ob_sells = np.concatenate(
								(self.ob_sells[:insert_ind], new, self.ob_sells[insert_ind:])
							)
				else:
					# Remove row with that price (might exist, might not)
					# Nothing changes if it doesn't exist in the ob
					if side == 'buy':
						self.ob_buys = self.ob_buys[self.ob_buys[:, 0] != price]
					else:
						self.ob_sells = self.ob_sells[self.ob_sells[:, 0] != price]

				# Limit the size of order book to 50 to keep array operations
				# speedy
				if side == 'buy':
					# Best buy prices are in the last X rows of the order book
					self.ob_buys = self.ob_buys[-50:]
				else:
					# Best sell prices are in the first X rows of the order book
					self.ob_sells = self.ob_sells[:50]

				# Update the best bid and ask prices here so that when we see
				# opportunity, we already have the buy/sell at numbers crunched
				if side == 'buy':
					self.best_buy_price = self.ob_buys[-1, 0]
					self.best_buy_size = self.ob_buys[-1, 1]
				else:
					self.best_sell_price = self.ob_sells[0, 0]
					self.best_sell_size = self.ob_sells[0, 1]

				# Update recent price to determine cutoffs for accepting msgs
				self.recent_price = (self.best_buy_price + self.best_sell_price) / 2
				self.recent_price_lower = self.ignore_cutoff_lower * self.recent_price
				self.recent_price_upper = self.ignore_cutoff_upper * self.recent_price

			elif 'bids' in msg:
				if msg['type'] == 'snapshot':
					# This is the first message, build our order books
					# Going to take the first 50 to keep the initialization simple
					self.ob_buys = np.array(msg['bids'][:50], dtype=np.float64)
					self.ob_sells = np.array(msg['asks'][:50], dtype=np.float64)

					# Order the order books from lowest price to highest price so
					# the best buy price is the last element and best sell price
					# is the first element
					self.ob_buys.sort(axis=0)
					self.ob_sells.sort(axis=0)

					# Initialize best price and size variables
					self.best_buy_price = self.ob_buys[-1, 0]
					self.best_buy_size = self.ob_buys[-1, 1]
					self.best_sell_price = self.ob_sells[0, 0]
					self.best_sell_size = self.ob_sells[0, 1]

					# Initialize recent prices and bounds for adding incoming
					# values into our order book
					self.recent_price = (self.best_buy_price + self.best_sell_price) / 2
					self.recent_price_lower = self.ignore_cutoff_lower * self.recent_price
					self.recent_price_upper = self.ignore_cutoff_upper * self.recent_price

		except KeyError:
			pass

		notify = False
		try:
			if side == 'buy':
				if old_best_buy_price != self.best_buy_price or old_best_buy_size != self.best_buy_size:
					notify = True
			else:
				if old_best_sell_price != self.best_sell_price or old_best_sell_size != self.best_sell_size:
					notify = True
		except NameError:
			self.logger.add('NameError in on_message')

		if notify:
			self.ob_updated_cond.notify_all()

		self.ob_updated_cond.release()
