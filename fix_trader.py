import base64
import datetime as dt
import hashlib
import hmac
import itertools
import json
import socket
import time
import uuid

from order import Order
from order_tracker import OrderTracker


class FIXTrader:

	def __init__(
			self, api_key, api_secret_key, api_passphrase, account,
			orderbook_ws, ob_updated_cond, logger):
		"""
		FIXTrader handles messages sent to GDAX through the FIX connection.
		On receiving an organize_order() method call, it creates an Order
		object which performs message handling for itself.

		Parameters:
			api_key: string
				32 character string representing the account's api key.
			api_secret_key: string
				88 character string representing the account's api secret key.
			api_passphrase: string
				11 character string representing the account's api passphrase.
			account: GDAXAccount
				Used to access usd and bitcoin in account so that orders can
				be sized appropriately.
			orderbook_ws: OrderBookWebSocket
				Used to access the prices and sizes at the most competitive
				prices for both asks and bids.
			ob_updated_cond: threading.Condition
				Passed to Order objects FIXTrader spawns so that they can check
				whether to cancel themselves if the order book has moved
				against their strategy.
			logger: Log
				Used to log messages as needed.
		"""

		self.logger = logger
		self.api_key = api_key
		self.api_secret_key = api_secret_key
		self.api_passphrase = api_passphrase
		self.account = account
		self.orderbook_ws = orderbook_ws
		self.ob_updated_cond = ob_updated_cond
		self.order_tracker = OrderTracker()
		self.seq_num = itertools.count(0)
		self.fix_socket = self.create_fix_socket()
		# \u0001 is the unicode field separator for FIX on Python 3
		# Must specify as unicode with u'\u0001' on Python 2
		self.separator = '\u0001'
		self.last_send_msg_time = time.time()
		self.order_id = None
		self.order_ids = []
		self.client_order_id = None
		self.client_order_ids = []
		self.order_status = None
		self.order_made = False
		self.order_type = None
		self.order_price = None
		self.order_size = None
		self.qty_filled = 0

		# Some dicts to help parse FIX message meanings
		with open('fix_msgs/fix_tag_field_pairs.json') as f:
			self.fix_tag_field_pairs = json.load(f)
		with open('fix_msgs/exec_trans_type_20.json') as f:
			self.exec_trans_type_20 = json.load(f)
		with open('fix_msgs/handl_inst_21.json') as f:
			self.handl_inst_21 = json.load(f)
		with open('fix_msgs/msg_type_35.json') as f:
			self.msg_type_35 = json.load(f)
		with open('fix_msgs/ord_status_39.json') as f:
			self.ord_status_39 = json.load(f)
		with open('fix_msgs/ord_type_40.json') as f:
			self.ord_type_40 = json.load(f)
		with open('fix_msgs/side_54.json') as f:
			self.side_54 = json.load(f)
		with open('fix_msgs/time_in_force_59.json') as f:
			self.time_in_force_59 = json.load(f)
		with open('fix_msgs/encrypt_method_98.json') as f:
			self.encrypt_method_98 = json.load(f)
		with open('fix_msgs/cxl_rej_reason_102.json') as f:
			self.cxl_rej_reason_102 = json.load(f)
		with open('fix_msgs/cxl_rej_reason_103.json') as f:
			self.ord_rej_reason_103 = json.load(f)
		with open('fix_msgs/ord_rej_reason_150.json') as f:
			self.exec_type_150 = json.load(f)
		with open('fix_msgs/aggressor_indicator_1057.json') as f:
			self.aggressor_indicator_1057 = json.load(f)
		self.request('logon')

	def create_fix_socket(self):
		"""
		Establishes a socket to communicate over.

		Returns:
			fix_socket: socket.socket
				The socket all FIX communications will transfer over.
		"""

		fix_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		fix_socket.connect(("127.0.0.1", 4197))

		return fix_socket

	def fix_check_sum(self, msg):
		"""
		All FIX messages must include a checksum. fix_check_sum() calculates
		this check sum to GDAX's specifications.

		Parameters:
			msg: string
				Message that the check sum is based off of.

		Returns:
			check_sum: int
				Check sum based off the input msg.
		"""

		check_sum = 0

		for char in msg:
			check_sum += ord(char)
		check_sum = str(check_sum % 256)
		while len(check_sum) < 3:
			check_sum = '0' + check_sum

		return check_sum

	def organize_order(self, order_type):
		"""
		Calculates the size of an order and the price to enter at based on
		order_type and creates an Order object which enters that position.

		Parameters:
			order_type: string
				'buy' or 'sell'. Denotes which side of the order book the
				position will be on. Also used to determine what price to
				enter at.

		Returns:
			None
		"""

		# Get pricing details necessary for trade
		if order_type == 'buy':
			order_price = self.orderbook_ws.best_buy_price
		else:
			order_price = self.orderbook_ws.best_sell_price

		# Update holdings to determine size of order we can make
		# Trade with 99.5% of (calculated) holdings to minimize
		# insufficient funds messages
		usd_trading = self.account.usd * .995
		btc_trading = self.account.btc * .995
		if order_type == 'buy':
			order_size = usd_trading / order_price
		else:
			order_size = btc_trading

		new_order = Order(
			order_price, order_size, order_type, self
		)

		message = f'Made {order_type} order'
		self.logger.add(message)

	def send_msg(self, msg):
		"""
		Sends the input msg to GDAX via the FIX socket. Also updates
		last_send_msg_time to the current time.

		Parameters:
			msg: bytes
				Ascii encoded message to be sent to GDAX via FIX.

		Returns:
			None
		"""

		# Send message
		self.fix_socket.sendall(msg)
		# Update time of last send
		self.last_send_msg_time = time.time()

	def request(
			self, request_type=None, order_type=None, order_size=None,
			order_price=None, client_order_id=None, order_id=None):
		"""
		Creates the appropriate message to send given request_type, sends the
		message off and logs.

		Parameters:
			request_type: string
				'logon', 'order', 'cancel' or 'heartbeat'. Represents the
				kind of request to make.
			order_type: string
				'buy' or 'sell'. Denotes which side of the order book the
				position will be on.
			order_size: float
				Size of the order.
			order_price: float
				Price the order should be made at.
			client_order_id: string
				Randomly generated uuid4 in string format that uniquely
				identifies an order.
			order_id: string
				Similar to client_order_id in that it identifies an order,
				but order_id is assigned by GDAX (as opposed to us like in the
				case of client_order_id)

		Returns:
			None
		"""

		seq_num = next(self.seq_num)

		msg = ''
		if request_type == 'logon':
			msg = self.create_logon_msg(seq_num)
		elif request_type == 'order':
			msg = self.create_order_msg(
				order_type, order_size, order_price, client_order_id, seq_num
			)
		elif request_type == 'cancel':
			msg = self.create_cancel_msg(order_id, client_order_id, seq_num)
		elif request_type == 'heartbeat':
			msg = self.create_heartbeat_msg(seq_num)

		self.logger.add(f'{request_type} msg: {self.analyze_fix_msg(msg)}')

		self.send_msg(msg)

	def finalize_msg(self, msg_type, msg_body):
		"""
		Adds fields, like the header and check sum, that FIX expects in every
		message.

		Parameters:
			msg_type: string
				FIX-specific denoter of the type of message being sent.
			msg_body: string
				The "body" of the message containing information specific to
				the method that called finalize_msg

		Returns:
			msg: bytes
				Ascii encoded message with the fields FIX expects in all
				messages.
		"""

		# msg_body_len is the number of characters (not bytes)
		# It must include everything after "8=FIX.4.2|9={}|" i.e. the "35=A|"
		# part of the header
		msg_body_len = len(f'35={msg_type}|') + len(msg_body)
		msg_header = f'8=FIX.4.2|9={msg_body_len}|35={msg_type}|'
		msg = msg_header + msg_body
		msg = msg.replace('|', self.separator)

		check_sum = self.fix_check_sum(msg)
		msg = msg + f'10={check_sum}' + self.separator
		msg = msg.encode('ascii')

		return msg

	def create_logon_msg(self, seq_num):
		"""
		Formats a FIX logon message.

		Parameters:
			seq_num: int
				Sequence identifier for FIX message.

		Returns:
			msg: bytes
				Ascii encoded FIX logon message.
		"""

		msg_type = 'A'

		fix_time_str = str(
			dt.datetime.utcnow()).replace("-", "").replace(" ", "-")[:-3]
		signature_msg = self.separator.join([
			fix_time_str, msg_type, str(seq_num),
			self.api_key, 'Coinbase', self.api_passphrase
		]).encode('utf-8')

		hmac_key = base64.b64decode(self.api_secret_key)
		signature = hmac.new(hmac_key, signature_msg, hashlib.sha256)
		signature_base64 = base64.b64encode(signature.digest()).decode()

		msg_body = \
			f'34={seq_num}|49={self.api_key}|52={fix_time_str}|56=Coinbase|' \
			f'96={signature_base64}|98=0|108=30|554={self.api_passphrase}|8013=Y|'

		msg = self.finalize_msg(msg_type, msg_body)

		return msg

	def create_order_msg(
			self, order_type, order_size, order_price, client_order_id,
			seq_num):
		"""
		Formats a FIX new order message.

		Parameters:
			order_type: string
				'buy' or 'sell' - Indicates which side of the order book
				this order is on.
			order_size: float
				Size of the order
			order_price: float
				Price to enter order at.
			client_order_id: string
				Randomly generated uuid4 in string format that uniquely
				identifies an order.
			seq_num: int
				Sequence identifier for FIX message.

		Returns:
			msg: bytes
				Ascii encoded FIX new order message.
		"""

		msg_type = 'D'

		fix_time_str = str(dt.datetime.utcnow()).replace("-", "").replace(" ", "-")[:-3]
		if order_type == 'buy':
			side = '1'
		else:
			side = '2'
		msg_body = \
			f'21=1|11={client_order_id}|55=BTC-USD|54={side}|44={order_price}|' \
			f'38={order_size}|40=2|59=P|34={seq_num}|49={self.api_key}|52={fix_time_str}|'

		msg = self.finalize_msg(msg_type, msg_body)

		return msg

	def create_cancel_msg(self, order_id, client_order_id, seq_num):
		"""
		Formats a FIX cancel order message.

		Parameters:
			order_id: string
				Identifying Order ID of the order to cancel.
			client_order_id: string
				Identifying Client Order ID of the order to cancel.
			seq_num: int
				Sequence identifier for FIX message.

		Returns:
			msg: bytes
				Ascii encoded FIX cancel order message.
		"""

		msg_type = 'F'

		fix_time_str = str(dt.datetime.utcnow()).replace("-", "").replace(" ", "-")[:-3]
		msg_body = \
			f'11={uuid.uuid4()}|37={order_id}|41={client_order_id}|55=BTC-USD' \
			f'|34={seq_num}|49={self.api_key}|52={fix_time_str}|'
		msg = self.finalize_msg(msg_type, msg_body)

		return msg

	def create_heartbeat_msg(self, seq_num):
		"""
		Formats a FIX heartbeat message.

		Parameters:
			seq_num: int
				Sequence identifier for FIX message.

		Returns:
			msg: bytes
				Ascii encoded FIX heartbeat message.
		"""

		msg_type = '1'
		fix_time_str = str(dt.datetime.utcnow()).replace("-", "").replace(" ", "-")[:-3]
		msg_body = f'34={seq_num}|49={self.api_key}|52={fix_time_str}|'

		msg = self.finalize_msg(msg_type, msg_body)

		return msg

	def analyze_fix_msg(self, msg):
		"""
		Analyzes the meaning of a received FIX message by decoding the message
		and looking up what parameters represent into a human-readable form.

		msg: bytes
			FIX bytes message to decompose.

		Returns:
			out: list
				List of dicts with tags that map to an associated message.
		"""
		decoded_msg = msg.decode('utf-8')
		# GDAX sometimes sends multiple messages
		# Split on FIX.4.2 and only grab the latest message
		msg_split = decoded_msg.split('8=FIX.4.2' + self.separator)
		msgs = []
		for item in msg_split:
			if item != '':
				msgs.append(item.split(self.separator))

		out = []
		for msg in msgs:
			recent_out = {}
			for item in msg:
				split_item = item.split('=', 1)
				try:
					tag = split_item[0]
					tag_msg = split_item[1]
					if tag == '20':
						tag_msg = self.exec_trans_type_20[tag_msg]
					elif tag == '21':
						tag_msg = self.handl_inst_21[tag_msg]
					elif tag == '35':
						tag_msg = self.msg_type_35[tag_msg]
					elif tag == '39':
						tag_msg = self.ord_status_39[tag_msg]
					elif tag == '40':
						tag_msg = self.ord_type_40[tag_msg]
					elif tag == '54':
						tag_msg = self.side_54[tag_msg]
					elif tag == '59':
						tag_msg = self.time_in_force_59[tag_msg]
					elif tag == '98':
						tag_msg = self.encrypt_method_98[tag_msg]
					elif tag == '102':
						tag_msg = self.cxl_rej_reason_102[tag_msg]
					elif tag == '103':
						tag_msg = self.ord_rej_reason_103[tag_msg]
					elif tag == '150':
						tag_msg = self.exec_type_150[tag_msg]
					elif tag == '1057':
						tag_msg = self.aggressor_indicator_1057[tag_msg]
					recent_out[self.fix_tag_field_pairs[tag]] = tag_msg

				except KeyError:
					self.logger.add('KeyError in analyze_fix_msg')
					self.logger.add(
						f"Haven't accounted for tag: {tag} in "
						f"self.fix_tag_field_pairs yet. tag_msg: {tag_msg}"
					)

				except IndexError:
					# Arises from empty string not having index of 1
					pass

			out.append(recent_out)

		return out
