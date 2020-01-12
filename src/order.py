import sys
import threading
import uuid
import queue

from truncate import truncate


class Order:

	def __init__(self, price, size, order_type, fix_trader):
		"""
		Order holds all information needed to make an order and keep tabs
		on the state of that order (for example, when the order is partially
		filled, it'll automatically update how much btc and usd are now in
		the account).
		Runs in a separate thread and listens for messages/updates.

		Parameters:
			price: float
				Price the order should be made at.
			size: float
				Size of the order.
			order_type: string
				'buy' or 'sell' - Indicates which side of the order book
				this order is on.
			fix_trader; FIXTrader
				A copy of fix_trader is kept to access information like
				account, order_tracker, account holdings, etc.
		"""

		self.logger = fix_trader.logger
		self.logger.add('Initializing new Order object')
		self.msgs = queue.Queue()
		self.order_id = None
		self.price = price
		self.size = truncate(size, 8)  # Truncating mitigates precision errors
		self.order_type = order_type
		self.fix_trader = fix_trader
		self.client_order_id = str(uuid.uuid4())
		self.fix_trader.order_tracker.orders_by_cl_oid_lock.acquire()
		self.fix_trader.order_tracker.orders_by_cl_oid[self.client_order_id] = self
		self.fix_trader.order_tracker.orders_by_cl_oid_lock.release()
		self.order_state = None
		self.strategy_state = None
		self.filled_this_msg = 0
		self.cumulative_filled = 0
		self.logger.add('Launching run method of new order object')
		threading.Thread(target=self.run).start()

	def __repr__(self):
		"""
		Pretty print of critical information about this order.

		Returns:
			string
				Formatted information about this order.
		"""
		return \
			f'msgs: {self.msgs}, client_order_id: {self.client_order_id}, ' \
			f'order_id: {self.order_id}, price: {self.price}, ' \
			f'size: {self.size}, order_type: {self.order_type}, ' \
			f'order_state: {self.order_state}, strategy_state: {self.strategy_state}'

	def run(self):
		"""
		Checks on the state of the order and responds accordingly determined
		by whether the order is rejected, open (which includes partially filled),
		fully filled, and if the order should be canceled due to a changes in
		the order book.

		Returns:
			None
		"""
		self.fix_trader.request(
			'order', order_type=self.order_type,
			order_size=self.size, order_price=self.price,
			client_order_id=self.client_order_id
		)

		# Check if order was rejected
		msg = self.msgs.get()

		if 'OrdStatus' in msg and msg['OrdStatus'] == 'Rejected':
			try:
				ord_rej_reason = msg['OrdRejReason']
			except KeyError:
				ord_rej_reason = msg['Text']

			if ord_rej_reason == 'Insufficient funds':
				self.logger.add('Insufficient funds! Updating account holdings')
				# Calculated holdings incorrectly, update over REST
				with self.fix_trader.account.account_lock:
					usd, btc = self.fix_trader.account.get_account_holdings()
					self.fix_trader.account.usd = usd
					self.fix_trader.account.btc = btc

			self.order_destructor()

		self.order_state = 'open'
		self.strategy_state = self.volume_side_strategy()
		while self.order_state == 'open' and self.strategy_state == 'valid':
			# Message related stuff
			try:
				msg = self.msgs.get(block=False)
				self.order_state, self.filled_this_msg = self.figure_order_state(msg)
				self.cumulative_filled += self.filled_this_msg
				self.update_holdings(self.filled_this_msg)

			except queue.Empty:
				pass

			finally:
				# Strategy related stuff
				self.strategy_state = self.volume_side_strategy()

		if self.order_state != 'filled':
			self.fix_trader.request(
				'cancel', order_id=self.order_id,
				client_order_id=self.client_order_id
			)

			while self.order_state != 'filled' and self.order_state != 'canceled':
				# Message related stuff
				try:
					msg = self.msgs.get()
					self.order_state, self.filled_this_msg = self.figure_order_state(msg)
					self.cumulative_filled += self.filled_this_msg
					self.update_holdings(self.filled_this_msg)

				except queue.Empty:
					pass

		self.order_destructor()

	def order_destructor(self):
		"""
		Removes order out of OrderTracker.orders_by_cl_oid as well as
		OrderTrack.orders_by_oid and exits the thread.

		Returns:
			None
		"""
		self.fix_trader.order_tracker.orders_by_cl_oid_lock.acquire()
		del self.fix_trader.order_tracker.orders_by_cl_oid[self.client_order_id]
		self.fix_trader.order_tracker.orders_by_cl_oid_lock.release()

		self.fix_trader.order_tracker.order_by_oid_lock.acquire()
		del self.fix_trader.order_tracker.orders_by_oid[self.order_id]
		self.fix_trader.order_tracker.order_by_oid_lock.release()

		self.logger.add('Exiting Order Thread')
		sys.exit()

	def update_holdings(self, amount_filled):
		"""
		Updates account holdings to reflect order fills.

		Parameters:
			amount_filled: float
				Absolute amount that was filled.

		Returns:
			None
		"""
		if amount_filled > 0:
			with self.fix_trader.account.account_lock:
				usd_change = self.price * amount_filled
				btc_change = amount_filled
				self.logger.add(
					f'Calculated changes: usd change: {usd_change} '
					f'btc change: {btc_change}'
				)
				if self.order_type == 'buy':
					self.fix_trader.account.usd -= usd_change
					self.fix_trader.account.btc += btc_change
				elif self.order_type == 'sell':
					self.fix_trader.account.usd += usd_change
					self.fix_trader.account.btc -= btc_change

	def volume_side_strategy(self):
		"""
		Determines if the order book is in a state where an order is 'valid'
		or 'invalid'. For volume_side_strategy(), this is determined by whether
		the order is made at the most competitive bid or ask price (depending
		on if it's a buy or sell order) and by whether the order is on the side
		of the order book with the most volume at that most competitive price.
		This is used to decide if the order should be canceled since the
		strategy criteria are no longer met.

		Returns:
			out_msg: string
				'valid' or 'invalid'. Whether the
		"""
		self.fix_trader.ob_updated_cond.acquire()
		self.fix_trader.ob_updated_cond.wait()

		if self.order_type == 'buy':
			current_price = self.fix_trader.orderbook_ws.best_buy_price
		else:
			current_price = self.fix_trader.orderbook_ws.best_sell_price

		if self.price != current_price:
			self.logger.add('Order outbid')
			out_msg = 'invalid'
		elif self.fix_trader.orderbook_ws.best_buy_size > self.fix_trader.orderbook_ws.best_sell_size \
				and self.order_type != 'buy':
			self.logger.add('Strategy no longer valid')
			out_msg = 'invalid'
		elif self.fix_trader.orderbook_ws.best_buy_size < self.fix_trader.orderbook_ws.best_sell_size \
				and self.order_type != 'sell':
			self.logger.add('Strategy no longer valid')
			out_msg = 'invalid'
		else:
			out_msg = 'valid'

		self.fix_trader.ob_updated_cond.release()

		return out_msg

	def figure_order_state(self, msg):
		"""
		Determines the state of the order by parsing the input message. Possible
		input states are 'Done for day' (i.e. filled), 'Partially filled'
		(i.e. still open), 'Rejected' or 'Canceled' (i.e. successfully canceled).

		Parameters:
			msg: dict
				Parsed FIX reply message of tag-message pairs.

		Returns:
			order_state: string
				'filled', 'open', 'rejected', or 'canceled'. Simple identifier
				of the current order state.
			amount_filled: float
				Absolute amount of the order that was filled in the message,
				if any.
		"""

		order_state = ''
		amount_filled = 0.0

		if 'OrdStatus' in msg:
			order_status = msg['OrdStatus']
			if order_status == 'Done for day':
				order_state = 'filled'
				amount_filled = self.size - self.cumulative_filled
			elif order_status == 'Partially filled':
				order_state = 'open'
				if 'LastShares' in msg:
					amount_filled = float(msg['LastShares'])
			elif order_status == 'Rejected':
				order_state = 'rejected'
			elif order_status == 'Canceled':
				order_state = 'canceled'
			else:
				order_state = 'open'

		return order_state, amount_filled
