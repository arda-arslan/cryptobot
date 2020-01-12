def reply_manager(fix_trader, logger, buffer=4096):
	"""
	reply_manager() listens for messages in the FIX socket and sends the
	message to the order object the message is associated with.

	Parameters:
		fix_trader: FIXTrader
			Used to pull messages from GDAX and for access to orders.
		logger: Log
			Used to log messages as needed.
		buffer: int
			Maximum buffer size (in bytes) the socket can receive.
			Experimentally, the default of 4096 is large enough for FIX messages.

	Returns:
		None
	"""

	while True:
		reply = fix_trader.fix_socket.recv(buffer)
		logger.add(f'New reply message raw: {reply}')
		responses = fix_trader.analyze_fix_msg(reply)

		# Figure out what each response deals with
		for msg in responses:
			logger.add(f'New reply message: {msg}')

			if 'MsgType' in msg:
				msg_type = msg['MsgType']
				if msg_type == 'Heartbeat':
					logger.add(f'heartbeat msg reply: {msg}')
				elif msg_type == 'Logon':
					logger.add(f'logon msg reply: {msg}')
				elif msg_type == 'Order Cancel Request':
					logger.add(f'cancel msg reply: {msg}')
				elif msg_type == 'Execution Report':
					logger.add(f'order msg reply: {msg}')
					try:
						if 'ClOrdID' in msg:
							fix_trader.order_tracker.orders_by_cl_oid_lock.acquire()
							order = fix_trader.order_tracker.orders_by_cl_oid[msg['ClOrdID']]
							fix_trader.order_tracker.orders_by_cl_oid_lock.release()

							order.order_id = msg['OrderID']

							fix_trader.order_tracker.order_by_oid_lock.acquire()
							fix_trader.order_tracker.orders_by_oid[msg['OrderID']] = order
							fix_trader.order_tracker.order_by_oid_lock.release()

						fix_trader.order_tracker.order_by_oid_lock.acquire()
						order = fix_trader.order_tracker.orders_by_oid[msg['OrderID']]
						fix_trader.order_tracker.order_by_oid_lock.release()

						order.condition.acquire()
						order.msgs.put(msg)
						order.condition.notify()
						order.condition.release()

					except KeyError:
						logger.add("KeyError in Buffer Manager")
